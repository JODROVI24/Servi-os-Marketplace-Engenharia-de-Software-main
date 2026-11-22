"""Descoberta dinâmica e cache TTL de modelos de chat via endpoint /models."""

from __future__ import annotations

import threading
import time
from typing import Any

import requests

from pertoja.llm.providers import _dedupe_str_list, normalize_base_url

_DISCOVERED_MODELS_CACHE: dict[tuple[str, str], tuple[float, list[str]]] = {}
_DISCOVERY_LOCK = threading.Lock()
_DISCOVERY_TTL_SECONDS = 900.0

_NON_CHAT_MODEL_TOKENS = (
    "whisper",
    "tts",
    "speech",
    "audio",
    "transcribe",
    "guard",
    "safeguard",
    "moderation",
    "embed",
    "image",
    "imagen",
    "veo",
    "omni",
    "orpheus",
    "playai",
    "rerank",
    "realtime",
    "live",
)

_CHAT_MODEL_PRIORITY_TOKENS = (
    "gpt-oss-20b",
    "flash-lite",
    "gpt-oss",
    "qwen",
    "llama",
    "flash",
    "gemma",
    "mistral",
    "kimi",
    "deepseek",
)


def clear_discovered_models_cache() -> None:
    """Limpa o cache em memória de modelos descobertos via /models."""
    with _DISCOVERY_LOCK:
        _DISCOVERED_MODELS_CACHE.clear()


def _get_cached_discovered_models(provider: str, base_url: str) -> list[str]:
    key = (str(provider or ""), normalize_base_url(base_url))
    now = time.monotonic()
    with _DISCOVERY_LOCK:
        entry = _DISCOVERED_MODELS_CACHE.get(key)
        if not entry:
            return []
        expires_at, models = entry
        if expires_at <= now:
            _DISCOVERED_MODELS_CACHE.pop(key, None)
            return []
        return list(models)


def _rank_discovered_chat_model(model_id: str) -> tuple[int, str]:
    low = model_id.lower()
    for idx, token in enumerate(_CHAT_MODEL_PRIORITY_TOKENS):
        if token in low:
            return idx, low
    return len(_CHAT_MODEL_PRIORITY_TOKENS), low


def _discover_active_chat_models(
    cand: dict[str, Any],
    *,
    http_get: Any = None,
    timeout: float = 3.0,
) -> list[str]:
    """Consulta GET {base_url}/models para descobrir modelos de chat ativos e guarda em cache."""
    provider = str(cand.get("provider") or "")
    base_url = normalize_base_url(cand.get("base_url") or "")
    if not base_url:
        return []

    cached = _get_cached_discovered_models(provider, base_url)
    if cached:
        return cached

    get_fn = http_get or requests.get
    api_key = cand.get("api_key") or "freellmapi-local"
    headers = {"Authorization": f"Bearer {api_key}"}
    extra_headers = cand.get("extra_headers") or {}
    if extra_headers:
        headers.update(extra_headers)

    try:
        resp = get_fn(f"{base_url}/models", headers=headers, timeout=timeout)
        status_code = getattr(resp, "status_code", None)
        if isinstance(status_code, int) and status_code >= 400:
            return []
        body = resp.json()
    except (requests.RequestException, OSError, ValueError, TypeError, AttributeError):
        return []

    raw_items: Any = None
    if isinstance(body, dict):
        raw_items = body.get("data")
        if not isinstance(raw_items, list):
            raw_items = body.get("models")
    elif isinstance(body, list):
        raw_items = body

    if not isinstance(raw_items, list):
        return []

    chat_models: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            raw_id = item.get("id") or item.get("name") or ""
            is_active = item.get("active", True)
            if is_active is False:
                continue
        elif isinstance(item, str):
            raw_id = item
        else:
            continue

        model_id = str(raw_id or "").strip()
        if not model_id:
            continue
        if model_id.startswith("models/"):
            model_id = model_id[len("models/") :]
        low = model_id.lower()
        if any(tok in low for tok in _NON_CHAT_MODEL_TOKENS):
            continue
        chat_models.append(model_id)

    ranked = _dedupe_str_list(sorted(chat_models, key=_rank_discovered_chat_model))[:3]
    if ranked:
        with _DISCOVERY_LOCK:
            _DISCOVERED_MODELS_CACHE[(provider, base_url)] = (
                time.monotonic() + _DISCOVERY_TTL_SECONDS,
                list(ranked),
            )
    return ranked
