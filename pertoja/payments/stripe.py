"""Adaptador para API REST do Stripe (Checkout Sessions, PaymentIntents, Refunds e Webhooks)."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from pertoja.payments.base import BasePaymentAdapter
from pertoja.payments.errors import PaymentGatewayError, WebhookSignatureError
from pertoja.payments.http import call_request_json
from pertoja.payments.utils import (
    _fallback_event_id,
    _get_header_ci,
    _map_status,
    _parse_json_bytes,
    _parse_kv_signature_header,
    _require_env,
    _return_base_url,
    _validate_timestamp,
)


class StripeAdapter(BasePaymentAdapter):
    """Adaptador para API REST do Stripe."""

    gateway_name = "stripe"

    def _api_base(self) -> str:
        return os.environ.get("STRIPE_API_BASE", "https://api.stripe.com").strip().rstrip("/")

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        secret_key = _require_env("STRIPE_SECRET_KEY", "Stripe")
        hdrs = {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if idempotency_key:
            hdrs["Idempotency-Key"] = idempotency_key
        return hdrs

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
        base_ret = _return_base_url()
        success_url = return_url or (
            f"{base_ret}/pedido.html?order_id={order_id}&payment=success" if base_ret else "https://example.com/success"
        )
        cancel_url = return_url or (
            f"{base_ret}/pedido.html?order_id={order_id}&payment=cancel" if base_ret else "https://example.com/cancel"
        )

        if method == "cartao":
            form_data = {
                "mode": "payment",
                "line_items[0][price_data][currency]": currency.lower(),
                "line_items[0][price_data][unit_amount]": str(amount_cents),
                "line_items[0][price_data][product_data][name]": description[:200],
                "line_items[0][quantity]": "1",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": public_id,
                "metadata[order_id]": str(order_id),
                "metadata[public_id]": public_id,
            }
            data = call_request_json(
                "POST",
                f"{base}/v1/checkout/sessions",
                headers=self._headers(public_id),
                data=form_data,
            )
            return {
                "gateway": self.gateway_name,
                "gateway_payment_id": str(data.get("payment_intent") or data.get("id") or ""),
                "gateway_reference": str(data.get("id") or public_id),
                "status": "requires_action",
                "checkout_url": data.get("url"),
                "pix_qr_code": None,
                "pix_qr_base64": None,
                "boleto_barcode": None,
                "boleto_digitable_line": None,
                "boleto_url": None,
                "expires_at": None,
                "raw_response": data,
            }

        payer_dict = payer or {}
        stripe_pm_type = "boleto" if method == "boleto" else "pix"
        pi_data = {
            "amount": str(amount_cents),
            "currency": currency.lower(),
            "payment_method_types[0]": stripe_pm_type,
            "confirm": "true",
            "payment_method_data[type]": stripe_pm_type,
            "payment_method_data[billing_details][name]": str(payer_dict.get("name") or "Cliente PertoJa")[:100],
            "payment_method_data[billing_details][email]": str(payer_dict.get("email") or "cliente@pertoja.local")[
                :120
            ],
            "description": description[:200],
            "metadata[order_id]": str(order_id),
            "metadata[public_id]": public_id,
        }
        if method == "boleto":
            raw_tax = "".join(ch for ch in str(payer_dict.get("tax_id") or payer_dict.get("cpf") or "") if ch.isdigit())
            pi_data["payment_method_data[boleto][tax_id]"] = raw_tax if len(raw_tax) in (11, 14) else "00000000000"
        data = call_request_json(
            "POST",
            f"{base}/v1/payment_intents",
            headers=self._headers(public_id),
            data=pi_data,
        )
        next_action = data.get("next_action") or {}
        boleto_details = next_action.get("boleto_display_details") or {}
        pix_details = next_action.get("pix_display_qr_code") or {}
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": str(data.get("id") or ""),
            "gateway_reference": public_id,
            "status": _map_status(data.get("status")),
            "checkout_url": boleto_details.get("hosted_voucher_url"),
            "pix_qr_code": pix_details.get("data"),
            "pix_qr_base64": None,
            "boleto_barcode": None,
            "boleto_digitable_line": boleto_details.get("number"),
            "boleto_url": boleto_details.get("hosted_voucher_url"),
            "expires_at": None,
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
                "gateway_payment_id ausente para confirmação no Stripe.",
                code="INVALID_PAYMENT_ID",
                http_status=400,
            )
        gw_id = str(gateway_payment_id).strip()
        base = self._api_base()
        gateway_reference = None
        if gw_id.startswith("cs_"):
            data = call_request_json(
                "GET",
                f"{base}/v1/checkout/sessions/{gw_id}",
                headers=self._headers(),
            )
            raw_st = "paid" if data.get("payment_status") == "paid" else data.get("status")
            gateway_reference = str(data.get("id") or gw_id)
            resolved_gw_pid = str(data.get("payment_intent") or gw_id)
        else:
            data = call_request_json(
                "GET",
                f"{base}/v1/payment_intents/{gw_id}",
                headers=self._headers(),
            )
            raw_st = data.get("status")
            resolved_gw_pid = str(data.get("id") or gw_id)

        mapped = _map_status(raw_st)
        res: dict[str, Any] = {
            "gateway": self.gateway_name,
            "gateway_payment_id": resolved_gw_pid,
            "status": mapped,
            "paid_at": datetime.now(timezone.utc).isoformat() if mapped == "paid" else None,
        }
        if gateway_reference:
            res["gateway_reference"] = gateway_reference
        return res

    def refund_payment(
        self,
        *,
        gateway_payment_id: str,
        amount_cents: int,
        reason: str = "",
        idempotency_key: str | None = None,
        full_refund: bool = False,
    ) -> dict[str, Any]:
        _ = (idempotency_key, full_refund)
        if not gateway_payment_id or not str(gateway_payment_id).strip():
            raise PaymentGatewayError(
                "gateway_payment_id ausente para estorno no Stripe.",
                code="INVALID_PAYMENT_ID",
                http_status=400,
            )
        base = self._api_base()
        target_pi = str(gateway_payment_id).strip()
        if target_pi.startswith("cs_"):
            session_data = call_request_json(
                "GET",
                f"{base}/v1/checkout/sessions/{target_pi}",
                headers=self._headers(),
            )
            resolved_pi = str(session_data.get("payment_intent") or "").strip()
            if not resolved_pi:
                raise PaymentGatewayError(
                    "Checkout Session do Stripe ainda não possui payment_intent associado para estorno.",
                    code="PAYMENT_INTENT_UNRESOLVED",
                    http_status=400,
                )
            target_pi = resolved_pi

        form_data: dict[str, Any] = {
            "payment_intent": target_pi,
            "amount": str(amount_cents),
        }
        if reason in ("duplicate", "fraudulent", "requested_by_customer"):
            form_data["reason"] = reason
        data = call_request_json(
            "POST",
            f"{base}/v1/refunds",
            headers=self._headers(f"ref_{target_pi}_{amount_cents}"),
            data=form_data,
        )
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": target_pi,
            "gateway_refund_id": str(data.get("id") or ""),
            "status": "succeeded" if data.get("status") in (None, "succeeded", "pending") else "failed",
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
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise WebhookSignatureError("Segredo de webhook Stripe não configurado.")

        sig_header = _get_header_ci(headers, "Stripe-Signature")
        if not sig_header:
            raise WebhookSignatureError("Cabeçalho Stripe-Signature ausente.")

        kv = _parse_kv_signature_header(sig_header)
        t_list = kv.get("t") or []
        v1_list = kv.get("v1") or []
        if not t_list or not v1_list:
            raise WebhookSignatureError("Formato inválido em Stripe-Signature.")

        t_str = t_list[0]
        _validate_timestamp(t_str)

        signed_payload = f"{t_str}.".encode("utf-8") + raw_body
        expected_hex = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest().lower()

        if not any(hmac.compare_digest(v1.lower(), expected_hex) for v1 in v1_list):
            raise WebhookSignatureError("Assinatura HMAC Stripe inválida.")

        payload = _parse_json_bytes(raw_body)
        event_type = str(payload.get("type") or "")
        obj = (payload.get("data") or {}).get("object") or {}
        gw_pid = str(obj.get("payment_intent") or obj.get("id") or "")
        gw_ref = str(obj.get("id") or "") or None
        pub_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("public_id")
        raw_status = obj.get("payment_status") or obj.get("status")
        if event_type in ("payment_intent.succeeded", "checkout.session.completed"):
            mapped = "paid"
        elif event_type in ("payment_intent.payment_failed",):
            mapped = "failed"
        elif event_type in ("payment_intent.canceled", "checkout.session.expired"):
            mapped = "expired" if "expired" in event_type else "cancelled"
        else:
            mapped = _map_status(raw_status)

        return {
            "verified": True,
            "event_id": _fallback_event_id(raw_body, payload.get("id")),
            "event_type": event_type or "stripe.event",
            "gateway_payment_id": gw_pid,
            "gateway_reference": gw_ref,
            "public_id": str(pub_id) if pub_id else None,
            "mapped_status": mapped,
            "amount_cents": obj.get("amount_received") or obj.get("amount_total") or obj.get("amount"),
        }
