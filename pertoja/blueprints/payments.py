"""Blueprint de configuração, métodos salvos e consulta de pagamentos."""

import secrets

from flask import Blueprint, jsonify, request

from pertoja.blueprints.payments_intents import register_payment_intent_routes
from pertoja.blueprints.payments_refunds import register_payment_refund_routes
from pertoja.db.connection import DBIntegrityError
from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    rate_limit,
    require_active_account,
    row_get,
)
from pertoja.payments import is_sandbox_enabled, list_gateway_configs
from pertoja.services.payments_logic import (
    VALID_PAYMENT_GATEWAYS,
    contains_forbidden_card_fields,
    lookup_payment_tx,
    serialize_payment_tx,
)

payments_bp = Blueprint("payments", __name__)


@payments_bp.route("/api/payments/config", methods=["GET"])
@rate_limit(60, 60)
def get_payments_config():
    """Retorna gateways configurados e disponibilidade do sandbox."""
    sandbox_enabled = is_sandbox_enabled()
    configs = list_gateway_configs()
    default_gateway = (
        "sandbox" if sandbox_enabled else next((g["id"] for g in configs if g.get("configured")), "mercadopago")
    )
    return jsonify({"default_gateway": default_gateway, "sandbox_enabled": sandbox_enabled, "gateways": configs}), 200


@payments_bp.route("/api/payments/methods", methods=["GET", "POST"])
@rate_limit(30, 60)
def payment_methods_collection():
    """Lista ou cadastra cartões tokenizados (PCI-safe, sem PAN/CVV)."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória.", "code": "UNAUTHORIZED"}), 401

    conn = compat_get_db_connection()
    try:
        if request.method == "GET":
            rows = conn.execute(
                """
                SELECT id, public_id, gateway, brand, last4, exp_month, exp_year, holder_label, is_default, criado_em
                FROM payment_methods
                WHERE user_id = ? AND active = 1
                ORDER BY is_default DESC, id DESC
            """,
                (user["id"],),
            ).fetchall()
            return jsonify([dict(r) for r in rows]), 200

        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        if contains_forbidden_card_fields(data):
            return jsonify(
                {"error": "Dados brutos de cartão (PAN/CVV) não são permitidos.", "code": "PCI_VIOLATION"}
            ), 400

        gateway = str(data.get("gateway") or "sandbox").strip().lower()
        if gateway not in VALID_PAYMENT_GATEWAYS:
            return jsonify({"error": "Gateway inválido."}), 400
        if gateway == "sandbox" and not is_sandbox_enabled():
            return jsonify({"error": "Gateway sandbox desabilitado."}), 403

        gateway_token = str(data.get("gateway_token") or "").strip()
        brand = str(data.get("brand") or "").strip()[:40]
        last4 = str(data.get("last4") or "").strip()
        holder_label = str(data.get("holder_label") or "").strip()[:80] or None
        gateway_customer_id = str(data.get("gateway_customer_id") or "").strip()[:120] or None
        is_default = 1 if data.get("is_default") else 0

        if not gateway_token or not brand or len(last4) != 4 or not last4.isdigit():
            return jsonify({"error": "Token, bandeira e last4 (4 dígitos) são obrigatórios."}), 400

        try:
            exp_month = int(data.get("exp_month"))
            exp_year = int(data.get("exp_year"))
        except (ValueError, TypeError):
            return jsonify({"error": "Mês e ano de validade inválidos."}), 400

        if not (1 <= exp_month <= 12) or exp_year < 2024:
            return jsonify({"error": "Data de validade fora do intervalo permitido."}), 400

        public_id = f"pm_{secrets.token_hex(12)}"
        cursor = conn.cursor()
        try:
            if is_default:
                cursor.execute("UPDATE payment_methods SET is_default = 0 WHERE user_id = ?", (user["id"],))
            cursor.execute(
                """
                INSERT INTO payment_methods (
                    public_id, user_id, gateway, gateway_customer_id, gateway_token,
                    brand, last4, exp_month, exp_year, holder_label, is_default, active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
                (
                    public_id,
                    user["id"],
                    gateway,
                    gateway_customer_id,
                    gateway_token,
                    brand,
                    last4,
                    exp_month,
                    exp_year,
                    holder_label,
                    is_default,
                ),
            )
            method_id = cursor.lastrowid
            conn.commit()
        except DBIntegrityError:
            conn.rollback()
            return jsonify({"error": "Método de pagamento já cadastrado para este gateway."}), 409

        return jsonify(
            {
                "id": method_id,
                "public_id": public_id,
                "gateway": gateway,
                "brand": brand,
                "last4": last4,
                "exp_month": exp_month,
                "exp_year": exp_year,
                "holder_label": holder_label,
                "is_default": bool(is_default),
            }
        ), 201
    finally:
        conn.close()


@payments_bp.route("/api/payments/methods/<method_ref>", methods=["DELETE"])
@rate_limit(30, 60)
def delete_payment_method(method_ref):
    """Remove método de pagamento tokenizado do usuário autenticado."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória.", "code": "UNAUTHORIZED"}), 401
    acct_err = require_active_account(user)
    if acct_err:
        return acct_err

    conn = compat_get_db_connection()
    try:
        ref = str(method_ref or "").strip()
        row = conn.execute("SELECT * FROM payment_methods WHERE public_id = ?", (ref,)).fetchone()
        if not row and ref.isdigit():
            row = conn.execute("SELECT * FROM payment_methods WHERE id = ?", (int(ref),)).fetchone()
        if not row or row["user_id"] != user["id"]:
            return jsonify({"error": "Método de pagamento não encontrado."}), 404

        conn.execute("DELETE FROM payment_methods WHERE id = ? AND user_id = ?", (row["id"], user["id"]))
        conn.commit()
        return jsonify({"message": "Método de pagamento removido com sucesso."}), 200
    finally:
        conn.close()


@payments_bp.route("/api/payments/order/<int:order_id>", methods=["GET"])
@rate_limit(60, 60)
def get_order_payments(order_id):
    """Lista todas as transações associadas a um pedido visíveis às partes."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória.", "code": "UNAUTHORIZED"}), 401

    conn = compat_get_db_connection()
    try:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            return jsonify({"error": "Pedido não encontrado."}), 404
        if user["id"] not in (order["cliente_id"], order["prestador_id"]):
            return jsonify({"error": "Sem permissão para visualizar pagamentos deste pedido."}), 403

        is_provider = user["id"] == order["prestador_id"] and user["id"] != order["cliente_id"]
        rows = conn.execute(
            "SELECT * FROM payment_transactions WHERE order_id = ? ORDER BY id DESC",
            (order_id,),
        ).fetchall()
        return jsonify(
            {
                "order_id": order_id,
                "pago": bool(int(row_get(order, "pago", 0) or 0)),
                "escrow_status": row_get(order, "escrow_status", "pendente"),
                "metodo_pagamento": row_get(order, "metodo_pagamento", "escrow"),
                "transactions": [serialize_payment_tx(r, is_provider=is_provider) for r in rows],
            }
        ), 200
    finally:
        conn.close()


@payments_bp.route("/api/payments/<payment_ref>", methods=["GET"])
@rate_limit(60, 60)
def get_payment_detail(payment_ref):
    """Retorna os detalhes de uma transação específica visível ao cliente ou prestador."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória.", "code": "UNAUTHORIZED"}), 401

    conn = compat_get_db_connection()
    try:
        tx = lookup_payment_tx(conn, payment_ref)
        if not tx:
            return jsonify({"error": "Pagamento não encontrado."}), 404
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (tx["order_id"],)).fetchone()
        if not order or user["id"] not in (order["cliente_id"], order["prestador_id"]):
            return jsonify({"error": "Pagamento não encontrado."}), 404

        is_provider = user["id"] == order["prestador_id"] and user["id"] != order["cliente_id"]
        return jsonify(serialize_payment_tx(tx, is_provider=is_provider)), 200
    finally:
        conn.close()


register_payment_intent_routes(payments_bp)
register_payment_refund_routes(payments_bp)
