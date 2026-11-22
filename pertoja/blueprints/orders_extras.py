"""Rotas de avaliações double-blind, SOS, rota compartilhada e chat do pedido."""

import math
import secrets

from flask import jsonify, request

from pertoja.db.connection import DBIntegrityError
from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    is_review_revealed,
    rate_limit,
    require_active_account,
    row_get,
    safe_coord,
)


def register_order_extra_routes(orders_bp) -> None:
    """Anexa rotas de avaliação, SOS, compartilhamento de rota e chat no orders_bp."""

    @orders_bp.route("/api/orders/<int:order_id>/review", methods=["POST"])
    def review_order(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória para avaliar pedido.", "code": "UNAUTHORIZED"}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        raw_nota = data.get("nota")
        try:
            if isinstance(raw_nota, bool) or raw_nota is None:
                raise ValueError()
            nota_f = float(raw_nota)
            if not math.isfinite(nota_f) or nota_f < 1 or nota_f > 5 or nota_f != int(nota_f):
                raise ValueError()
            nota = int(nota_f)
        except (ValueError, TypeError):
            return jsonify({"error": "A nota deve ser um número inteiro entre 1 e 5."}), 400

        comentario = str(data.get("comentario") or "").strip()[:2000]

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado.", "code": "NOT_FOUND"}), 404

            if user["tipo"] == "cliente":
                if order["cliente_id"] != user["id"]:
                    return jsonify(
                        {"error": "Sem permissão para avaliar pedido de outro cliente.", "code": "FORBIDDEN"}
                    ), 403
                autor_tipo = "cliente"
                avaliado_id = order["prestador_id"]
            elif user["tipo"] == "prestador":
                if order["prestador_id"] != user["id"]:
                    return jsonify(
                        {"error": "Sem permissão para avaliar pedido de outro prestador.", "code": "FORBIDDEN"}
                    ), 403
                autor_tipo = "prestador"
                avaliado_id = order["cliente_id"]
            else:
                return jsonify({"error": "Tipo de usuário inválido.", "code": "FORBIDDEN"}), 403

            if order["status"] != "finalizado":
                return jsonify({"error": "Apenas pedidos finalizados podem ser avaliados."}), 400

            existing = conn.execute(
                "SELECT id FROM reviews WHERE order_id = ? AND COALESCE(autor_tipo, 'cliente') = ?",
                (order_id, autor_tipo),
            ).fetchone()
            if existing:
                return jsonify({"error": "Este pedido já foi avaliado por você."}), 409

            target_user = conn.execute(
                "SELECT avaliacao_media, total_avaliacoes FROM users WHERE id = ?", (avaliado_id,)
            ).fetchone()
            old_total = int(row_get(target_user, "total_avaliacoes", 0) or 0)
            old_media = float(row_get(target_user, "avaliacao_media", 5.0) or 5.0)
            prev_real_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM reviews WHERE avaliado_id = ? OR (avaliado_id IS NULL AND prestador_id = ?)",
                (avaliado_id, avaliado_id),
            ).fetchone()
            prev_real_count = int(row_get(prev_real_row, "cnt", 0) or 0)

            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO reviews (order_id, cliente_id, prestador_id, nota, comentario, autor_tipo, avaliado_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (order_id, order["cliente_id"], order["prestador_id"], nota, comentario, autor_tipo, avaliado_id),
                )
            except DBIntegrityError:
                conn.rollback()
                return jsonify({"error": "Este pedido já foi avaliado por você."}), 409
            review_id = cursor.lastrowid

            if old_total > prev_real_count:
                novo_total = old_total + 1
                nova_media = round(((old_media * old_total) + nota) / novo_total, 2)
            else:
                stats = conn.execute(
                    "SELECT AVG(nota) AS media, COUNT(*) AS total FROM reviews WHERE avaliado_id = ? OR (avaliado_id IS NULL AND prestador_id = ?)",
                    (avaliado_id, avaliado_id),
                ).fetchone()
                nova_media = round(float(stats["media"]), 2) if stats and stats["media"] is not None else nota
                novo_total = int(stats["total"]) if stats and stats["total"] is not None else 1

            conn.execute(
                "UPDATE users SET avaliacao_media = ?, total_avaliacoes = ? WHERE id = ?",
                (nova_media, novo_total, avaliado_id),
            )

            other_tipo = "prestador" if autor_tipo == "cliente" else "cliente"
            other_rev = conn.execute(
                "SELECT id FROM reviews WHERE order_id = ? AND COALESCE(autor_tipo, 'cliente') = ?",
                (order_id, other_tipo),
            ).fetchone()
            revealed = bool(other_rev)
            if revealed:
                conn.execute("UPDATE reviews SET revealed_at = CURRENT_TIMESTAMP WHERE order_id = ?", (order_id,))
            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "message": "Avaliação registrada com sucesso!",
                "review_id": review_id,
                "autor_tipo": autor_tipo,
                "avaliacao_media": nova_media,
                "total_avaliacoes": novo_total,
                "revealed": revealed,
            }
        ), 201

    @orders_bp.route("/api/orders/<int:order_id>/reviews", methods=["GET"])
    def get_order_reviews(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404
            if user["id"] not in (order["cliente_id"], order["prestador_id"]):
                return jsonify({"error": "Sem permissão para visualizar avaliações deste pedido."}), 403

            rows = conn.execute("SELECT * FROM reviews WHERE order_id = ? ORDER BY id ASC", (order_id,)).fetchall()
        finally:
            conn.close()

        minha_avaliacao = None
        contraparte_raw = None
        for r in rows:
            r_tipo = row_get(r, "autor_tipo", "cliente") or "cliente"
            if r_tipo == user["tipo"]:
                minha_avaliacao = dict(r)
            else:
                contraparte_raw = r

        oculta_double_blind = False
        contraparte_avaliacao = None
        if contraparte_raw is not None:
            if is_review_revealed(contraparte_raw):
                contraparte_avaliacao = dict(contraparte_raw)
            else:
                oculta_double_blind = True

        return jsonify(
            {
                "order_id": order_id,
                "minha_avaliacao": minha_avaliacao,
                "contraparte_avaliacao": contraparte_avaliacao,
                "oculta_double_blind": oculta_double_blind,
            }
        ), 200

    @orders_bp.route("/api/reviews/<int:review_id>/reply", methods=["POST"])
    def reply_review(review_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        replica = str(data.get("replica") or "").strip()[:2000]
        if not replica:
            return jsonify({"error": "Informe o texto da réplica."}), 400

        conn = compat_get_db_connection()
        try:
            rev = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if not rev:
                return jsonify({"error": "Avaliação não encontrada."}), 404
            avaliado_id = row_get(rev, "avaliado_id") or rev["prestador_id"]
            if int(avaliado_id) != int(user["id"]):
                return jsonify({"error": "Apenas o usuário avaliado pode publicar uma réplica."}), 403
            if not is_review_revealed(rev):
                return jsonify({"error": "Avaliação ainda oculta pelo modo double-blind."}), 403
            if row_get(rev, "replied_at") is not None:
                return jsonify({"error": "Réplica já publicada e não pode ser editada."}), 409

            conn.execute(
                "UPDATE reviews SET replica = ?, replied_at = CURRENT_TIMESTAMP WHERE id = ?",
                (replica, review_id),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"message": "Réplica publicada com sucesso.", "review_id": review_id, "replica": replica}), 200

    @orders_bp.route("/api/reviews/<int:review_id>/contest", methods=["POST"])
    def contest_review(review_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        motivo = str(data.get("motivo") or "").strip()[:500]
        if not motivo:
            return jsonify({"error": "Informe o motivo da contestação."}), 400

        conn = compat_get_db_connection()
        try:
            rev = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if not rev:
                return jsonify({"error": "Avaliação não encontrada."}), 404
            avaliado_id = row_get(rev, "avaliado_id") or rev["prestador_id"]
            if int(avaliado_id) != int(user["id"]):
                return jsonify({"error": "Apenas o usuário avaliado pode contestar esta avaliação."}), 403
            if not is_review_revealed(rev):
                return jsonify({"error": "Avaliação ainda oculta pelo modo double-blind."}), 403
            if int(row_get(rev, "contestada", 0) or 0) == 1:
                return jsonify({"error": "Esta avaliação já foi contestada anteriormente."}), 409

            conn.execute(
                "UPDATE reviews SET contestada = 1, motivo_contestacao = ?, status_moderacao = 'em_revisao' WHERE id = ?",
                (motivo, review_id),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "message": "Contestação registrada e encaminhada para revisão.",
                "review_id": review_id,
                "status_moderacao": "em_revisao",
            }
        ), 200

    @orders_bp.route("/api/orders/<int:order_id>/sos", methods=["POST"])
    @rate_limit(10, 60)
    def trigger_order_sos(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        descricao = str(data.get("descricao") or "Acionamento de emergência SOS").strip()[:1000]
        tipo = str(data.get("tipo") or "sos").strip()[:40]
        lat = safe_coord(data.get("lat"), safe_coord(user["lat"], -23.5653, -90.0, 90.0), -90.0, 90.0)
        lng = safe_coord(data.get("lng"), safe_coord(user["lng"], -46.6517, -180.0, 180.0), -180.0, 180.0)
        denunciar = bool(data.get("denunciar_contraparte"))

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404
            if user["id"] not in (order["cliente_id"], order["prestador_id"]):
                return jsonify({"error": "Sem permissão para acionar SOS neste pedido."}), 403
            if order["status"] in ("finalizado", "cancelado"):
                return jsonify({"error": "Não é possível acionar SOS para pedido já encerrado."}), 400

            contraparte_id = order["prestador_id"] if user["id"] == order["cliente_id"] else order["cliente_id"]
            pode_suspender = bool(denunciar and order["status"] in ("confirmado", "em_transito", "em_execucao"))
            inc_status = "moderacao" if (denunciar and not pode_suspender) else "aberto"

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO safety_incidents (order_id, reporter_id, reported_user_id, tipo, descricao, lat, lng, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (order_id, user["id"], contraparte_id if denunciar else None, tipo, descricao, lat, lng, inc_status),
            )
            incident_id = cursor.lastrowid

            if pode_suspender:
                conn.execute(
                    "UPDATE users SET status_conta = 'suspenso_cautelar' WHERE id = ? AND COALESCE(status_conta, 'ativo') = 'ativo'",
                    (contraparte_id,),
                )
            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "message": "Alerta SOS registrado com prioridade máxima.",
                "incident_id": incident_id,
                "status": inc_status,
                "contraparte_suspensa": pode_suspender,
            }
        ), 201

    @orders_bp.route("/api/orders/<int:order_id>/location", methods=["POST", "GET"])
    @rate_limit(120, 60)
    def order_location(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404

            active_statuses = ("confirmado", "em_transito", "em_execucao")

            if request.method == "GET":
                if user["id"] not in (order["cliente_id"], order["prestador_id"]):
                    return jsonify({"error": "Sem permissão para visualizar localização deste pedido."}), 403

                lat_val = row_get(order, "prestador_lat_atual")
                lng_val = row_get(order, "prestador_lng_atual")
                has_real_gps = lat_val is not None and lng_val is not None and order["status"] in active_statuses
                if has_real_gps:
                    acc_val = row_get(order, "prestador_gps_accuracy")
                    upd_val = row_get(order, "prestador_gps_updated_at")
                    return jsonify(
                        {
                            "order_id": order_id,
                            "tracking_mode": "real_gps",
                            "is_estimated": False,
                            "label": "Posição GPS em tempo real",
                            "lat": float(lat_val),
                            "lng": float(lng_val),
                            "accuracy": float(acc_val) if acc_val is not None else None,
                            "updated_at": str(upd_val) if upd_val else None,
                            "recommended_poll_seconds": 12,
                        }
                    ), 200
                return jsonify(
                    {
                        "order_id": order_id,
                        "tracking_mode": "estimated",
                        "is_estimated": True,
                        "label": "Posição estimada",
                        "lat": None,
                        "lng": None,
                        "accuracy": None,
                        "updated_at": None,
                        "recommended_poll_seconds": 12,
                    }
                ), 200

            if user["tipo"] != "prestador" or int(order["prestador_id"]) != int(user["id"]):
                return jsonify({"error": "Apenas o prestador responsável pode atualizar a localização."}), 403
            if order["status"] not in active_statuses:
                return jsonify({"error": "Atualização de GPS permitida apenas para pedidos em andamento."}), 400

            data = request.get_json(silent=True) or {}
            raw_lat = data.get("lat")
            raw_lng = data.get("lng")
            if raw_lat is None or raw_lng is None or isinstance(raw_lat, bool) or isinstance(raw_lng, bool):
                return jsonify({"error": "Coordenadas lat e lng são obrigatórias."}), 400
            try:
                lat = float(raw_lat)
                lng = float(raw_lng)
            except (ValueError, TypeError):
                return jsonify({"error": "Coordenadas lat/lng inválidas."}), 400
            if not (math.isfinite(lat) and math.isfinite(lng) and -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                return jsonify({"error": "Coordenadas lat/lng fora dos limites geográficos."}), 400

            accuracy = None
            raw_acc = data.get("accuracy")
            if raw_acc is not None:
                if isinstance(raw_acc, bool):
                    return jsonify({"error": "Precisão GPS inválida."}), 400
                try:
                    accuracy = float(raw_acc)
                except (ValueError, TypeError):
                    return jsonify({"error": "Precisão GPS inválida."}), 400
                if not math.isfinite(accuracy) or accuracy < 0.0:
                    return jsonify({"error": "Precisão GPS deve ser não negativa."}), 400

            conn.execute(
                """
                UPDATE orders
                SET prestador_lat_atual = ?,
                    prestador_lng_atual = ?,
                    prestador_gps_accuracy = ?,
                    prestador_gps_updated_at = CURRENT_TIMESTAMP,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (lat, lng, accuracy, order_id),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "order_id": order_id,
                "lat": lat,
                "lng": lng,
                "accuracy": accuracy,
                "tracking_mode": "real_gps",
                "is_estimated": False,
                "label": "Posição GPS em tempo real",
            }
        ), 200

    @orders_bp.route("/api/orders/<int:order_id>/share-route", methods=["POST"])
    def share_order_route(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404
            if user["id"] not in (order["cliente_id"], order["prestador_id"]):
                return jsonify({"error": "Sem permissão para compartilhar rota deste pedido."}), 403

            token = row_get(order, "share_token") or secrets.token_urlsafe(16)
            conn.execute("UPDATE orders SET share_token = ? WHERE id = ?", (token, order_id))
            conn.commit()
        finally:
            conn.close()

        return jsonify({"share_token": token, "share_url": f"/api/shared-route/{token}"}), 200

    @orders_bp.route("/api/shared-route/<token>", methods=["GET"])
    def get_shared_route(token):
        conn = compat_get_db_connection()
        try:
            row = conn.execute(
                """
                SELECT o.id AS order_id, o.status, o.bairro_cliente, o.cidade_cliente,
                       o.prestador_lat_atual, o.prestador_lng_atual,
                       o.atualizado_em, s.titulo AS servico_titulo, u.nome AS prestador_nome
                FROM orders o
                LEFT JOIN services s ON o.servico_id = s.id
                LEFT JOIN users u ON o.prestador_id = u.id
                WHERE o.share_token = ?
            """,
                (token,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return jsonify({"error": "Link de compartilhamento inválido ou expirado."}), 404
        if row["status"] in ("finalizado", "cancelado"):
            return jsonify({"error": "Link de compartilhamento expirado pois o pedido foi encerrado."}), 410

        lat_atual = row_get(row, "prestador_lat_atual")
        lng_atual = row_get(row, "prestador_lng_atual")
        has_real_gps = (
            lat_atual is not None
            and lng_atual is not None
            and row["status"] in ("confirmado", "em_transito", "em_execucao")
        )

        return jsonify(
            {
                "order_id": row["order_id"],
                "status": row["status"],
                "servico_titulo": row["servico_titulo"],
                "prestador_nome": row["prestador_nome"],
                "bairro_cliente": row["bairro_cliente"],
                "cidade_cliente": row["cidade_cliente"],
                "tracking_mode": "real_gps" if has_real_gps else "estimated",
                "posicao_estimada": not has_real_gps,
                "prestador_lat_atual": float(lat_atual) if has_real_gps else None,
                "prestador_lng_atual": float(lng_atual) if has_real_gps else None,
                "atualizado_em": str(row["atualizado_em"]),
            }
        ), 200

    @orders_bp.route("/api/orders/<int:order_id>/messages", methods=["GET", "POST"])
    @rate_limit(60, 60)
    def order_messages(order_id):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Autenticação obrigatória."}), 401

        conn = compat_get_db_connection()
        try:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return jsonify({"error": "Pedido não encontrado."}), 404
            if user["id"] not in (order["cliente_id"], order["prestador_id"]):
                return jsonify({"error": "Sem permissão para acessar o chat deste pedido."}), 403

            if request.method == "GET":
                rows = conn.execute(
                    """
                    SELECT m.id, m.order_id, m.sender_id, m.sender_tipo, m.mensagem, m.criado_em, u.nome AS sender_nome
                    FROM order_messages m
                    LEFT JOIN users u ON m.sender_id = u.id
                    WHERE m.order_id = ?
                    ORDER BY m.id ASC
                """,
                    (order_id,),
                ).fetchall()
                return jsonify([dict(r) for r in rows]), 200

            if order["status"] in ("finalizado", "cancelado"):
                return jsonify({"error": "O chat é somente leitura após o encerramento do pedido."}), 400

            acct_err = require_active_account(user)
            if acct_err:
                return acct_err

            data = request.get_json(silent=True) or {}
            mensagem = str(data.get("mensagem") or "").strip()[:2000]
            if not mensagem:
                return jsonify({"error": "A mensagem não pode estar vazia."}), 400

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO order_messages (order_id, sender_id, sender_tipo, mensagem)
                VALUES (?, ?, ?, ?)
            """,
                (order_id, user["id"], user["tipo"], mensagem),
            )
            msg_id = cursor.lastrowid
            conn.commit()
            return jsonify(
                {
                    "id": msg_id,
                    "order_id": order_id,
                    "sender_id": user["id"],
                    "sender_tipo": user["tipo"],
                    "mensagem": mensagem,
                }
            ), 201
        finally:
            conn.close()
