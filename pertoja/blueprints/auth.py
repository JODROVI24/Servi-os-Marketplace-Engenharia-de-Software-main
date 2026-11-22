"""Blueprint de autenticação, sessão, recuperação de senha e recurso de conta."""

import hashlib
import os
import re
import secrets
import sqlite3
import time

from flask import Blueprint, current_app, g, jsonify, make_response, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from pertoja._compat import resolve_compat
from pertoja.blueprints.auth_verification import (
    create_email_verification_token,
    register_auth_verification_routes,
)
from pertoja.blueprints.profile_routes import register_profile_routes
from pertoja.config import (
    CATEGORIAS_PERMITIDAS,
    CATEGORIAS_TECNICAS,
    CSRF_COOKIE_NAME,
    PROF_REG_REGEX,
    is_production_runtime,
)
from pertoja.db.connection import PG_DB_ERRORS
from pertoja.extensions import (
    check_email_rate_limit,
    compat_get_db_connection,
    get_client_ip,
    get_current_user,
    hash_ip,
    parse_positive_price,
    rate_limit,
    row_get,
    safe_coord,
    set_csrf_cookie,
)
from pertoja.services.geo import geocode_address
from pertoja.services.notifications import send_transactional_email
from pertoja.services.passwords import validate_password_policy

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/register", methods=["POST"])
@rate_limit(10, 60)
def register():
    """Registra novo cliente ou prestador com aceite LGPD e validações de KYC."""
    data = request.get_json() or {}
    nome = str(data.get("nome") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    senha = str(data.get("senha") or "")
    tipo = str(data.get("tipo") or "cliente").strip()
    plano = str(data.get("plano") or "basico").strip().lower()
    if plano not in ("basico", "pro"):
        plano = "basico"
    telefone = str(data.get("telefone") or "").strip()
    bio = str(data.get("bio") or "").strip()

    cep = str(data.get("cep") or "").strip()
    endereco = str(data.get("endereco") or "").strip()
    numero = str(data.get("numero") or "").strip()
    complemento = str(data.get("complemento") or "").strip()
    bairro = str(data.get("bairro") or "").strip()
    cidade = str(data.get("cidade") or "").strip()
    estado = str(data.get("estado") or "").strip()

    raw_lat = data.get("lat")
    raw_lng = data.get("lng")

    if not nome or not email or not senha:
        return jsonify({"error": "Nome, e-mail e senha são obrigatórios."}), 400

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Formato de e-mail inválido."}), 400

    pwd_err, pwd_code = validate_password_policy(senha, "A senha")
    if pwd_err:
        return jsonify({"error": pwd_err, "code": pwd_code}), 400

    if tipo not in ("cliente", "prestador"):
        return jsonify({"error": "Tipo de usuário inválido. Escolha cliente ou prestador."}), 400

    aceite_termos = data.get("aceite_termos")
    if aceite_termos in (False, "false", "False", "0", 0):
        return jsonify({"error": "É necessário aceitar os Termos de Uso e Política de Privacidade."}), 400
    versao_termos = str(data.get("versao_termos") or "2026.1").strip()[:20]

    kyc_documento_tipo = str(data.get("kyc_documento_tipo") or "RG").strip().upper()
    if kyc_documento_tipo not in ("RG", "CIN", "CNH"):
        kyc_documento_tipo = "RG"
    registro_profissional = str(data.get("registro_profissional") or "").strip() or None
    if registro_profissional and not PROF_REG_REGEX.match(registro_profissional):
        return jsonify({"error": "Registro profissional inválido. Utilize formato CREA, CFT, CRT, NR-10 ou CAU."}), 400
    raw_cpf = str(data.get("cpf") or "").strip()
    cpf_limpo = re.sub(r"\D", "", raw_cpf) if raw_cpf else None
    if raw_cpf and len(cpf_limpo) != 11:
        return jsonify({"error": "CPF inválido. Informe 11 dígitos numéricos."}), 400

    geo_fn = resolve_compat("app", "geocode_address", geocode_address)
    if (raw_lat is None or raw_lat == "" or raw_lng is None or raw_lng == "") and (endereco or cep):
        busca = f"{endereco} {numero}, {bairro}, {cidade} - {estado}" if endereco else f"{cep}, Brasil"
        lat, lng = geo_fn(busca, street=endereco, neighborhood=bairro, city=cidade, state=estado)
        if lat is None or lng is None:
            lat, lng = -23.5653, -46.6517
    elif raw_lat is None or raw_lat == "" or raw_lng is None or raw_lng == "":
        lat, lng = -23.5653, -46.6517
    else:
        lat = safe_coord(raw_lat, -23.5653, -90.0, 90.0)
        lng = safe_coord(raw_lng, -46.6517, -180.0, 180.0)

    categoria = str(data.get("categoria") or "").strip()
    preco_inicial = data.get("preco_inicial")

    if tipo == "prestador" and categoria and categoria not in CATEGORIAS_PERMITIDAS:
        return jsonify({"error": f'Categoria "{categoria}" não permitida pela plataforma.'}), 400

    kyc_tier = 2 if (tipo == "prestador" and registro_profissional and categoria in CATEGORIAS_TECNICAS) else 1
    if tipo == "prestador" and categoria in CATEGORIAS_TECNICAS and kyc_tier < 2:
        return jsonify(
            {"error": "Categorias técnicas (Elétrica/Encanamento) exigem registro profissional e KYC Tier 2."}
        ), 403

    require_email_verif = bool(data.get("require_email_verification")) or (
        os.environ.get("REQUIRE_EMAIL_VERIFICATION") == "1"
    )
    email_verified_val = 0 if require_email_verif else 1

    conn = compat_get_db_connection()
    try:
        user_exist = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if user_exist:
            return jsonify({"error": "Este e-mail já está cadastrado."}), 409

        senha_hash = generate_password_hash(senha)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (nome, email, senha_hash, tipo, plano, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng, kyc_tier, kyc_status, kyc_documento_tipo, registro_profissional, cpf, status_conta, email_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'aprovado', ?, ?, ?, 'ativo', ?)
        """,
            (
                nome,
                email,
                senha_hash,
                tipo,
                plano,
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
                kyc_tier,
                kyc_documento_tipo,
                registro_profissional,
                cpf_limpo,
                email_verified_val,
            ),
        )
        user_id = cursor.lastrowid

        if aceite_termos in (True, "true", "True", "1", 1):
            cursor.execute(
                """
                INSERT INTO user_consents (user_id, doc_type, doc_version, ip_hash)
                VALUES (?, 'termos_privacidade', ?, ?)
            """,
                (user_id, versao_termos, hash_ip(get_client_ip())),
            )

        if tipo == "prestador" and categoria:
            if preco_inicial is not None and preco_inicial != "":
                preco = parse_positive_price(preco_inicial)
                if preco is None:
                    conn.rollback()
                    return jsonify({"error": "Preço inicial inválido."}), 400
            else:
                preco = 100.0
            titulo_svc = f"Serviço profissional de {categoria}"
            desc_svc = bio or f"Atendimento especializado em {categoria} na região de {cidade or 'São Paulo'}."
            cursor.execute(
                """
                INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
                (
                    user_id,
                    titulo_svc,
                    desc_svc,
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
                ),
            )

        verif_token = create_email_verification_token(conn, user_id, email) if require_email_verif else None
        conn.commit()

        if verif_token:
            base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
            v_url = (
                f"{base_url}/api/auth/verify-email?token={verif_token}"
                if base_url
                else f"/api/auth/verify-email?token={verif_token}"
            )
            send_transactional_email(
                email,
                "Confirme seu e-mail - PertoJá",
                f'<p>Confirme seu e-mail no <strong>PertoJá</strong>: <a href="{v_url}">Confirmar</a> ou código <code>{verif_token}</code></p>',
                f"Confirme seu e-mail no PertoJá: {v_url} (código: {verif_token})",
            )

        session.permanent = True
        session["user_id"] = user_id
        session["user_tipo"] = tipo
        session["user_nome"] = nome
        session["session_version"] = 1

        reg_payload: dict = {
            "message": "Cadastro realizado com sucesso!",
            "user": {
                "id": user_id,
                "nome": nome,
                "email": email,
                "tipo": tipo,
                "plano": plano,
                "telefone": telefone,
                "cep": cep,
                "endereco": endereco,
                "numero": numero,
                "bairro": bairro,
                "cidade": cidade,
                "estado": estado,
                "lat": lat,
                "lng": lng,
                "kyc_tier": kyc_tier,
                "kyc_status": "aprovado",
                "kyc_documento_tipo": kyc_documento_tipo,
                "registro_profissional": registro_profissional,
                "cpf": cpf_limpo,
                "status_conta": "ativo",
                "email_verified": bool(email_verified_val),
                "phone_verified": False,
            },
        }
        if verif_token and not is_production_runtime():
            reg_payload["verification_token"] = verif_token

        resp = make_response(jsonify(reg_payload), 201)
        set_csrf_cookie(resp)
        return resp
    except (sqlite3.Error, ValueError, RuntimeError, *PG_DB_ERRORS) as exc:
        current_app.logger.error(
            "Erro ao cadastrar usuário.",
            extra={"event": "auth_register_error", "error_type": type(exc).__name__},
        )
        return jsonify({"error": "Erro interno ao cadastrar usuário."}), 500
    finally:
        conn.close()


@auth_bp.route("/api/auth/login", methods=["POST"])
@rate_limit(10, 60)
def login():
    """Autentica usuário e inicializa sessão com cookie CSRF."""
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    senha = data.get("senha", "")

    if not email or not senha:
        return jsonify({"error": "E-mail e senha são obrigatórios."}), 400

    rl_resp = check_email_rate_limit("login", email, 10, 60)
    if rl_resp is not None:
        return rl_resp

    conn = compat_get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["senha_hash"], senha):
        return jsonify({"error": "Credenciais inválidas. Verifique seu e-mail e senha."}), 401

    if row_get(user, "status_conta", "ativo") in ("bloqueado", "anonimizado"):
        return jsonify({"error": "Conta bloqueada ou desativada."}), 403

    session.permanent = True
    session["user_id"] = user["id"]
    session["user_tipo"] = user["tipo"]
    session["user_nome"] = user["nome"]
    session["session_version"] = int(row_get(user, "session_version", 1) or 1)

    resp = make_response(
        jsonify(
            {
                "message": "Login realizado com sucesso!",
                "user": {
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
                    "bairro": user["bairro"],
                    "cidade": user["cidade"],
                    "estado": user["estado"],
                    "lat": user["lat"],
                    "lng": user["lng"],
                    "disponivel": bool(user["disponivel"]),
                    "kyc_tier": row_get(user, "kyc_tier", 1),
                    "kyc_status": row_get(user, "kyc_status", "aprovado"),
                    "kyc_documento_tipo": row_get(user, "kyc_documento_tipo", "RG"),
                    "registro_profissional": row_get(user, "registro_profissional"),
                    "status_conta": row_get(user, "status_conta", "ativo"),
                    "email_verified": bool(row_get(user, "email_verified", 1)),
                    "phone_verified": bool(row_get(user, "phone_verified", 0)),
                },
            }
        )
    )
    set_csrf_cookie(resp)
    return resp


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    """Encerra a sessão autenticada e remove o cookie CSRF."""
    session.clear()
    resp = make_response(jsonify({"message": "Sessão encerrada com sucesso."}))
    resp.delete_cookie(CSRF_COOKIE_NAME, path="/", samesite="Lax")
    g._csrf_cookie_set = True
    return resp


@auth_bp.route("/api/auth/csrf", methods=["GET"])
def get_csrf_token():
    """Retorna e garante emissão do cookie CSRF same-origin."""
    existing = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    token = existing or secrets.token_urlsafe(32)
    resp = make_response(jsonify({"csrf_token": token}), 200)
    if not existing:
        set_csrf_cookie(resp, token=token)
    return resp


@auth_bp.route("/api/auth/forgot-password", methods=["POST"])
@rate_limit(10, 60)
def forgot_password():
    """Gera token de redefinição de senha com validade temporária."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    issued_token = None
    if email:
        rl_resp = check_email_rate_limit("forgot_password", email, 10, 60)
        if rl_resp is not None:
            return rl_resp
        conn = compat_get_db_connection()
        try:
            conn.execute("DELETE FROM password_reset_tokens WHERE expires_at < ?", (time.time() - 86400,))
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if user:
                conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0", (user["id"],))
                issued_token = secrets.token_urlsafe(24)
                token_hash = hashlib.sha256(issued_token.encode("utf-8")).hexdigest()
                expires_at = time.time() + 1800
                conn.execute(
                    "INSERT INTO password_reset_tokens (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)",
                    (token_hash, user["id"], expires_at),
                )
            conn.commit()
        finally:
            conn.close()

        if issued_token:
            base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
            reset_url = (
                f"{base_url}/reset-password?token={issued_token}"
                if base_url
                else f"/reset-password?token={issued_token}"
            )
            send_transactional_email(
                email,
                "Redefinição de senha - PertoJá",
                f'<p>Redefina sua senha no <strong>PertoJá</strong>: <a href="{reset_url}">Redefinir</a> ou token <code>{issued_token}</code></p>',
                f"Redefina sua senha no PertoJá: {reset_url} (token: {issued_token})",
            )

    payload: dict = {"message": "Se o e-mail estiver cadastrado, as instruções de redefinição foram geradas."}
    if issued_token and not is_production_runtime():
        payload["reset_token"] = issued_token
    return jsonify(payload), 200


@auth_bp.route("/api/auth/reset-password", methods=["POST"])
@rate_limit(10, 60)
def reset_password():
    """Redefine senha mediante token válido e incrementa session_version."""
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "").strip()
    nova_senha = str(data.get("nova_senha") or "")

    if not token:
        return jsonify({"error": "Token de redefinição obrigatório."}), 400
    pwd_err, pwd_code = validate_password_policy(nova_senha, "A nova senha")
    if pwd_err:
        return jsonify({"error": pwd_err, "code": pwd_code}), 400

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = compat_get_db_connection()
    try:
        row = conn.execute(
            "SELECT token, user_id, expires_at, used FROM password_reset_tokens WHERE token = ? OR token = ?",
            (token_hash, token),
        ).fetchone()
        if not row or int(row_get(row, "used", 0)) != 0 or float(row["expires_at"]) <= time.time():
            return jsonify({"error": "Token inválido ou expirado."}), 400

        senha_hash = generate_password_hash(nova_senha)
        conn.execute(
            "UPDATE users SET senha_hash = ?, session_version = COALESCE(session_version, 1) + 1 WHERE id = ?",
            (senha_hash, row["user_id"]),
        )
        conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0", (row["user_id"],))
        conn.commit()
    finally:
        conn.close()

    return jsonify({"message": "Senha redefinida com sucesso."}), 200


@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    """Retorna os dados do usuário autenticado na sessão atual."""
    user = get_current_user()
    if not user:
        return jsonify({"authenticated": False}), 200

    return jsonify(
        {
            "authenticated": True,
            "user": {
                "id": user["id"],
                "nome": user["nome"],
                "email": user["email"],
                "tipo": user["tipo"],
                "plano": row_get(user, "plano", "basico"),
                "telefone": user["telefone"],
                "bio": user["bio"],
                "foto_url": user["foto_url"],
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
                "total_avaliacoes": user["total_avaliacoes"],
                "kyc_tier": row_get(user, "kyc_tier", 1),
                "kyc_status": row_get(user, "kyc_status", "aprovado"),
                "kyc_documento_tipo": row_get(user, "kyc_documento_tipo", "RG"),
                "registro_profissional": row_get(user, "registro_profissional"),
                "status_conta": row_get(user, "status_conta", "ativo"),
                "email_verified": bool(row_get(user, "email_verified", 1)),
                "phone_verified": bool(row_get(user, "phone_verified", 0)),
            },
        }
    )


@auth_bp.route("/api/account/appeal", methods=["POST"])
def create_account_appeal():
    """Registra recurso de revisão humana para conta suspensa ou restrita."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Autenticação obrigatória."}), 401

    data = request.get_json(silent=True) or {}
    motivo = str(data.get("motivo") or "").strip()
    evidencias = str(data.get("evidencias") or "").strip()
    if not motivo:
        return jsonify({"error": "Informe a justificativa do recurso."}), 400

    conn = compat_get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO account_appeals (user_id, motivo, evidencias, status)
            VALUES (?, ?, ?, 'em_analise')
        """,
            (user["id"], motivo, evidencias),
        )
        appeal_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        {"message": "Recurso registrado para revisão humana.", "appeal_id": appeal_id, "status": "em_analise"}
    ), 201


register_profile_routes(auth_bp)
register_auth_verification_routes(auth_bp)
