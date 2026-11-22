"""Blueprint de IA (health, chat de suporte sem PII e gerador de descrições)."""

import json
import os
import sqlite3
from datetime import datetime, timezone

import requests
from flask import Blueprint, current_app, jsonify, request

try:
    import openai
except ImportError:
    openai = None

from pertoja._compat import resolve_compat
from pertoja.db.connection import PG_DB_ERRORS
from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    rate_limit,
    require_active_account,
    row_get,
)
from pertoja.llm import (
    LLMUnavailableError,
    _sanitize_error_text,
    build_support_messages,
    build_support_system_prompt,
    call_llm,
    clear_last_call_meta,
    fallback_ad_description,
    fallback_chat_support_reply,
    get_active_provider_name,
    get_last_call_meta,
    get_llm_api_key,
    get_llm_base_url,
    get_llm_health_status,
    get_llm_model,
    redact_pii_for_llm,
    sanitize_history,
    sanitize_user_context_for_llm,
)
from pertoja.repositories.orders import get_order_recent_summaries

llm_bp = Blueprint("llm", __name__)


def get_llm_client_compat():
    """Retorna cliente OpenAI-compatible respeitando overrides de ambiente e módulo."""
    openai_mod = resolve_compat("app", "openai", openai)
    if openai_mod is None:
        return None
    return openai_mod.OpenAI(
        base_url=get_llm_base_url(),
        api_key=get_llm_api_key() or "freellmapi-local",
        max_retries=2,
        timeout=8.0,
    )


def call_llm_compat(messages, model, temperature, max_tokens):
    """Dispara chamada LLM via pertoja.llm honrando patches de `app.openai` e `app.requests`."""
    openai_mod = resolve_compat("app", "openai", openai)
    req_mod = resolve_compat("app", "requests", requests)
    try:
        log = current_app.logger
    except RuntimeError:
        log = None
    return call_llm(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        openai_mod=openai_mod,
        http_post=req_mod.post,
        http_get=req_mod.get,
        logger=log,
    )


def safe_llm_log_detail(exc: Exception) -> str:
    """Sanitiza detalhes de exceção removendo credenciais antes do log."""
    try:
        return _sanitize_error_text(exc)
    except (TypeError, ValueError):
        return type(exc).__name__


def build_safe_user_info(user) -> dict | None:
    """Extrai exclusivamente campos não pessoais (sem nome, e-mail, CPF ou telefone)."""
    return sanitize_user_context_for_llm(user)


def get_user_recent_orders_summary(user_id: int, limit: int = 3) -> list[dict]:
    """Busca resumo read-only dos últimos pedidos sem PII para contextualizar o suporte."""
    if not user_id:
        return []
    conn = None
    try:
        conn = compat_get_db_connection()
        return get_order_recent_summaries(conn, user_id, limit=limit)
    except (sqlite3.Error, ValueError, TypeError, RuntimeError, *PG_DB_ERRORS):
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except (sqlite3.Error, RuntimeError, AttributeError, *PG_DB_ERRORS):
                pass


def _catchable_chat_errors() -> tuple[type[BaseException], ...]:
    base: list[type[BaseException]] = [
        LLMUnavailableError,
        requests.RequestException,
        OSError,
        TimeoutError,
        ConnectionError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
    ]
    openai_mod = resolve_compat("app", "openai", openai)
    sdk_err = getattr(openai_mod, "OpenAIError", None) if openai_mod is not None else None
    if isinstance(sdk_err, type) and issubclass(sdk_err, Exception):
        base.append(sdk_err)
    return tuple(base)


@llm_bp.route("/api/chat/health", methods=["GET"])
@rate_limit(30, 60, "chat_health")
def chat_health():
    """Retorna o diagnóstico seguro do status dos provedores LLM para a UI de suporte."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória."}), 401
    err_acc = require_active_account(user)
    if err_acc:
        return err_acc
    return jsonify(get_llm_health_status()), 200


@llm_bp.route("/api/chat/support", methods=["POST"])
@rate_limit(20, 60, "chat_support")
def chat_support():
    """Endpoint de suporte: recebe dúvida e gera resposta sem envio de PII."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória."}), 401
    err_acc = require_active_account(user)
    if err_acc:
        return err_acc

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    message = str(data.get("message") or data.get("mensagem") or "").strip()
    if not message:
        return jsonify({"error": "A mensagem é obrigatória."}), 400
    if len(message) > 2000:
        return jsonify({"error": "A mensagem deve ter no máximo 2000 caracteres."}), 400

    context_parts = []
    raw_context = data.get("context")
    if raw_context is not None:
        if isinstance(raw_context, list):
            context_parts = [str(c) for c in raw_context if c]
        elif isinstance(raw_context, dict):
            context_parts.append(json.dumps(raw_context, ensure_ascii=False))
        elif raw_context:
            context_parts.append(str(raw_context))
    context_text = "\n".join(context_parts)

    history = sanitize_history(data.get("history"))
    user_info = build_safe_user_info(user)
    recent_orders = get_user_recent_orders_summary(row_get(user, "id"), limit=3)

    messages = build_support_messages(
        message=message,
        history=history,
        user_info=user_info,
        context_text=context_text,
        recent_orders=recent_orders,
    )

    model_used = get_llm_model()
    llm_caller = resolve_compat("app", "_call_llm", call_llm_compat)
    try:
        clear_last_call_meta()
        reply = llm_caller(
            messages=messages,
            model=model_used,
            temperature=0.4,
            max_tokens=800,
        )
        meta = get_last_call_meta()
        provider = meta.get("provider") or get_active_provider_name()
        actual_model = meta.get("model") or model_used
        return jsonify(
            {
                "reply": reply,
                "model": actual_model,
                "provider": provider,
                "fallback": False,
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            }
        ), 200
    except _catchable_chat_errors() as exc:
        fallback_reason = getattr(exc, "reason", None) or "provider_error"
        current_app.logger.warning(
            "Falha ao consultar LLM em /api/chat/support (motivo=%s, erro=%s): %s",
            fallback_reason,
            type(exc).__name__,
            safe_llm_log_detail(exc),
        )
        if os.environ.get("LLM_STRICT_MODE") == "1":
            return jsonify({"error": "Falha ao gerar resposta do suporte."}), 500
        reply = fallback_chat_support_reply(
            message,
            context_text,
            history=history,
            user_info=user_info,
            reason=fallback_reason,
        )
        return jsonify(
            {
                "reply": reply,
                "model": model_used,
                "provider": "fallback",
                "fallback": True,
                "fallback_reason": fallback_reason,
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            }
        ), 200


@llm_bp.route("/api/ads/generate-description", methods=["POST"])
@rate_limit(20, 60, "ads_generate_desc")
def generate_ad_description():
    """Gera descrição comercial de anúncio sem enviar PII para provedores externos."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória."}), 401
    err_acc = require_active_account(user)
    if err_acc:
        return err_acc

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    title = str(data.get("title") or data.get("titulo") or "").strip()
    if not title:
        return jsonify({"error": "O título é obrigatório."}), 400

    category = str(data.get("category") or data.get("categoria") or "").strip()
    description = str(data.get("description") or data.get("descricao") or "").strip()
    price = data.get("price") if data.get("price") is not None else data.get("preco")
    service_type = str(data.get("service_type") or data.get("tipo_servico") or "").strip()
    extra = str(data.get("extra") or data.get("observacoes") or "").strip()

    parts = ["Título: " + redact_pii_for_llm(title)]
    if category:
        parts.append("Categoria: " + redact_pii_for_llm(category))
    if price is not None and price != "":
        try:
            parts.append("Preço: R$ " + f"{float(price):.2f}")
        except (TypeError, ValueError):
            parts.append("Preço: informado")
    if service_type:
        parts.append("Tipo: " + redact_pii_for_llm(service_type))
    if description:
        parts.append("Descrição atual: " + redact_pii_for_llm(description))
    if extra:
        parts.append("Observações: " + redact_pii_for_llm(extra))
    context = "\n".join(parts)

    system_prompt = (
        "Você é um gerador de anúncios (descriptions) para o PertoJá Marketplace. "
        "Escreva uma descrição vencedora de anúncio em português do Brasil, "
        "apropriada para um anúncio de serviço, com tom atraente, claro e profissional. "
        "Máximo de ~280 caracteres. Use palavras chamativas e benefícios do serviço. "
        "Não invente preços, cidades ou categorias que não foram informados. "
        "Se faltar informação essencial, use um tom genérico e neutro."
    )
    prompt = "Seu anúncio:\n\n" + context + "\n\nDescrição do anúncio (máx ~280 chars):"

    model_used = get_llm_model()
    fallback_used = False
    fallback_reason = None
    provider = get_active_provider_name()
    llm_caller = resolve_compat("app", "_call_llm", call_llm_compat)
    try:
        clear_last_call_meta()
        generated = llm_caller(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=model_used,
            temperature=0.35,
            max_tokens=600,
        )
        meta = get_last_call_meta()
        provider = meta.get("provider") or provider
        model_used = meta.get("model") or model_used
    except _catchable_chat_errors() as exc:
        fallback_reason = getattr(exc, "reason", None) or "provider_error"
        current_app.logger.warning(
            "Falha ao consultar LLM em /api/ads/generate-description (motivo=%s, erro=%s): %s",
            fallback_reason,
            type(exc).__name__,
            safe_llm_log_detail(exc),
        )
        if os.environ.get("LLM_STRICT_MODE") == "1":
            return jsonify({"error": "Falha ao gerar a descrição do anúncio."}), 500
        generated = fallback_ad_description(
            title=title,
            category=category,
            description=description,
            price=price,
            service_type=service_type,
            extra=extra,
        )
        fallback_used = True
        provider = "fallback"

    resp_payload = {
        "generated_description": generated,
        "description": generated,
        "model_used": model_used,
        "provider": provider,
        "fallback": fallback_used,
        "title": title,
        "category": category or None,
        "price": price,
        "service_type": service_type or None,
        "length": len(generated),
    }
    if fallback_used:
        resp_payload["fallback_reason"] = fallback_reason

    return jsonify(resp_payload), 200


__all__ = [
    "build_safe_user_info",
    "build_support_system_prompt",
    "call_llm_compat",
    "get_llm_client_compat",
    "get_user_recent_orders_summary",
    "llm_bp",
    "openai",
    "safe_llm_log_detail",
]
