"""Cliente LLM multi-provedor com failover, descoberta de modelos e health check."""

from __future__ import annotations

import threading
from typing import Any

import requests

from pertoja.llm.discovery import (
    _discover_active_chat_models,
    _get_cached_discovered_models,
)
from pertoja.llm.pii import redact_pii_for_llm
from pertoja.llm.providers import (
    _REASON_PRIORITY,
    VALID_UNAVAILABLE_REASONS,
    _dedupe_str_list,
    _sanitize_error_text,
    get_llm_model,
    is_serverless_env,
    resolve_provider_chain,
)

_LAST_CALL_META = threading.local()

__all_discovery__ = (
    "_discover_active_chat_models",
    "_get_cached_discovered_models",
    "_rank_discovered_chat_model",
    "clear_discovered_models_cache",
)


class LLMUnavailableError(RuntimeError):
    """Erro lançado quando nenhum provedor LLM pôde atender à requisição."""

    def __init__(self, reason: str = "provider_error", detail: str = ""):
        clean_reason = reason if reason in VALID_UNAVAILABLE_REASONS else "provider_error"
        self.reason = clean_reason
        self.detail = str(detail or "").strip()
        msg = f"{clean_reason}: {self.detail}" if self.detail else clean_reason
        super().__init__(msg)


def clear_last_call_meta() -> None:
    """Limpa metadados da última chamada LLM na thread atual."""
    _LAST_CALL_META.meta = {}


def get_last_call_meta() -> dict[str, str]:
    """Retorna metadados {'provider', 'model'} da última chamada LLM bem-sucedida."""
    meta = getattr(_LAST_CALL_META, "meta", None)
    return dict(meta) if isinstance(meta, dict) else {}


def _extract_status_code(exc: Exception) -> int | None:
    sc = getattr(exc, "status_code", None)
    if isinstance(sc, int):
        return sc
    resp = getattr(exc, "response", None)
    sc_resp = getattr(resp, "status_code", None)
    if isinstance(sc_resp, int):
        return sc_resp
    return None


def _extract_response_error_snippet(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    if resp is not None:
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return str(exc or "")


def _classify_exception(exc: Exception) -> str:
    type_name = type(exc).__name__.lower()
    status_code = _extract_status_code(exc)
    detail_lower = _extract_response_error_snippet(exc).lower()

    if status_code in (401, 403) or any(t in type_name for t in ("authenticationerror", "permissiondeniederror")):
        return "auth_error"

    if status_code == 429 or "ratelimit" in type_name:
        return "rate_limited"

    if status_code == 404 or "notfounderror" in type_name:
        return "model_not_found"

    if status_code == 400 or "badrequesterror" in type_name:
        model_hints = (
            "model",
            "not found",
            "does not exist",
            "invalid_model",
            "unknown model",
            "decommissioned",
            "unsupported",
        )
        if any(h in detail_lower for h in model_hints):
            return "model_not_found"
        return "provider_error"

    if (
        status_code in (408, 504)
        or isinstance(exc, (TimeoutError, requests.exceptions.Timeout))
        or "timeout" in type_name
        or "timed out" in detail_lower
    ):
        return "timeout"

    if isinstance(exc, (ConnectionError, requests.exceptions.ConnectionError)) or (
        "connection" in type_name and "timeout" not in type_name
    ):
        return "connection_error"

    if any(k in detail_lower for k in ("unauthorized", "invalid api key", "authentication failed", "401", "403")):
        return "auth_error"
    if any(k in detail_lower for k in ("rate limit", "too many requests", "quota exceeded", "429")):
        return "rate_limited"
    if any(k in detail_lower for k in ("model not found", "does not exist", "unknown model")):
        return "model_not_found"
    if any(
        k in detail_lower
        for k in ("connection refused", "failed to establish a new connection", "name or service not known")
    ):
        return "connection_error"

    return "provider_error"


def _extract_openai_sdk_content(resp: Any) -> str:
    choices = getattr(resp, "choices", None)
    if not choices and isinstance(resp, dict):
        return _extract_json_content(resp, protocol="openai")
    if not choices:
        raise ValueError("Resposta do SDK sem choices.")
    msg = getattr(choices[0], "message", None)
    content = getattr(msg, "content", None) if msg is not None else None
    text = str(content or "").strip()
    if not text:
        raise ValueError("Resposta do LLM vazia.")
    return text


def _extract_json_content(body: Any, protocol: str = "openai") -> str:
    if not isinstance(body, dict):
        raise ValueError("Resposta JSON inválida do provedor LLM.")

    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict) and msg.get("content"):
                text = str(msg["content"]).strip()
                if text:
                    return text
            if first.get("text"):
                text = str(first["text"]).strip()
                if text:
                    return text

    if protocol == "apifreellm":
        for key in ("response", "reply", "message", "text", "content"):
            val = body.get(key)
            if isinstance(val, dict) and val.get("content"):
                val = val["content"]
            if isinstance(val, str) and val.strip():
                return val.strip()

    if body.get("error"):
        err_obj = body["error"]
        err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
        raise ValueError(f"Erro retornado pelo provedor: {err_msg}")

    raise ValueError("Resposta do provedor LLM sem conteúdo textual.")


def _flatten_messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            parts.append(f"[Instruções]\n{content}")
        elif role == "assistant":
            parts.append(f"Assistente: {content}")
        else:
            parts.append(f"Usuário: {content}")
    return "\n\n".join(parts)


def _redact_outbound_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        sanitized.append({**msg, "content": redact_pii_for_llm(msg.get("content", ""))})
    return sanitized


def _invoke_candidate(
    cand: dict[str, Any],
    model_name: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_retries: int,
    openai_mod: Any,
    http_post: Any,
) -> str:
    protocol = cand.get("protocol", "openai")
    api_key = cand.get("api_key") or "freellmapi-local"
    extra_headers = cand.get("extra_headers") or {}
    is_gemini_thinking = cand.get("provider") == "gemini" and str(model_name or "").startswith(("gemini-3", "gemini-4"))
    effective_max_tokens = max(int(max_tokens), 1200) if is_gemini_thinking else max_tokens

    if protocol == "openai" and openai_mod is not None:
        client_kwargs: dict[str, Any] = {
            "base_url": cand["base_url"],
            "api_key": api_key,
            "max_retries": max_retries,
            "timeout": timeout,
        }
        if extra_headers:
            client_kwargs["default_headers"] = dict(extra_headers)
        client = openai_mod.OpenAI(**client_kwargs)
        create_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
        if is_gemini_thinking:
            create_kwargs["reasoning_effort"] = "minimal"
        resp = client.chat.completions.create(**create_kwargs)
        return _extract_openai_sdk_content(resp)

    post_fn = http_post or requests.post
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        headers.update(extra_headers)

    if protocol == "apifreellm":
        base = cand["base_url"].rstrip("/")
        endpoint = base if base.lower().endswith(("/chat", "/chat/completions")) else f"{base}/chat"
        payload: dict[str, Any] = {
            "message": _flatten_messages_to_prompt(messages),
            "messages": messages,
            "model": model_name,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
    else:
        endpoint = f"{cand['base_url']}/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
        if is_gemini_thinking:
            payload["reasoning_effort"] = "minimal"

    resp = post_fn(endpoint, json=payload, headers=headers, timeout=timeout)
    status_code = getattr(resp, "status_code", None)
    if isinstance(status_code, int) and status_code >= 400:
        raise requests.exceptions.HTTPError(
            f"HTTP {status_code} ao chamar {cand['provider']}",
            response=resp,
        )
    resp.raise_for_status()
    body = resp.json()
    return _extract_json_content(body, protocol=protocol)


def _catchable_invoke_errors(openai_mod: Any) -> tuple[type[BaseException], ...]:
    errors: list[type[BaseException]] = [
        requests.RequestException,
        OSError,
        TimeoutError,
        ConnectionError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
    ]
    sdk_base = getattr(openai_mod, "OpenAIError", None) if openai_mod is not None else None
    if isinstance(sdk_base, type) and issubclass(sdk_base, Exception):
        errors.append(sdk_base)
    return tuple(errors)


def call_llm(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 800,
    *,
    openai_mod: Any = None,
    http_post: Any = None,
    http_get: Any = None,
    logger: Any = None,
) -> str:
    """Executa chamada ao LLM percorrendo provedores e modelos fallback com redação de PII."""
    clear_last_call_meta()

    candidates, skip_reasons = resolve_provider_chain(explicit_model=model)
    if not candidates:
        reason = "localhost_in_serverless" if "localhost_in_serverless" in skip_reasons else "unconfigured"
        detail = (
            "URL localhost ignorada em ambiente serverless sem provedor cloud configurado."
            if reason == "localhost_in_serverless"
            else "Nenhum provedor LLM configurado no ambiente."
        )
        if logger is not None:
            logger.warning("LLM indisponível (%s): %s", reason, detail)
        raise LLMUnavailableError(reason, detail)

    safe_messages = _redact_outbound_messages(messages)
    serverless = is_serverless_env()
    timeout = 10.0 if serverless else 15.0
    max_retries = 0 if serverless else 2
    catchable = _catchable_invoke_errors(openai_mod)

    failures: list[tuple[int, str, str]] = []
    if "localhost_in_serverless" in skip_reasons:
        failures.append(
            (
                _REASON_PRIORITY["localhost_in_serverless"],
                "localhost_in_serverless",
                "Gateway localhost ignorado em serverless.",
            )
        )

    for cand in candidates:
        provider = cand["provider"]
        protocol = cand.get("protocol", "openai")
        secrets = [cand.get("api_key", "")]
        cached_discovered = _get_cached_discovered_models(provider, cand["base_url"]) if protocol == "openai" else []
        models_to_try = _dedupe_str_list([*cached_discovered, cand["model"], *cand.get("fallback_models", [])])
        tried_models: set[str] = set()
        all_model_not_found = True
        timeout_retries = 0

        for idx, try_model in enumerate(models_to_try):
            tried_models.add(try_model)
            try:
                text = _invoke_candidate(
                    cand=cand,
                    model_name=try_model,
                    messages=safe_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    max_retries=max_retries,
                    openai_mod=openai_mod,
                    http_post=http_post,
                )
                _LAST_CALL_META.meta = {"provider": provider, "model": try_model}
                return text
            except catchable as exc:
                reason = _classify_exception(exc)
                if reason != "model_not_found":
                    all_model_not_found = False
                safe_detail = _sanitize_error_text(_extract_response_error_snippet(exc) or exc, secrets)
                failures.append((_REASON_PRIORITY.get(reason, 99), reason, f"{provider}/{try_model}: {safe_detail}"))
                if logger is not None:
                    logger.warning(
                        "Falha no provedor LLM %s (modelo=%s, motivo=%s): %s",
                        provider,
                        try_model,
                        reason,
                        safe_detail or "erro sem detalhe",
                    )
                if reason in ("model_not_found", "rate_limited") and idx + 1 < len(models_to_try):
                    continue
                if reason == "timeout" and timeout_retries < 1 and idx + 1 < len(models_to_try):
                    timeout_retries += 1
                    continue
                break

        if all_model_not_found and protocol == "openai":
            discovered = _discover_active_chat_models(cand, http_get=http_get)
            extra_models = [m for m in discovered if m not in tried_models][:2]
            for extra_model in extra_models:
                tried_models.add(extra_model)
                try:
                    text = _invoke_candidate(
                        cand=cand,
                        model_name=extra_model,
                        messages=safe_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=timeout,
                        max_retries=max_retries,
                        openai_mod=openai_mod,
                        http_post=http_post,
                    )
                    _LAST_CALL_META.meta = {"provider": provider, "model": extra_model}
                    return text
                except catchable as exc:
                    reason = _classify_exception(exc)
                    safe_detail = _sanitize_error_text(_extract_response_error_snippet(exc) or exc, secrets)
                    failures.append(
                        (_REASON_PRIORITY.get(reason, 99), reason, f"{provider}/{extra_model}: {safe_detail}")
                    )
                    if logger is not None:
                        logger.warning(
                            "Falha no provedor LLM %s (modelo=%s, motivo=%s): %s",
                            provider,
                            extra_model,
                            reason,
                            safe_detail or "erro sem detalhe",
                        )
                    if reason in ("model_not_found", "rate_limited"):
                        continue
                    break

    if failures:
        failures.sort(key=lambda item: item[0])
        _, best_reason, best_detail = failures[0]
    else:
        best_reason, best_detail = "provider_error", "Falha desconhecida ao chamar LLM."
    raise LLMUnavailableError(best_reason, best_detail)


def get_llm_health_status() -> dict[str, Any]:
    """Retorna diagnóstico seguro do estado dos provedores LLM (sem vazar chaves ou URLs)."""
    serverless = is_serverless_env()
    candidates, skip_reasons = resolve_provider_chain()
    available = [c["provider"] for c in candidates]
    configured = bool(candidates)
    mode = "live" if configured else "fallback"
    active_provider = candidates[0]["provider"] if candidates else "none"
    model = candidates[0]["model"] if candidates else get_llm_model()

    warning: str | None = None
    if "localhost_in_serverless" in skip_reasons:
        if configured:
            warning = (
                "FREELLM_API_BASE_URL aponta para localhost e foi ignorado em ambiente serverless; "
                f"usando {active_provider}."
            )
        else:
            warning = (
                "FREELLM_API_BASE_URL aponta para localhost (inacessível na Vercel/serverless) "
                "e nenhuma chave de API oficial/cloud está configurada."
            )
    elif not configured:
        warning = "Nenhum provedor LLM oficial configurado neste ambiente; operando em fallback local."

    if configured:
        if active_provider == "freellmapi" and not serverless:
            hint = "Gateway local explícito ativo (recomendamos OPENAI_API_KEY ou GEMINI_API_KEY em produção)."
        else:
            hint = f"Provedor {active_provider} ativo com modelo {model}."
    else:
        hint = (
            "Configure OPENAI_API_KEY (OpenAI oficial) ou GEMINI_API_KEY / GROQ_API_KEY nas "
            "variáveis de ambiente para ativar a IA online."
        )

    return {
        "configured": configured,
        "mode": mode,
        "active_provider": active_provider,
        "model": model,
        "available_providers": available,
        "serverless": serverless,
        "warning": warning,
        "hint": hint,
    }
