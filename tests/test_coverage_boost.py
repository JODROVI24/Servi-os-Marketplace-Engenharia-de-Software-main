"""Testes unitários complementares para database.py, scripts/migrate.py e payment_adapters.py."""

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from collections import namedtuple
from unittest.mock import MagicMock, patch

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import database
import payment_adapters
from scripts import migrate as migrate_script


class TestDatabaseAndMigrateCoverage(unittest.TestCase):
    """Testes para HybridRow, Postgres wrappers, legado e CLI de migrations."""

    def test_hybrid_row_and_postgres_wrappers(self):
        row = database.HybridRow({"id": 7, "nome": "Ana"}, (7, "Ana"))
        self.assertEqual(row["id"], 7)
        self.assertEqual(row[1], "Ana")
        self.assertEqual(len(row), 2)
        self.assertIn("nome", row)
        self.assertEqual(list(row), ["id", "nome"])
        self.assertEqual(list(row.keys()), ["id", "nome"])
        self.assertEqual(list(row.values()), [7, "Ana"])
        self.assertEqual(list(row.items()), [("id", 7), ("nome", "Ana")])
        self.assertEqual(row.get("missing", "x"), "x")
        self.assertIn("HybridRow", repr(row))
        self.assertEqual(row, database.HybridRow({"id": 7, "nome": "Ana"}))
        self.assertEqual(row, {"id": 7, "nome": "Ana"})
        self.assertEqual(row, (7, "Ana"))
        self.assertNotEqual(row, "other")

        raw_cur = MagicMock()
        raw_cur.description = [("id",), ("email",)]
        raw_cur.rowcount = 1
        raw_cur.fetchone.return_value = (12, "a@b.com")
        raw_cur.fetchall.return_value = [(12, "a@b.com")]
        raw_cur.fetchmany.return_value = [(12, "a@b.com")]
        raw_cur.__iter__.return_value = iter([(12, "a@b.com")])

        raw_conn = MagicMock()
        raw_conn.cursor.return_value = raw_cur

        conn_w = database.PostgresConnectionWrapper(raw_conn)
        with conn_w as cw:
            cur_w = cw.execute("SELECT id, email FROM users WHERE id = ?", (12,))
            self.assertEqual(cur_w.description, [("id",), ("email",)])
            self.assertEqual(cur_w.rowcount, 1)
            fetched = cur_w.fetchone()
            self.assertEqual(fetched["id"], 12)
            self.assertEqual(len(cur_w.fetchall()), 1)
            self.assertEqual(len(cur_w.fetchmany(1)), 1)
            self.assertEqual(len(cur_w.fetchmany()), 1)
            self.assertEqual(len(list(cur_w)), 1)

            NT = namedtuple("NT", ["id", "email"])
            self.assertEqual(cur_w._wrap_row(NT(1, "x"))["email"], "x")
            self.assertEqual(cur_w._wrap_row({"id": 2})["id"], 2)
            self.assertIsNone(cur_w._wrap_row(None))
            cur_w._cursor.description = None
            self.assertEqual(cur_w._wrap_row(("v0",))["col_0"], "v0")
            self.assertEqual(cur_w._wrap_row(42), 42)

            cw.executescript("-- comment\nSELECT 1; SELECT 2;")
            cur_w.close()
        raw_conn.commit.assert_called_once()

        # Rollback on exception inside context manager
        raw_conn.reset_mock()
        with self.assertRaises(RuntimeError), conn_w:
            raise RuntimeError("boom")
        raw_conn.rollback.assert_called_once()
        conn_w.close()
        raw_conn.close.assert_called_once()

    def test_connect_postgres_and_table_helpers(self):
        fake_conn = MagicMock()
        with (
            patch.object(database, "HAS_PSYCOPG2", True),
            patch.object(database, "psycopg2", MagicMock(connect=MagicMock(return_value=fake_conn))),
            patch.object(database, "extras", MagicMock(DictCursor="DC")),
        ):
            wrapped = database._connect_postgres("postgresql://u:p@host/db?sslmode=require")
            self.assertIsInstance(wrapped, database.PostgresConnectionWrapper)

        with patch.object(database, "HAS_PSYCOPG2", False):
            with self.assertRaises(ImportError):
                database._connect_postgres("postgresql://u:p@host/db")

        # _get_table_columns & _retire_legacy_table (PostgreSQL branch via mock cursor)
        pg_cur = MagicMock()
        pg_cur.execute.return_value.fetchall.return_value = [{"column_name": "id"}, ("status",)]
        cols = database._get_table_columns(pg_cur, "orders", "postgresql")
        self.assertEqual(cols, {"id", "status"})

        pg_cur_legacy = MagicMock()
        pg_cur_legacy.execute.return_value.fetchone.return_value = {"cnt": 2}
        pg_cur_legacy.execute.return_value.fetchall.side_effect = [
            [{"conname": "fk_old"}],
            [{"indexname": "idx_pay_old"}],
        ]
        database._retire_legacy_table(pg_cur_legacy, "payment_intents", "postgresql", "20261122")
        executed_sqls = [c.args[0] for c in pg_cur_legacy.execute.call_args_list]
        self.assertTrue(any("RENAME CONSTRAINT fk_old" in s for s in executed_sqls))
        self.assertTrue(any("ALTER INDEX IF EXISTS idx_pay_old" in s for s in executed_sqls))

    def test_migrate_cli_dry_run_and_apply(self):
        fd, tmp_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        orig_db = database.DB_PATH
        try:
            with patch.dict(os.environ, {"MARKETPLACE_DB": tmp_db, "ENABLE_DEMO_SEED": "0"}, clear=False):
                os.environ.pop("DATABASE_URL", None)
                os.environ.pop("POSTGRES_URL", None)
                database.DB_PATH = tmp_db
                database.init_db()
                self.assertEqual(migrate_script.main(["--dry-run"]), 0)
                self.assertEqual(migrate_script.main([]), 0)
                with patch.object(database, "run_migrations", return_value=[]):
                    self.assertEqual(migrate_script.main(["--dry-run"]), 0)
        finally:
            database.DB_PATH = orig_db
            if os.path.exists(tmp_db):
                os.remove(tmp_db)


class TestPaymentAdaptersCoverage(unittest.TestCase):
    """Cobertura para utilitários, Stripe, PagSeguro e erros de rede."""

    def test_helpers_and_request_json_errors(self):
        self.assertEqual(payment_adapters._get_header_ci(None, "X-Sig"), "")
        self.assertEqual(payment_adapters._get_header_ci({"X-Test": " val "}, "x-test"), "val")

        with self.assertRaises(payment_adapters.WebhookSignatureError):
            payment_adapters._parse_json_bytes(b"")
        with self.assertRaises(payment_adapters.WebhookSignatureError):
            payment_adapters._parse_json_bytes(b"{bad json")
        with self.assertRaises(payment_adapters.WebhookSignatureError):
            payment_adapters._parse_json_bytes(b"[1, 2]")

        with self.assertRaises(payment_adapters.WebhookSignatureError):
            payment_adapters._validate_timestamp("not-a-number")
        with self.assertRaises(payment_adapters.WebhookSignatureError):
            payment_adapters._validate_timestamp("1000")
        now_ms = str(int(time.time() * 1000))
        self.assertGreater(payment_adapters._validate_timestamp(now_ms), 0)

        self.assertEqual(payment_adapters._split_payer_name(""), ("", ""))
        self.assertEqual(payment_adapters._split_payer_name("Maria"), ("Maria", ""))
        self.assertEqual(payment_adapters._split_payer_name("Maria Silva"), ("Maria", "Silva"))

        for raw, expected in (
            ("approved", "paid"),
            ("requires_action", "requires_action"),
            ("pending", "pending"),
            ("authorized", "authorized"),
            ("rejected", "failed"),
            ("expired", "expired"),
            ("cancelled", "cancelled"),
            ("refunded", "refunded"),
            ("desconhecido", "pending"),
        ):
            self.assertEqual(payment_adapters._map_status(raw), expected)

        with patch("payment_adapters.requests.request", side_effect=requests.Timeout("t")):
            with self.assertRaises(payment_adapters.PaymentGatewayError) as ctx_to:
                payment_adapters._request_json("GET", "https://example.com")
            self.assertEqual(ctx_to.exception.code, "GATEWAY_TIMEOUT")

        with patch("payment_adapters.requests.request", side_effect=requests.ConnectionError("net")):
            with self.assertRaises(payment_adapters.PaymentGatewayError) as ctx_net:
                payment_adapters._request_json("GET", "https://example.com")
            self.assertEqual(ctx_net.exception.code, "GATEWAY_NETWORK_ERROR")

        bad_resp = MagicMock(status_code=422)
        bad_resp.json.return_value = {"error": "Dados inválidos"}
        with patch("payment_adapters.requests.request", return_value=bad_resp):
            with self.assertRaises(payment_adapters.PaymentGatewayError) as ctx_422:
                payment_adapters._request_json("POST", "https://example.com")
            self.assertIn("Dados inválidos", ctx_422.exception.message)

        empty_resp = MagicMock(status_code=204, content=b"")
        with patch("payment_adapters.requests.request", return_value=empty_resp):
            self.assertEqual(payment_adapters._request_json("DELETE", "https://example.com"), {})

        bad_json_resp = MagicMock(status_code=200, content=b"not-json")
        bad_json_resp.json.side_effect = ValueError("bad json")
        with patch("payment_adapters.requests.request", return_value=bad_json_resp):
            with self.assertRaises(payment_adapters.PaymentGatewayError):
                payment_adapters._request_json("GET", "https://example.com")

    def test_sandbox_disabled_and_registry_errors(self):
        with patch.dict(os.environ, {"ENABLE_PAYMENT_SANDBOX": "0"}, clear=False):
            self.assertFalse(payment_adapters.is_sandbox_enabled())
            with self.assertRaises(payment_adapters.GatewayNotConfiguredError):
                payment_adapters.get_payment_adapter("sandbox")
            sbx = payment_adapters.SandboxPaymentAdapter()
            with self.assertRaises(payment_adapters.GatewayNotConfiguredError):
                sbx.create_intent(
                    public_id="p1", order_id=1, amount_cents=1000, currency="BRL", method="pix", description="d"
                )
            with self.assertRaises(payment_adapters.GatewayNotConfiguredError):
                sbx.confirm_intent(gateway_payment_id="x", method="pix")
            with self.assertRaises(payment_adapters.GatewayNotConfiguredError):
                sbx.refund_payment(gateway_payment_id="x", amount_cents=100)

        with self.assertRaises(payment_adapters.PaymentGatewayError):
            payment_adapters.get_payment_adapter("desconhecido")

    def test_stripe_and_pagseguro_adapters(self):
        stripe = payment_adapters.StripeAdapter()
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_123"}, clear=False):
            with patch(
                "payment_adapters._request_json",
                return_value={
                    "id": "pi_123",
                    "status": "requires_action",
                    "next_action": {"pix_display_qr_code": {"data": "000201PIX"}},
                },
            ):
                res_pix = stripe.create_intent(
                    public_id="pub_1",
                    order_id=10,
                    amount_cents=5000,
                    currency="BRL",
                    method="pix",
                    description="Limpeza",
                )
                self.assertEqual(res_pix["gateway_payment_id"], "pi_123")
                self.assertEqual(res_pix["pix_qr_code"], "000201PIX")

            with patch(
                "payment_adapters._request_json",
                return_value={"id": "cs_test_1", "payment_status": "paid", "payment_intent": "pi_99"},
            ):
                conf = stripe.confirm_intent(gateway_payment_id="cs_test_1", method="cartao")
                self.assertEqual(conf["status"], "paid")
                self.assertEqual(conf["gateway_reference"], "cs_test_1")

            with patch("payment_adapters._request_json", return_value={"id": "cs_test_2", "payment_intent": ""}):
                with self.assertRaises(payment_adapters.PaymentGatewayError):
                    stripe.refund_payment(gateway_payment_id="cs_test_2", amount_cents=1000)

        pag = payment_adapters.PagSeguroAdapter()
        with patch.dict(
            os.environ,
            {
                "PAGSEGURO_TOKEN": "pg_tok",
                "PAGSEGURO_WEBHOOK_SECRET": "pg_wh_sec",
                "PAYMENT_RETURN_BASE_URL": "https://app.test",
            },
            clear=False,
        ):
            with patch(
                "payment_adapters._request_json",
                return_value={"id": "CHKO_1", "links": [{"rel": "PAY", "href": "https://pag.test/pay"}]},
            ):
                card_res = pag.create_intent(
                    public_id="pub_pg_1",
                    order_id=20,
                    amount_cents=8000,
                    currency="BRL",
                    method="cartao",
                    description="Pintura",
                )
                self.assertEqual(card_res["checkout_url"], "https://pag.test/pay")

            with patch(
                "payment_adapters._request_json",
                return_value={
                    "id": "ORDE_1",
                    "charges": [
                        {
                            "id": "CHAR_1",
                            "payment_method": {"boleto": {"barcode": "123", "formatted_barcode": "123.456"}},
                        }
                    ],
                },
            ):
                bol_res = pag.create_intent(
                    public_id="pub_pg_2",
                    order_id=21,
                    amount_cents=9000,
                    currency="BRL",
                    method="boleto",
                    description="Elétrica",
                )
                self.assertEqual(bol_res["gateway_payment_id"], "CHAR_1")
                self.assertEqual(bol_res["boleto_barcode"], "123")

            with patch(
                "payment_adapters._request_json",
                return_value={"id": "CHAR_1", "status": "PAID", "paid_at": "2026-11-22T10:00:00Z"},
            ):
                self.assertEqual(pag.confirm_intent(gateway_payment_id="CHAR_1", method="boleto")["status"], "paid")

            with patch(
                "payment_adapters._request_json",
                side_effect=[{"id": "ORDE_1", "charges": [{"id": "CHAR_1"}]}, {"id": "CANC_1"}],
            ):
                ref = pag.refund_payment(gateway_payment_id="ORDE_1", amount_cents=9000)
                self.assertEqual(ref["gateway_refund_id"], "CANC_1")

            raw = json.dumps(
                {"id": "ORDE_1", "charges": [{"id": "CHAR_1", "status": "PAID", "amount": {"value": 9000}}]}
            ).encode("utf-8")
            sig = "sha256=" + hmac.new(b"pg_wh_sec", raw, hashlib.sha256).hexdigest()
            wh = pag.verify_webhook(
                raw_body=raw, headers={"X-PagSeguro-Signature": sig, "X-PagSeguro-Timestamp": str(int(time.time()))}
            )
            self.assertTrue(wh["verified"])
            self.assertEqual(wh["mapped_status"], "paid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
