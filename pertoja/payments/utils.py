"""Funções utilitárias, validação criptográfica de webhooks e geradores PIX/Boleto."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from pertoja.payments.errors import GatewayNotConfiguredError, WebhookSignatureError

DEFAULT_TIMEOUT_SECONDS = 10
WEBHOOK_TOLERANCE_SECONDS = 300
SUPPORTED_GATEWAYS = ("sandbox", "mercadopago", "stripe", "pagseguro")


def is_sandbox_enabled() -> bool:
    """Retorna True se o gateway Sandbox estiver habilitado no ambiente atual."""
    explicit = os.environ.get("ENABLE_PAYMENT_SANDBOX", "").strip()
    if explicit == "1":
        return True
    if explicit == "0":
        return False
    return os.environ.get("VERCEL") != "1" and os.environ.get("FLASK_ENV") != "production"


def list_gateway_configs() -> list[dict[str, Any]]:
    """Lista metadados públicos dos gateways suportados sem expor segredos."""
    return [
        {
            "id": "sandbox",
            "name": "Sandbox (Simulação)",
            "configured": is_sandbox_enabled(),
            "methods": ["pix", "cartao", "boleto"],
        },
        {
            "id": "mercadopago",
            "name": "Mercado Pago",
            "configured": bool(os.environ.get("MERCADOPAGO_ACCESS_TOKEN", "").strip()),
            "methods": ["pix", "cartao", "boleto"],
        },
        {
            "id": "stripe",
            "name": "Stripe",
            "configured": bool(os.environ.get("STRIPE_SECRET_KEY", "").strip()),
            "methods": ["cartao", "pix", "boleto"],
        },
        {
            "id": "pagseguro",
            "name": "PagSeguro",
            "configured": bool(os.environ.get("PAGSEGURO_TOKEN", "").strip()),
            "methods": ["pix", "cartao", "boleto"],
        },
    ]


def _get_header_ci(headers: Mapping[str, str] | None, name: str) -> str:
    """Busca cabeçalho HTTP de forma case-insensitive."""
    if not headers:
        return ""
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value or "").strip()
    return ""


def _parse_json_bytes(raw_body: bytes) -> dict[str, Any]:
    """Decodifica payload JSON bruto de webhook ou lança WebhookSignatureError."""
    if not raw_body:
        raise WebhookSignatureError("Payload de webhook vazio.")
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookSignatureError("Payload de webhook não é JSON válido.") from exc
    if not isinstance(parsed, dict):
        raise WebhookSignatureError("Payload de webhook deve ser um objeto JSON.")
    return parsed


def _fallback_event_id(raw_body: bytes, *candidates: Any) -> str:
    """Retorna o primeiro event_id não vazio ou o hash SHA-256 do payload bruto."""
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return hashlib.sha256(raw_body).hexdigest()


def _validate_timestamp(ts_raw: str, tolerance: int = WEBHOOK_TOLERANCE_SECONDS) -> int:
    """Valida timestamp Unix (segundos ou milissegundos) dentro da janela de tolerância."""
    try:
        ts_val = int(float(ts_raw))
    except (TypeError, ValueError) as exc:
        raise WebhookSignatureError("Timestamp de webhook inválido.") from exc
    ts_sec = ts_val / 1000.0 if ts_val > 1e11 else float(ts_val)
    if abs(time.time() - ts_sec) > tolerance:
        raise WebhookSignatureError("Timestamp de webhook expirado.")
    return int(ts_sec)


def _parse_kv_signature_header(header_value: str) -> dict[str, list[str]]:
    """Extrai pares chave=valor separados por vírgula de cabeçalhos de assinatura."""
    parsed: dict[str, list[str]] = {}
    for part in header_value.split(","):
        item = part.strip()
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        parsed.setdefault(k.strip().lower(), []).append(v.strip())
    return parsed


def _require_env(name: str, gateway_label: str) -> str:
    """Obtém variável de ambiente obrigatória ou lança GatewayNotConfiguredError."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise GatewayNotConfiguredError(f"Gateway {gateway_label} não configurado ({name} ausente).")
    return value


def _return_base_url() -> str:
    """Retorna URL base configurada para redirecionamento de checkout."""
    return os.environ.get("PAYMENT_RETURN_BASE_URL", "").strip().rstrip("/")


def _notification_url(gateway: str) -> str:
    """Retorna URL de notificação webhook pública (HTTPS não-localhost) para o gateway."""
    if (gateway or "").strip().lower() == "mercadopago":
        explicit = os.environ.get("MERCADOPAGO_NOTIFICATION_URL", "").strip()
        if explicit:
            return explicit
        base = _return_base_url()
        lower = base.lower()
        if base.startswith("https://") and not any(host in lower for host in ("localhost", "127.0.0.1", "0.0.0.0")):
            return f"{base}/api/webhooks/payments/mercadopago"
    return ""


def _split_payer_name(full_name: Any) -> tuple[str, str]:
    """Divide nome completo em primeiro nome e sobrenome."""
    parts = str(full_name or "").strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _tlv(tag: str, value: str) -> str:
    """Formata campo EMVCo TLV (Tag-Length-Value)."""
    return f"{tag}{len(value):02d}{value}"


def _crc16_ccitt(payload: str) -> str:
    """Calcula CRC16-CCITT (polinômio 0x1021, inicial 0xFFFF) para EMVCo PIX."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _build_pix_emvco(
    *,
    txid: str,
    amount_cents: int,
    pix_key: str = "pagamentos@pertoja.sandbox.br",
    merchant_name: str = "PERTOJA MARKETPLACE",
    merchant_city: str = "SAO PAULO",
) -> str:
    """Gera string PIX Copia-e-Cola EMVCo válida com CRC16."""
    merchant_account = _tlv("00", "br.gov.bcb.pix") + _tlv("01", pix_key[:77])
    amount_str = f"{amount_cents / 100:.2f}"
    clean_txid = "".join(ch for ch in txid if ch.isalnum())[:25] or "SANDBOX001"
    additional_data = _tlv("05", clean_txid)

    body = (
        _tlv("00", "01")
        + _tlv("26", merchant_account)
        + _tlv("52", "0000")
        + _tlv("53", "986")
        + _tlv("54", amount_str)
        + _tlv("58", "BR")
        + _tlv("59", merchant_name[:25])
        + _tlv("60", merchant_city[:15])
        + _tlv("62", additional_data)
        + "6304"
    )
    return body + _crc16_ccitt(body)


def _build_boleto_codes(*, order_id: int, amount_cents: int, expires_at_dt: datetime) -> tuple[str, str]:
    """Gera código de barras (44 dígitos) e linha digitável (47 dígitos) determinísticos."""
    base_date = datetime(1997, 10, 7, tzinfo=timezone.utc)
    fator_venc = max(1000, min(9999, (expires_at_dt.date() - base_date.date()).days))
    valor_10 = f"{min(amount_cents, 9999999999):010d}"
    nosso_num = f"{order_id:025d}"[-25:]
    sem_dv = f"0019{fator_venc:04d}{valor_10}{nosso_num}"
    dv_geral = str((sum(int(c) for c in sem_dv) % 9) + 1)
    barcode = f"0019{dv_geral}{fator_venc:04d}{valor_10}{nosso_num}"

    c1 = f"0019{nosso_num[:5]}"
    c1_dv = str(sum(int(c) for c in c1) % 10)
    c2 = nosso_num[5:15]
    c2_dv = str(sum(int(c) for c in c2) % 10)
    c3 = nosso_num[15:25]
    c3_dv = str(sum(int(c) for c in c3) % 10)
    digitable = f"{c1}{c1_dv}{c2}{c2_dv}{c3}{c3_dv}{dv_geral}{fator_venc:04d}{valor_10}"
    return barcode, digitable


def _map_status(raw_status: str | None) -> str:
    """Normaliza status heterogêneos de gateways para o domínio interno."""
    st = (raw_status or "").strip().lower()
    if st in ("approved", "paid", "succeeded", "complete", "completed"):
        return "paid"
    if st in ("requires_action", "action_required", "requires_confirmation", "requires_payment_method"):
        return "requires_action"
    if st in ("pending", "in_process", "processing", "waiting", "in_analysis", "open"):
        return "pending"
    if st in ("authorized",):
        return "authorized"
    if st in ("rejected", "failed", "declined"):
        return "failed"
    if st in ("expired",):
        return "expired"
    if st in ("cancelled", "canceled"):
        return "cancelled"
    if st in ("refunded",):
        return "refunded"
    return "pending"
