"""Core configuration, secret resolution, /v1/models probing, and model partitioning
for the user-space ``custom-gateway-hub`` plugin.

Lives entirely inside ``$HERMES_HOME/plugins/custom-gateway-hub/`` so ``hermes update``
never touches or conflicts with these files.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_SLUG = "custom-gateway"
DEFAULT_API_MODE = "chat_completions"
DEFAULT_IMAGE_MODELS = (
    "gpt-image-2.5-sunburst",
    "gpt-image-2.5-flare",
    "gpt-image-2.5",
    "gpt-image-2",
    "gpt-image-1.5",
    "gemini-3.1-flash-image",
)

_WRITE_LOCK = threading.RLock()

_IMAGE_EXACT_PREFIXES = (
    "gpt-image",
    "dall-e",
    "imagen",
    "flux",
    "recraft",
    "ideogram",
    "midjourney",
    "sdxl",
    "stable-diffusion",
    "seedream",
    "qwen-image",
    "grok-2-image",
    "playground-v",
    "kolors",
)

_IMAGE_TOKEN_PATTERNS = (
    re.compile(r"(?:^|[-_/])image(?:[-_/]|$)"),
    re.compile(r"text-to-image"),
    re.compile(r"img2img"),
)

_VISION_CHAT_EXCLUSIONS = (
    "llava",
    "pixtral",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "internvl",
)


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        env_home = os.environ.get("HERMES_HOME")
        if env_home:
            return Path(env_home)
        return Path(__file__).resolve().parents[2]


def _key_env_for_slug(slug: str) -> str:
    try:
        from hermes_cli.config import custom_endpoint_key_env

        return custom_endpoint_key_env(slug)
    except Exception:
        sanitized = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_").upper() or "DEFAULT"
        return f"HERMES_CUSTOM_{sanitized}_API_KEY"


def _read_dotenv_map(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    try:
        for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key:
                values[key] = val
    except Exception as exc:
        logger.debug("Could not read dotenv file %s: %s", env_path, exc)
    return values


def _lookup_secret(var_name: str, dotenv_cache: Optional[dict[str, str]] = None) -> str:
    if not var_name:
        return ""
    try:
        from agent.secret_scope import get_secret_str

        scoped = (get_secret_str(var_name, "") or "").strip()
        if scoped:
            return scoped
    except Exception:
        pass
    env_val = (os.environ.get(var_name) or "").strip()
    if env_val:
        return env_val
    if dotenv_cache is None:
        dotenv_cache = _read_dotenv_map(_hermes_home() / ".env")
    return (dotenv_cache.get(var_name) or "").strip()


def mask_api_key(api_key: str) -> str:
    clean = (api_key or "").strip()
    if not clean:
        return ""
    if len(clean) <= 10:
        return "*" * len(clean)
    return f"{clean[:6]}...{clean[-4:]}"


def normalize_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def detect_model_family(model_id: str, *, is_image: bool = False) -> str:
    lower = (model_id or "").strip().lower()
    if is_image:
        if lower.startswith("gpt-image"):
            return "GPT Image"
        if "gemini" in lower or "imagen" in lower:
            return "Google Image"
        if "flux" in lower:
            return "FLUX"
        if "dall-e" in lower:
            return "DALL-E"
        return "Image Model"
    if lower.startswith(("gpt-6", "gpt-5", "gpt-4", "o1", "o3", "o4", "chatgpt")):
        return "OpenAI / GPT"
    if "claude" in lower:
        return "Anthropic / Claude"
    if "gemini" in lower:
        return "Google / Gemini"
    if "grok" in lower:
        return "xAI / Grok"
    if "kimi" in lower or "moonshot" in lower:
        return "Moonshot / Kimi"
    if "qwen" in lower:
        return "Alibaba / Qwen"
    if "deepseek" in lower:
        return "DeepSeek"
    return "Custom / Other"


def is_image_model(model_id: str, raw_meta: Optional[dict[str, Any]] = None) -> bool:
    """Return True when *model_id* (or optional `/v1/models` item metadata) represents an
    image generation/editing model rather than a text/chat model."""
    lower = (model_id or "").strip().lower()
    if not lower:
        return False

    if isinstance(raw_meta, dict):
        model_type = str(raw_meta.get("type") or raw_meta.get("mode") or "").strip().lower()
        if model_type in {"image", "image_generation", "images", "text-to-image"}:
            return True
        arch = raw_meta.get("architecture")
        if isinstance(arch, dict):
            out_mods = arch.get("output_modalities") or arch.get("modality")
            if isinstance(out_mods, list) and "image" in [str(x).lower() for x in out_mods]:
                if "text" not in [str(x).lower() for x in out_mods] or lower.endswith("-image"):
                    return True
            if isinstance(out_mods, str) and out_mods.lower().endswith("->image"):
                return True

    if any(excl in lower for excl in _VISION_CHAT_EXCLUSIONS):
        return False

    if lower.startswith(_IMAGE_EXACT_PREFIXES):
        return True

    return any(pattern.search(lower) for pattern in _IMAGE_TOKEN_PATTERNS)


def image_transport_hint(model_id: str) -> str:
    """Indicate whether an image model natively uses `/images/generations` or may use
    chat-completions image fallback."""
    lower = (model_id or "").strip().lower()
    if lower.startswith(("gpt-image", "dall-e", "flux", "imagen", "recraft", "ideogram", "sdxl")):
        return "images_api"
    if "gemini" in lower and "image" in lower:
        return "images_or_chat"
    return "images_api"


def _load_config_dict() -> dict[str, Any]:
    from hermes_cli.config import load_config

    cfg = load_config()
    return cfg if isinstance(cfg, dict) else {}


def _save_config_dict(cfg: dict[str, Any]) -> None:
    from hermes_cli.config import save_config

    save_config(cfg)


def _resolve_provider_slug(cfg: dict[str, Any]) -> str:
    img_custom = ((cfg.get("image_gen") or {}).get("custom_gateway") or {})
    if isinstance(img_custom, dict):
        cand = str(img_custom.get("provider") or "").strip()
        if cand:
            return cand.removeprefix("custom:")
    providers = cfg.get("providers")
    if isinstance(providers, dict):
        if DEFAULT_PROVIDER_SLUG in providers:
            return DEFAULT_PROVIDER_SLUG
        for key, val in providers.items():
            if isinstance(val, dict) and (val.get("base_url") or val.get("api") or val.get("url")):
                return str(key).strip()
    return DEFAULT_PROVIDER_SLUG


def resolve_gateway_credentials(
    cfg: Optional[dict[str, Any]] = None,
    *,
    base_url_override: Optional[str] = None,
    api_key_override: Optional[str] = None,
    api_mode_override: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve `(provider_slug, canonical_provider, base_url, api_key, key_env, api_mode)`."""
    cfg = cfg if isinstance(cfg, dict) else _load_config_dict()
    slug = _resolve_provider_slug(cfg)
    canonical_provider = f"custom:{slug}"
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    prov_entry = providers.get(slug) if isinstance(providers.get(slug), dict) else {}
    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    img_cfg = ((cfg.get("image_gen") or {}).get("custom_gateway") or {})
    if not isinstance(img_cfg, dict):
        img_cfg = {}

    key_env = (
        str(prov_entry.get("key_env") or "").strip()
        or str(img_cfg.get("key_env") or "").strip()
        or _key_env_for_slug(slug)
    )
    default_key_env = _key_env_for_slug(slug)

    base_url = normalize_base_url(
        base_url_override
        or str(prov_entry.get("base_url") or prov_entry.get("api") or prov_entry.get("url") or "")
        or str(img_cfg.get("base_url") or "")
        or str(model_cfg.get("base_url") or "")
    )
    api_mode = (
        (api_mode_override or "").strip()
        or str(prov_entry.get("api_mode") or "").strip()
        or str(model_cfg.get("api_mode") or "").strip()
        or DEFAULT_API_MODE
    )

    dotenv_cache = _read_dotenv_map(_hermes_home() / ".env")
    override_clean = (api_key_override or "").strip()
    if override_clean and "..." not in override_clean:
        api_key = override_clean
    else:
        api_key = (
            _lookup_secret(key_env, dotenv_cache)
            or _lookup_secret(default_key_env, dotenv_cache)
            or _lookup_secret("CUSTOM_IMAGE_API_KEY", dotenv_cache)
            or str(prov_entry.get("api_key") or "").strip()
            or str(model_cfg.get("api_key") or "").strip()
        )

    return {
        "provider_slug": slug,
        "canonical_provider": canonical_provider,
        "base_url": base_url,
        "api_key": api_key,
        "key_env": default_key_env,
        "api_mode": api_mode,
    }


def _ppt_master_env_path() -> Path:
    return _hermes_home() / "skills" / "productivity" / "ppt-master" / ".env"


def _get_ppt_master_status(expected_base_url: str, expected_image_model: str) -> dict[str, Any]:
    path = _ppt_master_env_path()
    if not path.is_file():
        return {
            "exists": False,
            "synced": False,
            "current_model": "",
            "current_base_url": "",
            "path": str(path),
        }
    vals = _read_dotenv_map(path)
    cur_model = vals.get("OPENAI_MODEL", "")
    cur_url = normalize_base_url(vals.get("OPENAI_BASE_URL", ""))
    synced = bool(
        cur_model == (expected_image_model or "").strip()
        and (not expected_base_url or cur_url == normalize_base_url(expected_base_url))
    )
    return {
        "exists": True,
        "synced": synced,
        "current_model": cur_model,
        "current_base_url": cur_url,
        "path": str(path),
    }


def _sync_ppt_master_env(base_url: str, api_key: str, image_model: str) -> dict[str, Any]:
    path = _ppt_master_env_path()
    if not path.parent.is_dir():
        return _get_ppt_master_status(base_url, image_model)
    existing = _read_dotenv_map(path) if path.is_file() else {}
    existing["IMAGE_BACKEND"] = existing.get("IMAGE_BACKEND") or "openai"
    if api_key:
        existing["OPENAI_API_KEY"] = api_key
    if base_url:
        existing["OPENAI_BASE_URL"] = normalize_base_url(base_url)
    if image_model:
        existing["OPENAI_MODEL"] = image_model.strip()

    lines = [f"{k}={v}" for k, v in existing.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _get_ppt_master_status(base_url, image_model)


def list_configured_image_models(cfg: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Return discovered image models from config (falling back to curated defaults) for
    `CustomGatewayImageProvider.list_models()` and UI state."""
    cfg = cfg if isinstance(cfg, dict) else _load_config_dict()
    img_section = cfg.get("image_gen") if isinstance(cfg.get("image_gen"), dict) else {}
    cg_section = img_section.get("custom_gateway") if isinstance(img_section.get("custom_gateway"), dict) else {}
    raw_list = cg_section.get("discovered_models")
    ids: list[str] = []
    if isinstance(raw_list, list):
        for item in raw_list:
            if isinstance(item, str) and item.strip() and item.strip() not in ids:
                ids.append(item.strip())
            elif isinstance(item, dict) and str(item.get("id") or "").strip():
                mid = str(item["id"]).strip()
                if mid not in ids:
                    ids.append(mid)

    active_img = str(cg_section.get("model") or img_section.get("model") or "").strip()
    if active_img and active_img not in ids and is_image_model(active_img):
        ids.insert(0, active_img)

    if not ids:
        ids = list(DEFAULT_IMAGE_MODELS)

    new_ids = set(cg_section.get("new_image_models") or []) if isinstance(cg_section.get("new_image_models"), list) else set()
    rows: list[dict[str, Any]] = []
    for mid in ids:
        family = detect_model_family(mid, is_image=True)
        hint = image_transport_hint(mid)
        rows.append({
            "id": mid,
            "display": mid,
            "family": family,
            "owned_by": family,
            "speed": "Fast" if ("flare" in mid or "flash" in mid) else "Standard",
            "strengths": (
                "Images API + Chat fallback" if hint == "images_or_chat" else "OpenAI-compatible /v1/images/generations"
            ),
            "price": "gateway",
            "transport": hint,
            "is_new": mid in new_ids,
        })
    return rows


def list_configured_chat_models(cfg: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Return saved chat/content models under `providers.<slug>.models`."""
    cfg = cfg if isinstance(cfg, dict) else _load_config_dict()
    slug = _resolve_provider_slug(cfg)
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    prov = providers.get(slug) if isinstance(providers.get(slug), dict) else {}
    models_Field = prov.get("models")
    ids: list[str] = []
    if isinstance(models_Field, dict):
        for mid in models_Field.keys():
            s = str(mid).strip()
            if s and not is_image_model(s) and s not in ids:
                ids.append(s)
    elif isinstance(models_Field, list):
        for mid in models_Field:
            s = str(mid).strip()
            if s and not is_image_model(s) and s not in ids:
                ids.append(s)

    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    active_chat = str(model_cfg.get("default") or prov.get("model") or "").strip()
    if active_chat and not is_image_model(active_chat) and active_chat not in ids:
        ids.insert(0, active_chat)

    cg_section = ((cfg.get("image_gen") or {}).get("custom_gateway") or {})
    new_ids = (
        set(cg_section.get("new_chat_models") or [])
        if isinstance(cg_section, dict) and isinstance(cg_section.get("new_chat_models"), list)
        else set()
    )

    return [
        {
            "id": mid,
            "family": detect_model_family(mid, is_image=False),
            "owned_by": detect_model_family(mid, is_image=False),
            "is_new": mid in new_ids,
        }
        for mid in ids
    ]


def get_hub_state() -> dict[str, Any]:
    """Full snapshot for `GET /api/plugins/custom-gateway-hub/state`."""
    cfg = _load_config_dict()
    creds = resolve_gateway_credentials(cfg)
    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    img_cfg = cfg.get("image_gen") if isinstance(cfg.get("image_gen"), dict) else {}
    cg_cfg = img_cfg.get("custom_gateway") if isinstance(img_cfg.get("custom_gateway"), dict) else {}
    openai_img_cfg = img_cfg.get("openai") if isinstance(img_cfg.get("openai"), dict) else {}

    active_content_model = str(model_cfg.get("default") or "").strip()
    active_content_provider = str(model_cfg.get("provider") or creds["canonical_provider"]).strip()

    active_image_provider = str(img_cfg.get("provider") or "custom-gateway").strip()
    active_image_model = (
        str(cg_cfg.get("model") or "").strip()
        or str(img_cfg.get("model") or "").strip()
        or str(openai_img_cfg.get("model") or "").strip()
        or DEFAULT_IMAGE_MODELS[0]
    )

    chat_models = list_configured_chat_models(cfg)
    image_models = list_configured_image_models(cfg)

    return {
        "ok": True,
        "provider_slug": creds["provider_slug"],
        "canonical_provider": creds["canonical_provider"],
        "base_url": creds["base_url"],
        "api_mode": creds["api_mode"],
        "key_env": creds["key_env"],
        "has_api_key": bool(creds["api_key"]),
        "masked_api_key": mask_api_key(creds["api_key"]),
        "active_content_model": active_content_model,
        "active_content_provider": active_content_provider,
        "active_image_model": active_image_model,
        "active_image_provider": active_image_provider,
        "chat_models": chat_models,
        "image_models": image_models,
        "total_models": len(chat_models) + len(image_models),
        "last_checked_at": cg_cfg.get("last_checked_at") or None,
        "last_latency_ms": cg_cfg.get("last_latency_ms") or None,
        "ppt_master": _get_ppt_master_status(creds["base_url"], active_image_model),
    }


def _clear_hermes_model_caches() -> None:
    try:
        from hermes_cli.model_tools import clear_provider_models_cache

        clear_provider_models_cache()
    except Exception as exc:
        logger.debug("clear_provider_models_cache skipped: %s", exc)


def probe_gateway_models(
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_mode: Optional[str] = None,
    persist: bool = True,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Live `Check Connection & Load Models` against `{base_url}/models`."""
    import requests

    cfg = _load_config_dict()
    creds = resolve_gateway_credentials(
        cfg,
        base_url_override=base_url,
        api_key_override=api_key,
        api_mode_override=api_mode,
    )
    resolved_base = creds["base_url"]
    resolved_key = creds["api_key"]
    if not resolved_base:
        return {
            "ok": False,
            "error": "Chưa cấu hình Base URL cho Custom Gateway (ví dụ: https://your-gateway.example.com/v1).",
            "error_code": "missing_base_url",
        }

    headers: dict[str, str] = {"Accept": "application/json"}
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    candidate_bases = [resolved_base]
    if not resolved_base.endswith("/v1"):
        candidate_bases.append(f"{resolved_base}/v1")

    last_error = ""
    last_status = 0
    payload: Any = None
    working_base = resolved_base
    latency_ms = 0

    for candidate in candidate_bases:
        models_url = f"{candidate}/models"
        t0 = time.perf_counter()
        try:
            resp = requests.get(models_url, headers=headers, timeout=(6.0, timeout_seconds))
            latency_ms = max(1, int(round((time.perf_counter() - t0) * 1000)))
            last_status = resp.status_code
            if resp.status_code == 404 and candidate != candidate_bases[-1]:
                continue
            if not resp.ok:
                try:
                    err_json = resp.json()
                    msg = (
                        err_json.get("error", {}).get("message")
                        if isinstance(err_json.get("error"), dict)
                        else err_json.get("detail") or err_json.get("error")
                    ) or resp.text[:300]
                except Exception:
                    msg = resp.text[:300]
                return {
                    "ok": False,
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                    "base_url": candidate,
                    "error": f"Gateway trả về HTTP {resp.status_code}: {msg}",
                    "error_code": "http_error",
                }
            payload = resp.json()
            working_base = candidate
            break
        except requests.Timeout:
            latency_ms = max(1, int(round((time.perf_counter() - t0) * 1000)))
            last_error = f"Quá thời gian chờ ({int(timeout_seconds)}s) khi kết nối tới {models_url}."
        except requests.RequestException as exc:
            latency_ms = max(1, int(round((time.perf_counter() - t0) * 1000)))
            last_error = f"Không thể kết nối tới {models_url}: {exc}"
        except ValueError as exc:
            return {
                "ok": False,
                "status_code": last_status,
                "latency_ms": latency_ms,
                "base_url": candidate,
                "error": f"Phản hồi từ {models_url} không phải JSON hợp lệ: {exc}",
                "error_code": "invalid_json",
            }

    if payload is None:
        return {
            "ok": False,
            "status_code": last_status,
            "latency_ms": latency_ms,
            "base_url": resolved_base,
            "error": last_error or "Không thể tải danh sách model từ Gateway.",
            "error_code": "connection_error",
        }

    raw_items = payload.get("data") if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
    if not isinstance(raw_items, list):
        raw_items = []

    prev_chat_ids = {row["id"] for row in list_configured_chat_models(cfg)}
    prev_image_ids = {row["id"] for row in list_configured_image_models(cfg)}

    discovered_chat: list[str] = []
    discovered_image: list[str] = []
    meta_by_id: dict[str, dict[str, Any]] = {}

    for item in raw_items:
        if isinstance(item, str):
            mid = item.strip()
            raw_meta: dict[str, Any] = {}
        elif isinstance(item, dict):
            mid = str(item.get("id") or item.get("name") or "").strip()
            raw_meta = item
        else:
            continue
        if not mid or mid in meta_by_id:
            continue
        meta_by_id[mid] = raw_meta
        if is_image_model(mid, raw_meta):
            discovered_image.append(mid)
        else:
            discovered_chat.append(mid)

    discovered_chat.sort(key=lambda s: s.lower())
    discovered_image.sort(key=lambda s: s.lower())

    new_chat = [m for m in discovered_chat if prev_chat_ids and m not in prev_chat_ids]
    new_image = [m for m in discovered_image if prev_image_ids and m not in prev_image_ids]
    checked_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    if persist:
        with _WRITE_LOCK:
            fresh_cfg = _load_config_dict()
            slug = _resolve_provider_slug(fresh_cfg)
            key_env = _key_env_for_slug(slug)

            providers = fresh_cfg.setdefault("providers", {})
            if not isinstance(providers, dict):
                providers = {}
                fresh_cfg["providers"] = providers
            prov_block = providers.setdefault(slug, {})
            if not isinstance(prov_block, dict):
                prov_block = {}
                providers[slug] = prov_block

            prov_block.setdefault("name", "Custom Gateway")
            prov_block["base_url"] = working_base
            prov_block["api_mode"] = creds["api_mode"]
            prov_block["key_env"] = key_env
            prov_block["discover_models"] = True

            existing_models_map = prov_block.get("models") if isinstance(prov_block.get("models"), dict) else {}
            merged_models: dict[str, Any] = {}
            for mid in discovered_chat:
                prev_entry = existing_models_map.get(mid)
                merged_models[mid] = dict(prev_entry) if isinstance(prev_entry, dict) else {}
            if merged_models:
                prov_block["models"] = merged_models

            img_block = fresh_cfg.setdefault("image_gen", {})
            if not isinstance(img_block, dict):
                img_block = {}
                fresh_cfg["image_gen"] = img_block
            cg_block = img_block.setdefault("custom_gateway", {})
            if not isinstance(cg_block, dict):
                cg_block = {}
                img_block["custom_gateway"] = cg_block

            cg_block["provider"] = slug
            cg_block["base_url"] = working_base
            cg_block["key_env"] = key_env
            if discovered_image:
                cg_block["discovered_models"] = discovered_image
            cg_block["new_chat_models"] = new_chat
            cg_block["new_image_models"] = new_image
            cg_block["last_checked_at"] = checked_at
            cg_block["last_latency_ms"] = latency_ms

            _save_config_dict(fresh_cfg)
        _clear_hermes_model_caches()

    state = get_hub_state()
    return {
        **state,
        "ok": True,
        "checked_at": checked_at,
        "latency_ms": latency_ms,
        "resolved_base_url": working_base,
        "discovered_chat_count": len(discovered_chat),
        "discovered_image_count": len(discovered_image),
        "new_chat_models": new_chat,
        "new_image_models": new_image,
    }


def _persist_api_key(key_env: str, api_key: str) -> None:
    clean = (api_key or "").strip()
    if not clean or "..." in clean:
        return
    from hermes_cli.config import save_env_value

    save_env_value(key_env, clean)
    save_env_value("CUSTOM_IMAGE_API_KEY", clean)
    os.environ[key_env] = clean
    os.environ["CUSTOM_IMAGE_API_KEY"] = clean
    try:
        from hermes_cli.env_loader import load_hermes_dotenv
        from agent.secret_scope import refresh_installed_secret_scope

        home = _hermes_home()
        load_hermes_dotenv(hermes_home=home)
        refresh_installed_secret_scope(home)
    except Exception as exc:
        logger.debug("Live secret scope refresh skipped: %s", exc)


def apply_hub_settings(
    *,
    content_model: Optional[str] = None,
    image_model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_mode: Optional[str] = None,
    api_key: Optional[str] = None,
    sync_ppt_master: bool = True,
) -> dict[str, Any]:
    """Persist selected Content Model, Image Model, and optional Endpoint edits cleanly."""
    with _WRITE_LOCK:
        cfg = _load_config_dict()
        creds = resolve_gateway_credentials(
            cfg,
            base_url_override=base_url,
            api_key_override=api_key,
            api_mode_override=api_mode,
        )
        slug = creds["provider_slug"]
        canonical_provider = creds["canonical_provider"]
        key_env = creds["key_env"]
        eff_base_url = creds["base_url"]
        eff_api_mode = creds["api_mode"]
        eff_api_key = creds["api_key"]

        if api_key and api_key.strip() and "..." not in api_key.strip():
            _persist_api_key(key_env, api_key.strip())
            eff_api_key = api_key.strip()

        # 1. Update providers.<slug>
        providers = cfg.setdefault("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            cfg["providers"] = providers
        prov_block = providers.setdefault(slug, {})
        if not isinstance(prov_block, dict):
            prov_block = {}
            providers[slug] = prov_block

        prov_block.setdefault("name", "Custom Gateway")
        if eff_base_url:
            prov_block["base_url"] = eff_base_url
        prov_block["api_mode"] = eff_api_mode
        prov_block["key_env"] = key_env
        prov_block["discover_models"] = True
        prov_block.pop("api_key", None)

        # 2. Update model section (Content / Chat Model)
        model_block = cfg.setdefault("model", {})
        if not isinstance(model_block, dict):
            model_block = {}
            cfg["model"] = model_block

        chosen_content = (content_model or "").strip() or str(model_block.get("default") or "").strip()
        model_block["provider"] = canonical_provider
        if chosen_content:
            model_block["default"] = chosen_content
            prov_block["model"] = chosen_content
            models_map = prov_block.setdefault("models", {})
            if isinstance(models_map, dict) and not is_image_model(chosen_content):
                models_map.setdefault(chosen_content, {})
        if eff_base_url:
            model_block["base_url"] = eff_base_url
        model_block["api_mode"] = eff_api_mode
        model_block["key_env"] = key_env
        model_block.pop("api_key", None)

        # Normalize legacy custom/* aliases if present
        aliases = model_block.get("aliases")
        if isinstance(aliases, dict):
            updated_aliases: dict[str, str] = {}
            for alias_k, alias_v in aliases.items():
                val_str = str(alias_v or "")
                if val_str.startswith("custom/"):
                    updated_aliases[alias_k] = f"{slug}/{val_str.split('/', 1)[1]}"
                else:
                    updated_aliases[alias_k] = val_str
            model_block["aliases"] = updated_aliases

        # 3. Update image_gen section (both custom_gateway and openai fallback kept in sync)
        img_block = cfg.setdefault("image_gen", {})
        if not isinstance(img_block, dict):
            img_block = {}
            cfg["image_gen"] = img_block
        cg_block = img_block.setdefault("custom_gateway", {})
        if not isinstance(cg_block, dict):
            cg_block = {}
            img_block["custom_gateway"] = cg_block
        openai_block = img_block.setdefault("openai", {})
        if not isinstance(openai_block, dict):
            openai_block = {}
            img_block["openai"] = openai_block

        chosen_image = (
            (image_model or "").strip()
            or str(cg_block.get("model") or img_block.get("model") or DEFAULT_IMAGE_MODELS[0]).strip()
        )

        img_block["provider"] = "custom-gateway"
        img_block["model"] = chosen_image

        cg_block["provider"] = slug
        if eff_base_url:
            cg_block["base_url"] = eff_base_url
        cg_block["key_env"] = key_env
        cg_block["model"] = chosen_image
        disc = cg_block.get("discovered_models")
        if isinstance(disc, list) and chosen_image and chosen_image not in disc:
            cg_block["discovered_models"] = [chosen_image, *disc]

        # Keep built-in openai image_gen sub-block synced too as zero-downtime fallback
        openai_block["provider"] = slug
        if eff_base_url:
            openai_block["base_url"] = eff_base_url
        openai_block["key_env"] = key_env
        openai_block["model"] = chosen_image

        # Clear "new" highlight badges once user explicitly applies a selection
        cg_block["new_chat_models"] = []
        cg_block["new_image_models"] = []

        _save_config_dict(cfg)

    _clear_hermes_model_caches()

    ppt_status = (
        _sync_ppt_master_env(eff_base_url, eff_api_key, chosen_image)
        if sync_ppt_master
        else _get_ppt_master_status(eff_base_url, chosen_image)
    )
    state = get_hub_state()
    state["ppt_master"] = ppt_status
    return state
