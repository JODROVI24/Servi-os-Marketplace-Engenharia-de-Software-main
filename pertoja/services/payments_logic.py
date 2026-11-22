"""Regras de negócio de pagamento, idempotência PCI-safe e liquidação de Escrow."""

import hashlib
import json

from flask import request

from pertoja.db.connection import DBIntegrityError
from pertoja.extensions import log_escrow_ledger, row_get

VALID_PAYMENT_GATEWAYS = ("sandbox", "mercadopago", "stripe", "pagseguro")
VALID_PAYMENT_METHODS = ("pix", "cartao", "boleto", "escrow")
FORBIDDEN_CARD_KEYS = frozenset(
    {
        "card_number",
        "pan",
        "cvv",
        "cvc",
        "security_code",
        "card_pan",
        "numero_cartao",
        "codigo_seguranca",
    }
)


def contains_forbidden_card_fields(payload) -> bool:
    """Rejeita recursivamente quaisquer chaves de PAN/CVV brutos (PCI-DSS)."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).strip().lower() in FORBIDDEN_CARD_KEYS:
                return True
            if contains_forbidden_card_fields(v):
                return True
    elif isinstance(payload, list):
        for item in payload:
            if contains_forbidden_card_fields(item):
                return True
    return False


def compute_request_hash(payload_dict: dict) -> str:
    """Gera hash SHA-256 canônico do corpo para verificação de idempotência."""
    canonical = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_idempotency_key(data) -> str | None:
    """Extrai chave de idempotência do cabeçalho HTTP ou payload JSON."""
    key = request.headers.get("Idempotency-Key")
    if not key and isinstance(data, dict):
        key = data.get("idempotency_key")
    if key is None:
        return None
    key = str(key).strip()
    return key[:128] if key else None


def check_idempotency(conn, user_id: int, scope: str, idempotency_key: str | None, request_hash: str):
    """Consulta registro prévio de idempotência retornando ('miss'|'conflict'|'replay', payload)."""
    if not idempotency_key:
        return ("miss", None)
    row = conn.execute(
        "SELECT * FROM payment_idempotency_keys WHERE user_id = ? AND scope = ? AND idempotency_key = ?",
        (user_id, scope, idempotency_key),
    ).fetchone()
    if not row:
        return ("miss", None)
    if row["request_hash"] != request_hash:
        return ("conflict", None)
    if row["response_status"] is not None and row["response_body"] is not None:
        try:
            body = json.loads(row["response_body"])
        except (json.JSONDecodeError, TypeError, ValueError):
            body = {"status": "ok"}
        return ("replay", (int(row["response_status"]), body))
    return ("conflict", None)


def save_idempotency(
    conn,
    user_id: int,
    scope: str,
    idempotency_key: str | None,
    request_hash: str,
    payment_id: int,
    response_status: int,
    response_body: dict,
):
    """Registra chave de idempotência tratando corrida via fallback para replay/conflict."""
    if not idempotency_key:
        return None
    try:
        conn.execute(
            """
            INSERT INTO payment_idempotency_keys (
                user_id, scope, idempotency_key, request_hash, payment_id, response_status, response_body
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                user_id,
                scope,
                idempotency_key,
                request_hash,
                payment_id,
                int(response_status),
                json.dumps(response_body, ensure_ascii=False),
            ),
        )
        return None
    except DBIntegrityError:
        conn.rollback()
        row = conn.execute(
            "SELECT * FROM payment_idempotency_keys WHERE user_id = ? AND scope = ? AND idempotency_key = ?",
            (user_id, scope, idempotency_key),
        ).fetchone()
        if row and row["request_hash"] == request_hash and row["response_status"] is not None:
            try:
                body = json.loads(row["response_body"])
            except (json.JSONDecodeError, TypeError, ValueError):
                body = response_body
            return ("replay", (int(row["response_status"]), body))
        return ("conflict", None)


def lookup_payment_tx(conn, payment_ref: str):
    """Localiza transação por public_id ou id numérico."""
    ref = str(payment_ref or "").strip()
    if not ref:
        return None
    row = conn.execute("SELECT * FROM payment_transactions WHERE public_id = ?", (ref,)).fetchone()
    if row:
        return row
    if ref.isdigit():
        return conn.execute("SELECT * FROM payment_transactions WHERE id = ?", (int(ref),)).fetchone()
    return None


def serialize_payment_tx(tx, is_provider: bool = False) -> dict:
    """Serializa transação mascarando segredos de cobrança quando visualizada pelo prestador."""
    return {
        "id": tx["id"],
        "payment_id": tx["public_id"],
        "public_id": tx["public_id"],
        "order_id": tx["order_id"],
        "user_id": tx["user_id"],
        "gateway": tx["gateway"],
        "method": tx["method"],
        "status": tx["status"],
        "amount_cents": int(tx["amount_cents"]),
        "refunded_cents": int(row_get(tx, "refunded_cents", 0) or 0),
        "currency": row_get(tx, "currency", "BRL"),
        "gateway_payment_id": row_get(tx, "gateway_payment_id"),
        "gateway_reference": row_get(tx, "gateway_reference"),
        "checkout_url": None if is_provider else row_get(tx, "checkout_url"),
        "pix_qr_code": None if is_provider else row_get(tx, "pix_qr_code"),
        "pix_qr_base64": None if is_provider else row_get(tx, "pix_qr_base64"),
        "boleto_barcode": row_get(tx, "boleto_barcode"),
        "boleto_digitable_line": row_get(tx, "boleto_digitable_line"),
        "boleto_url": None if is_provider else row_get(tx, "boleto_url"),
        "payment_method_id": None if is_provider else row_get(tx, "payment_method_id"),
        "escrow_synced": bool(int(row_get(tx, "escrow_synced", 0) or 0)),
        "failure_code": row_get(tx, "failure_code"),
        "failure_message": row_get(tx, "failure_message"),
        "expires_at": str(row_get(tx, "expires_at")) if row_get(tx, "expires_at") else None,
        "paid_at": str(row_get(tx, "paid_at")) if row_get(tx, "paid_at") else None,
        "criado_em": str(row_get(tx, "criado_em")) if row_get(tx, "criado_em") else None,
    }


def settle_payment_and_sync_escrow(conn, payment, order):
    """Liquida pagamento de forma atômica e sincroniza estado de Escrow e razão."""
    order_id = order["id"]
    payment_id = payment["id"]
    method = row_get(payment, "method", "escrow")
    preco = float(row_get(order, "preco_total", 0.0) or 0.0)

    if order["status"] in ("cancelado", "em_disputa"):
        return (False, f"Pedido em status '{order['status']}' não pode ser liquidado.")

    cursor = conn.cursor()
    if order["status"] == "finalizado":
        tx_status = "released"
        new_escrow = "liberado"
        cursor.execute(
            """
            UPDATE orders
            SET pago = 1, escrow_status = 'liberado', confirmado_cliente = 1,
                metodo_pagamento = ?, released_at = COALESCE(released_at, CURRENT_TIMESTAMP),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND pago = 0 AND status NOT IN ('cancelado', 'em_disputa')
        """,
            (method, order_id),
        )
        if cursor.rowcount != 1:
            return (False, "Pedido já pago ou em estado inválido.")
        cursor.execute(
            """
            UPDATE payment_transactions
            SET status = 'released', escrow_synced = 1,
                paid_at = COALESCE(paid_at, CURRENT_TIMESTAMP),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND escrow_synced = 0
        """,
            (payment_id,),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return (False, "Pagamento já sincronizado anteriormente.")
        log_escrow_ledger(
            conn, order_id, "escrow_release", preco, "liberado", f"Pagamento liberado na conclusão ({method})"
        )
    else:
        tx_status = "escrow_held"
        new_escrow = "retido"
        cursor.execute(
            """
            UPDATE orders
            SET pago = 1, escrow_status = 'retido', metodo_pagamento = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND pago = 0 AND status NOT IN ('cancelado', 'em_disputa')
        """,
            (method, order_id),
        )
        if cursor.rowcount != 1:
            return (False, "Pedido já pago ou em estado inválido.")
        cursor.execute(
            """
            UPDATE payment_transactions
            SET status = 'escrow_held', escrow_synced = 1,
                paid_at = COALESCE(paid_at, CURRENT_TIMESTAMP),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND escrow_synced = 0
        """,
            (payment_id,),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return (False, "Pagamento já sincronizado anteriormente.")
        log_escrow_ledger(conn, order_id, "escrow_hold", preco, "retido", f"Pagamento retido em Escrow ({method})")
    return (True, {"status": tx_status, "escrow_status": new_escrow})
