"""Política de senhas e checagem k-anonymity via HaveIBeenPwned."""

import hashlib

import requests
from flask import current_app

from pertoja._compat import resolve_compat
from pertoja.config import HIBP_RANGE_API_URL, HIBP_TIMEOUT_SECONDS, MIN_PASSWORD_LENGTH
from pertoja.logging_config import get_logger

_logger = get_logger("pertoja.services.passwords")


def is_password_pwned(password: str) -> bool:
    """Verifica via k-anonymity no HaveIBeenPwned enviando apenas os 5 primeiros hex do SHA-1."""
    if not password:
        return False
    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1_hex[:5], sha1_hex[5:]
    req_mod = resolve_compat("app", "requests", requests)
    try:
        resp = req_mod.get(
            f"{HIBP_RANGE_API_URL}{prefix}",
            headers={"User-Agent": "PertoJa-Marketplace/2.0", "Add-Padding": "true"},
            timeout=HIBP_TIMEOUT_SECONDS,
        )
        if getattr(resp, "status_code", None) != 200:
            return False
        for line in (resp.text or "").splitlines():
            if ":" not in line:
                continue
            cand_suffix, count_str = line.split(":", 1)
            if cand_suffix.strip().upper() == suffix:
                try:
                    return int(count_str.strip()) > 0
                except ValueError:
                    return False
        return False
    except (requests.RequestException, OSError, ValueError, TypeError) as exc:
        try:
            current_app.logger.warning(
                "Falha ao consultar HaveIBeenPwned (fallback gracioso): %s",
                type(exc).__name__,
                extra={"event": "hibp_fallback", "error_type": type(exc).__name__},
            )
        except RuntimeError:
            _logger.warning("Falha ao consultar HaveIBeenPwned (%s)", type(exc).__name__)
        return False


def validate_password_policy(password: str, field_label: str = "A senha"):
    """Valida comprimento mínimo (>= 10 caracteres) e checagem HaveIBeenPwned."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return (
            f"{field_label} deve conter no mínimo {MIN_PASSWORD_LENGTH} caracteres.",
            "PASSWORD_TOO_SHORT",
        )
    hibp_enabled = current_app.config.get("HIBP_CHECK_ENABLED")
    if hibp_enabled is None:
        hibp_enabled = not current_app.config.get("TESTING", False)
    if hibp_enabled and is_password_pwned(password):
        return (
            f"{field_label} escolhida aparece em vazamentos públicos de dados. Por favor, escolha uma senha diferente e mais forte.",
            "PASSWORD_PWNED",
        )
    return None, None
