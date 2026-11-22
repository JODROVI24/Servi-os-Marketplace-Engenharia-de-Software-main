"""Suíte estrutural e funcional da Fase 3 (arquitetura modular, observabilidade, LLM sem PII e ES modules)."""

from __future__ import annotations

import ast
import io
import json
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = REPO_ROOT / "public"


def _production_python_files() -> list[Path]:
    files = [
        REPO_ROOT / "app.py",
        REPO_ROOT / "database.py",
        REPO_ROOT / "payment_adapters.py",
        REPO_ROOT / "llm_client.py",
        REPO_ROOT / "api" / "index.py",
    ]
    files.extend(sorted((REPO_ROOT / "pertoja").rglob("*.py")))
    return [f for f in files if f.is_file()]


class TestPhase3Architecture(unittest.TestCase):
    """Valida todos os critérios arquiteturais e funcionais da Fase 3 (itens 3.1 a 3.8)."""

    def test_31_32_package_factory_line_budgets_and_blueprints(self):
        import app as app_mod
        from pertoja import create_app

        app_lines = len((REPO_ROOT / "app.py").read_text(encoding="utf-8").splitlines())
        self.assertLess(app_lines, 100, f"app.py deve ter menos de 100 linhas (atual: {app_lines})")

        for facade_name in ("database.py", "payment_adapters.py", "llm_client.py"):
            facade_lines = len((REPO_ROOT / facade_name).read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(facade_lines, 120, f"Fachada {facade_name} excedeu 120 linhas ({facade_lines})")

        for py_file in _production_python_files():
            line_count = len(py_file.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(
                line_count,
                600,
                f"Arquivo Python de produção acima do limite de 600 linhas: {py_file.relative_to(REPO_ROOT)} ({line_count})",
            )

        factory_app = create_app(config_overrides={"TESTING": True}, init_database=False)
        expected_blueprints = {
            "pages",
            "auth",
            "providers",
            "services",
            "orders",
            "payments",
            "webhooks",
            "llm",
        }
        self.assertTrue(expected_blueprints.issubset(set(factory_app.blueprints.keys())))
        for short_ep in (
            "verify_kyc",
            "create_order",
            "update_order_status",
            "trigger_order_sos",
            "open_order_dispute",
            "order_messages",
            "chat_support",
            "generate_ad_description",
        ):
            self.assertIn(short_ep, app_mod.app.view_functions)
            self.assertTrue(hasattr(app_mod.app.view_functions[short_ep], "__wrapped__"))

    def test_33_db_and_repositories_separation(self):
        import database
        import pertoja.db as db_pkg
        import pertoja.db.connection as db_conn
        from pertoja import repositories as repo

        for attr in ("get_db_connection", "init_db", "run_migrations", "DBIntegrityError"):
            self.assertTrue(hasattr(db_pkg, attr), f"pertoja.db sem {attr}")
            self.assertTrue(hasattr(database, attr), f"database facade sem {attr}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = os.path.join(tmpdir, "phase3_repo_test.db")
            orig_conn_db = db_conn.DB_PATH
            orig_facade_db = database.DB_PATH
            db_conn.DB_PATH = tmp_db
            database.DB_PATH = tmp_db
            try:
                database.init_db()
                conn = db_pkg.get_db_connection()
                try:
                    conn.execute(
                        "INSERT INTO users (nome, email, senha_hash, tipo) VALUES (?, ?, ?, ?)",
                        ("Cliente Teste", "repo.teste@example.com", "hash", "cliente"),
                    )
                    conn.commit()
                    by_email = repo.find_user_by_email(conn, "  REPO.TESTE@example.com ")
                    self.assertIsNotNone(by_email)
                    uid = int(by_email["id"])
                    by_id = repo.find_user_by_id(conn, uid)
                    self.assertEqual(by_id["email"], "repo.teste@example.com")
                    initial_ver = int(by_id["session_version"] or 1)
                    repo.increment_session_version(conn, uid)
                    conn.commit()
                    updated = repo.find_user_by_id(conn, uid)
                    self.assertEqual(int(updated["session_version"]), initial_ver + 1)

                    self.assertEqual(repo.list_provider_services(conn, uid), [])
                    self.assertIsNone(repo.get_service_by_id(conn, 999999))
                    self.assertIsNone(repo.find_payment_by_ref(conn, "nonexistent-ref"))
                    self.assertEqual(repo.list_active_payment_methods(conn, uid), [])
                finally:
                    conn.close()

                with patch.dict(os.environ, {}, clear=False):
                    repo.save_cached_geocode("avenida paulista, 1000, sao paulo", -23.5614, -46.6565)
                    cached = repo.get_cached_geocode("  Avenida   Paulista, 1000, Sao Paulo  ")
                    self.assertEqual(cached, (-23.5614, -46.6565))
            finally:
                db_conn.DB_PATH = orig_conn_db
                database.DB_PATH = orig_facade_db

    def test_34_payments_modular_adapters(self):
        import payment_adapters
        from pertoja import payments as pay_pkg
        from pertoja.payments.base import BasePaymentAdapter
        from pertoja.payments.errors import PaymentGatewayError
        from pertoja.payments.mercadopago import MercadoPagoAdapter
        from pertoja.payments.pagseguro import PagSeguroAdapter
        from pertoja.payments.sandbox import SandboxPaymentAdapter
        from pertoja.payments.stripe import StripeAdapter

        for gw, cls in (
            ("sandbox", SandboxPaymentAdapter),
            ("mercadopago", MercadoPagoAdapter),
            ("stripe", StripeAdapter),
            ("pagseguro", PagSeguroAdapter),
        ):
            self.assertTrue(issubclass(cls, BasePaymentAdapter))
            self.assertIsInstance(pay_pkg.get_payment_adapter(gw), cls)
            self.assertIs(getattr(payment_adapters, cls.__name__), cls)

        with self.assertRaises(PaymentGatewayError) as ctx:
            pay_pkg.get_payment_adapter("gateway-desconhecido")
        self.assertEqual(ctx.exception.http_status, 400)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_GATEWAY")

    def test_35_frontend_es_modules_and_html_script_tags(self):
        import app as app_mod

        modules = (
            "state.js",
            "ui.js",
            "map.js",
            "geocode.js",
            "checkout.js",
            "orders.js",
            "portal-common.js",
            "portal-support.js",
        )
        client = app_mod.app.test_client()
        for mod_name in modules:
            mod_path = PUBLIC_DIR / "js" / "modules" / mod_name
            self.assertTrue(mod_path.is_file(), f"Módulo ES ausente: {mod_path}")
            self.assertIn("export ", mod_path.read_text(encoding="utf-8"))
            resp = client.get(f"/js/modules/{mod_name}")
            self.assertEqual(resp.status_code, 200, f"/js/modules/{mod_name} retornou {resp.status_code}")

        html_expectations = {
            "index.html": '<script type="module" src="script.js"></script>',
            "pedido.html": '<script type="module" src="script.js"></script>',
            "portal-cliente.html": '<script type="module" src="js/portal-cliente.js"></script>',
            "portal-prestador.html": '<script type="module" src="js/portal-prestador.js"></script>',
        }
        for html_name, expected_tag in html_expectations.items():
            html_content = (PUBLIC_DIR / html_name).read_text(encoding="utf-8")
            self.assertIn(expected_tag, html_content, f"{html_name} deve carregar entrypoint via type='module'")

    def test_36_observability_ast_json_logging_and_sentry(self):
        from pertoja.logging_config import JsonLogFormatter, configure_logging, init_sentry

        prints: list[tuple[str, int]] = []
        broad_excepts: list[tuple[str, int, str]] = []
        for py_file in _production_python_files():
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            rel = str(py_file.relative_to(REPO_ROOT))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    prints.append((rel, node.lineno))
                elif isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        broad_excepts.append((rel, node.lineno, "bare"))
                    elif isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
                        broad_excepts.append((rel, node.lineno, node.type.id))

        self.assertEqual(prints, [], f"Chamadas print() encontradas em produção: {prints}")
        self.assertEqual(broad_excepts, [], f"Blocos except genéricos encontrados em produção: {broad_excepts}")

        formatter = JsonLogFormatter()
        stream = io.StringIO()
        test_logger = logging.getLogger("pertoja.phase3.test")
        test_logger.handlers.clear()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)
        test_logger.propagate = False

        try:
            raise ZeroDivisionError("probe")
        except ZeroDivisionError:
            test_logger.exception("Falha simulada", extra={"event": "phase3_probe", "order_id": 42})

        parsed = json.loads(stream.getvalue().strip())
        self.assertEqual(parsed["level"], "ERROR")
        self.assertEqual(parsed["logger"], "pertoja.phase3.test")
        self.assertEqual(parsed["message"], "Falha simulada")
        self.assertEqual(parsed["event"], "phase3_probe")
        self.assertEqual(parsed["order_id"], 42)
        self.assertIn("ZeroDivisionError", parsed["exception"])
        self.assertIn("timestamp", parsed)

        configured_pkg_logger = configure_logging()
        self.assertIsNotNone(configured_pkg_logger)

        with patch.dict(os.environ, {"SENTRY_DSN": ""}, clear=False):
            self.assertFalse(init_sentry(test_logger))

        with patch.dict(os.environ, {"SENTRY_DSN": "https://key@o0.ingest.sentry.io/1"}, clear=False):
            with patch.dict(sys.modules, {"sentry_sdk": None}):
                self.assertFalse(init_sentry(test_logger))

            fake_init = MagicMock()
            fake_flask_integration = MagicMock(return_value="flask-int")
            fake_sentry_sdk = types.ModuleType("sentry_sdk")
            fake_sentry_sdk.init = fake_init
            fake_integrations = types.ModuleType("sentry_sdk.integrations")
            fake_flask_mod = types.ModuleType("sentry_sdk.integrations.flask")
            fake_flask_mod.FlaskIntegration = fake_flask_integration
            with patch.dict(
                sys.modules,
                {
                    "sentry_sdk": fake_sentry_sdk,
                    "sentry_sdk.integrations": fake_integrations,
                    "sentry_sdk.integrations.flask": fake_flask_mod,
                },
            ):
                self.assertTrue(init_sentry(test_logger))
                fake_init.assert_called_once()
                _, kwargs = fake_init.call_args
                self.assertFalse(kwargs["send_default_pii"])

    def test_37_single_source_security_headers(self):
        from flask import Response

        from pertoja.security_headers import (
            apply_security_headers,
            clear_security_headers_cache,
            get_global_security_headers,
            is_sensitive_nocache_path,
        )

        vercel_cfg = json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8"))
        expected = {}
        for block in vercel_cfg.get("headers", []):
            if block.get("source") == "/(.*)":
                expected = {h["key"]: h["value"] for h in block.get("headers", [])}

        clear_security_headers_cache()
        loaded = get_global_security_headers()
        self.assertEqual(loaded, expected)
        self.assertIn("Content-Security-Policy", loaded)
        self.assertIn("Strict-Transport-Security", loaded)

        for py_file in _production_python_files():
            text = py_file.read_text(encoding="utf-8")
            self.assertNotIn("default-src 'self'", text, f"CSP duplicada em {py_file.name}")
            self.assertNotIn("max-age=63072000", text, f"HSTS duplicado em {py_file.name}")

        self.assertTrue(is_sensitive_nocache_path("/api/orders"))
        self.assertTrue(is_sensitive_nocache_path("/portal-cliente.html"))
        self.assertFalse(is_sensitive_nocache_path("/index.html"))

        api_resp = Response("{}", mimetype="application/json")
        apply_security_headers(api_resp, "/api/health")
        self.assertEqual(api_resp.headers.get("Content-Security-Policy"), expected["Content-Security-Policy"])
        self.assertEqual(api_resp.headers.get("Cache-Control"), "no-store, no-cache, must-revalidate, max-age=0")

        asset_resp = Response("console.log(1);", mimetype="application/javascript")
        apply_security_headers(asset_resp, "/js/modules/ui.js")
        self.assertEqual(
            asset_resp.headers.get("Cache-Control"), "public, max-age=604800, stale-while-revalidate=86400"
        )

    def test_38_llm_official_priority_and_zero_pii(self):
        import pertoja.llm as llm_pkg
        from pertoja.llm.pii import redact_pii_for_llm, sanitize_user_context_for_llm
        from pertoja.llm.prompts import build_support_system_prompt
        from pertoja.llm.providers import DEFAULT_OPENAI_BASE_URL, resolve_provider_chain

        self.assertEqual(DEFAULT_OPENAI_BASE_URL, "https://api.openai.com/v1")

        clean_env = {
            "OPENAI_API_KEY": "sk-openai-official-test",
            "GEMINI_API_KEY": "AIza-gemini-official-test",
            "APIFREELLM_API_KEY": "apifreellm-fallback-key",
            "FREELLM_API_BASE_URL": "http://localhost:3001/v1",
            "VERCEL": "1",
        }
        with patch.dict(os.environ, clean_env, clear=True):
            chain, unavailable = resolve_provider_chain()
            self.assertIn("localhost_in_serverless", unavailable)
            names = [c["provider"] for c in chain]
            self.assertLess(names.index("openai"), names.index("gemini"))
            self.assertLess(names.index("gemini"), names.index("apifreellm"))

        redacted = redact_pii_for_llm(
            "Cliente fulano@example.com CPF 123.456.789-00 CNPJ 12.345.678/0001-99 Tel (11) 98765-4321 CEP 01310-100"
        )
        for pii_val in ("fulano@example.com", "123.456.789-00", "12.345.678/0001-99", "98765-4321", "01310-100"):
            self.assertNotIn(pii_val, redacted)

        pii_user = {
            "id": 99,
            "nome": "Fulano da Silva Sauro",
            "email": "fulano@example.com",
            "cpf": "123.456.789-00",
            "cnpj": "12.345.678/0001-99",
            "telefone": "(11) 98765-4321",
            "cep": "01310-100",
            "tipo": "prestador",
            "plano": "pro",
            "kyc_tier": 2,
        }
        meta = sanitize_user_context_for_llm(pii_user)
        self.assertEqual(meta, {"tipo": "prestador", "plano": "pro", "kyc_tier": 2})

        prompt = build_support_system_prompt(
            user_info=pii_user,
            context_text="Atendimento de fulano@example.com no CEP 01310-100",
            recent_orders=[
                {
                    "id": 12,
                    "servico_titulo": "Reparo urgente tel (11) 98765-4321",
                    "status": "confirmado",
                    "escrow_status": "retido",
                }
            ],
        )
        for forbidden in ("Fulano da Silva Sauro", "fulano@example.com", "123.456.789-00", "98765-4321", "01310-100"):
            self.assertNotIn(forbidden, prompt)
        self.assertIn("Contexto não pessoal da sessão: perfil=prestador, plano=pro, kyc_tier=2", prompt)

        captured_payloads: list[dict] = []

        class _FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "Resposta sem PII"}}]}

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured_payloads.append({"url": url, "json": json})
            return _FakeResponse()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai-official-test"}, clear=True):
            with patch("pertoja.llm.client.requests.post", side_effect=_fake_post):
                reply = llm_pkg.call_llm(
                    [{"role": "system", "content": prompt}, {"role": "user", "content": "Como funciona o Escrow?"}]
                )
        self.assertEqual(reply, "Resposta sem PII")
        self.assertEqual(len(captured_payloads), 1)
        self.assertTrue(captured_payloads[0]["url"].startswith("https://api.openai.com/v1"))
        serialized = json.dumps(captured_payloads[0]["json"], ensure_ascii=False)
        for forbidden in ("Fulano da Silva Sauro", "fulano@example.com", "123.456.789-00", "98765-4321", "01310-100"):
            self.assertNotIn(forbidden, serialized)
