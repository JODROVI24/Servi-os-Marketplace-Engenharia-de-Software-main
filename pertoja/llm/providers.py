"""Configuração de provedores LLM oficiais (OpenAI, Gemini) e cadeia de failover."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_FREELM_BASE_URL = "http://localhost:3001/v1"
DEFAULT_FREELM_MODEL = "auto"

VALID_UNAVAILABLE_REASONS = (
    "unconfigured",
    "localhost_in_serverless",
    "auth_error",
    "model_not_found",
    "rate_limited",
    "timeout",
    "connection_error",
    "provider_error",
)

_REASON_PRIORITY = {
    "auth_error": 1,
    "rate_limited": 2,
    "model_not_found": 3,
    "timeout": 4,
    "connection_error": 5,
    "provider_error": 6,
    "localhost_in_serverless": 7,
    "unconfigured": 8,
}

_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

_CLOUD_KEY_ENV_ORDER = (
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "CEREBRAS_API_KEY",
    "MISTRAL_API_KEY",
    "APIFREELLM_API_KEY",
    "GITHUB_MODELS_TOKEN",
)


@dataclass(frozen=True)
class _CloudProviderSpec:
    name: str
    env_keys: tuple[str, ...]
    base_url: str
    default_model: str
    fallback_models: tuple[str, ...] = ()
    protocol: str = "openai"
    extra_headers: dict[str, str] = field(default_factory=dict)


# Provedores cloud: OpenAI oficial e Gemini/Groq/OpenRouter/etc. (ordem preserva compatibilidade)
_CLOUD_PROVIDERS: tuple[_CloudProviderSpec, ...] = (
    _CloudProviderSpec(
        name="openai",
        env_keys=("OPENAI_API_KEY",),
        base_url=DEFAULT_OPENAI_BASE_URL,
        default_model="gpt-4o-mini",
        fallback_models=("gpt-4.1-mini",),
    ),
    _CloudProviderSpec(
        name="groq",
        env_keys=("GROQ_API_KEY",),
        base_url="https://api.groq.com/openai/v1",
        default_model="openai/gpt-oss-20b",
        fallback_models=("openai/gpt-oss-120b", "qwen/qwen3.8-27b"),
    ),
    _CloudProviderSpec(
        name="gemini",
        env_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-3.5-flash-lite",
        fallback_models=("gemini-3.1-flash-lite", "gemini-3.8-flash"),
    ),
    _CloudProviderSpec(
        name="openrouter",
        env_keys=("OPENROUTER_API_KEY",),
        base_url="https://openrouter.ai/api/v1",
        default_model="openrouter/free",
        fallback_models=("meta-llama/llama-3.3-70b-instruct:free",),
        extra_headers={
            "HTTP-Referer": "https://pertoja.vercel.app",
            "X-Title": "PertoJa Marketplace",
        },
    ),
    _CloudProviderSpec(
        name="cerebras",
        env_keys=("CEREBRAS_API_KEY",),
        base_url="https://api.cerebras.ai/v1",
        default_model="llama-3.3-70b",
    ),
    _CloudProviderSpec(
        name="mistral",
        env_keys=("MISTRAL_API_KEY",),
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
    ),
    _CloudProviderSpec(
        name="apifreellm",
        env_keys=("APIFREELLM_API_KEY",),
        base_url="https://apifreellm.com/api/v1/chat",
        default_model="free-ai",
        protocol="apifreellm",
    ),
    _CloudProviderSpec(
        name="github-models",
        env_keys=("GITHUB_MODELS_TOKEN",),
        base_url="https://models.inference.ai.azure.com",
        default_model="gpt-4o-mini",
    ),
)

_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "freellmapi": DEFAULT_FREELM_MODEL,
    "none": DEFAULT_FREELM_MODEL,
    **{spec.name: spec.default_model for spec in _CLOUD_PROVIDERS},
}

_SECRET_PATTERNS = (
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\b(gsk_|AIza|sk-or-|sk-|csk-|apf_|ghp_|github_pat_|freellmapi-)[A-Za-z0-9._\-]{4,}"),
    re.compile(r"((?:api[_-]?key|token|authorization)\s*[=:]\s*)[^\s,;]+", re.IGNORECASE),
)


def _env_str(name: str) -> str:
    val = os.environ.get(name)
    return str(val).strip() if val is not None else ""


def _dedupe_str_list(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = str(item or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _sanitize_error_text(text: Any, extra_secrets: list[str] | None = None) -> str:
    """Remove segredos e trunca mensagens de erro antes de gravar em log."""
    clean = str(text or "").strip()
    if not clean:
        return ""

    secret_values: list[str] = []
    if extra_secrets:
        secret_values.extend(s for s in extra_secrets if s and len(s) >= 6)
    for env_name in ("FREELLM_API_KEY", *_CLOUD_KEY_ENV_ORDER):
        val = _env_str(env_name)
        if val and len(val) >= 6:
            secret_values.append(val)

    for secret in secret_values:
        if secret in clean:
            clean = clean.replace(secret, "***")

    for pattern in _SECRET_PATTERNS:
        clean = pattern.sub(r"\1***", clean)

    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > 240:
        clean = clean[:237].rstrip() + "..."
    return clean


def is_serverless_env() -> bool:
    """Retorna True quando executado em ambiente serverless (Vercel / AWS Lambda)."""
    for env_name in ("VERCEL", "VERCEL_ENV", "AWS_LAMBDA_FUNCTION_NAME"):
        val = _env_str(env_name)
        if not val:
            continue
        if env_name in ("VERCEL", "VERCEL_ENV") and val.lower() in ("0", "false", "no", "off"):
            continue
        return True
    return False


def is_localhost_url(url: str) -> bool:
    """Retorna True se a URL aponta para localhost, 127.0.0.1, 0.0.0.0 ou ::1."""
    raw = str(url or "").strip()
    if not raw:
        return False
    target = raw if "://" in raw else f"http://{raw}"
    try:
        parsed = urlparse(target)
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    return host in _LOCALHOST_HOSTS or host.endswith(".localhost")


def normalize_base_url(raw: str) -> str:
    """Normaliza URL base removendo espaços, '/' final e sufixo '/chat/completions'."""
    s = str(raw or "").strip()
    if not s:
        return ""
    s = s.rstrip("/")
    if s.lower().endswith("/chat/completions"):
        s = s[: -len("/chat/completions")]
    return s.rstrip("/")


def _first_configured_cloud_spec() -> tuple[_CloudProviderSpec, str] | None:
    for spec in _CLOUD_PROVIDERS:
        for env_key in spec.env_keys:
            val = _env_str(env_key)
            if val:
                return spec, val
    return None


def _detect_explicit_provider_name(url: str, key: str) -> str:
    low_url = (url or "").lower()
    if "api.openai.com" in low_url:
        return "openai"
    if "generativelanguage.googleapis.com" in low_url:
        return "gemini"
    if "apifreellm.com" in low_url or (key or "").startswith("apf_"):
        return "apifreellm"
    return "freellmapi"


def get_llm_base_url() -> str:
    """Retorna URL base prioritária normalizada, priorizando provedores cloud/oficiais."""
    explicit = _env_str("FREELLM_API_BASE_URL") or _env_str("OPENAI_BASE_URL")
    if explicit:
        return normalize_base_url(explicit)
    cloud = _first_configured_cloud_spec()
    if cloud is not None:
        return normalize_base_url(cloud[0].base_url)
    return DEFAULT_OPENAI_BASE_URL


def get_llm_api_key() -> str:
    """Retorna a API key conforme precedência entre URL explícita e provedores oficiais/cloud."""
    has_explicit_base = bool(_env_str("FREELLM_API_BASE_URL") or _env_str("OPENAI_BASE_URL"))
    explicit_key = _env_str("FREELLM_API_KEY") or _env_str("OPENAI_API_KEY")
    if has_explicit_base:
        return explicit_key
    if explicit_key:
        return explicit_key
    for env_name in _CLOUD_KEY_ENV_ORDER:
        val = _env_str(env_name)
        if val:
            return val
    return ""


def get_active_provider_name() -> str:
    """Retorna o nome do provedor primário ativo ou 'none' quando não configurado."""
    candidates, _ = resolve_provider_chain()
    if candidates:
        return candidates[0]["provider"]
    explicit_url = normalize_base_url(_env_str("FREELLM_API_BASE_URL") or _env_str("OPENAI_BASE_URL"))
    if explicit_url:
        explicit_key = _env_str("FREELLM_API_KEY") or _env_str("OPENAI_API_KEY")
        return _detect_explicit_provider_name(explicit_url, explicit_key)
    cloud = _first_configured_cloud_spec()
    if cloud is not None:
        return cloud[0].name
    return "none"


def get_llm_model() -> str:
    """Retorna o modelo padrão configurado ou o default do provedor ativo."""
    explicit_model = _env_str("LLM_MODEL") or _env_str("LLAMA_MODEL")
    if explicit_model:
        return explicit_model
    provider = get_active_provider_name()
    return _PROVIDER_DEFAULT_MODELS.get(provider, DEFAULT_FREELM_MODEL)


def _is_auto_placeholder(model: str) -> bool:
    low = (model or "").strip().lower()
    return low == "auto" or low.startswith("auto:")


def _build_primary_model_and_fallbacks(
    provider: str,
    default_model: str,
    base_fallbacks: tuple[str, ...],
    explicit_model: str,
    env_model: str,
) -> tuple[str, list[str]]:
    if provider == "freellmapi":
        chosen = explicit_model or env_model or default_model
        fb = ["auto", "auto:balanced"] if chosen != "auto" else []
        return chosen, [m for m in _dedupe_str_list(fb) if m != chosen]

    if explicit_model and not _is_auto_placeholder(explicit_model):
        chosen = explicit_model
    elif env_model and not _is_auto_placeholder(env_model):
        chosen = env_model
    else:
        chosen = default_model

    fb_pool = [default_model, *base_fallbacks] if chosen != default_model else list(base_fallbacks)
    fallbacks = [m for m in _dedupe_str_list(fb_pool) if m != chosen]
    return chosen, fallbacks


def resolve_provider_chain(explicit_model: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Monta a cadeia ordenada de candidatos LLM priorizando APIs oficiais e cloud."""
    clean_explicit = str(explicit_model or "").strip()
    env_model = _env_str("LLM_MODEL") or _env_str("LLAMA_MODEL")
    serverless = is_serverless_env()

    candidates: list[dict[str, Any]] = []
    skip_reasons: list[str] = []

    raw_base_url = _env_str("FREELLM_API_BASE_URL") or _env_str("OPENAI_BASE_URL")
    if raw_base_url:
        norm_url = normalize_base_url(raw_base_url)
        if serverless and is_localhost_url(norm_url):
            skip_reasons.append("localhost_in_serverless")
        elif norm_url:
            explicit_key = _env_str("FREELLM_API_KEY") or _env_str("OPENAI_API_KEY")
            provider_name = _detect_explicit_provider_name(norm_url, explicit_key)
            protocol = "apifreellm" if "apifreellm.com" in norm_url.lower() else "openai"
            default_for_provider = _PROVIDER_DEFAULT_MODELS.get(provider_name, DEFAULT_FREELM_MODEL)
            model_name, fallbacks = _build_primary_model_and_fallbacks(
                provider=provider_name,
                default_model=default_for_provider,
                base_fallbacks=(),
                explicit_model=clean_explicit,
                env_model=env_model,
            )
            candidates.append(
                {
                    "provider": provider_name,
                    "base_url": norm_url,
                    "api_key": explicit_key or "freellmapi-local",
                    "model": model_name,
                    "fallback_models": fallbacks,
                    "protocol": protocol,
                    "extra_headers": {},
                }
            )

    seen_endpoints = {(c["base_url"], c["api_key"]) for c in candidates}

    for spec in _CLOUD_PROVIDERS:
        api_key = ""
        for env_key in spec.env_keys:
            val = _env_str(env_key)
            if val:
                api_key = val
                break
        if not api_key:
            continue

        norm_cloud_url = normalize_base_url(spec.base_url)
        if (norm_cloud_url, api_key) in seen_endpoints:
            continue

        is_primary = len(candidates) == 0
        if is_primary:
            model_name, fallbacks = _build_primary_model_and_fallbacks(
                provider=spec.name,
                default_model=spec.default_model,
                base_fallbacks=spec.fallback_models,
                explicit_model=clean_explicit,
                env_model=env_model,
            )
        else:
            model_name = spec.default_model
            fallbacks = [m for m in _dedupe_str_list(spec.fallback_models) if m != model_name]

        candidates.append(
            {
                "provider": spec.name,
                "base_url": norm_cloud_url,
                "api_key": api_key,
                "model": model_name,
                "fallback_models": fallbacks,
                "protocol": spec.protocol,
                "extra_headers": dict(spec.extra_headers),
            }
        )
        seen_endpoints.add((norm_cloud_url, api_key))

    if not candidates and "localhost_in_serverless" not in skip_reasons:
        skip_reasons.append("unconfigured")

    return candidates, _dedupe_str_list(skip_reasons)
