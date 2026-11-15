"""Custom Gateway Hub — User Backend Plugin.

Registers ``CustomGatewayImageProvider`` (`image_gen.provider = "custom-gateway"`) so Hermes CLI,
Gateway turns, and Settings → Capabilities → Image Generation dynamically list all image models
discovered from the user's OpenAI-compatible Custom Gateway (`/v1/models`).
"""

from __future__ import annotations

import importlib.util
import io
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_b64_image,
    success_response,
)
from plugins.image_gen._common import (
    api_key_setup_schema,
    cache_url_best_effort,
    collect_source_images,
    import_openai,
    load_image_gen_config,
    materialize_image,
    openai_importable,
    prompt_required_error,
    record_token_usage,
    size_for,
)

logger = logging.getLogger(__name__)

_CORE_MODULE_NAME = "_custom_gateway_hub_core"


def _load_core():
    existing = sys.modules.get(_CORE_MODULE_NAME)
    core_path = Path(__file__).resolve().parent / "gateway_core.py"
    if existing is not None and getattr(existing, "__file__", None) == str(core_path):
        return existing
    spec = importlib.util.spec_from_file_location(_CORE_MODULE_NAME, core_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load gateway_core from {core_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_CORE_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_openai_client(openai_mod: Any, base_url: str, api_key: str) -> Any:
    from agent.process_bootstrap import build_keepalive_http_client

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "default_headers": {"OpenAI-Project": ""},
    }
    if base_url:
        kwargs["base_url"] = base_url
    http_client = build_keepalive_http_client(base_url)
    if http_client is not None:
        kwargs["http_client"] = http_client
    return openai_mod.OpenAI(**kwargs)


def _load_source_image_bytes(ref: str) -> tuple[bytes, str]:
    ref = ref.strip()
    lower = ref.lower()
    if lower.startswith(("http://", "https://")):
        from tools.url_safety import create_ssrf_safe_client, is_safe_url

        if not is_safe_url(ref):
            raise ValueError(f"Image reference URL failed SSRF safety check: {ref}")
        with create_ssrf_safe_client(timeout=60, follow_redirects=True) as client:
            resp = client.get(ref)
        resp.raise_for_status()
        fname = ref.split("?", 1)[0].rsplit("/", 1)[-1] or "image.png"
        return resp.content, fname
    if lower.startswith("data:"):
        import base64

        header, _, b64 = ref.partition(",")
        ext = (header.split("image/", 1)[1].split(";", 1)[0] if "image/" in header else "") or "png"
        return base64.b64decode(b64), f"image.{ext}"

    from agent.file_safety import raise_if_read_blocked

    raise_if_read_blocked(ref)
    with open(ref, "rb") as fh:
        data = fh.read()
    return data, os.path.basename(ref) or "image.png"


def _named_bytes_io(ref: str) -> io.BytesIO:
    data, fname = _load_source_image_bytes(ref)
    bio = io.BytesIO(data)
    bio.name = fname
    return bio


_DATA_IMAGE_RE = re.compile(r"data:image/(png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=\s]+)", re.IGNORECASE)
_MD_URL_RE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")


def _extract_chat_completion_image(response: Any, *, model: str, prompt: str, aspect: str) -> Optional[str]:
    """Extract base64 or URL image from OpenAI-compatible chat completions (used by gateways
    for models like `gemini-3.1-flash-image`)."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    if message is None:
        return None

    # 1. OpenRouter / LiteLLM style `message.images` list
    images = getattr(message, "images", None)
    if isinstance(images, list):
        for img in images:
            url_val = ""
            if isinstance(img, dict):
                url_val = str((img.get("image_url") or {}).get("url") or img.get("url") or "")
            else:
                img_url_obj = getattr(img, "image_url", None)
                url_val = str(getattr(img_url_obj, "url", None) or getattr(img, "url", None) or "")
            if url_val.startswith("data:image/"):
                m = _DATA_IMAGE_RE.search(url_val)
                if m:
                    ext = "jpg" if m.group(1).lower() == "jpeg" else m.group(1).lower()
                    b64_clean = re.sub(r"\s+", "", m.group(2))
                    return str(save_b64_image(b64_clean, prefix=f"cg_{model}", extension=ext))
            elif url_val.startswith(("http://", "https://")):
                return cache_url_best_effort(url_val, prefix=f"cg_{model}", label="Custom Gateway", log=logger)

    # 2. Content string or content parts
    content = getattr(message, "content", None)
    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "image_url":
                    u = str((part.get("image_url") or {}).get("url") or "")
                    texts.append(u)
                elif isinstance(part.get("text"), str):
                    texts.append(part["text"])
            else:
                txt = getattr(part, "text", None)
                if isinstance(txt, str):
                    texts.append(txt)

    joined = "\n".join(texts)
    m_data = _DATA_IMAGE_RE.search(joined)
    if m_data:
        ext = "jpg" if m_data.group(1).lower() == "jpeg" else m_data.group(1).lower()
        b64_clean = re.sub(r"\s+", "", m_data.group(2))
        return str(save_b64_image(b64_clean, prefix=f"cg_{model}", extension=ext))

    m_url = _MD_URL_RE.search(joined)
    if m_url:
        return cache_url_best_effort(m_url.group(1), prefix=f"cg_{model}", label="Custom Gateway", log=logger)
    return None


class CustomGatewayImageProvider(ImageGenProvider):
    """Dynamic OpenAI-compatible Custom Gateway image generation & editing provider."""

    @property
    def name(self) -> str:
        return "custom-gateway"

    @property
    def display_name(self) -> str:
        return "Custom Gateway"

    def list_models(self) -> list[dict[str, Any]]:
        core = _load_core()
        rows = core.list_configured_image_models()
        return [
            {
                "id": r["id"],
                "display": r.get("display") or r["id"],
                "speed": r.get("speed") or "Standard",
                "strengths": r.get("strengths") or "Custom Gateway image model",
                "price": r.get("price") or "gateway",
            }
            for r in rows
        ]

    def default_model(self) -> Optional[str]:
        core = _load_core()
        cfg = load_image_gen_config()
        cg = cfg.get("custom_gateway") if isinstance(cfg.get("custom_gateway"), dict) else {}
        cand = str(cg.get("model") or cfg.get("model") or "").strip()
        if cand:
            return cand
        rows = core.list_configured_image_models()
        return rows[0]["id"] if rows else core.DEFAULT_IMAGE_MODELS[0]

    def get_setup_schema(self) -> dict[str, Any]:
        core = _load_core()
        creds = core.resolve_gateway_credentials()
        return api_key_setup_schema(
            "Custom Gateway",
            "custom",
            "Dynamic image models loaded from your Custom Gateway (/v1/models)",
            key=creds["key_env"],
            prompt="Custom Gateway API key",
            url=creds["base_url"] or "",
        )

    def is_available(self) -> bool:
        core = _load_core()
        creds = core.resolve_gateway_credentials()
        return bool(creds["base_url"] and creds["api_key"]) and openai_importable()

    def capabilities(self) -> dict[str, Any]:
        return {"modalities": ["text", "image"], "max_reference_images": 16}

    def _resolve_active_model(self, explicit: Optional[str] = None) -> str:
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        env_override = (os.environ.get("CUSTOM_GATEWAY_IMAGE_MODEL") or "").strip()
        if env_override:
            return env_override
        cfg = load_image_gen_config()
        cg = cfg.get("custom_gateway") if isinstance(cfg.get("custom_gateway"), dict) else {}
        for cand in (cg.get("model"), cfg.get("model")):
            if isinstance(cand, str) and cand.strip():
                return cand.strip()
        return self.default_model() or "gpt-image-2.5-sunburst"

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)
        if not prompt:
            return prompt_required_error("custom-gateway", aspect)

        core = _load_core()
        creds = core.resolve_gateway_credentials()
        base_url = creds["base_url"]
        api_key = creds["api_key"]
        model_id = self._resolve_active_model(kwargs.get("model"))

        if not base_url or not api_key:
            return error_response(
                error=(
                    "Custom Gateway chưa đủ Base URL hoặc API Key. "
                    "Hãy mở tab 'Gateway Models' trên Hermes Desktop để kiểm tra kết nối và lưu cấu hình."
                ),
                error_type="auth_required",
                provider="custom-gateway",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        openai_mod, err = import_openai("custom-gateway", aspect)
        if err:
            return err

        size = size_for(aspect)
        sources = collect_source_images(image_url, reference_image_urls, limit=16)
        is_edit = bool(sources)
        client = _build_openai_client(openai_mod, base_url, api_key)

        request_payload: dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }
        if is_edit:
            try:
                files = [_named_bytes_io(ref) for ref in sources]
            except Exception as exc:
                return error_response(
                    error=f"Could not load source image for editing: {exc}",
                    error_type="io_error",
                    provider="custom-gateway",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            request_payload["image"] = files if len(files) > 1 else files[0]

        call_fn = client.images.edit if is_edit else client.images.generate
        try:
            response = call_fn(**request_payload)
            record_token_usage(
                getattr(response, "usage", None),
                model=model_id,
                provider="custom-gateway",
                base_url=base_url,
            )
            data = getattr(response, "data", None) or []
            if data:
                first = data[0]
                safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", f"cg_{model_id}")[:40]
                image_ref, mat_err = materialize_image(
                    getattr(first, "b64_json", None),
                    getattr(first, "url", None),
                    prefix=safe_prefix,
                    label="Custom Gateway",
                    provider="custom-gateway",
                    model=model_id,
                    prompt=prompt,
                    aspect=aspect,
                    log=logger,
                )
                if mat_err:
                    return mat_err
                extra: dict[str, Any] = {"size": size}
                if getattr(first, "revised_prompt", None):
                    extra["revised_prompt"] = first.revised_prompt
                return success_response(
                    image=image_ref,
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                    provider="custom-gateway",
                    modality="image" if is_edit else "text",
                    extra=extra,
                )
        except Exception as images_exc:
            # Some custom gateway image models (e.g. gemini-3.1-flash-image) expose image output
            # through /v1/chat/completions instead of /v1/images/generations. Try chat fallback on text-to-image.
            if not is_edit and core.image_transport_hint(model_id) == "images_or_chat":
                try:
                    chat_resp = client.chat.completions.create(
                        model=model_id,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    img_path = _extract_chat_completion_image(
                        chat_resp, model=model_id, prompt=prompt, aspect=aspect
                    )
                    if img_path:
                        return success_response(
                            image=img_path,
                            model=model_id,
                            prompt=prompt,
                            aspect_ratio=aspect,
                            provider="custom-gateway",
                            modality="text",
                            extra={"transport": "chat_completions"},
                        )
                except Exception as chat_exc:
                    logger.debug("Chat-completions image fallback failed for %s: %s", model_id, chat_exc)

            return error_response(
                error=f"Custom Gateway image {'editing' if is_edit else 'generation'} failed ({model_id}): {images_exc}",
                error_type="api_error",
                provider="custom-gateway",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        return error_response(
            error=f"Custom Gateway ({model_id}) returned no image data",
            error_type="empty_response",
            provider="custom-gateway",
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
        )


def register(ctx) -> None:
    """Plugin entry point — register `CustomGatewayImageProvider` in Hermes's image_gen registry."""
    ctx.register_image_gen_provider(CustomGatewayImageProvider())
