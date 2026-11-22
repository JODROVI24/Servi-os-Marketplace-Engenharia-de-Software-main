"""Redação e filtragem de dados pessoais (PII) antes de chamadas a provedores LLM."""

from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_CPF_RE = re.compile(r"(?:\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b)")
_CNPJ_RE = re.compile(r"(?:\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|\b\d{14}\b)")
_PHONE_RE = re.compile(
    r"(?:\+?55\s*)?(?:\(\d{2}\)\s*\d{4,5}[-\s]?\d{4}|\b\d{2}\s+9?\d{4}[-\s]?\d{4}\b|\b9\d{4}-\d{4}\b)"
)
_CEP_RE = re.compile(r"\b\d{5}-\d{3}\b")


def redact_pii_for_llm(text: Any) -> str:
    """Remove ou mascara PII (e-mail, CPF, CNPJ, telefone e CEP) antes de envio externo ao LLM."""
    raw = str(text or "")
    if not raw:
        return ""
    cleaned = _EMAIL_RE.sub("[email removido]", raw)
    cleaned = _CNPJ_RE.sub("[cnpj removido]", cleaned)
    cleaned = _CPF_RE.sub("[cpf removido]", cleaned)
    cleaned = _PHONE_RE.sub("[telefone removido]", cleaned)
    cleaned = _CEP_RE.sub("[cep removido]", cleaned)
    return cleaned


def sanitize_user_context_for_llm(user_info: Any) -> dict[str, Any] | None:
    """Mantém apenas metadados não-PII da sessão (perfil, plano, kyc_tier), descartando nome/CPF/e-mail."""
    if user_info is None:
        return None

    def _get(field: str, default: Any = None) -> Any:
        if isinstance(user_info, dict):
            return user_info.get(field, default)
        try:
            return user_info[field]
        except (KeyError, IndexError, TypeError):
            return getattr(user_info, field, default)

    tipo = str(_get("tipo", "") or _get("perfil", "") or "").strip()[:30]
    plano = str(_get("plano", "") or "").strip()[:30]
    kyc_tier = _get("kyc_tier")

    meta: dict[str, Any] = {}
    if tipo:
        meta["tipo"] = tipo
    if plano and tipo == "prestador":
        meta["plano"] = plano
    if kyc_tier is not None and tipo == "prestador":
        meta["kyc_tier"] = kyc_tier
    return meta or None
