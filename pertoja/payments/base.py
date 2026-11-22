"""Interface base comum para adaptadores de gateway de pagamento."""

from __future__ import annotations

from typing import Any, Mapping


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
        """Cria uma intenção ou cobrança de pagamento no gateway."""
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
        """Consulta ou confirma o estado atual de uma cobrança no gateway."""
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
        """Solicita estorno total ou parcial de uma transação aprovada."""
        raise NotImplementedError

    def verify_webhook(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        query_params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Valida assinatura HMAC/timestamp e extrai dados do evento webhook."""
        raise NotImplementedError
