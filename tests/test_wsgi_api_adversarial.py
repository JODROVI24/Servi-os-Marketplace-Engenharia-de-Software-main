#!/usr/bin/env python3
"""
Adversarial WSGI & Serverless API Test Suite
Challenger 1 - Empirical verification of VercelPathNormalizerWSGI and Flask API
"""
import os
import sys
import json
from io import BytesIO

# Ensure repo root and submodules are in sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Set VERCEL=1 to simulate Vercel Serverless environment
os.environ['VERCEL'] = '1'

from api.index import app, application, handler, VercelPathNormalizerWSGI

print("=" * 64)
print("CHALLENGER 1: ADVERSARIAL PYTHON WSGI API TEST SUITE")
print("=" * 64)

# Test 1: Verify AST top-level exports
print("\n[Test 1] Verifying top-level exports for @vercel/python AST parser...")
assert app is not None, "FAIL: 'app' is None"
assert application is app, "FAIL: 'application' does not match 'app'"
assert handler is app, "FAIL: 'handler' does not match 'app'"
assert isinstance(app.wsgi_app, VercelPathNormalizerWSGI), "FAIL: wsgi_app is not wrapped in VercelPathNormalizerWSGI"
print("  PASS: Top-level exports verified (app, application, handler all exist and point to WSGI app).")

def make_wsgi_request(method='GET', path_info='/api/index.py', query_string='', headers=None, body=b''):
    """Executes a direct raw WSGI call to app.wsgi_app mimicking Vercel gateway"""
    env = {
        'REQUEST_METHOD': method,
        'SCRIPT_NAME': '',
        'PATH_INFO': path_info,
        'QUERY_STRING': query_string,
        'SERVER_NAME': 'test-marketplace.vercel.app',
        'SERVER_PORT': '443',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': 'https',
        'wsgi.input': BytesIO(body),
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
        'CONTENT_LENGTH': str(len(body)),
    }
    if headers:
        for k, v in headers.items():
            header_key = 'HTTP_' + k.upper().replace('-', '_')
            env[header_key] = v

    response_status = None
    response_headers = None

    def start_response(status, res_headers, exc_info=None):
        nonlocal response_status, response_headers
        response_status = status
        response_headers = res_headers

    res_body_chunks = app.wsgi_app(env, start_response)
    res_body = b''.join(res_body_chunks)
    status_code = int(response_status.split()[0])
    
    # Try parsing JSON
    json_data = None
    try:
        json_data = json.loads(res_body.decode('utf-8'))
    except Exception:
        pass

    return status_code, response_headers, res_body, json_data

# Test 2: Standard rewritten routes
print("\n[Test 2] Testing standard rewritten routes (mimicking Vercel rewrites)...")

# 2a: Healthcheck
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=health')
assert status == 200, f"Expected 200, got {status}: {body}"
assert jdata.get('status') == 'healthy', f"Expected status healthy, got {jdata}"
print(f"  PASS: /api/health returned 200 OK (status={jdata.get('status')}, db={jdata.get('database')})")

# 2b: Services list
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=services')
assert status == 200, f"Expected 200, got {status}: {body}"
assert isinstance(jdata, list), f"Expected list of services, got {type(jdata)}"
assert len(jdata) > 0, "Expected at least 1 service"
print(f"  PASS: /api/services returned 200 OK ({len(jdata)} services returned)")

# Test 3: Complex query parameters and sanitation
print("\n[Test 3] Testing complex query parameters and __path sanitization...")

# 3a: Query with filtering
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', 'cat=Marcenaria&sort=price_asc&__path=services')
assert status == 200, f"Expected 200, got {status}: {body}"
assert isinstance(jdata, list), "Expected list of services"
for svc in jdata:
    assert svc['categoria'] == 'Marcenaria', f"Expected Marcenaria, got {svc['categoria']}"
print(f"  PASS: /api/services?cat=Marcenaria&sort=price_asc returned {len(jdata)} Marcenaria services (sorted).")

# 3b: Query with price range
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', 'min_price=100&max_price=300&__path=services')
assert status == 200, f"Expected 200, got {status}"
print(f"  PASS: /api/services with price range filtering returned {len(jdata)} services.")

# 3c: Special characters and encoded UTF-8 in query string
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', 'cat=El%C3%A9trica&__path=services')
assert status == 200, f"Expected 200, got {status}"
assert all(s['categoria'] == 'Elétrica' for s in jdata), "Expected Elétrica category"
print(f"  PASS: /api/services?cat=El%C3%A9trica properly decoded UTF-8 query param ({len(jdata)} services).")

# Test 4: Bare /api and /api/
print("\n[Test 4] Testing bare /api and /api/ rewrites...")

# 4a: Bare /api with __path=
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=')
assert status == 404, f"Expected 404 for bare /api, got {status}"
assert jdata and 'error' in jdata, f"Expected JSON error for bare /api, got {jdata}"
print(f"  PASS: Bare /api returned expected 404 JSON response: {jdata}")

# Test 5: Authentication & Security boundaries
print("\n[Test 5] Testing protected routes security enforcement...")

# 5a: Unauthenticated orders
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=orders')
assert status == 401, f"Expected 401, got {status}: {body}"
print(f"  PASS: Unauthenticated GET /api/orders returned 401 Unauthorized: {jdata}")

# 5b: Unauthenticated profile
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=profile')
assert status == 401, f"Expected 401, got {status}: {body}"
print(f"  PASS: Unauthenticated GET /api/profile returned 401 Unauthorized: {jdata}")

# 5c: Dynamic nested route orders pay
status, _, body, jdata = make_wsgi_request('POST', '/api/index.py', '__path=orders/999/pay')
assert status == 401, f"Expected 401, got {status}: {body}"
print(f"  PASS: Unauthenticated POST /api/orders/999/pay returned 401 Unauthorized: {jdata}")

# Test 6: Adversarial / Malicious WSGI parameters
print("\n[Test 6] Adversarial parameter stress testing...")

# 6a: Leading slashes in __path: __path=/health
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=/health')
assert status == 200, f"Expected 200 for leading slash __path, got {status}: {body}"
print("  PASS: Leading slash (__path=/health) stripped and resolved to /api/health (200 OK)")

# 6b: Multiple slashes in __path: __path=///services
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=///services')
assert status == 200, f"Expected 200 for triple slash __path, got {status}: {body}"
print("  PASS: Multiple slashes (__path=///services) handled cleanly (200 OK)")

# 6c: Direct PATH_INFO fallback mechanism 2 (HTTP_X_MATCHED_PATH)
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '', headers={'X-Matched-Path': '/api/health'})
assert status == 200, f"Expected 200 via X-Matched-Path, got {status}: {body}"
print("  PASS: Fallback via HTTP_X_MATCHED_PATH succeeded (200 OK)")

# 6d: Direct PATH_INFO fallback mechanism 3 (unprefixed path)
status, _, body, jdata = make_wsgi_request('GET', '/health', '')
assert status == 200, f"Expected 200 via unprefixed PATH_INFO, got {status}: {body}"
print("  PASS: Fallback via unprefixed PATH_INFO /health succeeded (200 OK)")

# 6e: Nonexistent API subpath
status, _, body, jdata = make_wsgi_request('GET', '/api/index.py', '__path=doesnotexist12345')
assert status == 404, f"Expected 404 for nonexistent subpath, got {status}: {body}"
print(f"  PASS: Nonexistent API subpath returned clean 404 JSON: {jdata}")

print("\n" + "=" * 64)
print("ALL ADVERSARIAL WSGI API TESTS PASSED SUCCESSFULLY!")
print("=" * 64)
