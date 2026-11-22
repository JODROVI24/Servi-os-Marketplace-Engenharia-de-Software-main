"""Registro público e fábrica de adaptadores de gateway de pagamento."""

from __future__ import annotations

from pertoja.payments.base import BasePaymentAdapter
from pertoja.payments.errors import (
    GatewayNotConfiguredError,
    PaymentGatewayError,
    WebhookSignatureError,
)
from pertoja.payments.http import _request_json
from pertoja.payments.mercadopago import MercadoPagoAdapter
from pertoja.payments.pagseguro import PagSeguroAdapter
from pertoja.payments.sandbox import SandboxPaymentAdapter
from pertoja.payments.stripe import StripeAdapter
from pertoja.payments.utils import (
    DEFAULT_TIMEOUT_SECONDS,
    SUPPORTED_GATEWAYS,
    WEBHOOK_TOLERANCE_SECONDS,
    _build_boleto_codes,
    _build_pix_emvco,
    _crc16_ccitt,
    _fallback_event_id,
    _get_header_ci,
    _map_status,
    _notification_url,
    _parse_json_bytes,
    _parse_kv_signature_header,
    _require_env,
    _return_base_url,
    _split_payer_name,
    _tlv,
    _validate_timestamp,
    is_sandbox_enabled,
    list_gateway_configs,
)

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


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "SUPPORTED_GATEWAYS",
    "WEBHOOK_TOLERANCE_SECONDS",
    "_ADAPTER_REGISTRY",
    "BasePaymentAdapter",
    "GatewayNotConfiguredError",
    "MercadoPagoAdapter",
    "PagSeguroAdapter",
    "PaymentGatewayError",
    "SandboxPaymentAdapter",
    "StripeAdapter",
    "WebhookSignatureError",
    "_build_boleto_codes",
    "_build_pix_emvco",
    "_crc16_ccitt",
    "_fallback_event_id",
    "_get_header_ci",
    "_map_status",
    "_notification_url",
    "_parse_json_bytes",
    "_parse_kv_signature_header",
    "_request_json",
    "_require_env",
    "_return_base_url",
    "_split_payer_name",
    "_tlv",
    "_validate_timestamp",
    "get_payment_adapter",
    "is_sandbox_enabled",
    "list_gateway_configs",
]
