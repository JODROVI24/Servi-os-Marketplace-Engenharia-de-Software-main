"""Adaptador para API REST do PagSeguro (Checkouts, Orders PIX/Boleto, Cancel e Webhooks)."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Mapping

from pertoja.payments.base import BasePaymentAdapter
from pertoja.payments.errors import PaymentGatewayError, WebhookSignatureError
from pertoja.payments.http import call_request_json
from pertoja.payments.utils import (
    _fallback_event_id,
    _get_header_ci,
    _map_status,
    _parse_json_bytes,
    _require_env,
    _return_base_url,
    _validate_timestamp,
)


class PagSeguroAdapter(BasePaymentAdapter):
    """Adaptador para API REST do PagSeguro."""

    gateway_name = "pagseguro"

    def _api_base(self) -> str:
        return os.environ.get("PAGSEGURO_API_BASE", "https://api.pagseguro.com").strip().rstrip("/")

    def _headers(self) -> dict[str, str]:
        token = _require_env("PAGSEGURO_TOKEN", "PagSeguro")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

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
        _ = (payment_method_token, metadata)
        base = self._api_base()
        item = {
            "reference_id": public_id,
            "name": description[:100],
            "quantity": 1,
            "unit_amount": amount_cents,
        }

        if method == "cartao":
            checkout_body: dict[str, Any] = {
                "reference_id": public_id,
                "items": [item],
            }
            if return_url or _return_base_url():
                checkout_body["redirect_url"] = return_url or f"{_return_base_url()}/pedido.html?order_id={order_id}"
            data = call_request_json(
                "POST",
                f"{base}/checkouts",
                headers=self._headers(),
                json_body=checkout_body,
            )
            links = {lk.get("rel"): lk.get("href") for lk in (data.get("links") or []) if isinstance(lk, dict)}
            return {
                "gateway": self.gateway_name,
                "gateway_payment_id": str(data.get("id") or ""),
                "gateway_reference": public_id,
                "status": "requires_action",
                "checkout_url": links.get("PAY") or links.get("SELF"),
                "pix_qr_code": None,
                "pix_qr_base64": None,
                "boleto_barcode": None,
                "boleto_digitable_line": None,
                "boleto_url": None,
                "expires_at": data.get("expiration_date"),
                "raw_response": data,
            }

        payer_dict = payer or {}
        raw_tax = "".join(ch for ch in str(payer_dict.get("tax_id") or payer_dict.get("cpf") or "") if ch.isdigit())
        customer_block = {
            "name": str(payer_dict.get("name") or "Cliente PertoJa")[:80],
            "email": str(payer_dict.get("email") or "cliente@pertoja.local")[:120],
            "tax_id": raw_tax if len(raw_tax) in (11, 14) else "00000000000",
        }
        order_body: dict[str, Any] = {
            "reference_id": public_id,
            "customer": customer_block,
            "items": [item],
        }
        if method == "pix":
            order_body["qr_codes"] = [{"amount": {"value": amount_cents}}]
        elif method == "boleto":
            order_body["charges"] = [
                {
                    "reference_id": public_id,
                    "description": description[:100],
                    "amount": {"value": amount_cents, "currency": currency.upper()},
                    "payment_method": {"type": "BOLETO"},
                }
            ]

        data = call_request_json(
            "POST",
            f"{base}/orders",
            headers=self._headers(),
            json_body=order_body,
        )
        qr_codes = data.get("qr_codes") or []
        qr0 = qr_codes[0] if qr_codes and isinstance(qr_codes[0], dict) else {}
        charges = data.get("charges") or []
        ch0 = charges[0] if charges and isinstance(charges[0], dict) else {}
        boleto_data = ((ch0.get("payment_method") or {}).get("boleto")) or {}
        order_gw_id = str(data.get("id") or "")
        charge_gw_id = str(ch0.get("id") or "")

        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": charge_gw_id or order_gw_id,
            "gateway_reference": order_gw_id or public_id,
            "status": "requires_action",
            "checkout_url": None,
            "pix_qr_code": qr0.get("text"),
            "pix_qr_base64": None,
            "boleto_barcode": boleto_data.get("barcode"),
            "boleto_digitable_line": boleto_data.get("formatted_barcode"),
            "boleto_url": None,
            "expires_at": qr0.get("expiration_date") or boleto_data.get("due_date"),
            "raw_response": data,
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
        # Nunca confia em simulate_outcome em gateways reais: consulta sempre a API.
        _ = (method, simulate_outcome, gateway_reference, public_id)
        if not gateway_payment_id or not str(gateway_payment_id).strip():
            raise PaymentGatewayError(
                "gateway_payment_id ausente para confirmação no PagSeguro.",
                code="INVALID_PAYMENT_ID",
                http_status=400,
            )
        gw_id = str(gateway_payment_id).strip()
        base = self._api_base()
        if gw_id.startswith("CHAR_"):
            ch0 = call_request_json(
                "GET",
                f"{base}/charges/{gw_id}",
                headers=self._headers(),
            )
            raw_status = ch0.get("status")
            resolved_id = str(ch0.get("id") or gw_id)
            paid_at = ch0.get("paid_at")
        else:
            data = call_request_json(
                "GET",
                f"{base}/orders/{gw_id}",
                headers=self._headers(),
            )
            charges = data.get("charges") or []
            ch0 = charges[0] if charges and isinstance(charges[0], dict) else {}
            raw_status = ch0.get("status") or data.get("status")
            resolved_id = str(ch0.get("id") or data.get("id") or gw_id)
            paid_at = ch0.get("paid_at")

        mapped = _map_status(raw_status)
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": resolved_id,
            "status": mapped,
            "paid_at": paid_at if mapped == "paid" else None,
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
        if not gateway_payment_id or not str(gateway_payment_id).strip():
            raise PaymentGatewayError(
                "gateway_payment_id ausente para estorno no PagSeguro.",
                code="INVALID_PAYMENT_ID",
                http_status=400,
            )
        base = self._api_base()
        target_charge = str(gateway_payment_id).strip()
        if target_charge.startswith("ORDE_"):
            order_data = call_request_json(
                "GET",
                f"{base}/orders/{target_charge}",
                headers=self._headers(),
            )
            charges = order_data.get("charges") or []
            ch0 = charges[0] if charges and isinstance(charges[0], dict) else {}
            resolved_charge = str(ch0.get("id") or "").strip()
            if not resolved_charge:
                raise PaymentGatewayError(
                    "Pedido PagSeguro não possui cobrança (CHAR_) associada para estorno.",
                    code="CHARGE_UNRESOLVED",
                    http_status=400,
                )
            target_charge = resolved_charge

        data = call_request_json(
            "POST",
            f"{base}/charges/{target_charge}/cancel",
            headers=self._headers(),
            json_body={"amount": {"value": amount_cents}},
        )
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": target_charge,
            "gateway_refund_id": str(data.get("id") or ""),
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
        secret = os.environ.get("PAGSEGURO_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise WebhookSignatureError("Segredo de webhook PagSeguro não configurado.")

        sig_header = _get_header_ci(headers, "X-PagSeguro-Signature")
        if not sig_header:
            raise WebhookSignatureError("Cabeçalho X-PagSeguro-Signature ausente.")

        ts_header = _get_header_ci(headers, "X-PagSeguro-Timestamp") or _get_header_ci(headers, "X-Timestamp")
        if ts_header:
            _validate_timestamp(ts_header)

        provided_hex = sig_header[len("sha256=") :] if sig_header.lower().startswith("sha256=") else sig_header
        provided_hex = provided_hex.strip().lower()
        expected_hex = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest().lower()

        if not hmac.compare_digest(provided_hex, expected_hex):
            raise WebhookSignatureError("Assinatura HMAC PagSeguro inválida.")

        payload = _parse_json_bytes(raw_body)
        charges = payload.get("charges") or []
        ch0 = charges[0] if charges and isinstance(charges[0], dict) else {}
        raw_status = ch0.get("status") or payload.get("status")
        charge_id = str(ch0.get("id") or "")
        order_id_gw = str(payload.get("id") or "")
        pub_id = payload.get("reference_id") or ch0.get("reference_id")
        return {
            "verified": True,
            "event_id": _fallback_event_id(raw_body, payload.get("event_id"), payload.get("id")),
            "event_type": str(payload.get("event_type") or "order.updated"),
            "gateway_payment_id": charge_id or order_id_gw,
            "gateway_reference": order_id_gw or None,
            "public_id": str(pub_id) if pub_id else None,
            "mapped_status": _map_status(raw_status),
            "amount_cents": (ch0.get("amount") or {}).get("value") if isinstance(ch0.get("amount"), dict) else None,
        }
