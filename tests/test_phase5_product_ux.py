"""Suíte de verificação ponta a ponta e contrato da Fase 5 (Produto, Verificação e UX)."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import database  # noqa: E402
from app import app  # noqa: E402
from pertoja.db import connection as db_conn  # noqa: E402
from pertoja.services import geo as geo_service  # noqa: E402
from pertoja.services import notifications as notif_service  # noqa: E402
from tests._csrf_test_client import BrowserCSRFTestClient  # noqa: E402

PUBLIC_DIR = REPO_ROOT / "public"
PASSWORD_VALID = "SenhaForte@2026!"


def _make_client() -> BrowserCSRFTestClient:
    return BrowserCSRFTestClient(app, app.response_class, use_cookies=True)


class TestPhase5ProductUX(unittest.TestCase):
    """Testes estáticos, de contrato e ponta a ponta para os itens 5.1 a 5.5."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._orig_db_path = database.DB_PATH
        cls._orig_conn_db_path = getattr(db_conn, "DB_PATH", database.DB_PATH)
        cls._orig_env_db = os.environ.get("MARKETPLACE_DB")

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        cls._temp_db = tmp.name

        os.environ["MARKETPLACE_DB"] = cls._temp_db
        database.DB_PATH = cls._temp_db
        db_conn.DB_PATH = cls._temp_db

        saved = {k: os.environ.get(k) for k in ("ENABLE_DEMO_SEED", "VERCEL", "FLASK_ENV")}
        try:
            os.environ["ENABLE_DEMO_SEED"] = "0"
            os.environ.pop("VERCEL", None)
            os.environ.pop("FLASK_ENV", None)
            database.init_db()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @classmethod
    def tearDownClass(cls) -> None:
        database.DB_PATH = cls._orig_db_path
        db_conn.DB_PATH = cls._orig_conn_db_path
        if cls._orig_env_db is None:
            os.environ.pop("MARKETPLACE_DB", None)
        else:
            os.environ["MARKETPLACE_DB"] = cls._orig_env_db
        try:
            if os.path.exists(cls._temp_db):
                os.remove(cls._temp_db)
        except OSError:
            pass

    def setUp(self) -> None:
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-phase5-secret"
        self._saved_env = {
            k: os.environ.get(k)
            for k in (
                "VERCEL",
                "VERCEL_ENV",
                "AWS_LAMBDA_FUNCTION_NAME",
                "FLASK_ENV",
                "REQUIRE_EMAIL_VERIFICATION",
                "RESEND_API_KEY",
                "SENDGRID_API_KEY",
                "MAIL_FROM",
                "WHATSAPP_API_URL",
                "WHATSAPP_API_TOKEN",
                "SMS_WEBHOOK_URL",
                "SMS_WEBHOOK_TOKEN",
            )
        }
        for k in self._saved_env:
            os.environ.pop(k, None)
        geo_service.reset_nominatim_throttle()
        conn = database.get_db_connection()
        try:
            conn.execute("DELETE FROM rate_limit")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _register_user(
        self,
        email: str,
        tipo: str = "cliente",
        *,
        require_email_verification: bool = False,
        categoria: str | None = None,
        telefone: str = "(11) 99999-1234",
    ) -> tuple[BrowserCSRFTestClient, dict]:
        client = _make_client()
        payload: dict = {
            "nome": f"Teste {tipo.title()}",
            "email": email,
            "senha": PASSWORD_VALID,
            "tipo": tipo,
            "telefone": telefone,
            "cep": "01310-100",
            "endereco": "Av. Paulista",
            "numero": "1000",
            "bairro": "Bela Vista",
            "cidade": "São Paulo",
            "estado": "SP",
            "lat": -23.5614,
            "lng": -46.6559,
            "aceite_termos": True,
        }
        if require_email_verification:
            payload["require_email_verification"] = True
        if tipo == "prestador" and categoria:
            payload["categoria"] = categoria
            payload["preco_inicial"] = 150.0
        res = client.post("/api/auth/register", json=payload)
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        return client, res.get_json()

    def _create_provider_and_service(self, email: str) -> tuple[BrowserCSRFTestClient, int, int]:
        prov_client, prov_reg = self._register_user(email, tipo="prestador", categoria="Limpeza")
        prov_id = prov_reg["user"]["id"]
        res_svcs = prov_client.get("/api/my-services")
        self.assertEqual(res_svcs.status_code, 200)
        services = res_svcs.get_json()
        self.assertGreaterEqual(len(services), 1)
        return prov_client, prov_id, services[0]["id"]

    # ------------------------------------------------------------------
    # Auditoria estática e contratos
    # ------------------------------------------------------------------

    def test_00_static_audit_and_frontend_contracts(self) -> None:
        prod_files = [
            REPO_ROOT / "app.py",
            REPO_ROOT / "database.py",
            REPO_ROOT / "payment_adapters.py",
            REPO_ROOT / "llm_client.py",
            REPO_ROOT / "api" / "index.py",
            *sorted((REPO_ROOT / "pertoja").rglob("*.py")),
        ]
        for py_path in prod_files:
            text = py_path.read_text(encoding="utf-8")
            lines = text.splitlines()
            self.assertLessEqual(len(lines), 600, f"{py_path} excede 600 linhas ({len(lines)})")
            for idx, line in enumerate(lines, 1):
                self.assertIsNone(
                    re.search(r"\bprint\s*\(|except\s+Exception\b|except\s*:", line),
                    f"Violação em {py_path}:{idx}: {line.strip()}",
                )

        for asset in [*PUBLIC_DIR.rglob("*.js"), *PUBLIC_DIR.glob("*.html")]:
            content = asset.read_text(encoding="utf-8")
            self.assertNotIn(
                "nominatim.openstreetmap.org",
                content,
                f"Chamada direta ao Nominatim encontrada em {asset}",
            )

        pedido_html = (PUBLIC_DIR / "pedido.html").read_text(encoding="utf-8")
        orders_js = (PUBLIC_DIR / "js" / "modules" / "orders.js").read_text(encoding="utf-8")
        prest_html = (PUBLIC_DIR / "portal-prestador.html").read_text(encoding="utf-8")
        prest_js = (PUBLIC_DIR / "js" / "portal-prestador.js").read_text(encoding="utf-8")

        self.assertIn('id="trackingModeBadge"', pedido_html)
        self.assertIn("Posição estimada", pedido_html)
        self.assertIn("Posição estimada", orders_js)
        self.assertIn("Posição GPS em tempo real", orders_js)
        self.assertIn("12000", orders_js)
        self.assertIn("12000", prest_js)
        self.assertIn("gpsTrackingPrestadorBar", prest_html)
        self.assertIn("/location", prest_js)

    # ------------------------------------------------------------------
    # Item 5.1: Rastreamento Honesto + GPS Real
    # ------------------------------------------------------------------

    def test_01_honest_tracking_and_real_gps(self) -> None:
        prov_client, _, service_id = self._create_provider_and_service("prov51@pertoja.com")
        other_prov_client, _, _ = self._create_provider_and_service("prov51_other@pertoja.com")
        cli_client, _ = self._register_user("cli51@pertoja.com", tipo="cliente")

        res_order = cli_client.post(
            "/api/orders",
            json={"servico_id": service_id, "aceite_termos": True},
        )
        self.assertEqual(res_order.status_code, 201)
        order_data = res_order.get_json()
        order_id = order_data["order_id"]
        pin = order_data["codigo_confirmacao"]

        # Antes do GPS real: tracking_mode == estimated
        res_loc_init = cli_client.get(f"/api/orders/{order_id}/location")
        self.assertEqual(res_loc_init.status_code, 200)
        loc_init = res_loc_init.get_json()
        self.assertEqual(loc_init["tracking_mode"], "estimated")
        self.assertIs(loc_init["is_estimated"], True)
        self.assertEqual(loc_init["label"], "Posição estimada")
        self.assertEqual(loc_init["recommended_poll_seconds"], 12)

        res_list_init = cli_client.get("/api/orders")
        self.assertEqual(res_list_init.status_code, 200)
        order_row = next(o for o in res_list_init.get_json() if o["order_id"] == order_id)
        self.assertIs(order_row["posicao_estimada"], True)
        self.assertEqual(order_row["tracking_mode"], "estimated")

        # Pedido ainda solicitado -> POST /location retorna 400 para o prestador dono
        res_early = prov_client.post(f"/api/orders/{order_id}/location", json={"lat": -23.56, "lng": -46.65})
        self.assertEqual(res_early.status_code, 400)

        # Avança para confirmado e em_transito
        self.assertEqual(
            prov_client.patch(f"/api/orders/{order_id}/status", json={"status": "confirmado"}).status_code,
            200,
        )
        self.assertEqual(
            prov_client.patch(f"/api/orders/{order_id}/status", json={"status": "em_transito"}).status_code,
            200,
        )

        # Gera link de rota compartilhada
        res_share = cli_client.post(f"/api/orders/{order_id}/share-route", json={})
        self.assertEqual(res_share.status_code, 200)
        share_token = res_share.get_json()["share_token"]

        # Autorização e validação de coordenadas
        self.assertEqual(
            cli_client.post(f"/api/orders/{order_id}/location", json={"lat": -23.56, "lng": -46.65}).status_code,
            403,
        )
        self.assertEqual(
            other_prov_client.post(f"/api/orders/{order_id}/location", json={"lat": -23.56, "lng": -46.65}).status_code,
            403,
        )
        self.assertEqual(
            prov_client.post(f"/api/orders/{order_id}/location", json={"lat": 200, "lng": -46.65}).status_code,
            400,
        )

        # Prestador dono envia GPS real durante em_transito
        res_gps = prov_client.post(
            f"/api/orders/{order_id}/location",
            json={"lat": -23.5678, "lng": -46.6543, "accuracy": 15.5},
        )
        self.assertEqual(res_gps.status_code, 200)
        gps_payload = res_gps.get_json()
        self.assertEqual(gps_payload["tracking_mode"], "real_gps")
        self.assertIs(gps_payload["is_estimated"], False)
        self.assertEqual(gps_payload["label"], "Posição GPS em tempo real")

        # GET /location, GET /orders e GET /shared-route/<token> refletem GPS real
        loc_real = cli_client.get(f"/api/orders/{order_id}/location").get_json()
        self.assertEqual(loc_real["tracking_mode"], "real_gps")
        self.assertIs(loc_real["is_estimated"], False)
        self.assertEqual(loc_real["label"], "Posição GPS em tempo real")
        self.assertAlmostEqual(loc_real["lat"], -23.5678, places=4)
        self.assertAlmostEqual(loc_real["lng"], -46.6543, places=4)

        orders_real = cli_client.get("/api/orders").get_json()
        row_real = next(o for o in orders_real if o["order_id"] == order_id)
        self.assertEqual(row_real["tracking_mode"], "real_gps")
        self.assertIs(row_real["posicao_estimada"], False)
        self.assertAlmostEqual(row_real["prestador_lat_atual"], -23.5678, places=4)
        self.assertAlmostEqual(row_real["prestador_lng_atual"], -46.6543, places=4)

        shared_real = _make_client().get(f"/api/shared-route/{share_token}").get_json()
        self.assertEqual(shared_real["tracking_mode"], "real_gps")
        self.assertIs(shared_real["posicao_estimada"], False)
        self.assertAlmostEqual(shared_real["prestador_lat_atual"], -23.5678, places=4)
        self.assertAlmostEqual(shared_real["prestador_lng_atual"], -46.6543, places=4)

        # Finaliza pedido e garante que POST /location dá 400 em finalizado
        self.assertEqual(
            prov_client.patch(
                f"/api/orders/{order_id}/status",
                json={"status": "em_execucao", "codigo_confirmacao": pin},
            ).status_code,
            200,
        )
        self.assertEqual(
            prov_client.patch(f"/api/orders/{order_id}/status", json={"status": "finalizado"}).status_code,
            200,
        )
        self.assertEqual(
            prov_client.post(f"/api/orders/{order_id}/location", json={"lat": -23.56, "lng": -46.65}).status_code,
            400,
        )

    # ------------------------------------------------------------------
    # Item 5.2: Verificação de E-mail + Bloqueio de Pedido
    # ------------------------------------------------------------------

    def test_02_email_verification_and_order_gate(self) -> None:
        _, _, service_id = self._create_provider_and_service("prov52@pertoja.com")

        with patch("pertoja.blueprints.auth.send_transactional_email") as mock_send:
            mock_send.return_value = {"sent": True, "provider": "local_outbox"}
            cli_client, reg_data = self._register_user(
                "cli52@pertoja.com",
                tipo="cliente",
                require_email_verification=True,
            )

        self.assertIs(reg_data["user"]["email_verified"], False)
        verif_token = reg_data.get("verification_token")
        self.assertTrue(verif_token)
        mock_send.assert_called_once()

        # Bloqueado ao criar pedido enquanto email_verified == 0
        res_blocked = cli_client.post("/api/orders", json={"servico_id": service_id, "aceite_termos": True})
        self.assertEqual(res_blocked.status_code, 403)
        self.assertEqual(res_blocked.get_json()["code"], "EMAIL_NOT_VERIFIED")

        # Token inválido e token expirado falham com 400
        self.assertEqual(cli_client.post("/api/auth/verify-email", json={"token": "invalido"}).status_code, 400)
        conn = database.get_db_connection()
        try:
            conn.execute(
                "INSERT INTO email_verification_tokens (token, user_id, email, expires_at, used) VALUES (?, ?, ?, ?, 0)",
                ("expired_tok_hash", reg_data["user"]["id"], "cli52@pertoja.com", time.time() - 60),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(cli_client.post("/api/auth/verify-email", json={"token": "expired_tok_hash"}).status_code, 400)

        # POST /api/auth/verify-email com token válido ativa email_verified=True (uso único)
        res_verify = cli_client.post("/api/auth/verify-email", json={"token": verif_token})
        self.assertEqual(res_verify.status_code, 200)
        self.assertIs(res_verify.get_json()["email_verified"], True)

        # Reuso falha com 400 (via POST e GET)
        self.assertEqual(cli_client.post("/api/auth/verify-email", json={"token": verif_token}).status_code, 400)
        self.assertEqual(cli_client.get(f"/api/auth/verify-email?token={verif_token}").status_code, 400)

        # Agora POST /api/orders funciona normalmente (201)
        res_ok = cli_client.post("/api/orders", json={"servico_id": service_id, "aceite_termos": True})
        self.assertEqual(res_ok.status_code, 201)

        # Também testa GET /api/auth/verify-email?token=... em novo reenvio
        res_resend = cli_client.post("/api/auth/send-verification-email", json={})
        self.assertEqual(res_resend.status_code, 200)
        new_tok = res_resend.get_json()["verification_token"]
        res_get_verify = cli_client.get(f"/api/auth/verify-email?token={new_tok}")
        self.assertEqual(res_get_verify.status_code, 200)
        self.assertIs(res_get_verify.get_json()["email_verified"], True)

    def test_02b_transactional_email_providers_resend_sendgrid_and_fallback(self) -> None:
        # Fallback local_outbox sem variáveis
        out_local = notif_service.send_transactional_email("a@b.com", "Assunto", "<p>Oi</p>", "Oi")
        self.assertEqual(out_local, {"sent": True, "provider": "local_outbox"})

        # Resend
        os.environ["RESEND_API_KEY"] = "re_test_123"
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        with patch("pertoja.services.notifications.requests.post", return_value=mock_resp) as mock_post:
            out_resend = notif_service.send_transactional_email("a@b.com", "Teste Resend", "<p>Hi</p>", "Hi")
        self.assertTrue(out_resend["sent"])
        self.assertEqual(out_resend["provider"], "resend")
        self.assertEqual(mock_post.call_args.args[0], "https://api.resend.com/emails")
        self.assertEqual(mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer re_test_123")

        # SendGrid
        os.environ.pop("RESEND_API_KEY", None)
        os.environ["SENDGRID_API_KEY"] = "sg_test_456"
        os.environ["MAIL_FROM"] = "PertoJá <suporte@pertoja.com.br>"
        mock_sg = MagicMock(status_code=202)
        mock_sg.raise_for_status.return_value = None
        with patch("pertoja.services.notifications.requests.post", return_value=mock_sg) as mock_post_sg:
            out_sg = notif_service.send_transactional_email("a@b.com", "Teste SG", "<p>Hi</p>", "Hi")
        self.assertTrue(out_sg["sent"])
        self.assertEqual(out_sg["provider"], "sendgrid")
        self.assertEqual(mock_post_sg.call_args.args[0], "https://api.sendgrid.com/v3/mail/send")
        self.assertEqual(mock_post_sg.call_args.kwargs["headers"]["Authorization"], "Bearer sg_test_456")

    # ------------------------------------------------------------------
    # Item 5.3: Recuperação de Senha (Token único 30 min)
    # ------------------------------------------------------------------

    def test_03_forgot_and_reset_password_single_use_30m(self) -> None:
        cli_client, reg_data = self._register_user("cli53@pertoja.com", tipo="cliente")
        user_id = reg_data["user"]["id"]

        with patch("pertoja.blueprints.auth.send_transactional_email") as mock_email:
            mock_email.return_value = {"sent": True, "provider": "local_outbox"}
            r1 = cli_client.post("/api/auth/forgot-password", json={"email": "cli53@pertoja.com"})
            self.assertEqual(r1.status_code, 200)
            tok1 = r1.get_json()["reset_token"]

            now_before = time.time()
            r2 = cli_client.post("/api/auth/forgot-password", json={"email": "cli53@pertoja.com"})
            self.assertEqual(r2.status_code, 200)
            tok2 = r2.get_json()["reset_token"]

        self.assertEqual(mock_email.call_count, 2)
        self.assertNotEqual(tok1, tok2)

        # Token anterior foi invalidado
        self.assertEqual(
            cli_client.post(
                "/api/auth/reset-password", json={"token": tok1, "nova_senha": "NovaSenha@2026!"}
            ).status_code,
            400,
        )

        # Verifica TTL <= 1800s (~30 min)
        conn = database.get_db_connection()
        try:
            row = conn.execute(
                "SELECT expires_at, used FROM password_reset_tokens WHERE user_id = ? AND used = 0",
                (user_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            ttl = float(row["expires_at"]) - now_before
            self.assertGreater(ttl, 1700.0)
            self.assertLessEqual(ttl, 1805.0)

            # Cria token expirado para validar rejeição
            conn.execute(
                "INSERT INTO password_reset_tokens (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)",
                ("tok_exp_53", user_id, time.time() - 30),
            )
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(
            cli_client.post(
                "/api/auth/reset-password",
                json={"token": "tok_exp_53", "nova_senha": "NovaSenha@2026!"},
            ).status_code,
            400,
        )

        # Reset com token válido incrementa session_version e invalida reuso
        res_reset = cli_client.post(
            "/api/auth/reset-password",
            json={"token": tok2, "nova_senha": "NovaSenha@2026!"},
        )
        self.assertEqual(res_reset.status_code, 200)

        conn = database.get_db_connection()
        try:
            sv_row = conn.execute("SELECT session_version FROM users WHERE id = ?", (user_id,)).fetchone()
            self.assertEqual(int(sv_row["session_version"]), 2)
        finally:
            conn.close()

        # Sessão anterior foi invalidada por session_version
        self.assertIs(cli_client.get("/api/auth/me").get_json()["authenticated"], False)

        # Reuso do mesmo token falha com 400
        self.assertEqual(
            cli_client.post(
                "/api/auth/reset-password",
                json={"token": tok2, "nova_senha": "OutraSenha@2026!"},
            ).status_code,
            400,
        )

    # ------------------------------------------------------------------
    # Item 5.4: Telefone OTP SMS / WhatsApp
    # ------------------------------------------------------------------

    def test_04_phone_otp_sms_whatsapp_and_lockout(self) -> None:
        anon = _make_client()
        self.assertEqual(anon.post("/api/auth/phone/send-otp", json={"canal": "sms"}).status_code, 401)
        self.assertEqual(anon.post("/api/auth/phone/verify-otp", json={"code": "123456"}).status_code, 401)

        prov_client, _ = self._register_user("prov54@pertoja.com", tipo="prestador", categoria="Limpeza")

        # Valida telefone inválido e canal inválido
        self.assertEqual(
            prov_client.post("/api/auth/phone/send-otp", json={"telefone": "123", "canal": "sms"}).status_code,
            400,
        )
        self.assertEqual(
            prov_client.post(
                "/api/auth/phone/send-otp",
                json={"telefone": "11999998888", "canal": "telegram"},
            ).status_code,
            400,
        )

        # Envio via WhatsApp com mock HTTP
        os.environ["WHATSAPP_API_URL"] = "https://wa.mock.local/send"
        mock_wa = MagicMock(status_code=200)
        mock_wa.raise_for_status.return_value = None
        with patch("pertoja.services.notifications.requests.post", return_value=mock_wa) as post_wa:
            res_wa = prov_client.post(
                "/api/auth/phone/send-otp",
                json={"telefone": "(11) 99999-8888", "canal": "whatsapp"},
            )
        self.assertEqual(res_wa.status_code, 200)
        self.assertEqual(res_wa.get_json()["canal"], "whatsapp")
        self.assertEqual(post_wa.call_args.args[0], "https://wa.mock.local/send")

        # Envio via SMS com mock HTTP
        os.environ["SMS_WEBHOOK_URL"] = "https://sms.mock.local/send"
        mock_sms = MagicMock(status_code=200)
        mock_sms.raise_for_status.return_value = None
        with patch("pertoja.services.notifications.requests.post", return_value=mock_sms) as post_sms:
            res_sms = prov_client.post(
                "/api/auth/phone/send-otp",
                json={"telefone": "(11) 98888-7777", "canal": "sms"},
            )
        self.assertEqual(res_sms.status_code, 200)
        self.assertEqual(res_sms.get_json()["canal"], "sms")
        self.assertEqual(post_sms.call_args.args[0], "https://sms.mock.local/send")
        valid_otp = res_sms.get_json()["dev_otp"]
        self.assertEqual(len(valid_otp), 6)

        # 5 tentativas erradas e bloqueio 429 (OTP_MAX_ATTEMPTS)
        wrong_otp = "000000" if valid_otp != "000000" else "999999"
        for _ in range(5):
            r_bad = prov_client.post("/api/auth/phone/verify-otp", json={"code": wrong_otp})
            self.assertEqual(r_bad.status_code, 400)
        r_locked = prov_client.post("/api/auth/phone/verify-otp", json={"code": valid_otp})
        self.assertEqual(r_locked.status_code, 429)
        self.assertEqual(r_locked.get_json()["code"], "OTP_MAX_ATTEMPTS")

        # Novo OTP válido atualiza phone_verified=True e tem uso único
        res_new = prov_client.post("/api/auth/phone/send-otp", json={"canal": "sms"})
        self.assertEqual(res_new.status_code, 200)
        otp2 = res_new.get_json()["dev_otp"]

        res_ok = prov_client.post("/api/auth/phone/verify-otp", json={"code": otp2})
        self.assertEqual(res_ok.status_code, 200)
        self.assertIs(res_ok.get_json()["phone_verified"], True)
        self.assertIs(prov_client.get("/api/auth/me").get_json()["user"]["phone_verified"], True)

        # Reuso falha com 400
        self.assertEqual(prov_client.post("/api/auth/phone/verify-otp", json={"code": otp2}).status_code, 400)

    # ------------------------------------------------------------------
    # Item 5.5: Proxy Nominatim Backend (User-Agent, Cache e 1 req/s)
    # ------------------------------------------------------------------

    def test_05_nominatim_proxy_user_agent_cache_and_rate_limit(self) -> None:
        self.assertEqual(geo_service.NOMINATIM_MIN_INTERVAL_SECONDS, 1.0)
        self.assertIn("PertoJaMarketplace", geo_service.NOMINATIM_USER_AGENT)

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = [{"lat": "-23.5614", "lon": "-46.6559"}]

        with patch("pertoja.services.geo.requests.get", return_value=mock_resp) as mock_get:
            lat1, lng1 = geo_service.geocode_address("Av. Paulista 1000, São Paulo - SP")
            self.assertAlmostEqual(lat1, -23.5614, places=4)
            self.assertAlmostEqual(lng1, -46.6559, places=4)
            self.assertEqual(mock_get.call_count, 1)
            sent_headers = mock_get.call_args.kwargs["headers"]
            self.assertEqual(sent_headers["User-Agent"], geo_service.NOMINATIM_USER_AGENT)

            # Segunda chamada usa geocode_cache sem nova requisição HTTP
            lat2, lng2 = geo_service.geocode_address("Av. Paulista 1000, São Paulo - SP")
            self.assertAlmostEqual(lat2, -23.5614, places=4)
            self.assertAlmostEqual(lng2, -46.6559, places=4)
            self.assertEqual(mock_get.call_count, 1)

        # Duas buscas distintas consecutivas sem cache devem acionar time.sleep via _throttle_nominatim_request
        geo_service.reset_nominatim_throttle()
        mock_resp_a = MagicMock(status_code=200)
        mock_resp_a.json.return_value = [{"lat": "-23.5501", "lon": "-46.6333"}]
        mock_resp_b = MagicMock(status_code=200)
        mock_resp_b.json.return_value = [{"lat": "-23.5802", "lon": "-46.6801"}]

        with (
            patch("pertoja.services.geo.requests.get", side_effect=[mock_resp_a, mock_resp_b]) as mock_get2,
            patch("pertoja.services.geo.time.monotonic", side_effect=[100.0, 100.0, 100.25, 101.0]),
            patch("pertoja.services.geo.time.sleep") as mock_sleep,
        ):
            r_a = geo_service.geocode_address("Rua Augusta 100, São Paulo - SP")
            r_b = geo_service.geocode_address("Rua Oscar Freire 200, São Paulo - SP")

        self.assertEqual(r_a, (-23.5501, -46.6333))
        self.assertEqual(r_b, (-23.5802, -46.6801))
        self.assertEqual(mock_get2.call_count, 2)
        mock_sleep.assert_called_once()
        self.assertAlmostEqual(mock_sleep.call_args.args[0], 0.75, places=2)


if __name__ == "__main__":
    unittest.main()
