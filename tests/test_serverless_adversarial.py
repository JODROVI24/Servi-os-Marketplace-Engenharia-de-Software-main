#!/usr/bin/env python3
"""
Adversarial Stress Test Suite for Vercel Serverless Integration (api/index.py)
and Backend API Endpoints.

Tested by Challenger 2 (Adversarial API & Serverless Verifier).
"""

import os
import sys
import json
import ast
import tempfile
import unittest
import subprocess
from io import BytesIO
import urllib.parse

# Ensure root repository is in sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import api.index as vercel_api
from api.index import VercelPathNormalizerWSGI


def invoke_wsgi(app_callable, path_info, query_string='', method='GET', body=b'', headers=None):
    """Utility helper to execute raw WSGI requests against the wrapped application."""
    environ = {
        'REQUEST_METHOD': method,
        'SERVER_NAME': 'localhost',
        'SERVER_PORT': '80',
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': 'http',
        'wsgi.input': BytesIO(body),
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
        'PATH_INFO': path_info,
        'QUERY_STRING': query_string,
        'CONTENT_LENGTH': str(len(body)),
    }
    if headers:
        for k, v in headers.items():
            key = 'HTTP_' + k.upper().replace('-', '_')
            environ[key] = v
        if 'content-type' in [k.lower() for k in headers]:
            for k, v in headers.items():
                if k.lower() == 'content-type':
                    environ['CONTENT_TYPE'] = v

    response_status = None
    response_headers = []

    def start_response(status, hdrs):
        nonlocal response_status, response_headers
        response_status = status
        response_headers = hdrs

    result_iter = app_callable(environ, start_response)
    response_body = b''.join(result_iter)
    status_code = int(response_status.split(' ')[0]) if response_status else 500

    return status_code, response_status, response_headers, response_body, environ


class TestASTAndExports(unittest.TestCase):
    """Test AST compliance for Vercel's Python builder and runtime exports."""

    def test_01_ast_top_level_exports(self):
        index_py = os.path.join(REPO_ROOT, 'api', 'index.py')
        with open(index_py, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=index_py)

        top_level_assigns = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        top_level_assigns.add(target.id)

        for expected in ['app', 'application', 'handler']:
            self.assertIn(
                expected,
                top_level_assigns,
                f"Missing top-level AST assignment for '{expected}' required by @vercel/python-analysis."
            )

    def test_02_runtime_module_exports(self):
        self.assertTrue(hasattr(vercel_api, 'app'))
        self.assertTrue(hasattr(vercel_api, 'application'))
        self.assertTrue(hasattr(vercel_api, 'handler'))

        # Check identity
        self.assertIs(vercel_api.app, vercel_api.application)
        self.assertIs(vercel_api.app, vercel_api.handler)
        self.assertTrue(callable(vercel_api.app))

    def test_03_middleware_wrapping(self):
        self.assertIsInstance(
            vercel_api.app.wsgi_app,
            VercelPathNormalizerWSGI,
            "Flask wsgi_app must be wrapped with VercelPathNormalizerWSGI."
        )


class TestVercelPathNormalizerWSGIAdversarial(unittest.TestCase):
    """Adversarial stress-testing of VercelPathNormalizerWSGI."""

    def setUp(self):
        # Dummy WSGI app to capture environ transformations
        self.captured_environ = {}
        def dummy_app(environ, start_response):
            self.captured_environ = dict(environ)
            start_response('200 OK', [('Content-Type', 'text/plain')])
            return [b'OK']
        self.normalizer = VercelPathNormalizerWSGI(dummy_app)

    def _call_normalizer(self, path_info, query_string, extra_environ=None):
        environ = {
            'PATH_INFO': path_info,
            'QUERY_STRING': query_string,
        }
        if extra_environ:
            environ.update(extra_environ)
        
        status = None
        def start_resp(s, h):
            nonlocal status
            status = s
        self.normalizer(environ, start_resp)
        return self.captured_environ

    def test_01_query_string_empty_and_root_paths(self):
        cases = [
            ('__path=', '/api', ''),
            ('__path=/', '/api', ''),
            ('__path=///', '/api', ''),
            ('__path=////', '/api', ''),
            ('__path=&other=1', '/api', 'other=1'),
        ]
        for qs, expected_path, expected_qs in cases:
            env = self._call_normalizer('/api/index.py', qs)
            self.assertEqual(env['PATH_INFO'], expected_path, f"Failed for qs: {qs}")
            self.assertEqual(env['QUERY_STRING'], expected_qs, f"Failed for qs: {qs}")

    def test_02_diverse_query_strings_and_positions(self):
        # 1. __path at start
        env = self._call_normalizer('/api/index.py', '__path=services&cat=Marcenaria')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        self.assertEqual(env['QUERY_STRING'], 'cat=Marcenaria')

        # 2. __path at end
        env = self._call_normalizer('/api/index.py', 'cat=Marcenaria&__path=services')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        self.assertEqual(env['QUERY_STRING'], 'cat=Marcenaria')

        # 3. __path in middle
        env = self._call_normalizer('/api/index.py', 'a=1&__path=services&b=2')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        self.assertEqual(env['QUERY_STRING'], 'a=1&b=2')

        # 4. Multiple query parameters preserved
        env = self._call_normalizer('/api/index.py', '__path=services&cat=Marcenaria&preco_max=200&radius=25&disponivel=1')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        parsed_qs = urllib.parse.parse_qs(env['QUERY_STRING'])
        self.assertEqual(parsed_qs['cat'], ['Marcenaria'])
        self.assertEqual(parsed_qs['preco_max'], ['200'])
        self.assertEqual(parsed_qs['radius'], ['25'])
        self.assertEqual(parsed_qs['disponivel'], ['1'])
        self.assertNotIn('__path', parsed_qs)

        # 5. Repeated parameter keys
        env = self._call_normalizer('/api/index.py', '__path=services&tag=casa&tag=reforma')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        parsed_qs = urllib.parse.parse_qs(env['QUERY_STRING'])
        self.assertEqual(parsed_qs['tag'], ['casa', 'reforma'])

        # 6. Blank value parameters
        env = self._call_normalizer('/api/index.py', '__path=services&empty_param=&filled=yes')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        parsed_qs = urllib.parse.parse_qs(env['QUERY_STRING'], keep_blank_values=True)
        self.assertEqual(parsed_qs['empty_param'], [''])
        self.assertEqual(parsed_qs['filled'], ['yes'])

    def test_03_special_characters_and_portuguese_accents(self):
        # Portuguese accents in query parameters: Elétrica, São Paulo, Higienização
        encoded_accents = '__path=services&cat=El%C3%A9trica&cidade=S%C3%A3o%20Paulo&q=higieniza%C3%A7%C3%A3o'
        env = self._call_normalizer('/api/index.py', encoded_accents)
        self.assertEqual(env['PATH_INFO'], '/api/services')
        parsed_qs = urllib.parse.parse_qs(env['QUERY_STRING'])
        self.assertEqual(parsed_qs['cat'], ['Elétrica'])
        self.assertEqual(parsed_qs['cidade'], ['São Paulo'])
        self.assertEqual(parsed_qs['q'], ['higienização'])

        # Raw Unicode characters in query string
        raw_unicode = '__path=services&cat=Elétrica&cidade=São Paulo'
        env = self._call_normalizer('/api/index.py', raw_unicode)
        self.assertEqual(env['PATH_INFO'], '/api/services')
        parsed_qs = urllib.parse.parse_qs(env['QUERY_STRING'])
        self.assertEqual(parsed_qs['cat'], ['Elétrica'])
        self.assertEqual(parsed_qs['cidade'], ['São Paulo'])

        # Special symbols in query values: & + / %
        symbols_qs = '__path=services&simbolo=%2B&ampersand=%26&barra=%2F'
        env = self._call_normalizer('/api/index.py', symbols_qs)
        self.assertEqual(env['PATH_INFO'], '/api/services')
        parsed_qs = urllib.parse.parse_qs(env['QUERY_STRING'])
        self.assertEqual(parsed_qs['simbolo'], ['+'])
        self.assertEqual(parsed_qs['ampersand'], ['&'])
        self.assertEqual(parsed_qs['barra'], ['/'])

    def test_04_subpath_variations_and_nested_routes(self):
        cases = [
            ('__path=health', '/api/health'),
            ('__path=services', '/api/services'),
            ('__path=services/15', '/api/services/15'),
            ('__path=orders/10/pay', '/api/orders/10/pay'),
            ('__path=cep/01001000', '/api/cep/01001000'),
            ('__path=cep/01001-000', '/api/cep/01001-000'),
            ('__path=auth/login', '/api/auth/login'),
            ('__path=auth/register', '/api/auth/register'),
        ]
        for qs, expected in cases:
            env = self._call_normalizer('/api/index.py', qs)
            self.assertEqual(env['PATH_INFO'], expected)

    def test_05_path_traversal_and_malicious_inputs(self):
        # Path traversals in __path
        env = self._call_normalizer('/api/index.py', '__path=../../etc/passwd')
        self.assertEqual(env['PATH_INFO'], '/api/../../etc/passwd')

        env = self._call_normalizer('/api/index.py', '__path=services/../../../etc/shadow')
        self.assertEqual(env['PATH_INFO'], '/api/services/../../../etc/shadow')

        # Percent-encoded path traversal
        env = self._call_normalizer('/api/index.py', '__path=..%2F..%2Fetc%2Fpasswd')
        self.assertEqual(env['PATH_INFO'], '/api/../../etc/passwd')

        # Query string with deceptive param names
        env = self._call_normalizer('/api/index.py', 'not__path=foo&__path=services')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        self.assertIn('not__path=foo', env['QUERY_STRING'])

        # Duplicate __path parameters takes first value safely
        env = self._call_normalizer('/api/index.py', '__path=services&__path=orders')
        self.assertEqual(env['PATH_INFO'], '/api/services')
        self.assertNotIn('__path', env['QUERY_STRING'])

        # Malformed query strings should not crash the normalizer
        env = self._call_normalizer('/api/index.py', '&&&===&&&')
        self.assertEqual(env['PATH_INFO'], '/api/index.py')

        env = self._call_normalizer('/api/index.py', '__path')
        self.assertEqual(env['PATH_INFO'], '/api/index.py')

        # Extremely large query string (stress test 20,000 chars)
        large_qs = '__path=services&payload=' + ('x' * 20000)
        env = self._call_normalizer('/api/index.py', large_qs)
        self.assertEqual(env['PATH_INFO'], '/api/services')
        self.assertEqual(len(env['QUERY_STRING']), len('payload=') + 20000)

    def test_06_fallback_case2_matched_path(self):
        # When __path is absent, inspect HTTP_X_MATCHED_PATH / HTTP_X_VERCEL_ORIGINAL_PATH / REQUEST_URI / RAW_URI
        headers_cases = [
            ({'HTTP_X_MATCHED_PATH': '/api/health'}, '/api/health'),
            ({'HTTP_X_MATCHED_PATH': '/health'}, '/api/health'),
            ({'HTTP_X_VERCEL_ORIGINAL_PATH': '/api/services?cat=Marcenaria'}, '/api/services'),
            ({'REQUEST_URI': '/api/orders/5'}, '/api/orders/5'),
            ({'RAW_URI': '/api/profile'}, '/api/profile'),
            ({'RAW_URI': '/profile'}, '/api/profile'),
        ]
        for extra, expected in headers_cases:
            env = self._call_normalizer('/api/index.py', '', extra_environ=extra)
            self.assertEqual(env['PATH_INFO'], expected, f"Failed for header {extra}")

    def test_07_fallback_case3_stripped_api_prefix(self):
        # When Vercel strips /api when forwarding to lambda
        known_routes = [
            ('/health', '/api/health'),
            ('/services', '/api/services'),
            ('/services/42', '/api/services/42'),
            ('/my-services', '/api/my-services'),
            ('/orders', '/api/orders'),
            ('/reviews', '/api/reviews'),
            ('/profile', '/api/profile'),
            ('/cep/01001000', '/api/cep/01001000'),
            ('/geocode', '/api/geocode'),
            ('/auth/login', '/api/auth/login'),
        ]
        for stripped_path, expected in known_routes:
            env = self._call_normalizer(stripped_path, '')
            self.assertEqual(env['PATH_INFO'], expected, f"Failed for stripped path {stripped_path}")

        # Unrecognized route without /api prefix remains untouched for safe 404
        env = self._call_normalizer('/unknown_route', '')
        self.assertEqual(env['PATH_INFO'], '/unknown_route')


class TestBackendAPIEndpointsAdversarial(unittest.TestCase):
    """Adversarial testing of backend endpoints dispatched through api.index.app."""

    @classmethod
    def setUpClass(cls):
        # Ensure temporary test DB
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix='.db')
        os.close(cls.db_fd)
        os.environ['MARKETPLACE_DB'] = cls.db_path
        import database
        database.DB_PATH = cls.db_path
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(cls.db_path):
                os.remove(cls.db_path)
        except OSError:
            pass

    def test_01_health_endpoint_via_rewrite(self):
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=health'
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode('utf-8'))
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')
        self.assertEqual(data.get('version'), '2.0.0')

    def test_02_services_endpoint_all_categories(self):
        categories = [
            'Marcenaria',
            'Elétrica',
            'Pintura',
            'Limpeza',
            'Jardinagem',
            'Encanamento',
            'Tecnologia'
        ]
        for cat in categories:
            encoded_cat = urllib.parse.quote(cat)
            status, _, _, body, _ = invoke_wsgi(
                vercel_api.app,
                path_info='/api/index.py',
                query_string=f'__path=services&cat={encoded_cat}'
            )
            self.assertEqual(status, 200, f"Failed to list services for category: {cat}")
            services = json.loads(body.decode('utf-8'))
            self.assertIsInstance(services, list)
            for s in services:
                self.assertEqual(s['categoria'], cat)

    def test_03_services_endpoint_adversarial_queries(self):
        # Query with non-existent category -> 200 with empty list
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=services&cat=NonExistentCategoryXYZ'
        )
        self.assertEqual(status, 200)
        services = json.loads(body.decode('utf-8'))
        self.assertEqual(services, [])

        # Non-matching text query -> 200 with empty list
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=services&query=NonExistentQueryXYZ12345'
        )
        self.assertEqual(status, 200)
        services = json.loads(body.decode('utf-8'))
        self.assertEqual(services, [])

        # SQL Injection attempt in category parameter
        sqli_cat = urllib.parse.quote("' OR '1'='1")
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string=f'__path=services&cat={sqli_cat}'
        )
        self.assertEqual(status, 200)
        # Parameterized queries must prevent SQL injection; returns empty list
        services = json.loads(body.decode('utf-8'))
        self.assertIsInstance(services, list)

    def test_04_unauthenticated_endpoints_return_401(self):
        # /api/auth/me specifically returns 200 with authenticated: false by design
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=auth/me'
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode('utf-8'))
        self.assertFalse(data.get('authenticated'))

        unauth_routes = [
            ('GET', '__path=my-services', b''),
            ('GET', '__path=profile', b''),
            ('GET', '__path=orders', b''),
            ('POST', '__path=orders', json.dumps({'servico_id': 1}).encode('utf-8')),
            ('POST', '__path=services', json.dumps({'titulo': 'Teste'}).encode('utf-8')),
            ('PUT', '__path=services/1', json.dumps({'titulo': 'Teste'}).encode('utf-8')),
            ('DELETE', '__path=services/1', b''),
        ]
        for method, qs, body in unauth_routes:
            status, _, _, resp_body, _ = invoke_wsgi(
                vercel_api.app,
                path_info='/api/index.py',
                query_string=qs,
                method=method,
                body=body,
                headers={'Content-Type': 'application/json'}
            )
            self.assertIn(
                status,
                [401, 403],
                f"Expected 401 or 403 for unauthenticated {method} with {qs}, got {status}: {resp_body}"
            )

    def test_05_auth_login_invalid_credentials_returns_401(self):
        payload = json.dumps({'email': 'invalid@user.com', 'senha': 'wrongpassword'}).encode('utf-8')
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=auth/login',
            method='POST',
            body=payload,
            headers={'Content-Type': 'application/json'}
        )
        self.assertEqual(status, 401)
        data = json.loads(body.decode('utf-8'))
        self.assertIn('error', data)

    def test_06_auth_register_validation_errors(self):
        # Empty payload
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=auth/register',
            method='POST',
            body=b'{}',
            headers={'Content-Type': 'application/json'}
        )
        self.assertIn(status, [400, 422])

        # Missing required fields
        incomplete = json.dumps({'nome': 'Test'}).encode('utf-8')
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=auth/register',
            method='POST',
            body=incomplete,
            headers={'Content-Type': 'application/json'}
        )
        self.assertIn(status, [400, 422])

    def test_07_bare_api_and_nonexistent_routes_return_404(self):
        # Bare /api
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path='
        )
        self.assertEqual(status, 404)
        data = json.loads(body.decode('utf-8'))
        self.assertEqual(data.get('error'), 'Endpoint da API não encontrado.')

        # Random nonexistent API route
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=nonexistent_xyz_987'
        )
        self.assertEqual(status, 404)
        data = json.loads(body.decode('utf-8'))
        self.assertEqual(data.get('error'), 'Endpoint da API não encontrado.')

    def test_08_path_traversal_returns_404_not_500(self):
        traversals = [
            '__path=../../etc/passwd',
            '__path=services/../../../etc/shadow',
            '__path=..%2F..%2Fetc%2Fpasswd',
        ]
        for qs in traversals:
            status, _, _, body, _ = invoke_wsgi(
                vercel_api.app,
                path_info='/api/index.py',
                query_string=qs
            )
            # Must safely return 404 or 400, NEVER 500 or 200 with file contents
            self.assertIn(status, [400, 404], f"Unexpected status {status} for traversal {qs}")

    def test_09_full_session_flow_through_normalizer(self):
        # 1. Login with seeded provider Carlos
        login_payload = json.dumps({'email': 'carlos@pertoja.com', 'senha': '123456'}).encode('utf-8')
        status, _, headers, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=auth/login',
            method='POST',
            body=login_payload,
            headers={'Content-Type': 'application/json'}
        )
        self.assertEqual(status, 200, f"Login failed: {body}")
        cookie_header = None
        for k, v in headers:
            if k.lower() == 'set-cookie':
                cookie_header = v.split(';')[0]
                break
        self.assertIsNotNone(cookie_header, "No Set-Cookie header received upon login.")

        auth_headers = {'Cookie': cookie_header, 'Content-Type': 'application/json'}

        # 2. Check /api/auth/me with session
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=auth/me',
            headers=auth_headers
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode('utf-8'))
        self.assertEqual(data['user']['email'], 'carlos@pertoja.com')
        self.assertEqual(data['user']['tipo'], 'prestador')

        # 3. Check /api/my-services
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=my-services',
            headers=auth_headers
        )
        self.assertEqual(status, 200)
        my_services = json.loads(body.decode('utf-8'))
        self.assertIsInstance(my_services, list)
        self.assertGreater(len(my_services), 0)

        # 4. Check /api/profile
        status, _, _, body, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=profile',
            headers=auth_headers
        )
        self.assertEqual(status, 200)

        # 5. Logout
        status, _, _, _, _ = invoke_wsgi(
            vercel_api.app,
            path_info='/api/index.py',
            query_string='__path=auth/logout',
            method='POST',
            headers=auth_headers
        )
        self.assertEqual(status, 200)


class TestServerlessColdStartSimulation(unittest.TestCase):
    """Simulate serverless cold-start in isolated subprocesses."""

    def test_01_cold_start_vercel_env_flag(self):
        script = """
import os, sys, json
os.environ['VERCEL'] = '1'
import api.index as vercel_api
from database import DB_PATH, get_db_connection

assert os.environ.get('VERCEL') == '1'
assert DB_PATH == '/tmp/marketplace.db', f'Expected /tmp/marketplace.db, got {DB_PATH}'
assert os.path.exists('/tmp/marketplace.db'), 'DB not created in /tmp'

conn = get_db_connection()
user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
service_count = conn.execute('SELECT COUNT(*) FROM services').fetchone()[0]
conn.close()

assert user_count > 0
assert service_count > 0

# Test WSGI invocation
from io import BytesIO
environ = {
    'REQUEST_METHOD': 'GET',
    'SERVER_NAME': 'localhost',
    'SERVER_PORT': '80',
    'wsgi.version': (1, 0),
    'wsgi.url_scheme': 'http',
    'wsgi.input': BytesIO(b''),
    'wsgi.errors': sys.stderr,
    'wsgi.multithread': False,
    'wsgi.multiprocess': False,
    'wsgi.run_once': False,
    'PATH_INFO': '/api/index.py',
    'QUERY_STRING': '__path=health',
}
status = None
def start_resp(s, h):
    global status
    status = s

body = b''.join(vercel_api.app(environ, start_resp))
assert status == '200 OK', f'Expected 200 OK, got {status}'
data = json.loads(body.decode('utf-8'))
assert data['environment'] == 'vercel', f"Expected environment == vercel, got {data.get('environment')}"
print('COLD_START_VERCEL_SUCCESS')
"""
        clean_env = os.environ.copy()
        clean_env.pop('MARKETPLACE_DB', None)
        clean_env['VERCEL'] = '1'
        res = subprocess.run(
            [sys.executable, '-c', script],
            cwd=REPO_ROOT,
            env=clean_env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"Cold start subprocess failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        self.assertIn('COLD_START_VERCEL_SUCCESS', res.stdout)

    def test_02_cold_start_aws_lambda_flag(self):
        script = """
import os, sys
os.environ.pop('VERCEL', None)
os.environ['AWS_LAMBDA_FUNCTION_NAME'] = 'test_vercel_lambda'
import api.index as vercel_api
from database import DB_PATH

assert os.environ.get('VERCEL') == '1', 'VERCEL flag should have been auto-set by AWS_LAMBDA_FUNCTION_NAME'
assert DB_PATH == '/tmp/marketplace.db'
print('COLD_START_AWS_LAMBDA_SUCCESS')
"""
        clean_env = os.environ.copy()
        clean_env.pop('MARKETPLACE_DB', None)
        clean_env.pop('VERCEL', None)
        clean_env['AWS_LAMBDA_FUNCTION_NAME'] = 'test_vercel_lambda'
        res = subprocess.run(
            [sys.executable, '-c', script],
            cwd=REPO_ROOT,
            env=clean_env,
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"AWS Lambda cold start failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        self.assertIn('COLD_START_AWS_LAMBDA_SUCCESS', res.stdout)

    def test_03_empirical_vulnerability_reproduction_fallback_import_error(self):
        """
        Adversarial challenge:
        Demonstrate that lines 85-99 in api/index.py have a Python closure scoping bug
        (NameError: cannot access free variable 'exc') when handling an import error.
        """
        script = """
import os, sys
import api.index as mod
mod.marketplace_dir = '/nonexistent/path/for/failure/test'
err_app = mod._init_marketplace_app()

from io import BytesIO
environ = {
    'REQUEST_METHOD': 'GET',
    'SERVER_NAME': 'localhost',
    'SERVER_PORT': '80',
    'wsgi.version': (1, 0),
    'wsgi.url_scheme': 'http',
    'wsgi.input': BytesIO(b''),
    'wsgi.errors': sys.stderr,
    'wsgi.multithread': False,
    'wsgi.multiprocess': False,
    'wsgi.run_once': False,
    'PATH_INFO': '/api/health',
    'QUERY_STRING': '',
}
status = None
def start_resp(s, h):
    global status
    status = s

try:
    resp = list(err_app(environ, start_resp))
    # If it raised 500 with NameError:
    print('RESPONSE_STATUS:', status)
except NameError as ne:
    print('CONFIRMED_NAME_ERROR:', ne)
"""
        clean_env = os.environ.copy()
        clean_env.pop('MARKETPLACE_DB', None)
        res = subprocess.run(
            [sys.executable, '-c', script],
            cwd=REPO_ROOT,
            env=clean_env,
            capture_output=True,
            text=True
        )
        # Verify that the bug manifests (either as a 500 error or NameError)
        output = res.stdout + res.stderr
        self.assertIn('NameError', output, "Scoping vulnerability in _init_marketplace_app should trigger NameError on exc")
        self.assertIn("cannot access free variable 'exc'", output)



if __name__ == '__main__':
    unittest.main(verbosity=2)
