"""Adaptador para API REST do Mercado Pago (PIX, Checkout Preferências, Boleto e Webhooks)."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import quote

from pertoja.payments.base import BasePaymentAdapter
from pertoja.payments.errors import PaymentGatewayError, WebhookSignatureError
from pertoja.payments.http import call_request_json
from pertoja.payments.utils import (
    _fallback_event_id,
    _get_header_ci,
    _map_status,
    _notification_url,
    _parse_json_bytes,
    _parse_kv_signature_header,
    _require_env,
    _return_base_url,
    _split_payer_name,
    _validate_timestamp,
)


class MercadoPagoAdapter(BasePaymentAdapter):
    """Adaptador para API REST do Mercado Pago."""

    gateway_name = "mercadopago"

    def _api_base(self) -> str:
        return os.environ.get("MERCADOPAGO_API_BASE", "https://api.mercadopago.com").strip().rstrip("/")

    def _access_token(self) -> str:
        return _require_env("MERCADOPAGO_ACCESS_TOKEN", "Mercado Pago")

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        token = self._access_token()
        hdrs = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            hdrs["X-Idempotency-Key"] = idempotency_key
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
        base = self._api_base()
        payer_dict = payer or {}
        payer_email = str(payer_dict.get("email") or "").strip() or "pagamentos@pertoja.com.br"
        first_name, last_name = _split_payer_name(payer_dict.get("name"))

        meta = metadata or {}
        item_id = str(meta.get("item_id") or meta.get("servico_id") or order_id)
        item_title = str(meta.get("item_title") or description or f"Pedido #{order_id}")[:250]
        item_description = str(meta.get("item_description") or description or item_title)[:250]
        category_id = str(meta.get("category_id") or "services")[:50]
        statement_descriptor = str(
            meta.get("statement_descriptor") or os.environ.get("MERCADOPAGO_STATEMENT_DESCRIPTOR") or "PERTOJA"
        ).strip()[:13]
        notif_url = _notification_url(self.gateway_name)
        unit_price = round(amount_cents / 100.0, 2)

        if method == "cartao" and not payment_method_token:
            base_ret = _return_base_url()
            raw_ret = str(return_url or "").strip()
            if raw_ret.startswith("/") and base_ret:
                resolved_return = f"{base_ret}{raw_ret}"
            elif raw_ret:
                resolved_return = raw_ret
            elif base_ret:
                resolved_return = f"{base_ret}/pedido.html?order_id={order_id}"
            else:
                resolved_return = ""

            pref_payer: dict[str, Any] = {"email": payer_email}
            if first_name:
                pref_payer["name"] = first_name
            if last_name:
                pref_payer["surname"] = last_name

            body: dict[str, Any] = {
                "items": [
                    {
                        "id": item_id,
                        "title": item_title,
                        "description": item_description,
                        "category_id": category_id,
                        "quantity": 1,
                        "currency_id": currency.upper(),
                        "unit_price": unit_price,
                    }
                ],
                "external_reference": public_id,
                "payer": pref_payer,
                "statement_descriptor": statement_descriptor,
                "metadata": meta or {"order_id": order_id, "public_id": public_id},
            }
            if resolved_return.startswith(("https://", "http://")):
                body["back_urls"] = {
                    "success": resolved_return,
                    "failure": resolved_return,
                    "pending": resolved_return,
                }
                body["auto_return"] = "approved"
            if notif_url:
                body["notification_url"] = notif_url

            data = call_request_json(
                "POST",
                f"{base}/checkout/preferences",
                headers=self._headers(public_id),
                json_body=body,
            )
            token = self._access_token()
            is_sandbox = token.startswith("TEST-") or os.environ.get("MERCADOPAGO_SANDBOX") == "1"
            checkout_url = (
                (data.get("sandbox_init_point") or data.get("init_point"))
                if is_sandbox
                else (data.get("init_point") or data.get("sandbox_init_point"))
            )
            return {
                "gateway": self.gateway_name,
                "gateway_payment_id": str(data.get("id") or ""),
                "gateway_reference": public_id,
                "status": "requires_action",
                "checkout_url": checkout_url,
                "pix_qr_code": None,
                "pix_qr_base64": None,
                "boleto_barcode": None,
                "boleto_digitable_line": None,
                "boleto_url": None,
                "expires_at": data.get("expiration_date_to"),
                "raw_response": data,
            }

        mp_payer: dict[str, Any] = {"email": payer_email}
        if first_name:
            mp_payer["first_name"] = first_name
        if last_name:
            mp_payer["last_name"] = last_name
        cpf_digits = "".join(ch for ch in str(payer_dict.get("cpf") or payer_dict.get("tax_id") or "") if ch.isdigit())
        if len(cpf_digits) == 11:
            mp_payer["identification"] = {"type": "CPF", "number": cpf_digits}

        if method == "boleto":
            zip_code = "".join(
                ch for ch in str(payer_dict.get("cep") or payer_dict.get("zip_code") or "") if ch.isdigit()
            )
            street_name = str(payer_dict.get("endereco") or payer_dict.get("street_name") or "").strip()
            street_number = str(payer_dict.get("numero") or payer_dict.get("street_number") or "").strip()
            neighborhood = str(payer_dict.get("bairro") or payer_dict.get("neighborhood") or "").strip()
            city = str(payer_dict.get("cidade") or payer_dict.get("city") or "").strip()
            federal_unit = str(payer_dict.get("estado") or payer_dict.get("federal_unit") or "").strip().upper()
            if len(cpf_digits) != 11 or not all(
                (zip_code, street_name, street_number, neighborhood, city, federal_unit)
            ):
                raise PaymentGatewayError(
                    "CPF e endereço completo são obrigatórios para Boleto no Mercado Pago.",
                    code="MISSING_PAYER_DATA",
                    http_status=400,
                )
            mp_payer["address"] = {
                "zip_code": zip_code,
                "street_name": street_name,
                "street_number": street_number,
                "neighborhood": neighborhood,
                "city": city,
                "federal_unit": federal_unit,
            }

        mp_method = "pix" if method == "pix" else ("bolbradesco" if method == "boleto" else "credit_card")
        pay_body: dict[str, Any] = {
            "transaction_amount": unit_price,
            "description": item_description,
            "external_reference": public_id,
            "payer": mp_payer,
            "statement_descriptor": statement_descriptor,
            "additional_info": {
                "items": [
                    {
                        "id": item_id,
                        "title": item_title,
                        "description": item_description,
                        "category_id": category_id,
                        "quantity": 1,
                        "unit_price": unit_price,
                    }
                ]
            },
        }
        tz_brt = timezone(timedelta(hours=-3))
        now_brt = datetime.now(tz_brt)
        if method == "pix":
            pay_body["date_of_expiration"] = (now_brt + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000-03:00")
        elif method == "boleto":
            pay_body["date_of_expiration"] = (now_brt + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000-03:00")
        if notif_url:
            pay_body["notification_url"] = notif_url

        if payment_method_token:
            pay_body["token"] = payment_method_token
        else:
            pay_body["payment_method_id"] = mp_method

        data = call_request_json(
            "POST",
            f"{base}/v1/payments",
            headers=self._headers(public_id),
            json_body=pay_body,
        )
        poi = data.get("point_of_interaction") or {}
        tx_data = poi.get("transaction_data") or {}
        tx_details = data.get("transaction_details") or {}
        barcode_obj = data.get("barcode") or {}

        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": str(data.get("id") or ""),
            "gateway_reference": public_id,
            "status": _map_status(data.get("status")) if data.get("status") else "requires_action",
            "checkout_url": tx_data.get("ticket_url") or tx_details.get("external_resource_url"),
            "pix_qr_code": tx_data.get("qr_code"),
            "pix_qr_base64": tx_data.get("qr_code_base64"),
            "boleto_barcode": barcode_obj.get("content") if isinstance(barcode_obj, dict) else None,
            "boleto_digitable_line": (
                tx_details.get("digitable_line")
                or (barcode_obj.get("content") if isinstance(barcode_obj, dict) else None)
            ),
            "boleto_url": tx_details.get("external_resource_url") if method == "boleto" else None,
            "expires_at": data.get("date_of_expiration"),
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
        _ = simulate_outcome
        base = self._api_base()
        gw_id = str(gateway_payment_id or "").strip()

        if (method == "cartao" or not gw_id.isdigit()) and public_id:
            encoded_ref = quote(str(public_id), safe="")
            search_data = call_request_json(
                "GET",
                f"{base}/v1/payments/search?external_reference={encoded_ref}&sort=date_created&criteria=desc",
                headers=self._headers(),
            )
            results = search_data.get("results") or []
            if results and isinstance(results[0], dict):
                latest = results[0]
                mapped = _map_status(latest.get("status"))
                return {
                    "gateway": self.gateway_name,
                    "gateway_payment_id": str(latest.get("id") or gw_id),
                    "gateway_reference": gateway_reference or gw_id,
                    "status": mapped,
                    "paid_at": latest.get("date_approved") if mapped == "paid" else None,
                }
            return {
                "gateway": self.gateway_name,
                "gateway_payment_id": gw_id,
                "gateway_reference": gateway_reference or gw_id,
                "status": "requires_action",
                "paid_at": None,
            }

        data = call_request_json(
            "GET",
            f"{base}/v1/payments/{gw_id}",
            headers=self._headers(),
        )
        mapped = _map_status(data.get("status"))
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": str(data.get("id") or gw_id),
            "status": mapped,
            "paid_at": data.get("date_approved") if mapped == "paid" else None,
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
        _ = reason
        base = self._api_base()
        idem_key = (idempotency_key or "").strip() or uuid.uuid4().hex
        refund_body: dict[str, Any] = {} if full_refund else {"amount": round(amount_cents / 100.0, 2)}
        data = call_request_json(
            "POST",
            f"{base}/v1/payments/{gateway_payment_id}/refunds",
            headers=self._headers(idem_key),
            json_body=refund_body,
        )
        refund_status = str(data.get("status") or "").strip().lower()
        if refund_status in ("rejected", "cancelled", "failed"):
            raise PaymentGatewayError(
                f"Estorno recusado pelo Mercado Pago (status: {refund_status}).",
                code="REFUND_REJECTED",
                http_status=400,
            )
        return {
            "gateway": self.gateway_name,
            "gateway_payment_id": gateway_payment_id,
            "gateway_refund_id": str(data.get("id") or ""),
            "status": "succeeded" if refund_status in ("", "approved") else "failed",
            "amount_cents": amount_cents,
        }

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        query_params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        secret = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise WebhookSignatureError("Segredo de webhook Mercado Pago não configurado.")

        x_sig = _get_header_ci(headers, "x-signature")
        x_req_id = _get_header_ci(headers, "x-request-id")
        if not x_sig or not x_req_id:
            raise WebhookSignatureError("Cabeçalhos x-signature ou x-request-id ausentes.")

        kv = _parse_kv_signature_header(x_sig)
        ts_list = kv.get("ts") or []
        v1_list = kv.get("v1") or []
        if not ts_list or not v1_list:
            raise WebhookSignatureError("Formato inválido em x-signature.")

        ts_str = ts_list[0]
        _validate_timestamp(ts_str)
        v1_hex = v1_list[0].lower()

        payload = _parse_json_bytes(raw_body)
        q = query_params or {}
        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        data_id = q.get("data.id") or q.get("id") or data_obj.get("id") or ""
        parts: list[str] = []
        if data_id:
            parts.append(f"id:{str(data_id).lower()}")
        if x_req_id:
            parts.append(f"request-id:{x_req_id}")
        parts.append(f"ts:{ts_str}")
        manifest = ";".join(parts) + ";"
        expected_hex = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest().lower()

        if not hmac.compare_digest(v1_hex, expected_hex):
            raise WebhookSignatureError("Assinatura HMAC Mercado Pago inválida.")

        topic = str(payload.get("type") or q.get("type") or q.get("topic") or "").strip().lower()
        action = str(payload.get("action") or "").strip().lower()
        event_type = str(payload.get("action") or payload.get("type") or topic or "payment.updated")
        raw_status = payload.get("status") or data_obj.get("status")
        amount_cents = payload.get("amount_cents")
        public_id = payload.get("external_reference") or data_obj.get("external_reference")
        resolved_gw_pid = str(data_id or "")

        is_payment_event = (topic == "payment") or action.startswith("payment.") or (not topic and not action)
        if not is_payment_event:
            return {
                "verified": True,
                "event_id": _fallback_event_id(raw_body, payload.get("id"), x_req_id),
                "event_type": event_type,
                "gateway_payment_id": resolved_gw_pid,
                "public_id": str(public_id) if public_id else None,
                "mapped_status": "ignored",
                "amount_cents": amount_cents,
            }

        if not raw_status and data_id:
            payment_data = call_request_json(
                "GET",
                f"{self._api_base()}/v1/payments/{data_id}",
                headers=self._headers(),
            )
            raw_status = payment_data.get("status")
            resolved_gw_pid = str(payment_data.get("id") or data_id)
            if payment_data.get("external_reference"):
                public_id = payment_data.get("external_reference")
            if payment_data.get("transaction_amount") is not None:
                amount_cents = int(round(float(payment_data["transaction_amount"]) * 100))

        return {
            "verified": True,
            "event_id": _fallback_event_id(raw_body, payload.get("id"), x_req_id),
            "event_type": event_type,
            "gateway_payment_id": resolved_gw_pid,
            "public_id": str(public_id) if public_id else None,
            "mapped_status": _map_status(raw_status) if raw_status else "pending",
            "amount_cents": amount_cents,
        }
