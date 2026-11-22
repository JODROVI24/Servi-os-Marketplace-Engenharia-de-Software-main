"""Adaptadores de gateway de pagamento (PCI-safe, Python puro + requests).

Não importa Flask nem módulos de banco de dados e não mantém estado global
mutável: todas as variáveis de ambiente são lidas dinamicamente por chamada.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import quote

import requests

DEFAULT_TIMEOUT_SECONDS = 10
WEBHOOK_TOLERANCE_SECONDS = 300

SUPPORTED_GATEWAYS = ("sandbox", "mercadopago", "stripe", "pagseguro")


class PaymentGatewayError(Exception):
    """Erro genérico na comunicação ou processamento junto ao gateway."""

    def __init__(
        self,
        message: str,
        code: str = "GATEWAY_ERROR",
        http_status: int = 502,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.retryable = retryable


class GatewayNotConfiguredError(PaymentGatewayError):
    """Erro lançado quando as credenciais do gateway não estão configuradas."""

    def __init__(
        self,
        message: str = "Gateway de pagamento não configurado.",
        code: str = "GATEWAY_NOT_CONFIGURED",
        http_status: int = 503,
    ) -> None:
        super().__init__(message, code=code, http_status=http_status, retryable=False)


class WebhookSignatureError(PaymentGatewayError):
    """Erro lançado quando a assinatura ou timestamp do webhook falha (fail-closed)."""

    def __init__(
        self,
        message: str = "Assinatura de webhook inválida ou ausente.",
        code: str = "INVALID_WEBHOOK_SIGNATURE",
        http_status: int = 401,
    ) -> None:
        super().__init__(message, code=code, http_status=http_status, retryable=False)


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


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Executa requisição HTTP com timeout fixo e mapeamento seguro de erros."""
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            data=data,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise PaymentGatewayError(
            "Tempo limite excedido na comunicação com o gateway.",
            code="GATEWAY_TIMEOUT",
            http_status=504,
            retryable=True,
        ) from exc
    except requests.RequestException as exc:
        raise PaymentGatewayError(
            "Falha de rede na comunicação com o gateway.",
            code="GATEWAY_NETWORK_ERROR",
            http_status=502,
            retryable=True,
        ) from exc

    if not (200 <= resp.status_code < 300):
        retryable = resp.status_code == 429 or resp.status_code >= 500
        http_status = 502 if resp.status_code >= 500 else 400
        err_msg = f"Gateway retornou status HTTP {resp.status_code}."
        try:
            err_json = resp.json()
            if isinstance(err_json, dict):
                detail = (
                    err_json.get("message") or err_json.get("error", {}).get("message")
                    if isinstance(err_json.get("error"), dict)
                    else err_json.get("error")
                )
                if isinstance(detail, str) and detail.strip():
                    err_msg = f"Gateway recusou a operação: {detail.strip()[:180]}"
        except ValueError:
            pass
        raise PaymentGatewayError(
            err_msg,
            code="GATEWAY_HTTP_ERROR",
            http_status=http_status,
            retryable=retryable,
        )

    if not resp.content:
        return {}
    try:
        parsed = resp.json()
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except ValueError as exc:
        raise PaymentGatewayError(
            "Resposta inválida do gateway (JSON esperado).",
            code="GATEWAY_INVALID_RESPONSE",
            http_status=502,
            retryable=False,
        ) from exc


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
    # 44 dígitos: banco(3) + moeda(1) + dv(1) + fator(4) + valor(10) + campo_livre(25)
    sem_dv = f"0019{fator_venc:04d}{valor_10}{nosso_num}"
    dv_geral = str((sum(int(c) for c in sem_dv) % 9) + 1)
    barcode = f"0019{dv_geral}{fator_venc:04d}{valor_10}{nosso_num}"

    # Linha digitável de 47 dígitos: campo1(10) + campo2(11) + campo3(11) + dv(1) + fator_valor(14)
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


class BasePaymentAdapter:
    """Contrato base para adaptadores de gateway de pagamento."""

    gateway_name: str = ""

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
        raise NotImplementedError

    def confirm_intent(
        self,
        *,
        gateway_payment_id: str,
        method: str,
        simulate_outcome: str = "paid",
        gateway_reference: str | None = None,
        public_id: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def refund_payment(
        self,
        *,
        gateway_payment_id: str,
        amount_cents: int,
        reason: str = "",
        idempotency_key: str | None = None,
        full_refund: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        query_params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


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

            data = _request_json(
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

        data = _request_json(
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
            search_data = _request_json(
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

        data = _request_json(
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
        data = _request_json(
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
            payment_data = _request_json(
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
            data = _request_json(
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
        data = _request_json(
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
            data = _request_json(
                "GET",
                f"{base}/v1/checkout/sessions/{gw_id}",
                headers=self._headers(),
            )
            raw_st = "paid" if data.get("payment_status") == "paid" else data.get("status")
            gateway_reference = str(data.get("id") or gw_id)
            resolved_gw_pid = str(data.get("payment_intent") or gw_id)
        else:
            data = _request_json(
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
            session_data = _request_json(
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
        data = _request_json(
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
            data = _request_json(
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

        data = _request_json(
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
            ch0 = _request_json(
                "GET",
                f"{base}/charges/{gw_id}",
                headers=self._headers(),
            )
            raw_status = ch0.get("status")
            resolved_id = str(ch0.get("id") or gw_id)
            paid_at = ch0.get("paid_at")
        else:
            data = _request_json(
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
            order_data = _request_json(
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

        data = _request_json(
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


_ADAPTER_REGISTRY: dict[str, type[BasePaymentAdapter]] = {
    "sandbox": SandboxPaymentAdapter,
    "mercadopago": MercadoPagoAdapter,
    "stripe": StripeAdapter,
    "pagseguro": PagSeguroAdapter,
}


def get_payment_adapter(gateway: str) -> BasePaymentAdapter:
    """Instancia o adaptador correspondente ao gateway solicitado."""
    key = (gateway or "").strip().lower()
    cls = _ADAPTER_REGISTRY.get(key)
    if cls is None:
        raise PaymentGatewayError(
            f"Gateway de pagamento não suportado: '{gateway}'.",
            code="UNSUPPORTED_GATEWAY",
            http_status=400,
        )
    if key == "sandbox" and not is_sandbox_enabled():
        raise GatewayNotConfiguredError("Gateway Sandbox desabilitado neste ambiente.")
    return cls()
