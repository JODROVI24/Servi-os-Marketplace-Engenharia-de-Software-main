#!/usr/bin/env python3
"""
Adversarial WSGI & Serverless API Test Suite
Challenger 1 - Empirical verification of VercelPathNormalizerWSGI and Flask API
"""

import json
import os
import sys
import tempfile
import unittest
from io import BytesIO

# Ensure repo root and submodules are in sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import database


class TestWsgiApiAdversarial(unittest.TestCase):
    """Testes adversariais do entrypoint WSGI Vercel (api/index.py)."""

    def test_wsgi_adversarial_suite(self):
        saved_env = {k: os.environ.get(k) for k in ("VERCEL", "FLASK_ENV", "MARKETPLACE_DB", "ENABLE_DEMO_SEED")}
        orig_db_path = database.DB_PATH
        fd, wsgi_tmp_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        try:
            os.environ["MARKETPLACE_DB"] = wsgi_tmp_db
            os.environ["ENABLE_DEMO_SEED"] = "1"
            os.environ.pop("VERCEL", None)
            os.environ.pop("FLASK_ENV", None)
            database.DB_PATH = wsgi_tmp_db
            database.init_db()

            from api.index import VercelPathNormalizerWSGI, app, application, handler

            self.assertIsNotNone(app, "FAIL: 'app' is None")
            self.assertIs(application, app, "FAIL: 'application' does not match 'app'")
            self.assertIs(handler, app, "FAIL: 'handler' does not match 'app'")
            self.assertIsInstance(
                app.wsgi_app,
                VercelPathNormalizerWSGI,
                "FAIL: wsgi_app is not wrapped in VercelPathNormalizerWSGI",
            )

            def make_wsgi_request(method="GET", path_info="/api/index.py", query_string="", headers=None, body=b""):
                """Executes a direct raw WSGI call to app.wsgi_app mimicking Vercel gateway."""
                env = {
                    "REQUEST_METHOD": method,
                    "SCRIPT_NAME": "",
                    "PATH_INFO": path_info,
                    "QUERY_STRING": query_string,
                    "SERVER_NAME": "test-marketplace.vercel.app",
                    "SERVER_PORT": "443",
                    "SERVER_PROTOCOL": "HTTP/1.1",
                    "wsgi.version": (1, 0),
                    "wsgi.url_scheme": "https",
                    "wsgi.input": BytesIO(body),
                    "wsgi.errors": sys.stderr,
                    "wsgi.multithread": False,
                    "wsgi.multiprocess": False,
                    "wsgi.run_once": False,
                    "CONTENT_LENGTH": str(len(body)),
                }
                if headers:
                    for k, v in headers.items():
                        header_key = "HTTP_" + k.upper().replace("-", "_")
                        env[header_key] = v

                response_status = None
                response_headers = None

                def start_response(status, res_headers, exc_info=None):
                    nonlocal response_status, response_headers
                    response_status = status
                    response_headers = res_headers

                res_body_chunks = app.wsgi_app(env, start_response)
                res_body = b"".join(res_body_chunks)
                status_code = int(response_status.split()[0])

                json_data = None
                try:
                    json_data = json.loads(res_body.decode("utf-8"))
                except Exception:
                    pass

                return status_code, response_headers, res_body, json_data

            # Test 2: Standard rewritten routes
            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=health")
            self.assertEqual(status, 200, f"Expected 200, got {status}: {body}")
            self.assertEqual(jdata.get("status"), "healthy")

            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=services")
            self.assertEqual(status, 200, f"Expected 200, got {status}: {body}")
            self.assertIsInstance(jdata, list)
            self.assertGreater(len(jdata), 0)

            # Test 3: Complex query parameters and __path sanitization
            status, _, body, jdata = make_wsgi_request(
                "GET", "/api/index.py", "cat=Marcenaria&sort=price_asc&__path=services"
            )
            self.assertEqual(status, 200, f"Expected 200, got {status}: {body}")
            self.assertIsInstance(jdata, list)
            for svc in jdata:
                self.assertEqual(svc["categoria"], "Marcenaria")

            status, _, body, jdata = make_wsgi_request(
                "GET", "/api/index.py", "min_price=100&max_price=300&__path=services"
            )
            self.assertEqual(status, 200, f"Expected 200, got {status}")

            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "cat=El%C3%A9trica&__path=services")
            self.assertEqual(status, 200, f"Expected 200, got {status}")
            self.assertTrue(all(s["categoria"] == "Elétrica" for s in jdata))

            # Test 4: Bare /api and /api/
            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=")
            self.assertEqual(status, 404, f"Expected 404 for bare /api, got {status}")
            self.assertTrue(jdata and "error" in jdata)

            # Test 5: Authentication & Security boundaries
            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=orders")
            self.assertEqual(status, 401, f"Expected 401, got {status}: {body}")

            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=profile")
            self.assertEqual(status, 401, f"Expected 401, got {status}: {body}")

            status, _, body, jdata = make_wsgi_request("POST", "/api/index.py", "__path=orders/999/pay")
            self.assertEqual(status, 403, f"Expected 403 without Origin/Referer, got {status}: {body}")

            status, _, body, jdata = make_wsgi_request(
                "POST",
                "/api/index.py",
                "__path=orders/999/pay",
                headers={"Origin": "https://test-marketplace.vercel.app"},
            )
            self.assertEqual(status, 401, f"Expected 401, got {status}: {body}")

            # Test 6: Adversarial / Malicious WSGI parameters
            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=/health")
            self.assertEqual(status, 200, f"Expected 200 for leading slash __path, got {status}: {body}")

            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=///services")
            self.assertEqual(status, 200, f"Expected 200 for triple slash __path, got {status}: {body}")

            status, _, body, jdata = make_wsgi_request(
                "GET", "/api/index.py", "", headers={"X-Matched-Path": "/api/health"}
            )
            self.assertEqual(status, 200, f"Expected 200 via X-Matched-Path, got {status}: {body}")

            status, _, body, jdata = make_wsgi_request("GET", "/health", "")
            self.assertEqual(status, 200, f"Expected 200 via unprefixed PATH_INFO, got {status}: {body}")

            status, _, body, jdata = make_wsgi_request("GET", "/api/index.py", "__path=doesnotexist12345")
            self.assertEqual(status, 404, f"Expected 404 for nonexistent subpath, got {status}: {body}")
        finally:
            database.DB_PATH = orig_db_path
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            try:
                if os.path.exists(wsgi_tmp_db):
                    os.remove(wsgi_tmp_db)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
