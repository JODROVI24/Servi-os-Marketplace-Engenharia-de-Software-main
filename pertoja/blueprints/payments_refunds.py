"""Rota de estorno de transações registrada no payments_bp."""

import secrets

from flask import jsonify, request

from pertoja._compat import resolve_compat
from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    log_escrow_ledger,
    rate_limit,
    require_active_account,
    row_get,
)
from pertoja.payments import (
    GatewayNotConfiguredError,
    PaymentGatewayError,
    get_payment_adapter,
)
from pertoja.services.payments_logic import (
    check_idempotency,
    compute_request_hash,
    extract_idempotency_key,
    lookup_payment_tx,
    save_idempotency,
)


def register_payment_refund_routes(payments_bp) -> None:
    """Anexa a rota POST /api/payments/<payment_ref>/refund ao payments_bp."""

    @payments_bp.route("/api/payments/<payment_ref>/refund", methods=["POST"])
    @rate_limit(20, 60)
    def refund_payment(payment_ref):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória.", "code": "UNAUTHORIZED"}), 401
        if user["tipo"] != "cliente":
            return jsonify({"error": "Apenas o cliente pode solicitar estorno."}), 403
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        idempotency_key = extract_idempotency_key(data)
        reason = str(data.get("reason") or data.get("motivo") or "").strip()[:300]

        conn = compat_get_db_connection()
        try:
            tx = lookup_payment_tx(conn, payment_ref)
            if not tx:
                return jsonify({"error": "Pagamento não encontrado."}), 404
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (tx["order_id"],)).fetchone()
            if not order or order["cliente_id"] != user["id"]:
                return jsonify({"error": "Pagamento não encontrado."}), 404

            escrow_atual = row_get(order, "escrow_status", "pendente")
            if order["status"] in ("em_execucao", "finalizado", "em_disputa") or escrow_atual in (
                "liberado",
                "aguardando_liberacao",
                "em_disputa",
                "congelado_disputa",
            ):
                return jsonify(
                    {"error": "Estorno direto indisponível neste estágio do pedido; utilize a abertura de disputa."}
                ), 409
            if tx["status"] not in ("paid", "escrow_held", "partially_refunded"):
                return jsonify({"error": f"Pagamento em status '{tx['status']}' não pode ser estornado."}), 409

            already_refunded = int(row_get(tx, "refunded_cents", 0) or 0)
            remaining_cents = int(tx["amount_cents"]) - already_refunded
            if remaining_cents <= 0:
                return jsonify({"error": "Pagamento já foi totalmente estornado."}), 409

            if data.get("amount_cents") is not None:
                try:
                    requested_cents = int(data.get("amount_cents"))
                except (ValueError, TypeError):
                    return jsonify({"error": "amount_cents inválido."}), 400
            elif data.get("amount") is not None:
                try:
                    requested_cents = int(round(float(data.get("amount")) * 100))
                except (ValueError, TypeError):
                    return jsonify({"error": "amount inválido."}), 400
            else:
                requested_cents = remaining_cents

            if requested_cents <= 0:
                return jsonify({"error": "Valor de estorno deve ser positivo."}), 400
            if requested_cents > remaining_cents:
                return jsonify({"error": "Valor de estorno excede o saldo disponível."}), 409

            req_hash = compute_request_hash(
                {
                    "payment_id": tx["id"],
                    "requested_cents": requested_cents,
                    "reason": reason,
                }
            )
            idem_state, idem_payload = check_idempotency(conn, user["id"], "refund_payment", idempotency_key, req_hash)
            if idem_state == "conflict":
                return jsonify(
                    {
                        "error": "Chave de idempotência reutilizada com parâmetros diferentes.",
                        "code": "IDEMPOTENCY_CONFLICT",
                    }
                ), 409
            if idem_state == "replay":
                return jsonify(idem_payload[1]), idem_payload[0]

            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE payment_transactions
                SET refunded_cents = refunded_cents + ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND (amount_cents - refunded_cents) >= ?
            """,
                (requested_cents, tx["id"], requested_cents),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({"error": "Saldo insuficiente ou estorno concorrente em andamento."}), 409

            refund_public_id = f"ref_{secrets.token_hex(12)}"
            adapter_factory = resolve_compat("app", "get_payment_adapter", get_payment_adapter)
            try:
                adapter = adapter_factory(tx["gateway"])
                ref_res = adapter.refund_payment(
                    gateway_payment_id=tx["gateway_payment_id"],
                    amount_cents=requested_cents,
                    reason=reason,
                    idempotency_key=refund_public_id,
                    full_refund=(
                        requested_cents == int(tx["amount_cents"]) and int(row_get(tx, "refunded_cents", 0) or 0) == 0
                    ),
                )
            except GatewayNotConfiguredError as exc:
                conn.rollback()
                return jsonify({"error": str(exc), "code": exc.code}), exc.http_status
            except PaymentGatewayError as exc:
                conn.rollback()
                return jsonify({"error": str(exc), "code": exc.code}), exc.http_status

            if ref_res.get("status") != "succeeded":
                conn.rollback()
                return jsonify({"error": "Estorno não foi aprovado pelo gateway.", "code": "REFUND_FAILED"}), 502

            refreshed_tx = conn.execute(
                "SELECT refunded_cents, amount_cents FROM payment_transactions WHERE id = ?",
                (tx["id"],),
            ).fetchone()
            total_refunded = int(refreshed_tx["refunded_cents"])
            is_full = total_refunded >= int(refreshed_tx["amount_cents"])
            new_tx_status = "refunded" if is_full else "partially_refunded"
            new_escrow_status = "estornado_total" if is_full else "estornado_parcial"
            gateway_refund_id = ref_res.get("gateway_refund_id")

            cursor.execute(
                """
                INSERT INTO payment_refunds (
                    public_id, payment_id, order_id, requested_by, amount_cents, reason, status, gateway_refund_id
                )
                VALUES (?, ?, ?, ?, ?, ?, 'succeeded', ?)
            """,
                (refund_public_id, tx["id"], order["id"], user["id"], requested_cents, reason, gateway_refund_id),
            )
            cursor.execute(
                "UPDATE payment_transactions SET status = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
                (new_tx_status, tx["id"]),
            )
            cursor.execute(
                "UPDATE orders SET escrow_status = ?, valor_estornado = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
                (new_escrow_status, round(total_refunded / 100.0, 2), order["id"]),
            )
            log_escrow_ledger(
                conn,
                order["id"],
                "escrow_refund",
                round(requested_cents / 100.0, 2),
                new_escrow_status,
                f"Estorno via {tx['gateway']}: {reason}" if reason else f"Estorno via {tx['gateway']}",
            )

            resp_body = {
                "refund_id": refund_public_id,
                "payment_id": tx["public_id"],
                "order_id": order["id"],
                "status": new_tx_status,
                "escrow_status": new_escrow_status,
                "refunded_cents": total_refunded,
                "requested_cents": requested_cents,
                "gateway_refund_id": gateway_refund_id,
            }
            idem_race = save_idempotency(
                conn, user["id"], "refund_payment", idempotency_key, req_hash, tx["id"], 200, resp_body
            )
            if idem_race:
                race_state, race_payload = idem_race
                if race_state == "conflict":
                    return jsonify({"error": "Conflito de idempotência."}), 409
                return jsonify(race_payload[1]), race_payload[0]

            conn.commit()
            return jsonify(resp_body), 200
        finally:
            conn.close()
