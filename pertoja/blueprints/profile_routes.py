"""Rotas de perfil, LGPD e verificação KYC registradas no blueprint auth."""

import re
import secrets
from datetime import datetime, timezone

from flask import jsonify, request, session
from werkzeug.security import generate_password_hash

from pertoja._compat import resolve_compat
from pertoja.config import PROF_REG_REGEX
from pertoja.extensions import (
    compat_get_db_connection,
    get_current_user,
    rate_limit,
    require_active_account,
    row_get,
    safe_coord,
)
from pertoja.services.geo import geocode_address


def register_profile_routes(auth_bp) -> None:
    """Anexa rotas de perfil, portabilidade/anonimização LGPD e KYC no auth_bp."""

    @auth_bp.route("/api/profile", methods=["GET", "PUT"])
    def profile():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Acesso não autorizado. Faça login."}), 401

        conn = compat_get_db_connection()
        if request.method == "GET":
            conn.close()
            return jsonify(
                {
                    "id": user["id"],
                    "nome": user["nome"],
                    "email": user["email"],
                    "tipo": user["tipo"],
                    "plano": row_get(user, "plano", "basico"),
                    "telefone": user["telefone"],
                    "bio": user["bio"],
                    "cep": user["cep"],
                    "endereco": user["endereco"],
                    "numero": user["numero"],
                    "complemento": user["complemento"],
                    "bairro": user["bairro"],
                    "cidade": user["cidade"],
                    "estado": user["estado"],
                    "lat": user["lat"],
                    "lng": user["lng"],
                    "disponivel": bool(user["disponivel"]),
                    "avaliacao_media": user["avaliacao_media"],
                    "total_avaliacoes": row_get(user, "total_avaliacoes", 0),
                    "kyc_tier": row_get(user, "kyc_tier", 1),
                    "kyc_status": row_get(user, "kyc_status", "aprovado"),
                    "kyc_documento_tipo": row_get(user, "kyc_documento_tipo", "RG"),
                    "registro_profissional": row_get(user, "registro_profissional"),
                    "status_conta": row_get(user, "status_conta", "ativo"),
                }
            )

        data = request.get_json() or {}

        def _clean_str(val, fallback=""):
            if val is None:
                return str(fallback or "").strip()
            return str(val).strip()

        nome = _clean_str(data.get("nome"), user["nome"])
        telefone = _clean_str(data.get("telefone"), user["telefone"])
        bio = _clean_str(data.get("bio"), user["bio"])

        cep = _clean_str(data.get("cep"), user["cep"])
        endereco = _clean_str(data.get("endereco"), user["endereco"])
        numero = _clean_str(data.get("numero"), user["numero"])
        complemento = _clean_str(data.get("complemento"), user["complemento"])
        bairro = _clean_str(data.get("bairro"), user["bairro"])
        cidade = _clean_str(data.get("cidade"), user["cidade"])
        estado = _clean_str(data.get("estado"), user["estado"])

        raw_lat = data.get("lat")
        raw_lng = data.get("lng")

        geo_fn = resolve_compat("app", "geocode_address", geocode_address)
        if raw_lat is None or raw_lat == "" or raw_lng is None or raw_lng == "":
            if endereco:
                g_lat, g_lng = geo_fn(
                    f"{endereco} {numero}, {bairro}, {cidade} - {estado}",
                    street=endereco,
                    neighborhood=bairro,
                    city=cidade,
                    state=estado,
                )
                lat = g_lat if g_lat is not None else safe_coord(user["lat"], -23.5653)
                lng = g_lng if g_lng is not None else safe_coord(user["lng"], -46.6517)
            else:
                lat = safe_coord(user["lat"], -23.5653)
                lng = safe_coord(user["lng"], -46.6517)
        else:
            lat = safe_coord(raw_lat, safe_coord(user["lat"], -23.5653))
            lng = safe_coord(raw_lng, safe_coord(user["lng"], -46.6517))

        disponivel = 1 if data.get("disponivel", bool(user["disponivel"])) else 0

        conn.execute(
            """
            UPDATE users
            SET nome = ?, telefone = ?, bio = ?, cep = ?, endereco = ?, numero = ?, complemento = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?, disponivel = ?
            WHERE id = ?
        """,
            (
                nome,
                telefone,
                bio,
                cep,
                endereco,
                numero,
                complemento,
                bairro,
                cidade,
                estado,
                lat,
                lng,
                disponivel,
                user["id"],
            ),
        )

        if user["tipo"] == "prestador":
            conn.execute(
                """
                UPDATE services
                SET cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?
                WHERE prestador_id = ?
            """,
                (cep, endereco, numero, bairro, cidade, estado, lat, lng, user["id"]),
            )

        conn.commit()
        conn.close()

        session["user_nome"] = nome
        return jsonify({"message": "Perfil e localização atualizados com sucesso!"})

    @auth_bp.route("/api/profile", methods=["DELETE"])
    def delete_profile():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Acesso não autorizado. Faça login."}), 401

        conn = compat_get_db_connection()
        try:
            dispute_order = conn.execute(
                "SELECT id FROM orders WHERE (cliente_id = ? OR prestador_id = ?) AND status = 'em_disputa' LIMIT 1",
                (user["id"], user["id"]),
            ).fetchone()
            if dispute_order:
                return jsonify(
                    {"error": "Não é possível excluir a conta enquanto houver pedido em disputa aberta."}
                ), 409

            anon_email = f"anon_{user['id']}_{secrets.token_hex(4)}@anon.pertoja.local"
            unusable_hash = generate_password_hash(secrets.token_hex(32))
            conn.execute(
                """
                UPDATE users
                SET nome = 'Usuário Anonimizado',
                    email = ?,
                    senha_hash = ?,
                    telefone = NULL,
                    bio = NULL,
                    foto_url = NULL,
                    cep = NULL,
                    endereco = NULL,
                    numero = NULL,
                    complemento = NULL,
                    bairro = NULL,
                    cidade = NULL,
                    estado = NULL,
                    lat = NULL,
                    lng = NULL,
                    cpf = NULL,
                    registro_profissional = NULL,
                    kyc_provider_ref = NULL,
                    disponivel = 0,
                    status_conta = 'anonimizado',
                    session_version = COALESCE(session_version, 1) + 1
                WHERE id = ?
            """,
                (anon_email, unusable_hash, user["id"]),
            )
            conn.execute(
                """
                UPDATE services
                SET ativo = 0,
                    cep = NULL,
                    endereco = NULL,
                    numero = NULL,
                    bairro = NULL,
                    cidade = NULL,
                    estado = NULL,
                    lat = NULL,
                    lng = NULL
                WHERE prestador_id = ?
            """,
                (user["id"],),
            )
            conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
            conn.execute("DELETE FROM payment_methods WHERE user_id = ?", (user["id"],))
            conn.commit()
        finally:
            conn.close()

        session.clear()
        return jsonify({"message": "Conta anonimizada e sessão encerrada conforme LGPD Art. 18."}), 200

    @auth_bp.route("/api/profile/export", methods=["GET"])
    def export_profile_data():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Acesso não autorizado. Faça login."}), 401

        conn = compat_get_db_connection()
        try:
            user_dict = dict(user)
            user_dict.pop("senha_hash", None)
            services = [
                dict(r) for r in conn.execute("SELECT * FROM services WHERE prestador_id = ?", (user["id"],)).fetchall()
            ]
            orders = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM orders WHERE cliente_id = ? OR prestador_id = ? ORDER BY criado_em DESC",
                    (user["id"], user["id"]),
                ).fetchall()
            ]
            reviews = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM reviews WHERE cliente_id = ? OR prestador_id = ? ORDER BY criado_em DESC",
                    (user["id"], user["id"]),
                ).fetchall()
            ]
            consents = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM user_consents WHERE user_id = ? ORDER BY accepted_at DESC",
                    (user["id"],),
                ).fetchall()
            ]
        finally:
            conn.close()

        return jsonify(
            {
                "exported_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
                "user": user_dict,
                "services": services,
                "orders": orders,
                "reviews": reviews,
                "consents": consents,
            }
        ), 200

    @auth_bp.route("/api/kyc/verify", methods=["POST"])
    @rate_limit(10, 60)
    def verify_kyc():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Acesso não autorizado. Faça login."}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        current_kyc_status = row_get(user, "kyc_status", "aprovado")
        if current_kyc_status in ("em_revisao", "reprovado"):
            return jsonify({"error": "Verificação KYC em revisão ou reprovada. Aguarde análise da equipe."}), 403

        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data:
            return jsonify({"error": "Payload de verificação KYC obrigatório."}), 400

        raw_doc_tipo = data.get("kyc_documento_tipo") or data.get("documento_tipo")
        doc_tipo = str(raw_doc_tipo or "").strip().upper()
        if doc_tipo not in ("RG", "CIN", "CNH"):
            return jsonify({"error": "Tipo de documento inválido ou ausente. Escolha RG, CIN ou CNH."}), 400

        raw_reg = data.get("registro_profissional")
        if raw_reg is not None and str(raw_reg).strip():
            registro_prof = str(raw_reg).strip()
            if not PROF_REG_REGEX.match(registro_prof):
                return jsonify(
                    {"error": "Registro profissional inválido. Utilize formato CREA, CFT, CRT, NR-10 ou CAU."}
                ), 400
        else:
            registro_prof = row_get(user, "registro_profissional")

        selfie_ok = data.get("selfie_verificada") is True
        homonimo = bool(data.get("homonimo"))
        raw_cpf = str(data.get("cpf") or "").strip()
        cpf_limpo = re.sub(r"\D", "", raw_cpf) if raw_cpf else None
        if raw_cpf and len(cpf_limpo) != 11:
            return jsonify({"error": "CPF inválido. Informe 11 dígitos numéricos."}), 400

        req_tier = data.get("tier")
        if req_tier is not None:
            if isinstance(req_tier, bool):
                return jsonify({"error": "Tier KYC inválido."}), 400
            try:
                req_tier = int(req_tier)
            except (ValueError, TypeError):
                return jsonify({"error": "Tier KYC inválido."}), 400
        else:
            req_tier = None

        has_valid_cpf_tier0 = req_tier == 0 and cpf_limpo is not None and len(cpf_limpo) == 11
        if not (selfie_ok or has_valid_cpf_tier0):
            return jsonify(
                {"error": "É necessário confirmar selfie_verificada=true ou informar CPF válido para Tier 0."}
            ), 400

        has_valid_reg = bool(registro_prof and PROF_REG_REGEX.match(str(registro_prof)))
        if selfie_ok and has_valid_reg and (req_tier is None or req_tier >= 2):
            tier = 2
        elif has_valid_cpf_tier0 and not selfie_ok:
            tier = 0
        elif req_tier == 0:
            tier = 0
        else:
            tier = 1

        kyc_status = "em_revisao" if homonimo else "aprovado"
        provider_ref = f"kyc-{user['id']}-{secrets.token_hex(4)}"
        conn = compat_get_db_connection()
        try:
            conn.execute(
                """
                UPDATE users
                SET kyc_tier = ?,
                    kyc_status = ?,
                    kyc_documento_tipo = ?,
                    kyc_provider_ref = ?,
                    kyc_verified_at = CURRENT_TIMESTAMP,
                    registro_profissional = COALESCE(?, registro_profissional),
                    cpf = COALESCE(?, cpf)
                WHERE id = ?
            """,
                (tier, kyc_status, doc_tipo, provider_ref, registro_prof, cpf_limpo, user["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify(
            {
                "message": (
                    "Cadastro encaminhado para revisão humana (homônimo)."
                    if homonimo
                    else "Verificação KYC concluída com sucesso."
                ),
                "kyc_tier": tier,
                "kyc_status": kyc_status,
                "kyc_documento_tipo": doc_tipo,
                "kyc_provider_ref": provider_ref,
                "registro_profissional": registro_prof,
            }
        ), 200
