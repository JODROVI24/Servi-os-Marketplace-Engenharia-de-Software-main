"""Blueprint do catálogo público e CRUD de serviços."""

import hashlib
import math

from flask import Blueprint, jsonify, request, session

from pertoja.config import CATEGORIAS_PERMITIDAS, CATEGORIAS_TECNICAS
from pertoja.db.connection import DBIntegrityError
from pertoja.extensions import (
    calcular_distancia,
    compat_get_db_connection,
    get_current_user,
    mask_phone,
    parse_positive_price,
    require_active_account,
    row_get,
    safe_coord,
)

services_bp = Blueprint("services", __name__)


@services_bp.route("/api/services", methods=["GET"])
def list_services():
    """Busca serviços ativos com filtro geoespacial, categoria, busca textual e score bayesiano."""
    cat = request.args.get("cat", "Todos")
    query = request.args.get("query", "").strip().lower()
    user_lat = request.args.get("lat", type=float)
    user_lng = request.args.get("lng", type=float)
    radius = request.args.get("radius", default=15.0, type=float)
    if user_lat is not None and (not math.isfinite(user_lat) or user_lat < -90.0 or user_lat > 90.0):
        return jsonify({"error": "Parâmetro lat inválido."}), 400
    if user_lng is not None and (not math.isfinite(user_lng) or user_lng < -180.0 or user_lng > 180.0):
        return jsonify({"error": "Parâmetro lng inválido."}), 400
    if radius is not None and (not math.isfinite(radius) or radius < 0):
        return jsonify({"error": "Parâmetro radius inválido."}), 400
    order = (request.args.get("order") or "distance").strip().lower()
    only_available = request.args.get("only_available", "").strip().lower() in ("1", "true", "yes")

    conn = compat_get_db_connection()
    sql = """
        SELECT
            s.id AS service_id,
            s.titulo,
            s.descricao,
            s.categoria,
            s.preco,
            s.ativo,
            COALESCE(s.cep, u.cep) AS cep,
            COALESCE(s.endereco, u.endereco) AS endereco,
            COALESCE(s.numero, u.numero) AS numero,
            COALESCE(s.bairro, u.bairro) AS bairro,
            COALESCE(s.cidade, u.cidade) AS cidade,
            COALESCE(s.estado, u.estado) AS estado,
            COALESCE(s.lat, u.lat) AS lat,
            COALESCE(s.lng, u.lng) AS lng,
            u.id AS prestador_id,
            u.nome AS prestador_nome,
            u.telefone AS prestador_telefone,
            u.bio AS prestador_bio,
            u.avaliacao_media,
            u.total_avaliacoes,
            u.disponivel,
            COALESCE(u.plano, 'basico') AS plano,
            COALESCE(u.kyc_tier, 1) AS kyc_tier,
            COALESCE(u.kyc_status, 'aprovado') AS kyc_status,
            COALESCE(u.status_conta, 'ativo') AS status_conta
        FROM services s
        JOIN users u ON s.prestador_id = u.id
        WHERE s.ativo = 1 AND COALESCE(u.status_conta, 'ativo') = 'ativo'
    """
    params = []

    if only_available:
        sql += " AND u.disponivel = 1"

    if cat and cat != "Todos":
        sql += " AND LOWER(s.categoria) = LOWER(?)"
        params.append(cat)

    if query:
        sql += (
            " AND (LOWER(s.titulo) LIKE ? OR LOWER(s.descricao) LIKE ? OR LOWER(u.nome) LIKE ? "
            "OR LOWER(COALESCE(s.bairro, u.bairro)) LIKE ? OR LOWER(COALESCE(s.cidade, u.cidade)) LIKE ?)"
        )
        like_q = f"%{query}%"
        params.extend([like_q, like_q, like_q, like_q, like_q])

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    center_lat = user_lat if user_lat is not None else -23.5653
    center_lng = user_lng if user_lng is not None else -46.6517
    force_approx = request.args.get("approx") == "1"
    session_user_id = session.get("user_id")

    def _deterministic_jitter(service_id: int) -> tuple[float, float]:
        digest = hashlib.sha256(f"pertoja-jitter-{service_id}".encode("utf-8")).digest()
        d_lat = ((digest[0] / 255.0) * 2.0 - 1.0) * 0.0025
        d_lng = ((digest[1] / 255.0) * 2.0 - 1.0) * 0.0025
        return d_lat, d_lng

    for r in rows:
        svc_lat = r["lat"] if r["lat"] is not None else -23.5653
        svc_lng = r["lng"] if r["lng"] is not None else -46.6517

        dist_km = calcular_distancia(center_lat, center_lng, svc_lat, svc_lng)
        if radius and dist_km > radius:
            continue

        v = int(row_get(r, "total_avaliacoes", 0) or 0)
        avg = float(row_get(r, "avaliacao_media", 4.5) or 4.5)
        nota_bayes = ((v * avg) + (5 * 4.5)) / (v + 5)
        score = 1000 * (1 - min(dist_km / 15.0, 1.0)) + (nota_bayes * 100) + (200 if r["disponivel"] else 0)

        is_owner = bool(session_user_id and int(session_user_id) == int(r["prestador_id"]))
        is_approx = (not is_owner) or force_approx

        if is_approx:
            d_lat, d_lng = _deterministic_jitter(r["service_id"])
            out_lat = round(svc_lat + d_lat, 6)
            out_lng = round(svc_lng + d_lng, 6)
        else:
            out_lat = svc_lat
            out_lng = svc_lng

        partes_end = []
        if not is_approx and r["endereco"]:
            end_num = f"{r['endereco']}" + (f", {r['numero']}" if r["numero"] else "")
            partes_end.append(end_num)
        if r["bairro"]:
            partes_end.append(r["bairro"])
        if r["cidade"]:
            cid_uf = f"{r['cidade']}" + (f" - {r['estado']}" if r["estado"] else "")
            partes_end.append(cid_uf)

        endereco_formatado = " · ".join(partes_end) if partes_end else "São Paulo - SP"
        if is_approx:
            endereco_formatado = f"{endereco_formatado} (localização aproximada)"
        tel_out = r["prestador_telefone"] if not is_approx else mask_phone(r["prestador_telefone"])

        results.append(
            {
                "id": r["service_id"],
                "titulo": r["titulo"],
                "descricao": r["descricao"],
                "categoria": r["categoria"],
                "preco": r["preco"],
                "lat": out_lat,
                "lng": out_lng,
                "localizacao_aproximada": is_approx,
                "bairro": r["bairro"] or "",
                "cidade": r["cidade"] or "São Paulo",
                "estado": r["estado"] or "SP",
                "endereco_completo": endereco_formatado,
                "endereco": {
                    "cep": "" if is_approx else (r["cep"] or ""),
                    "logradouro": "" if is_approx else (r["endereco"] or ""),
                    "numero": "" if is_approx else (r["numero"] or ""),
                    "bairro": r["bairro"] or "",
                    "cidade": r["cidade"] or "São Paulo",
                    "estado": r["estado"] or "SP",
                    "completo": endereco_formatado,
                },
                "prestador": {
                    "id": r["prestador_id"],
                    "nome": r["prestador_nome"],
                    "telefone": tel_out,
                    "bio": r["prestador_bio"],
                    "avaliacao": r["avaliacao_media"],
                    "total_avaliacoes": r["total_avaliacoes"],
                    "disponivel": bool(r["disponivel"]),
                    "plano": row_get(r, "plano", "basico"),
                    "kyc_tier": int(row_get(r, "kyc_tier", 1) or 1),
                    "kyc_status": row_get(r, "kyc_status", "aprovado"),
                    "novo_no_pertoja": v < 5,
                    "super_profissional": bool(
                        (r["avaliacao_media"] or 0) >= 4.8 and (r["total_avaliacoes"] or 0) >= 5
                    ),
                    "lat": out_lat,
                    "lng": out_lng,
                },
                "distancia_km": round(dist_km, 1),
                "score": round(score),
                "score_detalhes": {
                    "raio_max_km": 15.0,
                    "nota_bayesiana": round(nota_bayes, 2),
                    "novo_no_pertoja": v < 5,
                },
            }
        )

    if order == "score":
        results.sort(key=lambda x: (-x["score"], x["distancia_km"]))
    else:
        results.sort(key=lambda x: x["distancia_km"])
    return jsonify(results)


@services_bp.route("/api/services", methods=["POST"])
def create_service():
    """Publica um novo serviço para o prestador autenticado."""
    user = get_current_user()
    if not user or user["tipo"] != "prestador":
        return jsonify({"error": "Apenas prestadores podem cadastrar serviços."}), 403

    if row_get(user, "status_conta", "ativo") in ("suspenso_cautelar", "bloqueado"):
        return jsonify({"error": "Conta suspensa ou bloqueada não pode publicar serviços."}), 403

    data = request.get_json() or {}
    titulo = str(data.get("titulo") or "").strip()[:120]
    descricao = str(data.get("descricao") or "").strip()[:2000]
    categoria = str(data.get("categoria") or "").strip()
    preco = data.get("preco")

    texto_combinado = f"{titulo} {descricao} {categoria}".lower()
    escopos_proibidos = (
        "escolta armada",
        "arma de fogo",
        "gás alta pressão sem certificação",
        "gas alta pressao sem certificacao",
        "ilícito",
        "ilicito",
    )
    if any(p in texto_combinado for p in escopos_proibidos):
        return jsonify({"error": "Escopo de serviço proibido pelas políticas de segurança do PertoJá."}), 400

    if not titulo or not categoria or preco is None:
        return jsonify({"error": "Título, categoria e preço são obrigatórios."}), 400

    if categoria not in CATEGORIAS_PERMITIDAS:
        return jsonify(
            {"error": f'Categoria "{categoria}" não permitida. Escolha entre: {", ".join(CATEGORIAS_PERMITIDAS)}.'}
        ), 400

    kyc_status = row_get(user, "kyc_status", "aprovado")
    kyc_tier = int(row_get(user, "kyc_tier", 1) or 1)
    exige_tier2 = bool(data.get("exige_kyc_tier2")) or (categoria in CATEGORIAS_TECNICAS)
    if kyc_status in ("reprovado", "em_revisao") or (exige_tier2 and kyc_tier < 2):
        return jsonify({"error": "Verificação KYC Tier 2 obrigatória para publicar este serviço."}), 403

    cep = str(data.get("cep") or user["cep"] or "").strip()
    endereco = str(data.get("endereco") or user["endereco"] or "").strip()
    numero = str(data.get("numero") or user["numero"] or "").strip()
    bairro = str(data.get("bairro") or user["bairro"] or "").strip()
    cidade = str(data.get("cidade") or user["cidade"] or "São Paulo").strip()
    estado = str(data.get("estado") or user["estado"] or "SP").strip()
    lat = safe_coord(data.get("lat"), safe_coord(user["lat"], -23.5653, -90.0, 90.0), -90.0, 90.0)
    lng = safe_coord(data.get("lng"), safe_coord(user["lng"], -46.6517, -180.0, 180.0), -180.0, 180.0)

    preco = parse_positive_price(preco)
    if preco is None:
        return jsonify({"error": "O preço deve ser um valor numérico positivo válido."}), 400

    conn = compat_get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """,
        (user["id"], titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng),
    )
    conn.commit()
    service_id = cursor.lastrowid
    conn.close()

    return jsonify({"message": "Anúncio publicado com sucesso com endereço real!", "id": service_id}), 201


@services_bp.route("/api/services/<int:service_id>", methods=["PUT"])
def update_service(service_id):
    """Atualiza dados e localização de um serviço pertencente ao prestador autenticado."""
    user = get_current_user()
    if not user or user["tipo"] != "prestador":
        return jsonify({"error": "Apenas prestadores podem alterar serviços."}), 403
    acct_err = require_active_account(user)
    if acct_err:
        return acct_err

    conn = compat_get_db_connection()
    try:
        service = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
        if not service:
            return jsonify({"error": "Serviço não encontrado."}), 404

        if service["prestador_id"] != user["id"]:
            return jsonify({"error": "Você não tem permissão para alterar este serviço."}), 403

        data = request.get_json() or {}
        if "titulo" in data and not str(data.get("titulo") or "").strip():
            return jsonify({"error": "Título não pode ser vazio."}), 400
        titulo = str(data.get("titulo") or service["titulo"]).strip()[:120]
        descricao = str(
            data.get("descricao") if data.get("descricao") is not None else (service["descricao"] or "")
        ).strip()[:2000]
        categoria = str(data.get("categoria") or service["categoria"]).strip()
        preco = data.get("preco", service["preco"])
        ativo = 1 if data.get("ativo", bool(service["ativo"])) else 0

        if any(k in data for k in ("titulo", "descricao", "categoria", "exige_kyc_tier2")):
            texto_combinado = f"{titulo} {descricao} {categoria}".lower()
            escopos_proibidos = (
                "escolta armada",
                "arma de fogo",
                "gás alta pressão sem certificação",
                "gas alta pressao sem certificacao",
                "ilícito",
                "ilicito",
            )
            if any(p in texto_combinado for p in escopos_proibidos):
                return jsonify({"error": "Escopo de serviço proibido pelas políticas de segurança do PertoJá."}), 400
            if categoria not in CATEGORIAS_PERMITIDAS:
                return jsonify(
                    {
                        "error": f'Categoria "{categoria}" não permitida. Escolha entre: {", ".join(CATEGORIAS_PERMITIDAS)}.'
                    }
                ), 400
            kyc_status = row_get(user, "kyc_status", "aprovado")
            kyc_tier = int(row_get(user, "kyc_tier", 1) or 1)
            exige_tier2 = bool(data.get("exige_kyc_tier2")) or (categoria in CATEGORIAS_TECNICAS)
            if kyc_status in ("reprovado", "em_revisao") or (exige_tier2 and kyc_tier < 2):
                return jsonify({"error": "Verificação KYC Tier 2 obrigatória para publicar este serviço."}), 403

        cep = str(data.get("cep") or service["cep"] or user["cep"] or "").strip()
        endereco = str(data.get("endereco") or service["endereco"] or user["endereco"] or "").strip()
        numero = str(data.get("numero") or service["numero"] or user["numero"] or "").strip()
        bairro = str(data.get("bairro") or service["bairro"] or user["bairro"] or "").strip()
        cidade = str(data.get("cidade") or service["cidade"] or user["cidade"] or "São Paulo").strip()
        estado = str(data.get("estado") or service["estado"] or user["estado"] or "SP").strip()
        lat = safe_coord(data.get("lat"), safe_coord(service["lat"] or user["lat"], -23.5653, -90.0, 90.0), -90.0, 90.0)
        lng = safe_coord(
            data.get("lng"), safe_coord(service["lng"] or user["lng"], -46.6517, -180.0, 180.0), -180.0, 180.0
        )

        preco = parse_positive_price(preco)
        if preco is None:
            return jsonify({"error": "Preço deve ser um valor positivo válido."}), 400

        conn.execute(
            """
            UPDATE services
            SET titulo = ?, descricao = ?, categoria = ?, preco = ?, cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?, ativo = ?
            WHERE id = ?
        """,
            (
                titulo,
                descricao,
                categoria,
                preco,
                cep,
                endereco,
                numero,
                bairro,
                cidade,
                estado,
                lat,
                lng,
                ativo,
                service_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"message": "Serviço, endereço e preço atualizados com sucesso!"})


@services_bp.route("/api/services/<int:service_id>", methods=["DELETE"])
def delete_service(service_id):
    """Remove ou desativa um serviço pertencente ao prestador autenticado."""
    user = get_current_user()
    if not user or user["tipo"] != "prestador":
        return jsonify({"error": "Acesso não autorizado."}), 403
    acct_err = require_active_account(user)
    if acct_err:
        return acct_err

    conn = compat_get_db_connection()
    service = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    if not service:
        conn.close()
        return jsonify({"error": "Serviço não encontrado."}), 404

    if service["prestador_id"] != user["id"]:
        conn.close()
        return jsonify({"error": "Acesso negado."}), 403

    try:
        conn.execute("DELETE FROM services WHERE id = ?", (service_id,))
        conn.commit()
    except DBIntegrityError:
        conn.rollback()
        conn.execute("UPDATE services SET ativo = 0 WHERE id = ?", (service_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({"message": "Serviço excluído com sucesso."})
