import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import database
import payment_adapters
from app import app

try:
    from tests._csrf_test_client import BrowserCSRFTestClient
except ImportError:
    from _csrf_test_client import BrowserCSRFTestClient


def _make_csrf_client():
    return BrowserCSRFTestClient(app, app.response_class, use_cookies=True)


def _crc16_ccitt(payload: str) -> str:
    """Calcula CRC16-CCITT (polinômio 0x1021, inicial 0xFFFF) padrão EMVCo PIX."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


class TestPaymentsSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_db_path = database.DB_PATH
        cls._orig_env_db = os.environ.get("MARKETPLACE_DB")
        cls.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.temp_file.close()
        os.environ["MARKETPLACE_DB"] = cls.temp_file.name
        database.DB_PATH = cls.temp_file.name
        saved = {k: os.environ.get(k) for k in ("ENABLE_DEMO_SEED", "VERCEL", "FLASK_ENV")}
        try:
            os.environ["ENABLE_DEMO_SEED"] = "1"
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
    def tearDownClass(cls):
        database.DB_PATH = cls._orig_db_path
        if cls._orig_env_db is None:
            os.environ.pop("MARKETPLACE_DB", None)
        else:
            os.environ["MARKETPLACE_DB"] = cls._orig_env_db
        try:
            if hasattr(cls, "temp_file") and os.path.exists(cls.temp_file.name):
                os.remove(cls.temp_file.name)
        except OSError:
            pass

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-payments-secret"
        self._saved_env = {k: os.environ.get(k) for k in ("VERCEL", "FLASK_ENV", "ENABLE_PAYMENT_SANDBOX")}
        os.environ.pop("VERCEL", None)
        os.environ.pop("FLASK_ENV", None)
        os.environ.pop("ENABLE_PAYMENT_SANDBOX", None)
        self.client = _make_csrf_client()

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ---------------- Helpers ----------------

    def _login(self, email, senha="123456", client=None):
        c = client or self.client
        res = c.post("/api/auth/login", json={"email": email, "senha": senha})
        self.assertEqual(res.status_code, 200, f"Login falhou para {email}: {res.data}")
        return json.loads(res.data)["user"]

    def _create_user_and_login(self, nome, email, tipo="cliente"):
        c = _make_csrf_client()
        res = c.post(
            "/api/auth/register",
            json={
                "nome": nome,
                "email": email,
                "senha": "Password123!",
                "tipo": tipo,
            },
        )
        self.assertIn(res.status_code, (200, 201), f"Cadastro falhou: {res.data}")
        return c, json.loads(res.data)["user"]

    def _get_service_id_by_provider_email(self, provider_email):
        conn = database.get_db_connection()
        try:
            row = conn.execute(
                """
                SELECT s.id FROM services s
                JOIN users u ON s.prestador_id = u.id
                WHERE u.email = ? AND s.ativo = 1
                LIMIT 1
            """,
                (provider_email,),
            ).fetchone()
            self.assertIsNotNone(row, f"Nenhum serviço ativo encontrado para {provider_email}")
            return row["id"]
        finally:
            conn.close()

    def _create_order(self, client_session, servico_id=None, metodo_pagamento="pix", valor_total=150.0):
        if servico_id is None:
            servico_id = self._get_service_id_by_provider_email("marta@pertoja.com")
        res = client_session.post(
            "/api/orders",
            json={
                "servico_id": servico_id,
                "metodo_pagamento": metodo_pagamento,
                "endereco": "Rua Teste Pagamentos, 100",
                "observacoes": "Teste automatizado",
            },
        )
        self.assertEqual(res.status_code, 201, f"Erro ao criar pedido: {res.data}")
        order_id = json.loads(res.data)["order_id"]
        if valor_total is not None:
            conn = database.get_db_connection()
            try:
                conn.execute("UPDATE orders SET preco_total = ? WHERE id = ?", (valor_total, order_id))
                conn.commit()
            finally:
                conn.close()
        return order_id

    # ---------------- 1. Config & Environment ----------------

    def test_01_payments_config_no_secrets_and_dynamic_env(self):
        with patch.dict(
            os.environ,
            {
                "MERCADOPAGO_ACCESS_TOKEN": "APP_USR_SECRET_MP_999",
                "MERCADOPAGO_WEBHOOK_SECRET": "mp_wh_secret_999",
                "STRIPE_SECRET_KEY": "sk_test_secret_stripe_999",
                "STRIPE_WEBHOOK_SECRET": "whsec_secret_999",
                "PAGSEGURO_TOKEN": "ps_token_secret_999",
                "PAGSEGURO_WEBHOOK_SECRET": "ps_wh_secret_999",
                "SANDBOX_WEBHOOK_SECRET": "sbx_wh_secret_999",
                "VERCEL": "0",
            },
            clear=False,
        ):
            os.environ.pop("ENABLE_PAYMENT_SANDBOX", None)
            res = self.client.get("/api/payments/config")
            self.assertEqual(res.status_code, 200)
            raw = res.data.decode("utf-8")
            for secret in (
                "APP_USR_SECRET_MP_999",
                "mp_wh_secret_999",
                "sk_test_secret_stripe_999",
                "whsec_secret_999",
                "ps_token_secret_999",
                "ps_wh_secret_999",
                "sbx_wh_secret_999",
            ):
                self.assertNotIn(secret, raw)

            data = json.loads(raw)
            self.assertTrue(data["sandbox_enabled"])
            self.assertEqual(data["default_gateway"], "sandbox")
            by_id = {g["id"]: g for g in data["gateways"]}
            self.assertEqual(set(by_id.keys()), {"sandbox", "mercadopago", "stripe", "pagseguro"})
            for gid in ("sandbox", "mercadopago", "stripe", "pagseguro"):
                self.assertTrue(by_id[gid]["configured"])

        # VERCEL=1 sem ENABLE_PAYMENT_SANDBOX -> sandbox desabilitado (fail-closed)
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False), patch("database.ensure_production_database"):
            os.environ.pop("ENABLE_PAYMENT_SANDBOX", None)
            res_prod = self.client.get("/api/payments/config")
            self.assertEqual(res_prod.status_code, 200)
            data_prod = json.loads(res_prod.data)
            self.assertFalse(data_prod["sandbox_enabled"])
            self.assertNotEqual(data_prod["default_gateway"], "sandbox")

        # VERCEL=1 com ENABLE_PAYMENT_SANDBOX=1 -> sandbox habilitado explicitamente
        with patch.dict(os.environ, {"VERCEL": "1", "ENABLE_PAYMENT_SANDBOX": "1"}, clear=False):
            res_override = self.client.get("/api/payments/config")
            self.assertEqual(res_override.status_code, 200)
            self.assertTrue(json.loads(res_override.data)["sandbox_enabled"])

    # ---------------- 2. Intents, Methods, PCI-Guard, Idempotency & IDOR ----------------

    def test_02_create_intents_pix_cartao_boleto_formats(self):
        self._login("cliente@pertoja.com")

        # PIX com CRC16 EMVCo válido
        order_pix = self._create_order(self.client, metodo_pagamento="pix", valor_total=123.45)
        res_pix = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_pix,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        self.assertEqual(res_pix.status_code, 201)
        pix_data = json.loads(res_pix.data)
        self.assertEqual(pix_data["amount_cents"], 12345)
        self.assertTrue(pix_data["payment_id"].startswith("pay_"))
        emv = pix_data["pix_qr_code"]
        self.assertIn("br.gov.bcb.pix", emv)
        self.assertIn("6304", emv)
        payload_without_crc = emv[:-4]
        expected_crc = _crc16_ccitt(payload_without_crc)
        self.assertEqual(emv[-4:], expected_crc)
        self.assertIn("pix_qr_base64", pix_data)

        # Cartão com checkout_url
        order_card = self._create_order(self.client, metodo_pagamento="cartao", valor_total=200.00)
        res_card = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_card,
                "gateway": "sandbox",
                "method": "cartao",
            },
        )
        self.assertEqual(res_card.status_code, 201)
        card_data = json.loads(res_card.data)
        self.assertEqual(card_data["amount_cents"], 20000)
        self.assertTrue(card_data["checkout_url"])

        # Boleto com linha digitável, código de barras e URL
        order_bol = self._create_order(self.client, metodo_pagamento="boleto", valor_total=89.90)
        res_bol = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_bol,
                "gateway": "sandbox",
                "method": "boleto",
            },
        )
        self.assertEqual(res_bol.status_code, 201)
        bol_data = json.loads(res_bol.data)
        self.assertEqual(bol_data["amount_cents"], 8990)
        self.assertRegex(bol_data["boleto_digitable_line"], r"^\d{47}$")
        self.assertRegex(bol_data["boleto_barcode"], r"^\d{44}$")
        self.assertTrue(bol_data["boleto_url"])

    def test_03_reject_amount_tampering_and_raw_pan_cvv(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="cartao", valor_total=150.00)

        # Adulteração de amount_cents e amount
        res_tamper1 = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
                "amount_cents": 1,
            },
        )
        self.assertEqual(res_tamper1.status_code, 400)

        res_tamper2 = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
                "amount": 0.01,
            },
        )
        self.assertEqual(res_tamper2.status_code, 400)

        # Rejeição PCI-DSS de PAN/CVV (top-level e aninhado em dict/list)
        forbidden_payloads = [
            {"card_number": "4111111111111111"},
            {"pan": "5500000000000004"},
            {"cvv": "123"},
            {"cvc": "999"},
            {"security_code": "456"},
            {"card_pan": "4111111111111111"},
            {"metadata": {"nested": {"card_number": "4111111111111111"}}},
            {"items": [{"security_code": "123"}]},
        ]
        for extra in forbidden_payloads:
            payload = {"order_id": order_id, "gateway": "sandbox", "method": "cartao"}
            payload.update(extra)
            res = self.client.post("/api/payments/intents", json=payload)
            self.assertEqual(res.status_code, 400, f"Deveria rejeitar campo PCI proibido: {extra}")
            self.assertEqual(json.loads(res.data).get("code"), "PCI_VIOLATION")

    def test_04_idempotency_replay_conflict_and_user_scope(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=180.00)
        idem_key = "idem-key-unique-001"

        with patch("app.get_payment_adapter", wraps=payment_adapters.get_payment_adapter) as spy_adapter:
            res1 = self.client.post(
                "/api/payments/intents",
                json={"order_id": order_id, "gateway": "sandbox", "method": "pix"},
                headers={"Idempotency-Key": idem_key},
            )
            self.assertEqual(res1.status_code, 201)
            body1 = json.loads(res1.data)
            self.assertEqual(spy_adapter.call_count, 1)

            # Replay idêntico não deve invocar adaptador novamente
            res2 = self.client.post(
                "/api/payments/intents",
                json={"order_id": order_id, "gateway": "sandbox", "method": "pix"},
                headers={"Idempotency-Key": idem_key},
            )
            self.assertEqual(res2.status_code, 201)
            body2 = json.loads(res2.data)
            self.assertEqual(body1, body2)
            self.assertEqual(spy_adapter.call_count, 1)

        # Mesmo Idempotency-Key com payload diferente -> 409 IDEMPOTENCY_CONFLICT
        res_conflict = self.client.post(
            "/api/payments/intents",
            json={"order_id": order_id, "gateway": "sandbox", "method": "boleto"},
            headers={"Idempotency-Key": idem_key},
        )
        self.assertEqual(res_conflict.status_code, 409)
        self.assertEqual(json.loads(res_conflict.data).get("code"), "IDEMPOTENCY_CONFLICT")

        # Escopo por usuário: outro cliente usando a mesma Idempotency-Key no próprio pedido funciona normalmente
        other_client, _ = self._create_user_and_login("Outro Cliente", "outro_idem@pertoja.com", tipo="cliente")
        other_order = self._create_order(other_client, metodo_pagamento="pix", valor_total=95.00)
        res_other = other_client.post(
            "/api/payments/intents",
            json={"order_id": other_order, "gateway": "sandbox", "method": "pix"},
            headers={"Idempotency-Key": idem_key},
        )
        self.assertEqual(res_other.status_code, 201)
        self.assertNotEqual(json.loads(res_other.data)["payment_id"], body1["payment_id"])

    def test_05_idor_and_provider_redaction(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=140.00)
        res_intent = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        self.assertEqual(res_intent.status_code, 201)
        payment_id = json.loads(res_intent.data)["payment_id"]

        # Outro cliente não envolvido -> 403 em order-scoped, 404 uniforme em payment_ref (anti-oráculo)
        intruder, _ = self._create_user_and_login("Intruso", "intruso_idor@pertoja.com", tipo="cliente")
        self.assertEqual(
            intruder.post(
                "/api/payments/intents", json={"order_id": order_id, "gateway": "sandbox", "method": "pix"}
            ).status_code,
            403,
        )
        self.assertEqual(intruder.get(f"/api/payments/{payment_id}").status_code, 404)
        self.assertEqual(intruder.get(f"/api/payments/order/{order_id}").status_code, 403)
        self.assertEqual(intruder.post(f"/api/payments/{payment_id}/confirm", json={}).status_code, 404)
        self.assertEqual(intruder.post(f"/api/payments/{payment_id}/refund", json={}).status_code, 404)

        # Prestador que NÃO é dono do serviço/pedido -> 404 em payment_ref, 403 em order_id
        carlos_client = _make_csrf_client()
        self._login("carlos@pertoja.com", client=carlos_client)
        self.assertEqual(carlos_client.get(f"/api/payments/{payment_id}").status_code, 404)
        self.assertEqual(carlos_client.get(f"/api/payments/order/{order_id}").status_code, 403)

        # Prestador dono do pedido (marta@pertoja.com) pode visualizar, mas com campos sensíveis redigidos
        marta_client = _make_csrf_client()
        self._login("marta@pertoja.com", client=marta_client)
        res_marta_tx = marta_client.get(f"/api/payments/{payment_id}")
        self.assertEqual(res_marta_tx.status_code, 200)
        marta_tx = json.loads(res_marta_tx.data)
        for redacted_field in ("pix_qr_code", "pix_qr_base64", "checkout_url", "boleto_url", "payment_method_id"):
            self.assertIsNone(marta_tx[redacted_field], f"Campo {redacted_field} deveria ser None para prestador")

        res_marta_ord = marta_client.get(f"/api/payments/order/{order_id}")
        self.assertEqual(res_marta_ord.status_code, 200)
        ord_txs = json.loads(res_marta_ord.data)["transactions"]
        self.assertEqual(len(ord_txs), 1)
        for redacted_field in ("pix_qr_code", "pix_qr_base64", "checkout_url", "boleto_url", "payment_method_id"):
            self.assertIsNone(ord_txs[0][redacted_field])

        # Prestador não pode iniciar, confirmar nem estornar pagamento
        self.assertEqual(marta_client.post("/api/payments/intents", json={"order_id": order_id}).status_code, 403)
        self.assertEqual(marta_client.post(f"/api/payments/{payment_id}/confirm", json={}).status_code, 403)
        self.assertEqual(marta_client.post(f"/api/payments/{payment_id}/refund", json={}).status_code, 403)

        # Referência inexistente -> 404
        self.assertEqual(self.client.get("/api/payments/pay_nao_existe_123").status_code, 404)
        self.assertEqual(self.client.get("/api/payments/order/9999999").status_code, 404)

    # ---------------- 3. Confirm, Production Fail-Closed, Live Gateways ----------------

    def test_06_sandbox_confirm_escrow_sync_and_repeat_409(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=210.00)
        res_intent = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        payment_id = json.loads(res_intent.data)["payment_id"]

        res_conf = self.client.post(f"/api/payments/{payment_id}/confirm", json={"simulate_outcome": "paid"})
        self.assertEqual(res_conf.status_code, 200)
        conf_data = json.loads(res_conf.data)
        self.assertEqual(conf_data["status"], "escrow_held")
        self.assertEqual(conf_data["escrow_status"], "retido")
        self.assertTrue(conf_data["pago"])

        # Verifica orders + escrow_ledger
        conn = database.get_db_connection()
        try:
            order_row = conn.execute("SELECT pago, escrow_status FROM orders WHERE id = ?", (order_id,)).fetchone()
            self.assertEqual(order_row["pago"], 1)
            self.assertEqual(order_row["escrow_status"], "retido")
            ledger_rows = conn.execute(
                "SELECT * FROM escrow_ledger WHERE order_id = ? AND tipo_evento = 'escrow_hold'", (order_id,)
            ).fetchall()
            self.assertEqual(len(ledger_rows), 1)
        finally:
            conn.close()

        # Repetir confirmação -> 409 sem duplicar ledger
        res_repeat = self.client.post(f"/api/payments/{payment_id}/confirm", json={"simulate_outcome": "paid"})
        self.assertEqual(res_repeat.status_code, 409)
        conn = database.get_db_connection()
        try:
            ledger_rows = conn.execute(
                "SELECT * FROM escrow_ledger WHERE order_id = ? AND tipo_evento = 'escrow_hold'", (order_id,)
            ).fetchall()
            self.assertEqual(len(ledger_rows), 1)
        finally:
            conn.close()

    def test_07_production_fail_closed_blocks_sandbox(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=100.00)
        res_intent = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        self.assertEqual(res_intent.status_code, 201)
        payment_id = json.loads(res_intent.data)["payment_id"]

        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False), patch("database.ensure_production_database"):
            os.environ.pop("ENABLE_PAYMENT_SANDBOX", None)
            res_new_intent = self.client.post(
                "/api/payments/intents",
                json={
                    "order_id": order_id,
                    "gateway": "sandbox",
                    "method": "pix",
                },
            )
            self.assertEqual(res_new_intent.status_code, 403)
            self.assertEqual(json.loads(res_new_intent.data).get("code"), "SANDBOX_DISABLED")

            res_conf = self.client.post(f"/api/payments/{payment_id}/confirm", json={"simulate_outcome": "paid"})
            self.assertEqual(res_conf.status_code, 403)
            self.assertEqual(json.loads(res_conf.data).get("code"), "SANDBOX_DISABLED")

    def test_08_live_gateways_ignore_simulate_outcome_and_query_http(self):
        self._login("cliente@pertoja.com")

        gateway_cases = [
            (
                "mercadopago",
                {"MERCADOPAGO_ACCESS_TOKEN": "mp_tok_live_test"},
                {
                    "id": "mp_pay_001",
                    "status": "pending",
                    "point_of_interaction": {"transaction_data": {"qr_code": "000201MP", "qr_code_base64": "QUJD"}},
                },
                {"id": "mp_pay_001", "status": "pending"},
            ),
            (
                "stripe",
                {"STRIPE_SECRET_KEY": "sk_test_live_mock"},
                {
                    "id": "cs_test_001",
                    "url": "https://checkout.stripe.com/c/pay/cs_test_001",
                    "payment_intent": "pi_001",
                    "payment_status": "unpaid",
                },
                {"id": "cs_test_001", "payment_status": "unpaid", "status": "open"},
            ),
            (
                "pagseguro",
                {"PAGSEGURO_TOKEN": "ps_tok_live_mock"},
                {"id": "ORDE_001", "qr_codes": [{"id": "QR_1", "text": "000201PS", "links": []}]},
                {"id": "ORDE_001", "charges": [{"status": "WAITING"}]},
            ),
        ]

        for gw, env_vars, create_resp_json, status_resp_json in gateway_cases:
            order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=155.00)
            with patch.dict(os.environ, env_vars, clear=False):
                mock_create_resp = MagicMock(status_code=201, text=json.dumps(create_resp_json))
                mock_create_resp.json.return_value = create_resp_json

                mock_get_resp = MagicMock(status_code=200, text=json.dumps(status_resp_json))
                mock_get_resp.json.return_value = status_resp_json

                with patch(
                    "payment_adapters.requests.request", side_effect=[mock_create_resp, mock_get_resp]
                ) as mock_req:
                    res_i = self.client.post(
                        "/api/payments/intents",
                        json={
                            "order_id": order_id,
                            "gateway": gw,
                            "method": "cartao" if gw == "stripe" else "pix",
                        },
                    )
                    self.assertEqual(res_i.status_code, 201, f"{gw} intent falhou: {res_i.data}")
                    pay_id = json.loads(res_i.data)["payment_id"]

                    # Cliente tenta forçar simulate_outcome='paid' -> gateway real deve ignorar e consultar API
                    res_c = self.client.post(f"/api/payments/{pay_id}/confirm", json={"simulate_outcome": "paid"})
                    self.assertEqual(res_c.status_code, 200)
                    conf_body = json.loads(res_c.data)
                    self.assertNotEqual(
                        conf_body["status"], "escrow_held", f"{gw} não deveria aceitar simulate_outcome=paid"
                    )
                    self.assertFalse(conf_body["pago"])
                    self.assertEqual(mock_req.call_count, 2)

    # ---------------- 4. Refunds ----------------

    def test_09_partial_and_full_refunds_and_guards(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=100.00)
        res_i = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        pay_id = json.loads(res_i.data)["payment_id"]
        self.assertEqual(self.client.post(f"/api/payments/{pay_id}/confirm", json={}).status_code, 200)

        # Estorno parcial de R$ 40,00 (4000 centavos)
        res_p1 = self.client.post(
            f"/api/payments/{pay_id}/refund",
            json={
                "amount_cents": 4000,
                "reason": "Ajuste parcial",
            },
        )
        self.assertEqual(res_p1.status_code, 200)
        d1 = json.loads(res_p1.data)
        self.assertEqual(d1["status"], "partially_refunded")
        self.assertEqual(d1["escrow_status"], "estornado_parcial")
        self.assertEqual(d1["refunded_cents"], 4000)

        # Over-refund (tentar estornar 7000 quando restam 6000) -> 409
        res_over = self.client.post(f"/api/payments/{pay_id}/refund", json={"amount_cents": 7000})
        self.assertEqual(res_over.status_code, 409)

        # Estorno <= 0 -> 400
        res_zero = self.client.post(f"/api/payments/{pay_id}/refund", json={"amount_cents": 0})
        self.assertEqual(res_zero.status_code, 400)

        # Estorno restante (6000 centavos) -> estornado_total
        res_p2 = self.client.post(f"/api/payments/{pay_id}/refund", json={"reason": "Restante"})
        self.assertEqual(res_p2.status_code, 200)
        d2 = json.loads(res_p2.data)
        self.assertEqual(d2["status"], "refunded")
        self.assertEqual(d2["escrow_status"], "estornado_total")
        self.assertEqual(d2["refunded_cents"], 10000)

        # Double-refund após total -> 409
        res_double = self.client.post(f"/api/payments/{pay_id}/refund", json={"amount_cents": 100})
        self.assertEqual(res_double.status_code, 409)

        conn = database.get_db_connection()
        try:
            ord_row = conn.execute(
                "SELECT escrow_status, valor_estornado FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            self.assertEqual(ord_row["escrow_status"], "estornado_total")
            self.assertAlmostEqual(ord_row["valor_estornado"], 100.0, places=2)
            refunds = conn.execute("SELECT * FROM payment_refunds WHERE order_id = ?", (order_id,)).fetchall()
            self.assertEqual(len(refunds), 2)
            ledger = conn.execute(
                "SELECT * FROM escrow_ledger WHERE order_id = ? AND tipo_evento = 'escrow_refund'", (order_id,)
            ).fetchall()
            self.assertEqual(len(ledger), 2)
        finally:
            conn.close()

    def test_10_refund_rollback_on_gateway_error_and_block_liberado(self):
        self._login("cliente@pertoja.com")

        # Caso A: falha do gateway faz rollback de refunded_cents
        order_a = self._create_order(self.client, metodo_pagamento="pix", valor_total=120.00)
        res_i = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_a,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        pay_a = json.loads(res_i.data)["payment_id"]
        self.assertEqual(self.client.post(f"/api/payments/{pay_a}/confirm", json={}).status_code, 200)

        failing_adapter = MagicMock()
        failing_adapter.refund_payment.side_effect = payment_adapters.PaymentGatewayError(
            "Gateway indisponível", http_status=502
        )
        with patch("app.get_payment_adapter", return_value=failing_adapter):
            res_fail = self.client.post(f"/api/payments/{pay_a}/refund", json={"amount_cents": 5000})
            self.assertEqual(res_fail.status_code, 502)

        conn = database.get_db_connection()
        try:
            tx_row = conn.execute(
                "SELECT refunded_cents, status FROM payment_transactions WHERE public_id = ?", (pay_a,)
            ).fetchone()
            self.assertEqual(tx_row["refunded_cents"], 0)
            self.assertEqual(tx_row["status"], "escrow_held")
            ref_rows = conn.execute("SELECT * FROM payment_refunds WHERE order_id = ?", (order_a,)).fetchall()
            self.assertEqual(len(ref_rows), 0)
        finally:
            conn.close()

        # Caso B: auto-estorno bloqueado quando pedido já está liberado (409)
        conn = database.get_db_connection()
        try:
            conn.execute("UPDATE orders SET escrow_status = 'liberado' WHERE id = ?", (order_a,))
            conn.commit()
        finally:
            conn.close()

        res_liberado = self.client.post(f"/api/payments/{pay_a}/refund", json={"amount_cents": 5000})
        self.assertEqual(res_liberado.status_code, 409)

    # ---------------- 5. Webhooks & CSRF ----------------

    def test_11_webhook_csrf_exemption_vs_regular_post_csrf(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=90.00)

        # POST normal com Origin malicioso -> 403 CSRF
        res_csrf = self.client.post(
            "/api/payments/intents",
            json={"order_id": order_id, "gateway": "sandbox", "method": "pix"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(res_csrf.status_code, 403)

        # Webhook POST com Origin externo é isento de CSRF (chega na verificação HMAC -> 401 sem segredo)
        with patch.dict(os.environ, {"SANDBOX_WEBHOOK_SECRET": ""}, clear=False):
            res_wh = self.client.post(
                "/api/webhooks/payments/sandbox",
                data=b'{"event_id":"ev_csrf_1"}',
                content_type="application/json",
                headers={"Origin": "https://evil.example"},
            )
            self.assertEqual(res_wh.status_code, 401)

    def test_12_webhook_hmac_fail_closed_all_gateways(self):
        now_ts = str(int(time.time()))
        old_ts = str(int(time.time()) - 360)

        # 1) Sandbox
        raw_sbx = json.dumps({"event_id": "ev_sbx_1", "gateway_payment_id": "sbx_1", "status": "paid"}).encode("utf-8")
        with patch.dict(os.environ, {"SANDBOX_WEBHOOK_SECRET": ""}, clear=False):
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/sandbox", data=raw_sbx, content_type="application/json"
                ).status_code,
                401,
            )
        with patch.dict(os.environ, {"SANDBOX_WEBHOOK_SECRET": "sbx_sec"}, clear=False):
            bad_sig = "sha256=" + ("0" * 64)
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/sandbox",
                    data=raw_sbx,
                    content_type="application/json",
                    headers={"X-Sandbox-Signature": bad_sig, "X-Sandbox-Timestamp": now_ts},
                ).status_code,
                401,
            )
            good_sig = "sha256=" + hmac.new(b"sbx_sec", raw_sbx, hashlib.sha256).hexdigest()
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/sandbox",
                    data=raw_sbx,
                    content_type="application/json",
                    headers={"X-Sandbox-Signature": good_sig, "X-Sandbox-Timestamp": old_ts},
                ).status_code,
                401,
            )

        # 2) Mercado Pago
        raw_mp = json.dumps({"id": "ev_mp_1", "data": {"id": "mp_999"}, "status": "approved"}).encode("utf-8")
        with patch.dict(os.environ, {"MERCADOPAGO_WEBHOOK_SECRET": ""}, clear=False):
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/mercadopago", data=raw_mp, content_type="application/json"
                ).status_code,
                401,
            )
        with patch.dict(os.environ, {"MERCADOPAGO_WEBHOOK_SECRET": "mp_sec"}, clear=False):
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/mercadopago",
                    data=raw_mp,
                    content_type="application/json",
                    headers={"x-signature": f"ts={now_ts},v1=deadbeef", "x-request-id": "req-1"},
                ).status_code,
                401,
            )
            manifest_old = f"id:mp_999;request-id:req-1;ts:{old_ts};".encode("utf-8")
            sig_old = hmac.new(b"mp_sec", manifest_old, hashlib.sha256).hexdigest()
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/mercadopago",
                    data=raw_mp,
                    content_type="application/json",
                    headers={"x-signature": f"ts={old_ts},v1={sig_old}", "x-request-id": "req-1"},
                ).status_code,
                401,
            )

        # 3) Stripe
        raw_st = json.dumps(
            {"id": "evt_st_1", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_1"}}}
        ).encode("utf-8")
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": ""}, clear=False):
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/stripe", data=raw_st, content_type="application/json"
                ).status_code,
                401,
            )
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test"}, clear=False):
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/stripe",
                    data=raw_st,
                    content_type="application/json",
                    headers={"Stripe-Signature": f"t={now_ts},v1=bad"},
                ).status_code,
                401,
            )
            sig_st_old = hmac.new(b"whsec_test", f"{old_ts}.".encode("utf-8") + raw_st, hashlib.sha256).hexdigest()
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/stripe",
                    data=raw_st,
                    content_type="application/json",
                    headers={"Stripe-Signature": f"t={old_ts},v1={sig_st_old}"},
                ).status_code,
                401,
            )

        # 4) PagSeguro
        raw_ps = json.dumps({"id": "ORDE_PS_1", "event_id": "ev_ps_1", "charges": [{"status": "PAID"}]}).encode("utf-8")
        with patch.dict(os.environ, {"PAGSEGURO_WEBHOOK_SECRET": ""}, clear=False):
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/pagseguro", data=raw_ps, content_type="application/json"
                ).status_code,
                401,
            )
        with patch.dict(os.environ, {"PAGSEGURO_WEBHOOK_SECRET": "ps_sec"}, clear=False):
            self.assertEqual(
                self.client.post(
                    "/api/webhooks/payments/pagseguro",
                    data=raw_ps,
                    content_type="application/json",
                    headers={"X-PagSeguro-Signature": "sha256=bad"},
                ).status_code,
                401,
            )

    def test_13_webhook_settles_payment_and_ignores_duplicate_event(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=175.00)
        res_i = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        pay_id = json.loads(res_i.data)["payment_id"]

        conn = database.get_db_connection()
        try:
            gw_pid = conn.execute(
                "SELECT gateway_payment_id FROM payment_transactions WHERE public_id = ?", (pay_id,)
            ).fetchone()["gateway_payment_id"]
        finally:
            conn.close()

        payload = {
            "event_id": "evt_sbx_settle_001",
            "event_type": "payment.paid",
            "gateway_payment_id": gw_pid,
            "status": "paid",
        }
        raw_body = json.dumps(payload).encode("utf-8")
        now_ts = str(int(time.time()))
        secret = "sbx_live_wh_secret_123"
        sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"SANDBOX_WEBHOOK_SECRET": secret}, clear=False):
            # Cliente anônimo (sem sessão) envia webhook válido
            anon_client = app.test_client()
            res1 = anon_client.post(
                "/api/webhooks/payments/sandbox",
                data=raw_body,
                content_type="application/json",
                headers={"X-Sandbox-Signature": sig, "X-Sandbox-Timestamp": now_ts},
            )
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(json.loads(res1.data)["status"], "processed")

            # Replay do mesmo (gateway, event_id) -> 200 duplicate_ignored sem duplicar ledger
            res2 = anon_client.post(
                "/api/webhooks/payments/sandbox",
                data=raw_body,
                content_type="application/json",
                headers={"X-Sandbox-Signature": sig, "X-Sandbox-Timestamp": now_ts},
            )
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(json.loads(res2.data)["status"], "duplicate_ignored")

        conn = database.get_db_connection()
        try:
            ord_row = conn.execute("SELECT pago, escrow_status FROM orders WHERE id = ?", (order_id,)).fetchone()
            self.assertEqual(ord_row["pago"], 1)
            self.assertEqual(ord_row["escrow_status"], "retido")
            ledger_rows = conn.execute(
                "SELECT * FROM escrow_ledger WHERE order_id = ? AND tipo_evento = 'escrow_hold'", (order_id,)
            ).fetchall()
            self.assertEqual(len(ledger_rows), 1)
        finally:
            conn.close()

    # ---------------- 6. Tokenized Methods, LGPD & Legacy /pay ----------------

    def test_14_tokenized_payment_methods_and_lgpd_cleanup(self):
        c_lgpd, lgpd_user = self._create_user_and_login("Usuario LGPD", "lgpd_pay@pertoja.com", tipo="cliente")

        # Rejeita PAN/CVV em POST /api/payments/methods
        res_pci = c_lgpd.post(
            "/api/payments/methods",
            json={
                "gateway": "sandbox",
                "gateway_token": "tok_pci_1",
                "brand": "visa",
                "last4": "4242",
                "exp_month": 12,
                "exp_year": 2029,
                "card_number": "4242424242424242",
            },
        )
        self.assertEqual(res_pci.status_code, 400)

        # Cria método tokenizado válido
        res_add = c_lgpd.post(
            "/api/payments/methods",
            json={
                "gateway": "sandbox",
                "gateway_token": "tok_sbx_4242",
                "brand": "visa",
                "last4": "4242",
                "exp_month": 12,
                "exp_year": 2029,
                "holder_label": "Cartão Principal",
                "is_default": True,
            },
        )
        self.assertEqual(res_add.status_code, 201)
        pm = json.loads(res_add.data)
        self.assertEqual(pm["last4"], "4242")

        # GET lista método salvo
        res_list = c_lgpd.get("/api/payments/methods")
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(json.loads(res_list.data)), 1)

        # DELETE de outro usuário -> 404 uniforme (anti-oráculo)
        other_c, _ = self._create_user_and_login("Outro PM", "other_pm@pertoja.com", tipo="cliente")
        self.assertEqual(other_c.delete(f"/api/payments/methods/{pm['public_id']}").status_code, 404)

        # LGPD DELETE /api/profile limpa payment_methods do usuário
        res_del_prof = c_lgpd.delete("/api/profile")
        self.assertEqual(res_del_prof.status_code, 200)
        conn = database.get_db_connection()
        try:
            rem = conn.execute("SELECT * FROM payment_methods WHERE user_id = ?", (lgpd_user["id"],)).fetchall()
            self.assertEqual(len(rem), 0)
        finally:
            conn.close()

    def test_15_legacy_pay_endpoint_backward_compatibility(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="boleto", valor_total=130.00)

        res_pay = self.client.post(f"/api/orders/{order_id}/pay", json={"metodo_pagamento": "boleto"})
        self.assertEqual(res_pay.status_code, 200)
        pay_data = json.loads(res_pay.data)
        self.assertTrue(pay_data["pago"])
        self.assertEqual(pay_data["metodo_pagamento"], "boleto")
        self.assertEqual(pay_data["escrow_status"], "retido")

        conn = database.get_db_connection()
        try:
            tx = conn.execute(
                "SELECT * FROM payment_transactions WHERE order_id = ? ORDER BY id DESC LIMIT 1", (order_id,)
            ).fetchone()
            self.assertIsNotNone(tx)
            self.assertEqual(tx["gateway"], "sandbox")
            self.assertEqual(tx["method"], "boleto")
            self.assertEqual(tx["escrow_synced"], 1)
        finally:
            conn.close()

    # ---------------- 7. Dual-Engine DDL & Legacy Table Cleanup ----------------

    def test_16_migration_007_ddl_rules_and_postgres_wrapper(self):
        mig_path = os.path.join(REPO_ROOT, "scripts", "migrations", "007_payment_system.sql")
        with open(mig_path, "r", encoding="utf-8") as f:
            sql_text = f.read()

        self.assertNotIn("AUTOINCREMENT", sql_text.upper())
        self.assertNotIn("datetime(", sql_text.lower())
        for line_no, line in enumerate(sql_text.splitlines(), 1):
            if line.strip().startswith("--"):
                self.assertNotIn(";", line, f"Comentário SQL na linha {line_no} não pode conter ponto e vírgula")

        # Simula PostgresCursorWrapper.executescript verificando que chunks de comentário não são executados
        executed_stmts = []

        class FakeRawPgCursor:
            rowcount = 1
            description = None

            def execute(self, sql, params=None):
                executed_stmts.append(sql)

            def fetchone(self):
                return None

            def fetchall(self):
                return []

            def close(self):
                pass

        wrapper = database.PostgresCursorWrapper(FakeRawPgCursor())
        wrapper.executescript(sql_text)
        self.assertGreaterEqual(len(executed_stmts), 12)
        for stmt in executed_stmts:
            self.assertFalse(stmt.strip().startswith("--") and "\n" not in stmt.strip())

    def test_17_legacy_46fc283_table_cleanup(self):
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        try:
            raw_conn = sqlite3.connect(tmp_db.name)
            raw_conn.row_factory = sqlite3.Row
            # Cria tabelas legadas sem amount_cents / gateway_token / event_id
            raw_conn.executescript("""
                CREATE TABLE payment_transactions (id INTEGER PRIMARY KEY, order_id INTEGER, status TEXT);
                CREATE TABLE payment_methods (id INTEGER PRIMARY KEY, user_id INTEGER, brand TEXT);
                CREATE TABLE payment_webhooks (id INTEGER PRIMARY KEY, gateway TEXT);
                CREATE TABLE payment_tokens (id INTEGER PRIMARY KEY, token TEXT);
                INSERT INTO payment_transactions (order_id, status) VALUES (1, 'paid');
            """)
            raw_conn.commit()

            cur = raw_conn.cursor()
            database._cleanup_legacy_payment_tables(raw_conn, cur, "sqlite")

            tables = {
                r["name"] for r in raw_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            # Tabelas vazias foram removidas
            self.assertNotIn("payment_methods", tables)
            self.assertNotIn("payment_webhooks", tables)
            self.assertNotIn("payment_tokens", tables)
            # Tabela com dados foi renomeada para payment_transactions_legacy_<ts>
            self.assertNotIn("payment_transactions", tables)
            self.assertTrue(
                any(re.match(r"^payment_transactions_legacy_\d+$", t) for t in tables),
                f"Tabela legada com dados deveria ser renomeada; tabelas encontradas: {tables}",
            )
            raw_conn.close()
        finally:
            if os.path.exists(tmp_db.name):
                os.remove(tmp_db.name)

    # ---------------- 8. Regression Tests (QA Audit Fixes #132-#140) ----------------

    def test_18_mercadopago_webhook_query_param_and_fetch_payment(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="cartao", valor_total=190.00)
        pref_resp = {
            "id": "pref_mp_100",
            "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref_mp_100",
        }

        with patch.dict(
            os.environ,
            {
                "MERCADOPAGO_ACCESS_TOKEN": "mp_tok_test",
                "MERCADOPAGO_WEBHOOK_SECRET": "mp_wh_secret_18",
            },
            clear=False,
        ):
            mock_pref = MagicMock(status_code=201, text=json.dumps(pref_resp))
            mock_pref.json.return_value = pref_resp
            with patch("payment_adapters.requests.request", return_value=mock_pref):
                res_i = self.client.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "mercadopago",
                        "method": "cartao",
                    },
                )
                self.assertEqual(res_i.status_code, 201)
                pay_id = json.loads(res_i.data)["payment_id"]

            now_ts = str(int(time.time()))
            req_id = "mp-req-18"
            data_id = "99887766"
            manifest = f"id:{data_id};request-id:{req_id};ts:{now_ts};".encode("utf-8")
            sig = hmac.new(b"mp_wh_secret_18", manifest, hashlib.sha256).hexdigest()

            # Webhook real do MP omite status e envia ?data.id=... na query string
            wh_body = json.dumps(
                {"id": "evt_mp_18", "type": "payment", "action": "payment.updated", "data": {"id": data_id}}
            ).encode("utf-8")
            mp_get_resp = {
                "id": int(data_id),
                "status": "approved",
                "transaction_amount": 190.00,
                "external_reference": pay_id,
            }
            mock_get = MagicMock(status_code=200, text=json.dumps(mp_get_resp))
            mock_get.json.return_value = mp_get_resp

            with patch("payment_adapters.requests.request", return_value=mock_get) as mock_req:
                res_wh = app.test_client().post(
                    f"/api/webhooks/payments/mercadopago?data.id={data_id}",
                    data=wh_body,
                    content_type="application/json",
                    headers={"x-signature": f"ts={now_ts},v1={sig}", "x-request-id": req_id},
                )
                self.assertEqual(res_wh.status_code, 200)
                self.assertEqual(json.loads(res_wh.data)["status"], "processed")
                self.assertEqual(mock_req.call_count, 1)

        conn = database.get_db_connection()
        try:
            ord_row = conn.execute("SELECT pago, escrow_status FROM orders WHERE id = ?", (order_id,)).fetchone()
            self.assertEqual(ord_row["pago"], 1)
            self.assertEqual(ord_row["escrow_status"], "retido")
            tx_row = conn.execute(
                "SELECT status, gateway_payment_id FROM payment_transactions WHERE public_id = ?", (pay_id,)
            ).fetchone()
            self.assertEqual(tx_row["status"], "escrow_held")
            self.assertEqual(tx_row["gateway_payment_id"], data_id)
        finally:
            conn.close()

    def test_19_stripe_checkout_session_webhook_and_refund(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="cartao", valor_total=220.00)
        cs_resp = {
            "id": "cs_test_19",
            "url": "https://checkout.stripe.com/c/pay/cs_test_19",
            "payment_status": "unpaid",
        }

        with patch.dict(
            os.environ,
            {
                "STRIPE_SECRET_KEY": "sk_test_19",
                "STRIPE_WEBHOOK_SECRET": "whsec_19",
            },
            clear=False,
        ):
            mock_cs = MagicMock(status_code=200, text=json.dumps(cs_resp))
            mock_cs.json.return_value = cs_resp
            with patch("payment_adapters.requests.request", return_value=mock_cs):
                res_i = self.client.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "stripe",
                        "method": "cartao",
                    },
                )
                self.assertEqual(res_i.status_code, 201)
                pay_id = json.loads(res_i.data)["payment_id"]

            now_ts = str(int(time.time()))
            wh_payload = {
                "id": "evt_stripe_19",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_test_19",
                        "payment_intent": "pi_resolved_19",
                        "payment_status": "paid",
                        "client_reference_id": pay_id,
                        "metadata": {"public_id": pay_id},
                    }
                },
            }
            raw_wh = json.dumps(wh_payload).encode("utf-8")
            sig = hmac.new(b"whsec_19", f"{now_ts}.".encode("utf-8") + raw_wh, hashlib.sha256).hexdigest()

            res_wh = app.test_client().post(
                "/api/webhooks/payments/stripe",
                data=raw_wh,
                content_type="application/json",
                headers={"Stripe-Signature": f"t={now_ts},v1={sig}"},
            )
            self.assertEqual(res_wh.status_code, 200)
            self.assertEqual(json.loads(res_wh.data)["status"], "processed")

        conn = database.get_db_connection()
        try:
            tx_row = conn.execute(
                "SELECT gateway_payment_id, gateway_reference, status FROM payment_transactions WHERE public_id = ?",
                (pay_id,),
            ).fetchone()
            self.assertEqual(tx_row["gateway_payment_id"], "pi_resolved_19")
            self.assertEqual(tx_row["gateway_reference"], "cs_test_19")
            self.assertEqual(tx_row["status"], "escrow_held")
        finally:
            conn.close()

        # Também testa refund_payment resolvendo cs_... -> pi_... diretamente no adaptador
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_19"}, clear=False):
            mock_sess = MagicMock(
                status_code=200, text=json.dumps({"id": "cs_test_19", "payment_intent": "pi_from_sess_19"})
            )
            mock_sess.json.return_value = {"id": "cs_test_19", "payment_intent": "pi_from_sess_19"}
            mock_ref = MagicMock(status_code=200, text=json.dumps({"id": "re_19", "status": "succeeded"}))
            mock_ref.json.return_value = {"id": "re_19", "status": "succeeded"}
            with patch("payment_adapters.requests.request", side_effect=[mock_sess, mock_ref]) as mock_req:
                adapter = payment_adapters.get_payment_adapter("stripe")
                out = adapter.refund_payment(gateway_payment_id="cs_test_19", amount_cents=5000)
                self.assertEqual(out["gateway_refund_id"], "re_19")
                self.assertEqual(mock_req.call_count, 2)
                self.assertEqual(mock_req.call_args_list[1].kwargs["data"]["payment_intent"], "pi_from_sess_19")

    def test_20_pagseguro_customer_payload_and_order_to_charge_refund(self):
        with patch.dict(os.environ, {"PAGSEGURO_TOKEN": "ps_tok_20"}, clear=False):
            ps_order_resp = {"id": "ORDE_20", "qr_codes": [{"id": "QR_20", "text": "000201PS20", "links": []}]}
            mock_create = MagicMock(status_code=201, text=json.dumps(ps_order_resp))
            mock_create.json.return_value = ps_order_resp
            with patch("payment_adapters.requests.request", return_value=mock_create) as mock_req:
                adapter = payment_adapters.get_payment_adapter("pagseguro")
                res = adapter.create_intent(
                    public_id="pay_ps_20",
                    order_id=20,
                    amount_cents=15000,
                    currency="BRL",
                    method="pix",
                    description="Teste PS",
                    payer={"name": "Cliente PS", "email": "ps@pertoja.com", "cpf": ""},
                )
                self.assertEqual(res["gateway_reference"], "ORDE_20")
                sent_body = mock_req.call_args.kwargs["json"]
                self.assertIn("customer", sent_body)
                self.assertEqual(sent_body["customer"]["email"], "ps@pertoja.com")

            # Refund em ORDE_20 resolve CHAR_20 via GET /orders/ORDE_20 e chama POST /charges/CHAR_20/cancel
            mock_get_ord = MagicMock(
                status_code=200, text=json.dumps({"id": "ORDE_20", "charges": [{"id": "CHAR_20"}]})
            )
            mock_get_ord.json.return_value = {"id": "ORDE_20", "charges": [{"id": "CHAR_20"}]}
            mock_cancel = MagicMock(status_code=201, text=json.dumps({"id": "CHAR_20", "status": "CANCELED"}))
            mock_cancel.json.return_value = {"id": "CHAR_20", "status": "CANCELED"}
            with patch("payment_adapters.requests.request", side_effect=[mock_get_ord, mock_cancel]) as mock_req:
                ref_out = adapter.refund_payment(gateway_payment_id="ORDE_20", amount_cents=15000)
                self.assertEqual(ref_out["status"], "succeeded")
                self.assertIn("/charges/CHAR_20/cancel", mock_req.call_args_list[1].kwargs["url"])

    def test_21_refund_blocked_during_execution_guarantee_and_dispute(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=110.00)
        res_i = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        pay_id = json.loads(res_i.data)["payment_id"]
        self.assertEqual(self.client.post(f"/api/payments/{pay_id}/confirm", json={}).status_code, 200)

        for ord_status, esc_status in (
            ("em_execucao", "retido"),
            ("finalizado", "aguardando_liberacao"),
            ("em_disputa", "em_disputa"),
        ):
            conn = database.get_db_connection()
            try:
                conn.execute(
                    "UPDATE orders SET status = ?, escrow_status = ? WHERE id = ?", (ord_status, esc_status, order_id)
                )
                conn.commit()
            finally:
                conn.close()
            res_ref = self.client.post(f"/api/payments/{pay_id}/refund", json={"amount_cents": 1000})
            self.assertEqual(res_ref.status_code, 409, f"Deveria bloquear estorno em ({ord_status}, {esc_status})")

    def test_22_confirm_blocks_terminal_states_and_missing_live_gw_id(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=95.00)
        res_i = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        pay_id = json.loads(res_i.data)["payment_id"]

        for terminal_status in ("failed", "cancelled", "expired"):
            conn = database.get_db_connection()
            try:
                conn.execute(
                    "UPDATE payment_transactions SET status = ?, escrow_synced = 0 WHERE public_id = ?",
                    (terminal_status, pay_id),
                )
                conn.commit()
            finally:
                conn.close()
            res_c = self.client.post(f"/api/payments/{pay_id}/confirm", json={"simulate_outcome": "paid"})
            self.assertEqual(res_c.status_code, 409, f"Deveria bloquear reconfirmação em status {terminal_status}")

        # Stripe confirm_intent com gateway_payment_id=None -> PaymentGatewayError (400)
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_22"}, clear=False):
            adapter = payment_adapters.get_payment_adapter("stripe")
            with self.assertRaises(payment_adapters.PaymentGatewayError) as ctx:
                adapter.confirm_intent(gateway_payment_id=None, method="cartao")
            self.assertEqual(ctx.exception.http_status, 400)

    def test_23_webhook_empty_event_id_fallback_and_settle_failure_rollback(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=160.00)
        res_i = self.client.post(
            "/api/payments/intents",
            json={
                "order_id": order_id,
                "gateway": "sandbox",
                "method": "pix",
            },
        )
        pay_id = json.loads(res_i.data)["payment_id"]

        conn = database.get_db_connection()
        try:
            gw_pid = conn.execute(
                "SELECT gateway_payment_id FROM payment_transactions WHERE public_id = ?", (pay_id,)
            ).fetchone()["gateway_payment_id"]
            # Simula pedido já pago por outro meio para forçar _settle_payment_and_sync_escrow -> False
            conn.execute("UPDATE orders SET pago = 1 WHERE id = ?", (order_id,))
            conn.commit()
        finally:
            conn.close()

        # Payload sem event_id -> fallback para sha256(raw_body)
        raw_body = json.dumps({"gateway_payment_id": gw_pid, "status": "paid"}).encode("utf-8")
        expected_hash = hashlib.sha256(raw_body).hexdigest()
        now_ts = str(int(time.time()))
        secret = "sbx_wh_23"
        sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"SANDBOX_WEBHOOK_SECRET": secret}, clear=False):
            res1 = app.test_client().post(
                "/api/webhooks/payments/sandbox",
                data=raw_body,
                content_type="application/json",
                headers={"X-Sandbox-Signature": sig, "X-Sandbox-Timestamp": now_ts},
            )
            self.assertEqual(res1.status_code, 200)
            body1 = json.loads(res1.data)
            self.assertEqual(body1["event_id"], expected_hash)
            self.assertEqual(body1["status"], "ignored")

            # Replay do mesmo payload sem event_id -> duplicate_ignored
            res2 = app.test_client().post(
                "/api/webhooks/payments/sandbox",
                data=raw_body,
                content_type="application/json",
                headers={"X-Sandbox-Signature": sig, "X-Sandbox-Timestamp": now_ts},
            )
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(json.loads(res2.data)["status"], "duplicate_ignored")

        conn = database.get_db_connection()
        try:
            tx_row = conn.execute(
                "SELECT escrow_synced, status FROM payment_transactions WHERE public_id = ?", (pay_id,)
            ).fetchone()
            self.assertEqual(tx_row["escrow_synced"], 0)
            self.assertNotEqual(tx_row["status"], "escrow_held")
        finally:
            conn.close()

    def test_24_csrf_strict_webhook_prefix_and_pay_order_pci_guard(self):
        # /api/webhooks/payments_evil NÃO é isento de CSRF -> 403
        res_evil = self.client.post(
            "/api/webhooks/payments_evil",
            data=b"{}",
            content_type="application/json",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(res_evil.status_code, 403)

        # pay_order rejeita PAN/CVV -> 400 PCI_VIOLATION
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="cartao", valor_total=100.00)
        res_pci = self.client.post(
            f"/api/orders/{order_id}/pay",
            json={
                "metodo_pagamento": "cartao",
                "card_number": "4111111111111111",
            },
        )
        self.assertEqual(res_pci.status_code, 400)
        self.assertEqual(json.loads(res_pci.data).get("code"), "PCI_VIOLATION")

    # ---------------- 9. Mercado Pago Official Alignment Regression Tests (#151-#158) ----------------

    def test_25_mercadopago_checkout_pro_preference_payload_and_sandbox_url(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="cartao", valor_total=150.00)
        pref_resp = {
            "id": "123456-pref-uuid-25",
            "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=123456-pref-uuid-25",
            "sandbox_init_point": "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=123456-pref-uuid-25",
        }

        with patch.dict(
            os.environ,
            {
                "MERCADOPAGO_ACCESS_TOKEN": "TEST-mp-tok-25",
                "PAYMENT_RETURN_BASE_URL": "https://pertoja.com.br",
                "MERCADOPAGO_NOTIFICATION_URL": "",
            },
            clear=False,
        ):
            mock_pref = MagicMock(status_code=201, text=json.dumps(pref_resp))
            mock_pref.json.return_value = pref_resp
            with patch("payment_adapters.requests.request", return_value=mock_pref) as mock_req:
                res = self.client.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "mercadopago",
                        "method": "cartao",
                        "return_url": f"/pedido.html?order_id={order_id}",
                    },
                )
                self.assertEqual(res.status_code, 201, res.data)
                data = json.loads(res.data)
                self.assertEqual(data["checkout_url"], pref_resp["sandbox_init_point"])

                req_kwargs = mock_req.call_args.kwargs
                self.assertTrue(req_kwargs["url"].endswith("/checkout/preferences"))
                sent_body = req_kwargs["json"]
                expected_return = f"https://pertoja.com.br/pedido.html?order_id={order_id}"
                self.assertEqual(
                    sent_body["back_urls"],
                    {
                        "success": expected_return,
                        "failure": expected_return,
                        "pending": expected_return,
                    },
                )
                self.assertEqual(sent_body["auto_return"], "approved")
                self.assertEqual(
                    sent_body["notification_url"],
                    "https://pertoja.com.br/api/webhooks/payments/mercadopago",
                )
                self.assertEqual(sent_body["statement_descriptor"], "PERTOJA")
                item0 = sent_body["items"][0]
                self.assertTrue(item0["id"])
                self.assertTrue(item0["description"])
                self.assertEqual(item0["category_id"], "services")

    def test_26_mercadopago_checkout_pro_confirm_searches_external_reference(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="cartao", valor_total=150.00)
        pref_resp = {
            "id": "999888-pref-uuid-26",
            "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=999888-pref-uuid-26",
        }

        with patch.dict(os.environ, {"MERCADOPAGO_ACCESS_TOKEN": "APP_USR-tok-26"}, clear=False):
            mock_pref = MagicMock(status_code=201, text=json.dumps(pref_resp))
            mock_pref.json.return_value = pref_resp
            with patch("payment_adapters.requests.request", return_value=mock_pref):
                res_i = self.client.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "mercadopago",
                        "method": "cartao",
                    },
                )
                self.assertEqual(res_i.status_code, 201)
                pay_id = json.loads(res_i.data)["payment_id"]

            search_resp = {
                "results": [
                    {
                        "id": 987654321,
                        "status": "approved",
                        "date_approved": "2026-11-17T20:00:00.000-03:00",
                        "external_reference": pay_id,
                    }
                ]
            }
            mock_search = MagicMock(status_code=200, text=json.dumps(search_resp))
            mock_search.json.return_value = search_resp
            with patch("payment_adapters.requests.request", return_value=mock_search) as mock_req:
                res_c = self.client.post(f"/api/payments/{pay_id}/confirm", json={})
                self.assertEqual(res_c.status_code, 200, res_c.data)
                c_data = json.loads(res_c.data)
                self.assertEqual(c_data["status"], "escrow_held")
                called_url = mock_req.call_args.kwargs["url"]
                self.assertIn("/v1/payments/search", called_url)
                self.assertIn(f"external_reference={pay_id}", called_url)

        conn = database.get_db_connection()
        try:
            tx_row = conn.execute(
                "SELECT status, gateway_payment_id FROM payment_transactions WHERE public_id = ?",
                (pay_id,),
            ).fetchone()
            self.assertEqual(tx_row["status"], "escrow_held")
            self.assertEqual(tx_row["gateway_payment_id"], "987654321")
            ord_row = conn.execute("SELECT pago, escrow_status FROM orders WHERE id = ?", (order_id,)).fetchone()
            self.assertEqual(ord_row["pago"], 1)
            self.assertEqual(ord_row["escrow_status"], "retido")
        finally:
            conn.close()

    def test_27_mercadopago_boleto_validation_payload_and_digitable_line(self):
        client_bol, user_bol = self._create_user_and_login(
            "Cliente Boleto", f"boleto_{int(time.time() * 1000)}@pertoja.com"
        )
        order_id = self._create_order(client_bol, metodo_pagamento="boleto", valor_total=150.00)

        with patch.dict(os.environ, {"MERCADOPAGO_ACCESS_TOKEN": "APP_USR-tok-27"}, clear=False):
            # Sem CPF/endereço -> 400 limpo sem chamar o gateway
            with patch("payment_adapters.requests.request") as mock_req:
                res_missing = client_bol.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "mercadopago",
                        "method": "boleto",
                    },
                )
                self.assertEqual(res_missing.status_code, 400)
                self.assertEqual(json.loads(res_missing.data).get("code"), "MISSING_PAYER_DATA")
                self.assertEqual(mock_req.call_count, 0)

            # Preenche CPF e endereço completo do usuário
            conn = database.get_db_connection()
            try:
                conn.execute(
                    """
                    UPDATE users
                    SET cpf = ?, cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?
                    WHERE id = ?
                    """,
                    (
                        "123.456.789-01",
                        "01310-100",
                        "Av Paulista",
                        "1000",
                        "Bela Vista",
                        "São Paulo",
                        "sp",
                        user_bol["id"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            digitable = "23793.38128 60000.000003 00000.000406 1 99990000015000"
            mp_boleto_resp = {
                "id": 55443322,
                "status": "pending",
                "date_of_expiration": "2026-11-20T23:59:59.000-03:00",
                "barcode": {"content": "23791999900000150003381260000000003000000040"},
                "transaction_details": {
                    "digitable_line": digitable,
                    "external_resource_url": "https://www.mercadopago.com.br/payments/55443322/ticket",
                },
            }
            mock_bol = MagicMock(status_code=201, text=json.dumps(mp_boleto_resp))
            mock_bol.json.return_value = mp_boleto_resp
            with patch("payment_adapters.requests.request", return_value=mock_bol) as mock_req:
                res_ok = client_bol.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "mercadopago",
                        "method": "boleto",
                    },
                )
                self.assertEqual(res_ok.status_code, 201, res_ok.data)
                out = json.loads(res_ok.data)
                self.assertEqual(out["boleto_digitable_line"], digitable)

                sent_body = mock_req.call_args.kwargs["json"]
                self.assertEqual(sent_body["payment_method_id"], "bolbradesco")
                self.assertTrue(sent_body.get("date_of_expiration"))
                self.assertEqual(sent_body["payer"]["identification"], {"type": "CPF", "number": "12345678901"})
                self.assertEqual(
                    sent_body["payer"]["address"],
                    {
                        "zip_code": "01310100",
                        "street_name": "Av Paulista",
                        "street_number": "1000",
                        "neighborhood": "Bela Vista",
                        "city": "São Paulo",
                        "federal_unit": "SP",
                    },
                )

    def test_28_mercadopago_webhook_v2_ms_ts_missing_data_id_non_payment_and_underpayment(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="cartao", valor_total=150.00)
        pref_resp = {
            "id": "pref_mp_28",
            "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref_mp_28",
        }
        secret = "mp_wh_secret_28"

        with patch.dict(
            os.environ,
            {
                "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-tok-28",
                "MERCADOPAGO_WEBHOOK_SECRET": secret,
            },
            clear=False,
        ):
            mock_pref = MagicMock(status_code=201, text=json.dumps(pref_resp))
            mock_pref.json.return_value = pref_resp
            with patch("payment_adapters.requests.request", return_value=mock_pref):
                res_i = self.client.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "mercadopago",
                        "method": "cartao",
                    },
                )
                self.assertEqual(res_i.status_code, 201)
                pay_id = json.loads(res_i.data)["payment_id"]

            conn = database.get_db_connection()
            try:
                tx_amount_cents = conn.execute(
                    "SELECT amount_cents FROM payment_transactions WHERE public_id = ?",
                    (pay_id,),
                ).fetchone()["amount_cents"]
            finally:
                conn.close()

            # 1) 13-digit ms ts + missing data.id (não usa payload['id']) + tópico não-pagamento -> 200 ignored
            ts_ms = str(int(time.time() * 1000))
            self.assertEqual(len(ts_ms), 13)
            req_id_1 = "mp-req-28-a"
            manifest_1 = f"request-id:{req_id_1};ts:{ts_ms};".encode("utf-8")
            sig_1 = hmac.new(secret.encode("utf-8"), manifest_1, hashlib.sha256).hexdigest()
            body_1 = json.dumps(
                {
                    "id": "evt_top_level_only_28",
                    "type": "merchant_order",
                    "action": "merchant_order.updated",
                }
            ).encode("utf-8")

            with patch("payment_adapters.requests.request") as mock_req:
                res_non_pay = app.test_client().post(
                    "/api/webhooks/payments/mercadopago",
                    data=body_1,
                    content_type="application/json",
                    headers={"x-signature": f"ts={ts_ms},v1={sig_1}", "x-request-id": req_id_1},
                )
                self.assertEqual(res_non_pay.status_code, 200, res_non_pay.data)
                self.assertEqual(json.loads(res_non_pay.data)["status"], "ignored")
                self.assertEqual(mock_req.call_count, 0)

            # 2) Underpayment (amount_cents < tx.amount_cents) com 13-digit ms ts -> 200 amount_mismatch_ignored sem liquidar pedido
            req_id_2 = "mp-req-28-b"
            data_id = "777888999"
            manifest_2 = f"id:{data_id};request-id:{req_id_2};ts:{ts_ms};".encode("utf-8")
            sig_2 = hmac.new(secret.encode("utf-8"), manifest_2, hashlib.sha256).hexdigest()
            body_2 = json.dumps(
                {
                    "id": "evt_underpay_28",
                    "type": "payment",
                    "action": "payment.updated",
                    "data": {"id": data_id},
                }
            ).encode("utf-8")

            under_amount = round((tx_amount_cents - 500) / 100.0, 2)
            mp_get_under = {
                "id": int(data_id),
                "status": "approved",
                "transaction_amount": under_amount,
                "external_reference": pay_id,
            }
            mock_get = MagicMock(status_code=200, text=json.dumps(mp_get_under))
            mock_get.json.return_value = mp_get_under
            with patch("payment_adapters.requests.request", return_value=mock_get):
                res_under = app.test_client().post(
                    f"/api/webhooks/payments/mercadopago?data.id={data_id}",
                    data=body_2,
                    content_type="application/json",
                    headers={"x-signature": f"ts={ts_ms},v1={sig_2}", "x-request-id": req_id_2},
                )
                self.assertEqual(res_under.status_code, 200, res_under.data)
                self.assertEqual(json.loads(res_under.data)["status"], "amount_mismatch_ignored")

        conn = database.get_db_connection()
        try:
            ord_row = conn.execute("SELECT pago FROM orders WHERE id = ?", (order_id,)).fetchone()
            self.assertEqual(ord_row["pago"], 0)
            tx_row = conn.execute("SELECT status FROM payment_transactions WHERE public_id = ?", (pay_id,)).fetchone()
            self.assertNotEqual(tx_row["status"], "escrow_held")
        finally:
            conn.close()

    def test_29_mercadopago_refund_idempotency_full_empty_body_and_rejected_rollback(self):
        self._login("cliente@pertoja.com")
        order_id = self._create_order(self.client, metodo_pagamento="pix", valor_total=150.00)
        mp_pix_resp = {
            "id": 555666777,
            "status": "pending",
            "point_of_interaction": {"transaction_data": {"qr_code": "000201MP29", "qr_code_base64": "iVBORw0KGgo="}},
        }

        with patch.dict(os.environ, {"MERCADOPAGO_ACCESS_TOKEN": "APP_USR-tok-29"}, clear=False):
            mock_create = MagicMock(status_code=201, text=json.dumps(mp_pix_resp))
            mock_create.json.return_value = mp_pix_resp
            with patch("payment_adapters.requests.request", return_value=mock_create):
                res_i = self.client.post(
                    "/api/payments/intents",
                    json={
                        "order_id": order_id,
                        "gateway": "mercadopago",
                        "method": "pix",
                    },
                )
                self.assertEqual(res_i.status_code, 201)
                pay_id = json.loads(res_i.data)["payment_id"]

            mock_confirm = MagicMock(status_code=200, text=json.dumps({"id": 555666777, "status": "approved"}))
            mock_confirm.json.return_value = {"id": 555666777, "status": "approved"}
            with patch("payment_adapters.requests.request", return_value=mock_confirm):
                self.assertEqual(self.client.post(f"/api/payments/{pay_id}/confirm", json={}).status_code, 200)

            # 1) Status não-aprovado no refund (in_process -> status='failed') faz rollback da reserva e retorna 502
            mock_inproc = MagicMock(status_code=201, text=json.dumps({"id": "ref_inproc_29", "status": "in_process"}))
            mock_inproc.json.return_value = {"id": "ref_inproc_29", "status": "in_process"}
            with patch("payment_adapters.requests.request", return_value=mock_inproc):
                res_502 = self.client.post(f"/api/payments/{pay_id}/refund", json={})
                self.assertEqual(res_502.status_code, 502)

            # 2) Status 'rejected' no MP também faz rollback da reserva (não persiste refunded_cents)
            mock_rej = MagicMock(status_code=201, text=json.dumps({"id": "ref_rej_29", "status": "rejected"}))
            mock_rej.json.return_value = {"id": "ref_rej_29", "status": "rejected"}
            with patch("payment_adapters.requests.request", return_value=mock_rej):
                res_rej = self.client.post(f"/api/payments/{pay_id}/refund", json={})
                self.assertEqual(res_rej.status_code, 400)
                self.assertEqual(json.loads(res_rej.data).get("code"), "REFUND_REJECTED")

            conn = database.get_db_connection()
            try:
                tx_mid = conn.execute(
                    "SELECT refunded_cents, amount_cents, status FROM payment_transactions WHERE public_id = ?",
                    (pay_id,),
                ).fetchone()
                self.assertEqual(tx_mid["refunded_cents"], 0)
                self.assertEqual(tx_mid["status"], "escrow_held")
            finally:
                conn.close()

            # 3) Refund total aprovado envia {} ao MP e usa refund_public_id único em X-Idempotency-Key
            mock_ok = MagicMock(status_code=201, text=json.dumps({"id": "ref_ok_29", "status": "approved"}))
            mock_ok.json.return_value = {"id": "ref_ok_29", "status": "approved"}
            with patch("payment_adapters.requests.request", return_value=mock_ok) as mock_req:
                res_ok = self.client.post(f"/api/payments/{pay_id}/refund", json={})
                self.assertEqual(res_ok.status_code, 200, res_ok.data)
                ok_data = json.loads(res_ok.data)
                req_kwargs = mock_req.call_args.kwargs
                self.assertEqual(req_kwargs["json"], {})
                self.assertEqual(req_kwargs["headers"]["X-Idempotency-Key"], ok_data["refund_id"])
                self.assertTrue(ok_data["refund_id"].startswith("ref_"))

        conn = database.get_db_connection()
        try:
            tx_end = conn.execute(
                "SELECT refunded_cents, amount_cents, status FROM payment_transactions WHERE public_id = ?",
                (pay_id,),
            ).fetchone()
            self.assertEqual(tx_end["refunded_cents"], tx_end["amount_cents"])
            self.assertEqual(tx_end["status"], "refunded")
        finally:
            conn.close()

    def test_30_csrf_double_submit_and_missing_origin_on_payments(self):
        raw_client = app.test_client()
        same_origin = {"Origin": "http://localhost"}

        # Login sem Origin/Referer -> 403 CSRF_ORIGIN_REQUIRED
        res_no_origin = raw_client.post("/api/auth/login", json={"email": "cliente@pertoja.com", "senha": "123456"})
        self.assertEqual(res_no_origin.status_code, 403)
        self.assertEqual(json.loads(res_no_origin.data).get("code"), "CSRF_ORIGIN_REQUIRED")

        # Login com Origin obtém sessão + csrf_token
        res_login = raw_client.post(
            "/api/auth/login",
            json={"email": "cliente@pertoja.com", "senha": "123456"},
            headers=same_origin,
        )
        self.assertEqual(res_login.status_code, 200)
        csrf_val = raw_client.get_cookie("csrf_token").value
        valid_headers = {**same_origin, "X-CSRF-Token": csrf_val}

        servico_id = self._get_service_id_by_provider_email("marta@pertoja.com")
        res_order = raw_client.post("/api/orders", json={"servico_id": servico_id}, headers=same_origin)
        self.assertEqual(res_order.status_code, 201)
        order_id = json.loads(res_order.data)["order_id"]

        # Criar intent sem Origin -> 403; com Origin e sem token -> 403; com token válido -> 201
        self.assertEqual(
            raw_client.post(
                "/api/payments/intents", json={"order_id": order_id, "gateway": "sandbox", "method": "pix"}
            ).status_code,
            403,
        )
        self.assertEqual(
            raw_client.post(
                "/api/payments/intents",
                json={"order_id": order_id, "gateway": "sandbox", "method": "pix"},
                headers=same_origin,
            ).status_code,
            403,
        )

        res_int = raw_client.post(
            "/api/payments/intents",
            json={"order_id": order_id, "gateway": "sandbox", "method": "pix"},
            headers=valid_headers,
        )
        self.assertEqual(res_int.status_code, 201)
        payment_id = json.loads(res_int.data)["payment_id"]

        # Confirm e refund também exigem double-submit CSRF token
        self.assertEqual(
            raw_client.post(
                f"/api/payments/{payment_id}/confirm", json={"simulate_outcome": "paid"}, headers=same_origin
            ).status_code,
            403,
        )
        res_conf = raw_client.post(
            f"/api/payments/{payment_id}/confirm", json={"simulate_outcome": "paid"}, headers=valid_headers
        )
        self.assertEqual(res_conf.status_code, 200)

        self.assertEqual(
            raw_client.post(
                f"/api/payments/{payment_id}/refund", json={}, headers={**same_origin, "X-CSRF-Token": "errado"}
            ).status_code,
            403,
        )
        res_ref = raw_client.post(f"/api/payments/{payment_id}/refund", json={}, headers=valid_headers)
        self.assertEqual(res_ref.status_code, 200)


if __name__ == "__main__":
    unittest.main()
