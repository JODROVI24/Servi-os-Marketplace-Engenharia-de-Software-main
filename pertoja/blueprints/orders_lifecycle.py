"""Rotas de ciclo de vida do pedido (status, confirmação e disputa) para orders_bp."""

from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from pertoja.db.connection import DBIntegrityError
from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    log_escrow_ledger,
    rate_limit,
    require_active_account,
    row_get,
)


def register_order_lifecycle_routes(orders_bp) -> None:
    """Anexa rotas de atualização de status, confirmação 48h e abertura de disputa."""

    @orders_bp.route("/api/orders/<int:order_id>/status", methods=["PATCH"])
    @rate_limit(30, 60)
    def update_order_status(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Não autenticado."}), 401

        data = request.get_json() or {}
        novo_status = data.get("status")
        motivo = str(data.get("motivo") or "").strip()[:500]
        valid_statuses = (
            "solicitado",
            "confirmado",
            "em_transito",
            "em_execucao",
            "finalizado",
            "cancelado",
            "em_disputa",
        )
        if novo_status not in valid_statuses:
            return jsonify({"error": f"Status inválido. Escolha: {', '.join(valid_statuses)}"}), 400

        if row_get(user, "status_conta", "ativo") != "ativo" and novo_status != "cancelado":
            return jsonify(
                {"error": "Conta suspensa cautelarmente ou bloqueada não pode avançar ou confirmar chamados."}
            ), 403

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404

            if user["tipo"] == "prestador" and order["prestador_id"] != user["id"]:
                return jsonify({"error": "Sem permissão para alterar este pedido."}), 403
            if user["tipo"] == "cliente" and order["cliente_id"] != user["id"]:
                return jsonify({"error": "Sem permissão para alterar este pedido."}), 403

            atual_status = order["status"]
            if atual_status == "cancelado":
                return jsonify({"error": "Não é permitido alterar um pedido cancelado."}), 400

            if novo_status == "em_disputa":
                return jsonify({"error": "Para abrir disputa, utilize POST /api/orders/<id>/dispute."}), 400

            allowed_transitions = {
                "solicitado": {"confirmado", "cancelado"},
                "confirmado": {"em_transito", "cancelado"},
                "em_transito": {"em_execucao", "cancelado"},
                "em_execucao": {"finalizado", "cancelado"},
                "finalizado": {"finalizado"},
            }
            if atual_status not in allowed_transitions or novo_status not in allowed_transitions[atual_status]:
                return jsonify({"error": f"Transição inválida de {atual_status} para {novo_status}."}), 400

            if novo_status in ("confirmado", "em_transito", "em_execucao") and user["tipo"] != "prestador":
                return jsonify({"error": f"Apenas o prestador pode alterar o status para {novo_status}."}), 403

            if atual_status == "finalizado" and novo_status == "finalizado" and user["tipo"] != "cliente":
                return jsonify({"error": "Apenas o cliente pode confirmar a conclusão do pedido finalizado."}), 403

            if novo_status == "cancelado" and not motivo:
                return jsonify({"error": "Informe o motivo do cancelamento."}), 400

            if novo_status == "em_execucao":
                pin_tentativas = int(row_get(order, "pin_tentativas", 0) or 0)
                if pin_tentativas >= 5:
                    return jsonify(
                        {"error": "Limite de 5 tentativas de PIN excedido. Pedido bloqueado por segurança."}
                    ), 429
                pin_esperado = str(row_get(order, "codigo_confirmacao", "") or "").strip()
                if not pin_esperado:
                    return jsonify({"error": "Código de confirmação (PIN) ausente no pedido."}), 400
                pin_informado = str(data.get("codigo_confirmacao") or "").strip()
                if not pin_informado or pin_informado != pin_esperado:
                    conn.execute(
                        "UPDATE orders SET pin_tentativas = COALESCE(pin_tentativas, 0) + 1, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
                        (order_id,),
                    )
                    conn.commit()
                    return jsonify(
                        {
                            "error": "Código de confirmação (PIN) obrigatório e deve corresponder ao informado pelo cliente.",
                            "pin_tentativas": pin_tentativas + 1,
                        }
                    ), 400

            escrow_status = row_get(order, "escrow_status", "pendente")
            taxa_deslocamento = float(row_get(order, "taxa_deslocamento", 0.0) or 0.0)
            valor_estornado = float(row_get(order, "valor_estornado", 0.0) or 0.0)
            pago_int = int(row_get(order, "pago", 0) or 0)
            preco = float(row_get(order, "preco_total", 0.0) or 0.0)
            release_due_at = row_get(order, "release_due_at")
            confirmado_cli = int(row_get(order, "confirmado_cliente", 0) or 0)

            cursor = conn.cursor()
            if novo_status == "cancelado":
                if atual_status == "em_execucao" and pago_int == 1 and user["tipo"] == "cliente":
                    return jsonify(
                        {"error": "Pedido em execução e já pago exige abertura de mediação (/dispute)."}
                    ), 400
                if pago_int == 1:
                    if atual_status in ("em_transito", "em_execucao") and user["tipo"] == "cliente":
                        taxa_deslocamento = min(round(preco * 0.20, 2), 40.0)
                        valor_estornado = round(max(0.0, preco - taxa_deslocamento), 2)
                        escrow_status = "estornado_parcial"
                    else:
                        taxa_deslocamento = 0.0
                        valor_estornado = preco
                        escrow_status = "estornado_total"
                    log_escrow_ledger(
                        conn,
                        order_id,
                        "escrow_refund",
                        valor_estornado,
                        escrow_status,
                        f"Cancelamento ({atual_status}): {motivo}",
                    )
                cursor.execute(
                    """
                    UPDATE orders
                    SET status = ?, motivo_cancelamento = ?, escrow_status = ?,
                        taxa_deslocamento = ?, valor_estornado = ?, atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ? AND status != 'cancelado'
                """,
                    (novo_status, motivo, escrow_status, taxa_deslocamento, valor_estornado, order_id),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    return jsonify({"error": "Conflito ao atualizar status do pedido."}), 409
            elif novo_status == "finalizado":
                if user["tipo"] == "cliente":
                    if confirmado_cli == 1 or escrow_status == "liberado":
                        return jsonify({"error": "Conclusão do pedido já foi confirmada anteriormente."}), 409
                    if pago_int == 1:
                        escrow_status = "liberado"
                        log_escrow_ledger(
                            conn, order_id, "escrow_release", preco, "liberado", "Confirmação de conclusão pelo cliente"
                        )
                    else:
                        escrow_status = "pendente"
                    cursor.execute(
                        """
                        UPDATE orders
                        SET status = ?, escrow_status = ?, confirmado_cliente = 1,
                            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                            released_at = CASE WHEN pago = 1 THEN CURRENT_TIMESTAMP ELSE released_at END,
                            atualizado_em = CURRENT_TIMESTAMP
                        WHERE id = ? AND COALESCE(confirmado_cliente, 0) = 0 AND COALESCE(escrow_status, 'pendente') != 'liberado'
                    """,
                        (novo_status, escrow_status, order_id),
                    )
                    if cursor.rowcount != 1:
                        conn.rollback()
                        return jsonify({"error": "Conclusão já confirmada."}), 409
                else:
                    if atual_status == "finalizado":
                        return jsonify({"error": "Pedido já finalizado."}), 409
                    if pago_int == 1:
                        due_utc = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=48)
                        release_due_at = due_utc.strftime("%Y-%m-%d %H:%M:%S")
                        escrow_status = "aguardando_liberacao"
                        log_escrow_ledger(
                            conn,
                            order_id,
                            "escrow_48h_window",
                            preco,
                            "aguardando_liberacao",
                            f"Janela de liberação 48h iniciada até {release_due_at}",
                        )
                    cursor.execute(
                        """
                        UPDATE orders
                        SET status = ?, escrow_status = ?,
                            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                            release_due_at = COALESCE(?, release_due_at),
                            atualizado_em = CURRENT_TIMESTAMP
                        WHERE id = ? AND status = 'em_execucao'
                    """,
                        (novo_status, escrow_status, release_due_at, order_id),
                    )
                    if cursor.rowcount != 1:
                        conn.rollback()
                        return jsonify({"error": "Conflito ao finalizar pedido."}), 409
            else:
                conn.execute(
                    """
                    UPDATE orders
                    SET status = ?, atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (novo_status, order_id),
                )

            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "message": f"Status do pedido atualizado para {novo_status}.",
                "status": novo_status,
                "escrow_status": escrow_status,
                "taxa_deslocamento": taxa_deslocamento,
                "valor_estornado": valor_estornado,
                "release_due_at": str(release_due_at) if release_due_at else None,
            }
        )

    @orders_bp.route("/api/orders/<int:order_id>/confirm-completion", methods=["POST"])
    def confirm_order_completion(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401
        if user["tipo"] != "cliente":
            return jsonify({"error": "Apenas o cliente pode confirmar a conclusão do serviço."}), 403
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404
            if order["cliente_id"] != user["id"]:
                return jsonify({"error": "Sem permissão para confirmar este pedido."}), 403
            if order["status"] not in ("em_execucao", "finalizado"):
                return jsonify({"error": f"Pedido em status '{order['status']}' não pode ser confirmado."}), 400

            escrow_status = row_get(order, "escrow_status", "pendente")
            confirmado_cli = int(row_get(order, "confirmado_cliente", 0) or 0)
            if confirmado_cli == 1 or escrow_status == "liberado":
                return jsonify({"error": "Conclusão do pedido já foi confirmada anteriormente."}), 409

            pago_int = int(row_get(order, "pago", 0) or 0)
            if pago_int == 1:
                escrow_status = "liberado"
                log_escrow_ledger(
                    conn,
                    order_id,
                    "escrow_release",
                    order["preco_total"],
                    "liberado",
                    "Confirmação de conclusão via /confirm-completion",
                )
            else:
                escrow_status = "pendente"

            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE orders
                SET status = 'finalizado',
                    confirmado_cliente = 1,
                    escrow_status = ?,
                    completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                    released_at = CASE WHEN pago = 1 THEN CURRENT_TIMESTAMP ELSE released_at END,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND COALESCE(confirmado_cliente, 0) = 0 AND COALESCE(escrow_status, 'pendente') != 'liberado'
            """,
                (escrow_status, order_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({"error": "Conclusão já confirmada anteriormente."}), 409
            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "message": "Conclusão confirmada e pagamento liberado com sucesso!",
                "order_id": order_id,
                "status": "finalizado",
                "confirmado_cliente": True,
                "escrow_status": escrow_status,
            }
        ), 200

    @orders_bp.route("/api/orders/<int:order_id>/dispute", methods=["POST"])
    @rate_limit(10, 60)
    def open_order_dispute(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        motivo = str(data.get("motivo") or "").strip()[:500]
        descricao = str(data.get("descricao") or data.get("evidencias") or "").strip()[:2000]
        if not motivo:
            return jsonify({"error": "Informe o motivo da disputa."}), 400

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404
            if user["id"] not in (order["cliente_id"], order["prestador_id"]):
                return jsonify({"error": "Sem permissão para abrir disputa neste pedido."}), 403
            if order["status"] == "em_disputa":
                return jsonify({"error": "Este pedido já possui disputa aberta."}), 409
            if order["status"] not in ("confirmado", "em_transito", "em_execucao", "finalizado"):
                return jsonify(
                    {"error": f"Não é possível abrir disputa para pedido com status '{order['status']}'."}
                ), 400

            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO disputes (order_id, opened_by, motivo, descricao, status)
                    VALUES (?, ?, ?, ?, 'aberta')
                """,
                    (order_id, user["id"], motivo, descricao),
                )
            except DBIntegrityError:
                conn.rollback()
                return jsonify({"error": "Já existe uma disputa aberta para este pedido."}), 409
            dispute_id = cursor.lastrowid
            conn.execute(
                """
                UPDATE orders
                SET status = 'em_disputa', escrow_status = 'em_disputa', atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (order_id,),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "message": "Disputa aberta com sucesso. O valor permanece retido em garantia durante a mediação.",
                "dispute_id": dispute_id,
                "order_id": order_id,
                "status": "em_disputa",
                "escrow_status": "em_disputa",
            }
        ), 201
