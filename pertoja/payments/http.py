"""Cliente HTTP JSON compartilhado para chamadas aos gateways de pagamento."""

from __future__ import annotations

from typing import Any

import requests

from pertoja._compat import resolve_compat
from pertoja.payments.errors import PaymentGatewayError
from pertoja.payments.utils import DEFAULT_TIMEOUT_SECONDS


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
    req_mod = resolve_compat("payment_adapters", "requests", requests)
    try:
        resp = req_mod.request(
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


def call_request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Invoca _request_json respeitando monkeypatch de `payment_adapters._request_json`."""
    fn = resolve_compat("payment_adapters", "_request_json", _request_json)
    return fn(
        method,
        url,
        headers=headers,
        json_body=json_body,
        data=data,
        timeout=timeout,
    )
