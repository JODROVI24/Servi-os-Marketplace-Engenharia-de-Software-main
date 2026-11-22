"""Testes unitários dedicados para llm_client.py."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import llm_client


class TestLlmClientUnit(unittest.TestCase):
    """Cobertura de classificação de erros, descoberta de modelos e fallbacks offline."""

    def setUp(self):
        llm_client.clear_discovered_models_cache()

    def test_url_and_serverless_helpers(self):
        self.assertTrue(llm_client.is_localhost_url("http://localhost:3001/v1"))
        self.assertTrue(llm_client.is_localhost_url("127.0.0.1:8000"))
        self.assertTrue(llm_client.is_localhost_url("http://sub.localhost:3000"))
        self.assertFalse(llm_client.is_localhost_url(""))
        self.assertFalse(llm_client.is_localhost_url("https://api.groq.com/openai/v1"))

        self.assertEqual(
            llm_client.normalize_base_url(" https://api.groq.com/openai/v1/chat/completions/ "),
            "https://api.groq.com/openai/v1",
        )
        self.assertEqual(llm_client.normalize_base_url(""), "")

        with patch.dict(os.environ, {"VERCEL": "0", "VERCEL_ENV": "false"}, clear=True):
            self.assertFalse(llm_client.is_serverless_env())
        with patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "fn"}, clear=True):
            self.assertTrue(llm_client.is_serverless_env())

    def test_sanitize_error_text_masks_secrets(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_super_secret_token_value"}, clear=True):
            raw = "Falha Bearer abcdef123456 com gsk_super_secret_token_value e api_key=segredo123 " + ("x" * 300)
            sanitized = llm_client._sanitize_error_text(raw, extra_secrets=["extra_secret_val"])
            self.assertNotIn("gsk_super_secret_token_value", sanitized)
            self.assertNotIn("abcdef123456", sanitized)
            self.assertNotIn("segredo123", sanitized)
            self.assertLessEqual(len(sanitized), 240)
            self.assertEqual(llm_client._sanitize_error_text(""), "")

    def test_classify_exception_and_content_extraction(self):
        exc_401 = requests.HTTPError("401", response=SimpleNamespace(status_code=401, text=""))
        exc_429 = requests.HTTPError("429", response=SimpleNamespace(status_code=429, text=""))
        exc_404 = requests.HTTPError("404", response=SimpleNamespace(status_code=404, text=""))
        exc_400_model = requests.HTTPError(
            "400", response=SimpleNamespace(status_code=400, text="model decommissioned")
        )
        exc_400_other = requests.HTTPError("400", response=SimpleNamespace(status_code=400, text="bad payload"))

        self.assertEqual(llm_client._classify_exception(exc_401), "auth_error")
        self.assertEqual(llm_client._classify_exception(exc_429), "rate_limited")
        self.assertEqual(llm_client._classify_exception(exc_404), "model_not_found")
        self.assertEqual(llm_client._classify_exception(exc_400_model), "model_not_found")
        self.assertEqual(llm_client._classify_exception(exc_400_other), "provider_error")
        self.assertEqual(
            llm_client._classify_exception(requests.exceptions.ReadTimeout("timed out")),
            "timeout",
        )
        self.assertEqual(
            llm_client._classify_exception(requests.exceptions.ConnectionError("connection refused")),
            "connection_error",
        )
        self.assertEqual(llm_client._classify_exception(Exception("quota exceeded")), "rate_limited")
        self.assertEqual(llm_client._classify_exception(Exception("401 unauthorized")), "auth_error")
        self.assertEqual(llm_client._classify_exception(Exception("unknown model")), "model_not_found")
        self.assertEqual(llm_client._classify_exception(RuntimeError("boom")), "provider_error")

        # _extract_openai_sdk_content & _extract_json_content
        sdk_resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  Olá!  "))])
        self.assertEqual(llm_client._extract_openai_sdk_content(sdk_resp), "Olá!")
        self.assertEqual(
            llm_client._extract_openai_sdk_content({"choices": [{"message": {"content": "Dict OK"}}]}),
            "Dict OK",
        )
        with self.assertRaises(ValueError):
            llm_client._extract_openai_sdk_content(SimpleNamespace(choices=[]))
        with self.assertRaises(ValueError):
            llm_client._extract_json_content("not-a-dict")  # type: ignore[arg-type]
        self.assertEqual(llm_client._extract_json_content({"choices": [{"text": " Text OK "}]}), "Text OK")
        self.assertEqual(
            llm_client._extract_json_content({"reply": "FreeLLM OK"}, protocol="apifreellm"),
            "FreeLLM OK",
        )
        with self.assertRaises(ValueError):
            llm_client._extract_json_content({"error": {"message": "bad"}})
        with self.assertRaises(ValueError):
            llm_client._extract_json_content({})

    def test_flatten_messages_and_model_discovery(self):
        flat = llm_client._flatten_messages_to_prompt(
            [
                {"role": "system", "content": "Seja breve"},
                {"role": "assistant", "content": "Oi"},
                {"role": "user", "content": "Ajuda"},
                {"role": "user", "content": ""},
            ]
        )
        self.assertIn("[Instruções]", flat)
        self.assertIn("Assistente: Oi", flat)
        self.assertIn("Usuário: Ajuda", flat)

        cand = {
            "provider": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "k",
        }

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock(status_code=200)
            resp.json.return_value = {
                "models": [
                    {"name": "models/whisper-large", "active": True},
                    {"name": "models/gemini-3.5-flash-lite", "active": True},
                    {"name": "models/inactive-model", "active": False},
                    "models/gemma-3-27b",
                ]
            }
            return resp

        discovered = llm_client._discover_active_chat_models(cand, http_get=fake_get)
        self.assertIn("gemini-3.5-flash-lite", discovered)
        self.assertNotIn("whisper-large", discovered)
        self.assertNotIn("inactive-model", discovered)
        # Cache hit on second call
        self.assertEqual(llm_client._discover_active_chat_models(cand, http_get=lambda *a, **kw: None), discovered)

        llm_client.clear_discovered_models_cache()
        err_resp = MagicMock(status_code=500)
        self.assertEqual(llm_client._discover_active_chat_models(cand, http_get=lambda *a, **kw: err_resp), [])
        self.assertEqual(llm_client._discover_active_chat_models({"provider": "x", "base_url": ""}), [])

    def test_offline_chat_support_and_ad_description_fallbacks(self):
        # Reason notes + unknown fallback
        for reason in ("localhost_in_serverless", "rate_limited", "auth_error", "timeout", "provider_error"):
            reply = llm_client.fallback_chat_support_reply("qual a capital da franca?", reason=reason)
            self.assertIn("modo offline", reply.lower())

        # FAQ topics
        kyc_reply = llm_client.fallback_chat_support_reply("Como funciona o KYC CREA e plano pro?")
        self.assertIn("Tier 2", kyc_reply)
        self.assertIn("Plano Pro", kyc_reply)

        sos_lgpd = llm_client.fallback_chat_support_reply("Quero saber do SOS emergência, LGPD e gerar com ia anúncio")
        self.assertIn("SOS", sos_lgpd)
        self.assertIn("LGPD", sos_lgpd)
        self.assertIn("Gerar com IA", sos_lgpd)

        # Anti-repeat followups across categories
        dispute_msg = "Como abrir disputa e não liberar pagamento?"
        first_dispute = llm_client.fallback_chat_support_reply(dispute_msg)
        repeat_dispute = llm_client.fallback_chat_support_reply(
            dispute_msg,
            history=[{"role": "user", "content": dispute_msg}, {"role": "assistant", "content": first_dispute}],
        )
        self.assertIn("Passo a passo", repeat_dispute)

        # Long ad description compaction preserves price and respects 280 chars
        long_ad = llm_client.fallback_ad_description(
            title="Instalação Elétrica Residencial Completa",
            category="Elétrica",
            description="Atendimento completo para quadros de distribuição, disjuntores, tomadas e iluminação em residências e comércios com material de alta qualidade "
            * 2,
            price=250.5,
            service_type="Residencial",
            extra="Laudo técnico incluso",
        )
        self.assertLessEqual(len(long_ad), 280)
        self.assertIn("250,50", long_ad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
