"""Serviço de notificações transacionais (e-mail e OTP SMS/WhatsApp)."""

import os
from email.utils import parseaddr

import requests

from pertoja.config import is_production_runtime
from pertoja.logging_config import get_logger

_logger = get_logger("pertoja.services.notifications")
_HTTP_TIMEOUT_SECONDS = 5


def _parse_sender(mail_from: str) -> dict[str, str]:
    """Converte cabeçalho MAIL_FROM no formato esperado pelo SendGrid."""
    name, addr = parseaddr(mail_from)
    sender: dict[str, str] = {"email": addr or mail_from}
    if name:
        sender["name"] = name
    return sender


def send_transactional_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str = "",
) -> dict:
    """Envia e-mail transacional via Resend, SendGrid ou outbox estruturado local."""
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    sendgrid_key = os.environ.get("SENDGRID_API_KEY", "").strip()
    mail_from = (os.environ.get("MAIL_FROM") or "PertoJá <no-reply@pertoja.com.br>").strip()

    if resend_key:
        provider = "resend"
        payload = {
            "from": mail_from,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        if text_body:
            payload["text"] = text_body
        try:
            resp = requests.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return {"sent": True, "provider": provider, "status_code": resp.status_code}
        except (requests.RequestException, ValueError, TypeError, OSError) as exc:
            _logger.warning(
                "Falha ao enviar e-mail transacional.",
                extra={"event": "email_send_failed", "provider": provider, "error_type": type(exc).__name__},
            )
            return {"sent": False, "provider": provider, "error": type(exc).__name__}

    if sendgrid_key:
        provider = "sendgrid"
        content = []
        if text_body:
            content.append({"type": "text/plain", "value": text_body})
        content.append({"type": "text/html", "value": html_body})
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": _parse_sender(mail_from),
            "subject": subject,
            "content": content,
        }
        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"},
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return {"sent": True, "provider": provider, "status_code": resp.status_code}
        except (requests.RequestException, ValueError, TypeError, OSError) as exc:
            _logger.warning(
                "Falha ao enviar e-mail transacional.",
                extra={"event": "email_send_failed", "provider": provider, "error_type": type(exc).__name__},
            )
            return {"sent": False, "provider": provider, "error": type(exc).__name__}

    _logger.info(
        "E-mail transacional simulado em ambiente local.",
        extra={"event": "email_simulated_dev", "subject": subject},
    )
    return {"sent": True, "provider": "local_outbox"}


def send_phone_otp(telefone: str, code: str, canal: str = "sms") -> dict:
    """Envia código OTP via WhatsApp API, SMS webhook ou simulação local."""
    canal_norm = str(canal or "sms").strip().lower()
    if canal_norm not in ("sms", "whatsapp"):
        canal_norm = "sms"

    whatsapp_url = os.environ.get("WHATSAPP_API_URL", "").strip()
    sms_url = os.environ.get("SMS_WEBHOOK_URL", "").strip()

    if canal_norm == "whatsapp" and whatsapp_url:
        provider = "whatsapp_api"
        token = os.environ.get("WHATSAPP_API_TOKEN", "").strip()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = {
            "to": telefone,
            "canal": "whatsapp",
            "message": f"Seu código de verificação PertoJá é: {code}",
        }
        try:
            resp = requests.post(whatsapp_url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return {"sent": True, "provider": provider, "canal": canal_norm}
        except (requests.RequestException, ValueError, TypeError, OSError) as exc:
            _logger.warning(
                "Falha ao enviar OTP via WhatsApp.",
                extra={"event": "otp_send_failed", "provider": provider, "error_type": type(exc).__name__},
            )
            return {"sent": False, "provider": provider, "canal": canal_norm, "error": type(exc).__name__}

    if canal_norm == "sms" and sms_url:
        provider = "sms_webhook"
        token = os.environ.get("SMS_WEBHOOK_TOKEN", "").strip()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = {
            "to": telefone,
            "canal": "sms",
            "message": f"Seu código de verificação PertoJá é: {code}",
        }
        try:
            resp = requests.post(sms_url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return {"sent": True, "provider": provider, "canal": canal_norm}
        except (requests.RequestException, ValueError, TypeError, OSError) as exc:
            _logger.warning(
                "Falha ao enviar OTP via SMS.",
                extra={"event": "otp_send_failed", "provider": provider, "error_type": type(exc).__name__},
            )
            return {"sent": False, "provider": provider, "canal": canal_norm, "error": type(exc).__name__}

    log_extra: dict[str, str] = {"event": "otp_simulated_dev", "canal": canal_norm}
    if not is_production_runtime():
        log_extra["mode"] = "dev"
    _logger.info("Código OTP simulado em ambiente local.", extra=log_extra)
    return {"sent": True, "provider": "local_otp", "canal": canal_norm}
