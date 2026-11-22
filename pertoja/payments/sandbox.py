"""Adaptador de pagamento Sandbox para simulação determinística local."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from pertoja.payments.base import BasePaymentAdapter
from pertoja.payments.errors import GatewayNotConfiguredError, WebhookSignatureError
from pertoja.payments.utils import (
    _build_boleto_codes,
    _build_pix_emvco,
    _fallback_event_id,
    _get_header_ci,
    _map_status,
    _parse_json_bytes,
    _validate_timestamp,
    is_sandbox_enabled,
)


class SandboxPaymentAdapter(BasePaymentAdapter):
    """Adaptador determinístico local para testes e desenvolvimento."""

    gateway_name = "sandbox"

    def create_intent(
        self,
        *,
        public_id: str,
        order_id: int,
        amount_cents: int,
        currency: str,
        method: str,
        description: str,
        payer: dict[str, Any] | None = None,
        return_url: str | None = None,
        payment_method_token: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not is_sandbox_enabled():
            raise GatewayNotConfiguredError("Sandbox de pagamentos desabilitado.")

        now = datetime.now(timezone.utc)
        gateway_payment_id = f"sbx_pay_{public_id}"
        gateway_reference = f"sbx_ref_{public_id}"
        checkout_url = None
        pix_qr_code = None
        pix_qr_base64 = None
        boleto_barcode = None
        boleto_digitable_line = None
        boleto_url = None
        expires_at = None

        if method == "pix":
            pix_qr_code = _build_pix_emvco(txid=public_id, amount_cents=amount_cents)
            expires_at = (now + timedelta(minutes=30)).isoformat()
        elif method == "boleto":
            exp_dt = now + timedelta(days=3)
            boleto_barcode, boleto_digitable_line = _build_boleto_codes(
                order_id=order_id, amount_cents=amount_cents, expires_at_dt=exp_dt
            )
            boleto_url = f"/pedido.html?order_id={order_id}&sandbox_tx={public_id}&method=boleto"
            expires_at = exp_dt.isoformat()
        elif method == "cartao":
            checkout_url = f"/pedido.html?order_id={order_id}&sandbox_tx={public_id}&method=cartao"
            expires_at = (now + timedelta(hours=1)).isoformat()
        else:
            expires_at = (now + timedelta(hours=1)).isoformat()

        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": gateway_payment_id,
            "gateway_reference": gateway_reference,
            "status": "requires_action",
            "checkout_url": checkout_url,
            "pix_qr_code": pix_qr_code,
            "pix_qr_base64": pix_qr_base64,
            "boleto_barcode": boleto_barcode,
            "boleto_digitable_line": boleto_digitable_line,
            "boleto_url": boleto_url,
            "expires_at": expires_at,
            "raw_response": {"sandbox": True, "public_id": public_id, "order_id": order_id},
        }

    def confirm_intent(
        self,
        *,
        gateway_payment_id: str,
        method: str,
        simulate_outcome: str = "paid",
        gateway_reference: str | None = None,
        public_id: str | None = None,
    ) -> dict[str, Any]:
        _ = (gateway_reference, public_id)
        if not is_sandbox_enabled():
            raise GatewayNotConfiguredError("Sandbox de pagamentos desabilitado.")
        outcome = (simulate_outcome or "paid").strip().lower()
        status = outcome if outcome in ("paid", "failed", "expired", "cancelled") else "paid"
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": gateway_payment_id,
            "status": status,
            "paid_at": datetime.now(timezone.utc).isoformat() if status == "paid" else None,
        }

    def refund_payment(
        self,
        *,
        gateway_payment_id: str,
        amount_cents: int,
        reason: str = "",
        idempotency_key: str | None = None,
        full_refund: bool = False,
    ) -> dict[str, Any]:
        _ = (reason, idempotency_key, full_refund)
        if not is_sandbox_enabled():
            raise GatewayNotConfiguredError("Sandbox de pagamentos desabilitado.")
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": gateway_payment_id,
            "gateway_refund_id": f"sbx_ref_{uuid.uuid4().hex[:16]}",
            "status": "succeeded",
            "amount_cents": amount_cents,
        }

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        query_params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = query_params
        secret = os.environ.get("SANDBOX_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise WebhookSignatureError("Segredo de webhook sandbox não configurado.")

        sig_header = _get_header_ci(headers, "X-Sandbox-Signature")
        if not sig_header.startswith("sha256="):
            raise WebhookSignatureError("Cabeçalho X-Sandbox-Signature ausente ou inválido.")
        provided_hex = sig_header[len("sha256=") :].strip().lower()

        ts_header = _get_header_ci(headers, "X-Sandbox-Timestamp")
        if ts_header:
            _validate_timestamp(ts_header)

        expected_hex = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest().lower()
        if not hmac.compare_digest(provided_hex, expected_hex):
            raise WebhookSignatureError("Assinatura HMAC sandbox inválida.")

        payload = _parse_json_bytes(raw_body)
        return {
            "verified": True,
            "event_id": _fallback_event_id(raw_body, payload.get("event_id"), payload.get("id")),
            "event_type": str(payload.get("event_type") or payload.get("type") or "payment.updated"),
            "gateway_payment_id": str(payload.get("gateway_payment_id") or ""),
            "public_id": str(payload.get("public_id") or "") or None,
            "mapped_status": _map_status(payload.get("status")),
            "amount_cents": payload.get("amount_cents"),
        }
