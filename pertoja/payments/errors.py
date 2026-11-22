"""Exceções específicas dos adaptadores de gateway de pagamento."""

from __future__ import annotations


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
