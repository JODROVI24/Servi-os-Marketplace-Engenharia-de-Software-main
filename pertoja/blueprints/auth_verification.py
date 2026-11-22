"""Rotas de verificação de e-mail e OTP por telefone registradas no blueprint auth."""

import hashlib
import hmac
import os
import re
import secrets
import time

from flask import jsonify, request

from pertoja.config import is_production_runtime
from pertoja.extensions import (
    check_email_rate_limit,
    compat_get_db_connection,
    get_current_user,
    rate_limit,
    require_active_account,
    row_get,
)
from pertoja.services.notifications import send_phone_otp, send_transactional_email

_EMAIL_VERIF_TTL_SECONDS = 86400
_OTP_TTL_SECONDS = 600
_OTP_MAX_ATTEMPTS = 5


def _build_verification_email_body(token: str) -> tuple[str, str]:
    """Monta assunto e corpo HTML/texto para verificação de e-mail."""
    base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    verify_url = (
        f"{base_url}/api/auth/verify-email?token={token}" if base_url else f"/api/auth/verify-email?token={token}"
    )
    html = (
        "<p>Confirme seu e-mail no <strong>PertoJá</strong>.</p>"
        f'<p><a href="{verify_url}">Clique aqui para confirmar</a> ou informe o código: <code>{token}</code></p>'
    )
    text = f"Confirme seu e-mail no PertoJá acessando {verify_url} ou informando o código: {token}"
    return html, text


def create_email_verification_token(conn, user_id: int, email: str) -> str:
    """Invalida tokens pendentes e grava novo token de verificação de e-mail."""
    token = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = time.time() + _EMAIL_VERIF_TTL_SECONDS
    conn.execute("UPDATE email_verification_tokens SET used = 1 WHERE user_id = ? AND used = 0", (user_id,))
    conn.execute(
        "INSERT INTO email_verification_tokens (token, user_id, email, expires_at, used) VALUES (?, ?, ?, ?, 0)",
        (token_hash, user_id, email, expires_at),
    )
    return token


def register_auth_verification_routes(auth_bp) -> None:
    """Anexa rotas de verificação de e-mail e OTP de telefone ao auth_bp."""

    @auth_bp.route("/api/auth/send-verification-email", methods=["POST"])
    @rate_limit(10, 60)
    def send_verification_email():
        user = get_current_user()
        data = request.get_json(silent=True) or {}
        raw_email = str(data.get("email") or "").strip().lower()

        if raw_email:
            rl_resp = check_email_rate_limit("send_verification_email", raw_email, 10, 60)
            if rl_resp is not None:
                return rl_resp

        if user:
            acct_err = require_active_account(user)
            if acct_err:
                return acct_err
            target_id = user["id"]
            target_email = user["email"]
            conn = compat_get_db_connection()
            try:
                token = create_email_verification_token(conn, target_id, target_email)
                conn.commit()
            finally:
                conn.close()

            html_body, text_body = _build_verification_email_body(token)
            send_transactional_email(target_email, "Confirme seu e-mail - PertoJá", html_body, text_body)
            payload: dict = {"message": "E-mail de verificação enviado com sucesso."}
            if not is_production_runtime():
                payload["verification_token"] = token
            return jsonify(payload), 200

        if raw_email:
            conn = compat_get_db_connection()
            token = None
            try:
                row = conn.execute(
                    "SELECT id, email, email_verified FROM users WHERE email = ?",
                    (raw_email,),
                ).fetchone()
                if row and int(row_get(row, "email_verified", 1) or 0) == 0:
                    token = create_email_verification_token(conn, row["id"], row["email"])
                    conn.commit()
            finally:
                conn.close()

            if token:
                html_body, text_body = _build_verification_email_body(token)
                send_transactional_email(raw_email, "Confirme seu e-mail - PertoJá", html_body, text_body)

        return jsonify({"message": "Se o e-mail estiver cadastrado e pendente, enviaremos a verificação."}), 200

    @auth_bp.route("/api/auth/verify-email", methods=["POST", "GET"])
    def verify_email():
        data = request.get_json(silent=True) or {}
        token = str(data.get("token") or request.args.get("token") or "").strip()
        if not token:
            return jsonify({"error": "Token de verificação obrigatório."}), 400

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn = compat_get_db_connection()
        try:
            row = conn.execute(
                "SELECT token, user_id, expires_at, used FROM email_verification_tokens WHERE token = ? OR token = ?",
                (token_hash, token),
            ).fetchone()
            if not row or int(row_get(row, "used", 0)) != 0 or float(row["expires_at"]) <= time.time():
                return jsonify({"error": "Token de verificação inválido ou expirado."}), 400

            conn.execute(
                "UPDATE email_verification_tokens SET used = 1 WHERE user_id = ? AND used = 0",
                (row["user_id"],),
            )
            conn.execute(
                "UPDATE users SET email_verified = 1, email_verified_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["user_id"],),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"message": "E-mail verificado com sucesso!", "email_verified": True}), 200

    @auth_bp.route("/api/auth/phone/send-otp", methods=["POST"])
    @rate_limit(10, 60)
    def send_phone_otp_route():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Acesso não autorizado. Faça login."}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        raw_telefone = data.get("telefone")
        telefone_str = str(raw_telefone if raw_telefone is not None else (user["telefone"] or "")).strip()
        digits = re.sub(r"\D", "", telefone_str)
        if len(digits) < 10 or len(digits) > 13:
            return jsonify({"error": "Telefone inválido. Informe entre 10 e 13 dígitos com DDD."}), 400

        canal = str(data.get("canal") or "sms").strip().lower()
        if canal not in ("sms", "whatsapp"):
            return jsonify({"error": "Canal inválido. Escolha sms ou whatsapp."}), 400

        code = f"{secrets.randbelow(900000) + 100000}"
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        expires_at = time.time() + _OTP_TTL_SECONDS

        conn = compat_get_db_connection()
        try:
            conn.execute("UPDATE phone_otp_tokens SET used = 1 WHERE user_id = ? AND used = 0", (user["id"],))
            conn.execute(
                """
                INSERT INTO phone_otp_tokens (user_id, telefone, code_hash, canal, expires_at, attempts, used)
                VALUES (?, ?, ?, ?, ?, 0, 0)
            """,
                (user["id"], digits, code_hash, canal, expires_at),
            )
            if raw_telefone is not None or not user["telefone"]:
                conn.execute(
                    "UPDATE users SET telefone = ?, phone_verified = 0, phone_verified_at = NULL WHERE id = ?",
                    (telefone_str, user["id"]),
                )
            else:
                conn.execute(
                    "UPDATE users SET phone_verified = 0, phone_verified_at = NULL WHERE id = ?",
                    (user["id"],),
                )
            conn.commit()
        finally:
            conn.close()

        send_phone_otp(digits, code, canal=canal)
        payload: dict = {
            "message": f"Código OTP enviado via {canal.upper()}.",
            "canal": canal,
            "expires_in": _OTP_TTL_SECONDS,
        }
        if not is_production_runtime():
            payload["dev_otp"] = code
        return jsonify(payload), 200

    @auth_bp.route("/api/auth/phone/verify-otp", methods=["POST"])
    @rate_limit(15, 60)
    def verify_phone_otp_route():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Acesso não autorizado. Faça login."}), 401
        acct_err = require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or data.get("otp") or "").strip()
        if not code:
            return jsonify({"error": "Código OTP obrigatório."}), 400

        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        conn = compat_get_db_connection()
        try:
            row = conn.execute(
                """
                SELECT id, code_hash, expires_at, attempts, used
                FROM phone_otp_tokens
                WHERE user_id = ? AND used = 0
                ORDER BY id DESC
                LIMIT 1
            """,
                (user["id"],),
            ).fetchone()
            if not row or float(row["expires_at"]) <= time.time():
                return jsonify({"error": "Código OTP inválido ou expirado."}), 400

            attempts = int(row_get(row, "attempts", 0) or 0)
            if attempts >= _OTP_MAX_ATTEMPTS:
                conn.execute("UPDATE phone_otp_tokens SET used = 1 WHERE id = ?", (row["id"],))
                conn.commit()
                return jsonify(
                    {
                        "error": "Limite de tentativas excedido. Solicite um novo código.",
                        "code": "OTP_MAX_ATTEMPTS",
                    }
                ), 429

            if not hmac.compare_digest(code_hash, row["code_hash"]):
                new_attempts = attempts + 1
                conn.execute(
                    "UPDATE phone_otp_tokens SET attempts = ? WHERE id = ?",
                    (new_attempts, row["id"]),
                )
                conn.commit()
                return jsonify({"error": "Código OTP inválido.", "code": "OTP_INVALID"}), 400

            conn.execute("UPDATE phone_otp_tokens SET used = 1 WHERE id = ?", (row["id"],))
            conn.execute(
                "UPDATE users SET phone_verified = 1, phone_verified_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user["id"],),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"message": "Telefone verificado com sucesso!", "phone_verified": True}), 200
