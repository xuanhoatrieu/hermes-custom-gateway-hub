"""FastAPI routes for `custom-gateway-hub` (v1.1.0), mounted at `/api/plugins/custom-gateway-hub/`.

Endpoints:
  - `GET /state`  — Current endpoint config, first-run `needs_setup` flag, active Content & Image models,
                    cached model lists, proxy HTTP 502 guard state, and ppt-master sync status.
  - `POST /check` — Live `/v1/models` connection test + automatic Chat vs Image model discovery & persistence.
  - `POST /apply` — Zero-touch save for Content Model, Image Model, Endpoint/API Key, Proxy HTTP 502 guard,
                    Desktop model visibility normalization, and `ppt-master/.env` sync.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from functools import partial
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

_CORE_MODULE_NAME = "_custom_gateway_hub_core"


def _load_core():
    existing = sys.modules.get(_CORE_MODULE_NAME)
    core_path = Path(__file__).resolve().parent.parent / "gateway_core.py"
    if existing is not None and getattr(existing, "__file__", None) == str(core_path):
        return existing
    spec = importlib.util.spec_from_file_location(_CORE_MODULE_NAME, core_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load gateway_core from {core_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_CORE_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def _emit_gateway_event(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from tui_gateway.plugin_events import broadcast_plugin_event

        broadcast_plugin_event("custom-gateway-hub", event_name, payload)
    except Exception as exc:
        logger.debug("broadcast_plugin_event skipped (%s): %s", event_name, exc)


class CheckConnectionPayload(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_mode: Optional[str] = None
    persist: bool = True


class ApplySettingsPayload(BaseModel):
    content_model: Optional[str] = None
    image_model: Optional[str] = None
    base_url: Optional[str] = None
    api_mode: Optional[str] = None
    api_key: Optional[str] = None
    sync_ppt_master: bool = True
    ensure_proxy_image_hint: Optional[bool] = True


@router.get("/state")
async def get_state() -> dict[str, Any]:
    core = _load_core()
    return await asyncio.to_thread(core.get_hub_state)


@router.post("/check")
async def check_connection(body: CheckConnectionPayload) -> dict[str, Any]:
    core = _load_core()
    result = await asyncio.to_thread(
        partial(
            core.probe_gateway_models,
            base_url=body.base_url,
            api_key=body.api_key,
            api_mode=body.api_mode,
            persist=body.persist,
        )
    )
    if result.get("ok"):
        _emit_gateway_event(
            "models.synced",
            {
                "total_models": result.get("total_models", 0),
                "chat_count": result.get("discovered_chat_count", 0),
                "image_count": result.get("discovered_image_count", 0),
                "new_chat_models": result.get("new_chat_models", []),
                "new_image_models": result.get("new_image_models", []),
                "latency_ms": result.get("latency_ms"),
            },
        )
    return result


@router.post("/apply")
async def apply_settings(body: ApplySettingsPayload) -> dict[str, Any]:
    core = _load_core()
    result = await asyncio.to_thread(
        partial(
            core.apply_hub_settings,
            content_model=body.content_model,
            image_model=body.image_model,
            base_url=body.base_url,
            api_mode=body.api_mode,
            api_key=body.api_key,
            sync_ppt_master=body.sync_ppt_master,
            ensure_proxy_image_hint=body.ensure_proxy_image_hint,
        )
    )
    _emit_gateway_event(
        "config.updated",
        {
            "active_content_model": result.get("active_content_model"),
            "active_image_model": result.get("active_image_model"),
            "base_url": result.get("base_url"),
        },
    )
    return result
