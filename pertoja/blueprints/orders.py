"""Blueprint de criação, pagamento legado e listagem de pedidos."""

import secrets

from flask import Blueprint, jsonify, request

from pertoja.blueprints.orders_extras import register_order_extra_routes
from pertoja.blueprints.orders_lifecycle import register_order_lifecycle_routes
from pertoja.extensions import (
    compat_get_db_connection,
    get_client_ip,
    get_current_user,
    hash_ip,
    is_review_revealed,
    log_escrow_ledger,
    mask_phone,
    rate_limit,
    require_active_account,
    row_get,
    safe_coord,
)
from pertoja.services.payments_logic import contains_forbidden_card_fields

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/api/orders", methods=["POST"])
@rate_limit(20, 60)
def create_order():
    """Cria novo chamado de serviço para o cliente autenticado com PIN de 4 dígitos."""
    user = get_current_user()
    if not user:
        return jsonify(
            {
                "error": "Autenticação obrigatória. Faça login para concluir o pedido.",
                "code": "UNAUTHORIZED",
                "login_url": "/login.html?redirect=/pedido.html",
            }
        ), 401

    if user["tipo"] != "cliente":
        return jsonify(
            {
                "error": "Apenas clientes autenticados podem solicitar serviços. Prestadores de serviços não têm permissão para criar chamados.",
                "code": "FORBIDDEN",
            }
        ), 403

    if row_get(user, "status_conta", "ativo") in ("suspenso_cautelar", "bloqueado"):
        return jsonify(
            {"error": "Conta suspensa cautelarmente ou bloqueada não pode criar chamados.", "code": "FORBIDDEN"}
        ), 403

    if row_get(user, "kyc_status", "aprovado") in ("em_revisao", "reprovado"):
        return jsonify(
            {"error": "Conta em revisão cadastral (KYC) ou reprovada não pode criar chamados.", "code": "FORBIDDEN"}
        ), 403

    if int(row_get(user, "email_verified", 1) or 0) == 0:
        return jsonify({"error": "Confirme seu e-mail antes de solicitar serviços.", "code": "EMAIL_NOT_VERIFIED"}), 403

    data = request.get_json() or {}

    aceite_termos = data.get("aceite_termos")
    if aceite_termos in (False, "false", "False", "0", 0):
        return jsonify(
            {"error": "É necessário aceitar os Termos de Uso e Política de Privacidade para criar o pedido."}
        ), 400

    if data.get("cliente_id") is not None:
        try:
            if int(data.get("cliente_id")) != int(user["id"]):
                return jsonify(
                    {
                        "error": "Tentativa de forjar cliente_id arbitrária detectada. O pedido só pode ser associado à sessão autenticada.",
                        "code": "FORBIDDEN",
                    }
                ), 403
        except (ValueError, TypeError):
            return jsonify({"error": "cliente_id inválido.", "code": "BAD_REQUEST"}), 400

    servico_id = data.get("servico_id")
    if not servico_id:
        return jsonify({"error": "servico_id é obrigatório.", "code": "BAD_REQUEST"}), 400

    conn = compat_get_db_connection()
    service = conn.execute("SELECT * FROM services WHERE id = ? AND ativo = 1", (servico_id,)).fetchone()
    if not service:
        conn.close()
        return jsonify({"error": "Serviço selecionado não está disponível.", "code": "NOT_FOUND"}), 404

    if service["prestador_id"] == user["id"]:
        conn.close()
        return jsonify(
            {"error": "Não é permitido solicitar seu próprio serviço.", "code": "SELF_HIRE_NOT_ALLOWED"}
        ), 400

    prestador = conn.execute("SELECT id, status_conta FROM users WHERE id = ?", (service["prestador_id"],)).fetchone()
    if not prestador or row_get(prestador, "status_conta", "ativo") != "ativo":
        conn.close()
        return jsonify({"error": "Prestador indisponível ou suspenso no momento.", "code": "PROVIDER_UNAVAILABLE"}), 403

    observacoes = str(data.get("observacoes") or "").strip()[:1000]
    complemento_cli = str(data.get("complemento") or row_get(user, "complemento", "")).strip()
    modalidade = str(data.get("modalidade") or "imediato").strip().lower()
    if modalidade not in ("imediato", "agendado"):
        modalidade = "imediato"
    agendado_para = str(data.get("agendado_para") or "").strip() or None
    metodo_pagamento = str(data.get("metodo_pagamento") or "escrow").strip().lower()
    if metodo_pagamento == "escrow_local":
        metodo_pagamento = "escrow"
    elif metodo_pagamento not in ("pix", "cartao", "boleto", "escrow"):
        metodo_pagamento = "escrow"
    codigo_confirmacao = f"{secrets.randbelow(9000) + 1000}"

    cep_cli = str(data.get("cep") or user["cep"] or "").strip()
    end_cli = str(data.get("endereco") or user["endereco"] or "").strip()
    num_cli = str(data.get("numero") or user["numero"] or "").strip()
    bairro_cli = str(data.get("bairro") or user["bairro"] or "").strip()
    cidade_cli = str(data.get("cidade") or user["cidade"] or "São Paulo").strip()
    estado_cli = str(data.get("estado") or user["estado"] or "SP").strip()

    user_lat_fallback = safe_coord(user["lat"], -23.5653, -90.0, 90.0)
    user_lng_fallback = safe_coord(user["lng"], -46.6517, -180.0, 180.0)
    lat_cliente = safe_coord(data.get("lat"), user_lat_fallback, -90.0, 90.0)
    lng_cliente = safe_coord(data.get("lng"), user_lng_fallback, -180.0, 180.0)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO orders (
            cliente_id, prestador_id, servico_id, preco_total, observacoes,
            cep_cliente, endereco_cliente, numero_cliente, complemento_cliente,
            bairro_cliente, cidade_cliente, estado_cliente, lat_cliente, lng_cliente,
            modalidade, agendado_para, metodo_pagamento, pago, codigo_confirmacao, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'solicitado')
    """,
        (
            user["id"],
            service["prestador_id"],
            service["id"],
            service["preco"],
            observacoes,
            cep_cli,
            end_cli,
            num_cli,
            complemento_cli,
            bairro_cli,
            cidade_cli,
            estado_cli,
            lat_cliente,
            lng_cliente,
            modalidade,
            agendado_para,
            metodo_pagamento,
            codigo_confirmacao,
        ),
    )
    conn.commit()
    order_id = cursor.lastrowid
    if aceite_termos in (True, "true", "True", "1", 1):
        conn.execute(
            "INSERT INTO user_consents (user_id, doc_type, doc_version, ip_hash) VALUES (?, 'pedido_escrow', ?, ?)",
            (user["id"], str(data.get("versao_termos") or "2026.1").strip()[:20], hash_ip(get_client_ip())),
        )
        conn.commit()
    conn.close()

    return jsonify(
        {
            "message": "Pedido solicitado com sucesso!",
            "order_id": order_id,
            "status": "solicitado",
            "cliente_id": user["id"],
            "codigo_confirmacao": codigo_confirmacao,
            "modalidade": modalidade,
            "metodo_pagamento": metodo_pagamento,
        }
    ), 201


@orders_bp.route("/api/orders/<int:order_id>/pay", methods=["POST"])
def pay_order(order_id):
    """Processa pagamento direto/escrow legado no card do pedido."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória para efetuar pagamento.", "code": "UNAUTHORIZED"}), 401

    if user["tipo"] != "cliente":
        return jsonify({"error": "Apenas clientes podem efetuar pagamento de pedidos.", "code": "FORBIDDEN"}), 403
    acct_err = require_active_account(user)
    if acct_err:
        return acct_err

    conn = compat_get_db_connection()
    try:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            return jsonify({"error": "Pedido não encontrado.", "code": "NOT_FOUND"}), 404

        if order["cliente_id"] != user["id"]:
            return jsonify({"error": "Sem permissão para pagar pedido de outro cliente.", "code": "FORBIDDEN"}), 403

        data = request.get_json(silent=True) or {}
        if contains_forbidden_card_fields(data):
            return jsonify(
                {"error": "Dados brutos de cartão (PAN/CVV) não são permitidos.", "code": "PCI_VIOLATION"}
            ), 400
        escrow_hold = bool(data.get("escrow_hold"))
        metodo_pagamento = (
            str(data.get("metodo_pagamento") or row_get(order, "metodo_pagamento", "escrow")).strip().lower()
        )
        if metodo_pagamento not in ("pix", "cartao", "boleto", "escrow"):
            metodo_pagamento = "escrow"

        if order["status"] in ("em_disputa", "cancelado"):
            return jsonify(
                {"error": f"Não é possível efetuar pagamento de pedido com status '{order['status']}'."}
            ), 400

        escrow_atual = row_get(order, "escrow_status", "pendente")
        if int(row_get(order, "pago", 0) or 0) == 1 or escrow_atual in ("retido", "aguardando_liberacao", "liberado"):
            return jsonify({"error": "Pagamento já efetuado ou pedido já em escrow/liberado."}), 409

        amount_cents = max(1, int(round(float(row_get(order, "preco_total", 0.0) or 0.0) * 100)))
        cursor = conn.cursor()
        if (escrow_hold and order["status"] != "finalizado") or order["status"] in (
            "solicitado",
            "confirmado",
            "em_transito",
        ):
            cursor.execute(
                """
                UPDATE orders
                SET pago = 1, escrow_status = 'retido', metodo_pagamento = ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND pago = 0 AND status NOT IN ('finalizado', 'cancelado', 'em_disputa')
                  AND COALESCE(escrow_status, 'pendente') NOT IN ('retido', 'aguardando_liberacao', 'liberado')
            """,
                (metodo_pagamento, order_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({"error": "Pagamento já processado ou estado inválido."}), 409
            log_escrow_ledger(
                conn,
                order_id,
                "escrow_hold",
                order["preco_total"],
                "retido",
                f"Pagamento retido em Escrow ({metodo_pagamento})",
            )
            cursor.execute(
                """
                INSERT INTO payment_transactions (
                    public_id, order_id, user_id, gateway, method, status,
                    amount_cents, gateway_payment_id, escrow_synced, paid_at
                )
                VALUES (?, ?, ?, 'sandbox', ?, 'escrow_held', ?, ?, 1, CURRENT_TIMESTAMP)
            """,
                (
                    f"pay_{secrets.token_hex(12)}",
                    order_id,
                    user["id"],
                    metodo_pagamento,
                    amount_cents,
                    f"sbx_legacy_{order_id}_{secrets.token_hex(6)}",
                ),
            )
            conn.commit()
            return jsonify(
                {
                    "message": "Pagamento retido em garantia (escrow) com sucesso!",
                    "order_id": order_id,
                    "status": order["status"],
                    "pago": True,
                    "escrow_status": "retido",
                    "metodo_pagamento": metodo_pagamento,
                }
            ), 200

        cursor.execute(
            """
            UPDATE orders
            SET pago = 1, status = 'finalizado', escrow_status = 'liberado',
                confirmado_cliente = 1,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                released_at = CURRENT_TIMESTAMP,
                metodo_pagamento = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND pago = 0 AND status NOT IN ('cancelado', 'em_disputa')
              AND COALESCE(escrow_status, 'pendente') NOT IN ('retido', 'aguardando_liberacao', 'liberado')
        """,
            (metodo_pagamento, order_id),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({"error": "Pagamento já processado ou estado inválido."}), 409
        log_escrow_ledger(
            conn,
            order_id,
            "escrow_release",
            order["preco_total"],
            "liberado",
            f"Pagamento liberado na conclusão ({metodo_pagamento})",
        )
        cursor.execute(
            """
            INSERT INTO payment_transactions (
                public_id, order_id, user_id, gateway, method, status,
                amount_cents, gateway_payment_id, escrow_synced, paid_at
            )
            VALUES (?, ?, ?, 'sandbox', ?, 'released', ?, ?, 1, CURRENT_TIMESTAMP)
        """,
            (
                f"pay_{secrets.token_hex(12)}",
                order_id,
                user["id"],
                metodo_pagamento,
                amount_cents,
                f"sbx_legacy_{order_id}_{secrets.token_hex(6)}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        {
            "message": "Pagamento confirmado e pedido finalizado com sucesso!",
            "order_id": order_id,
            "status": "finalizado",
            "escrow_status": "liberado",
            "pago": True,
        }
    ), 200


@orders_bp.route("/api/orders", methods=["GET"])
def list_orders():
    """Lista os pedidos do cliente ou prestador autenticado respeitando mascaramento LGPD."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Acesso não autorizado."}), 401

    conn = compat_get_db_connection()
    if user["tipo"] == "cliente":
        sql = """
            SELECT
                o.id AS order_id,
                o.status,
                o.preco_total,
                o.observacoes,
                o.complemento_cliente,
                o.modalidade,
                o.agendado_para,
                o.metodo_pagamento,
                o.pago,
                o.codigo_confirmacao,
                o.motivo_cancelamento,
                o.escrow_status,
                o.taxa_deslocamento,
                o.valor_estornado,
                o.share_token,
                o.confirmado_cliente,
                o.release_due_at,
                o.prestador_lat_atual,
                o.prestador_lng_atual,
                o.prestador_gps_accuracy,
                o.prestador_gps_updated_at,
                EXISTS(SELECT 1 FROM reviews r WHERE r.order_id = o.id AND COALESCE(r.autor_tipo, 'cliente') = 'cliente') AS ja_avaliado,
                o.criado_em,
                COALESCE(s.titulo, 'Serviço Solicitado') AS servico_titulo,
                COALESCE(s.categoria, 'Geral') AS servico_categoria,
                u.id AS prestador_id,
                COALESCE(u.nome, 'Profissional') AS prestador_nome,
                u.telefone AS prestador_telefone,
                COALESCE(s.endereco, u.endereco) AS prestador_endereco,
                COALESCE(s.numero, u.numero) AS prestador_numero,
                COALESCE(s.bairro, u.bairro) AS prestador_bairro,
                COALESCE(s.cidade, u.cidade) AS prestador_cidade,
                COALESCE(s.estado, u.estado) AS prestador_estado,
                COALESCE(s.lat, u.lat) AS prestador_lat,
                COALESCE(s.lng, u.lng) AS prestador_lng
            FROM orders o
            LEFT JOIN services s ON o.servico_id = s.id
            LEFT JOIN users u ON o.prestador_id = u.id
            WHERE o.cliente_id = ?
            ORDER BY o.criado_em DESC
        """
        orders = conn.execute(sql, (user["id"],)).fetchall()
    else:
        sql = """
            SELECT
                o.id AS order_id,
                o.status,
                o.preco_total,
                o.observacoes,
                o.cep_cliente,
                o.endereco_cliente,
                o.numero_cliente,
                o.complemento_cliente,
                o.bairro_cliente,
                o.cidade_cliente,
                o.estado_cliente,
                o.lat_cliente,
                o.lng_cliente,
                o.modalidade,
                o.agendado_para,
                o.metodo_pagamento,
                o.pago,
                o.codigo_confirmacao,
                o.motivo_cancelamento,
                o.escrow_status,
                o.taxa_deslocamento,
                o.valor_estornado,
                o.share_token,
                o.confirmado_cliente,
                o.release_due_at,
                o.prestador_lat_atual,
                o.prestador_lng_atual,
                o.prestador_gps_accuracy,
                o.prestador_gps_updated_at,
                EXISTS(SELECT 1 FROM reviews r WHERE r.order_id = o.id AND COALESCE(r.autor_tipo, 'cliente') = 'prestador') AS ja_avaliado,
                o.criado_em,
                COALESCE(s.titulo, 'Serviço Solicitado') AS servico_titulo,
                COALESCE(s.categoria, 'Geral') AS servico_categoria,
                u.id AS cliente_id,
                COALESCE(u.nome, 'Cliente') AS cliente_nome,
                u.telefone AS cliente_telefone
            FROM orders o
            LEFT JOIN services s ON o.servico_id = s.id
            LEFT JOIN users u ON o.cliente_id = u.id
            WHERE o.prestador_id = ?
            ORDER BY o.criado_em DESC
        """
        orders = conn.execute(sql, (user["id"],)).fetchall()

    counterpart_tipo = "prestador" if user["tipo"] == "cliente" else "cliente"
    counterpart_reviews = {}
    order_ids = [o["order_id"] for o in orders]
    if order_ids:
        placeholders = ",".join(["?"] * len(order_ids))
        rev_rows = conn.execute(
            f"SELECT id, order_id, revealed_at, criado_em, replied_at, contestada FROM reviews WHERE order_id IN ({placeholders}) AND COALESCE(autor_tipo, 'cliente') = ?",
            (*order_ids, counterpart_tipo),
        ).fetchall()
        for rr in rev_rows:
            if is_review_revealed(rr):
                counterpart_reviews[rr["order_id"]] = {
                    "id": rr["id"],
                    "replied": row_get(rr, "replied_at") is not None,
                    "contestada": bool(int(row_get(rr, "contestada", 0) or 0)),
                }

    conn.close()
    mask_pii = request.args.get("mask_pii") == "1"
    result = []
    for o in orders:
        item = dict(o)
        item["ja_avaliado"] = bool(item.get("ja_avaliado"))
        item["confirmado_cliente"] = bool(int(item.get("confirmado_cliente") or 0))
        item["release_due_at"] = str(item["release_due_at"]) if item.get("release_due_at") else None
        rev_info = counterpart_reviews.get(item["order_id"])
        item["cliente_review_id"] = rev_info["id"] if rev_info else None
        item["cliente_review_replied"] = bool(rev_info["replied"]) if rev_info else False
        item["cliente_review_contestada"] = bool(rev_info["contestada"]) if rev_info else False
        item["escrow_status"] = item.get("escrow_status") or "pendente"
        item["taxa_deslocamento"] = float(item.get("taxa_deslocamento") or 0.0)
        item["valor_estornado"] = float(item.get("valor_estornado") or 0.0)
        item["em_disputa"] = item.get("status") == "em_disputa"

        has_real_gps = (
            item.get("prestador_lat_atual") is not None
            and item.get("prestador_lng_atual") is not None
            and item.get("status") in ("confirmado", "em_transito", "em_execucao")
        )
        item["tracking_mode"] = "real_gps" if has_real_gps else "estimated"
        item["posicao_estimada"] = not has_real_gps
        if has_real_gps:
            item["prestador_gps_updated_at"] = (
                str(item["prestador_gps_updated_at"]) if item.get("prestador_gps_updated_at") else None
            )
        else:
            item["prestador_lat_atual"] = None
            item["prestador_lng_atual"] = None
            item["prestador_gps_accuracy"] = None
            item["prestador_gps_updated_at"] = None

        if user["tipo"] == "prestador":
            item["codigo_confirmacao"] = None
            item["pin_obrigatorio"] = True
            bairro = item.get("bairro_cliente") or ""
            cidade = item.get("cidade_cliente") or "São Paulo"
            st = item.get("status")
            item["endereco_protegido"] = st not in ("confirmado", "em_transito", "em_execucao")
            item["endereco_cliente_resumo"] = f"{bairro}, {cidade}".strip(", ")
            item["cliente_telefone"] = mask_phone(item.get("cliente_telefone"))
            if mask_pii or st not in ("confirmado", "em_transito", "em_execucao"):
                item["endereco_cliente"] = "Protegido"
                item["numero_cliente"] = ""
                item["complemento_cliente"] = ""
                item["cep_cliente"] = ""
                item["lat_cliente"] = None
                item["lng_cliente"] = None
        else:
            item["prestador_endereco"] = "Protegido"
            item["prestador_numero"] = ""
            item["prestador_lat"] = None
            item["prestador_lng"] = None
            item["prestador_telefone"] = mask_phone(item.get("prestador_telefone"))

        result.append(item)
    return jsonify(result)


register_order_lifecycle_routes(orders_bp)
register_order_extra_routes(orders_bp)
