import os
import sys
import re
import json
import math
import secrets
import hashlib
import hmac
import requests
import openai
import gzip
import time
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse
from flask import Flask, request, jsonify, session, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import database
from database import (
    get_db_connection, init_db, get_cached_geocode, save_cached_geocode,
    DBIntegrityError, get_active_engine
)
from payment_adapters import (
    get_payment_adapter,
    list_gateway_configs,
    is_sandbox_enabled,
    PaymentGatewayError,
    GatewayNotConfiguredError,
    WebhookSignatureError,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'public')

ALLOWED_STATIC_EXTENSIONS = {
    '.html', '.css', '.js', '.webp', '.jpg', '.png', '.svg', '.ico', '.woff2', '.woff'
}

CATEGORIAS_PERMITIDAS = (
    'Limpeza', 'Elétrica', 'Encanamento', 'Marcenaria', 'Pintura', 'Jardinagem', 'Tecnologia'
)
CATEGORIAS_TECNICAS = ('Elétrica', 'Encanamento')
PROF_REG_REGEX = re.compile(r'^(CREA|CFT|CRT|NR-10|CAU)[A-Z0-9\-\/ ]{2,30}$', re.IGNORECASE)


def _parse_dt(val):
    """Converte string ISO/SQL ou datetime para datetime naive UTC."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(val).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _log_escrow_ledger(conn, order_id, tipo_evento, valor, status_escrow, observacao=''):
    """Registra movimentação imutável no razão de Escrow (ET-08)."""
    conn.execute('''
        INSERT INTO escrow_ledger (order_id, tipo_evento, valor, status_escrow, observacao)
        VALUES (?, ?, ?, ?, ?)
    ''', (order_id, tipo_evento, float(valor or 0.0), status_escrow, observacao))


def _is_review_revealed(rev_row):
    """Verifica se uma avaliação já foi revelada via double-blind (avaliação mútua ou 7 dias)."""
    if not rev_row:
        return False
    if _row_get(rev_row, 'revealed_at') is not None:
        return True
    dt = _parse_dt(_row_get(rev_row, 'criado_em'))
    return bool(dt is not None and (datetime.utcnow() - dt) >= timedelta(days=7))


def _mask_phone(phone):
    if not phone:
        return ''
    s = str(phone)
    return (s[:-4] + '****') if len(s) >= 4 else '****'


def _load_dotenv():
    """Carrega variáveis de arquivos .env locais sem expor credenciais no código."""
    env_path = os.path.join(BASE_DIR, '.env')
    if os.path.isfile(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val


_load_dotenv()

def _resolve_secret_key():
    env_key = os.environ.get('SECRET_KEY')
    if env_key and env_key.strip():
        return env_key.strip()
    if os.environ.get('REQUIRE_SECRET_KEY') == '1':
        raise RuntimeError('SECRET_KEY é obrigatória quando REQUIRE_SECRET_KEY=1.')
    db_url = (
        os.environ.get('POSTGRES_URL')
        or os.environ.get('DATABASE_URL')
        or os.environ.get('POSTGRES_URL_NON_POOLING')
    )
    if db_url and db_url.strip():
        return hmac.new(db_url.strip().encode('utf-8'), b'pertoja-session-key-v1', hashlib.sha256).hexdigest()
    if os.environ.get('VERCEL') == '1' or os.environ.get('FLASK_ENV') == 'production':
        return secrets.token_hex(32)
    return 'pertoja-dev-local-secret-key-2026'


app = Flask(__name__, static_folder=STATIC_DIR)
app.secret_key = _resolve_secret_key()
app.config.update(
    TESTING=False,
    MAX_CONTENT_LENGTH=1024 * 1024,
    PERMANENT_SESSION_LIFETIME=43200,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=(os.environ.get('VERCEL') == '1' or os.environ.get('HTTPS') == '1')
)

# ================= Otimização de Performance, Caching e Segurança =================


@app.before_request
def _csrf_origin_check():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if request.path == '/api/webhooks/payments' or request.path.startswith('/api/webhooks/payments/'):
            return None
        origin = request.headers.get('Origin')
        referer = request.headers.get('Referer')
        host = (urlparse(f'//{request.host}').hostname or '').lower() if request.host else ''
        for hdr in (origin, referer):
            if hdr is not None:
                parsed = urlparse(hdr)
                hdr_host = (parsed.hostname or '').lower()
                if not hdr_host or (host and hdr_host != host):
                    return jsonify({'error': 'Origem da requisição não autorizada.'}), 403


@app.after_request
def add_performance_and_security_headers(response):
    # Cabeçalhos de Segurança HTTP (OWASP / WCAG)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(self)'
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://www.mercadopago.com https://sdk.mercadopago.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com https://cdn.tailwindcss.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https: blob:; "
        "connect-src 'self' https://viacep.com.br https://brasilapi.com.br https://nominatim.openstreetmap.org https://*.tile.openstreetmap.org https://api.mercadopago.com https://www.mercadopago.com; "
        "base-uri 'self'; frame-ancestors 'self'; object-src 'none'; form-action 'self'"
    )

    # Políticas de Cache HTTP (Core Web Vitals)
    path = request.path
    if any(path.endswith(ext) for ext in ('.css', '.js', '.webp', '.jpg', '.png', '.svg', '.ico', '.woff2', '.woff')):
        response.headers['Cache-Control'] = 'public, max-age=604800, stale-while-revalidate=86400'
    elif path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    elif any(seg in path for seg in ('/portal-cliente', '/portal-prestador', '/login', '/cadastro')):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    else:
        response.headers['Cache-Control'] = 'private, no-cache, must-revalidate'

    # Compressão Gzip automática (somente fora da Vercel, pois o Edge da Vercel já comprime nativamente)
    is_vercel = os.environ.get('VERCEL') == '1' or 'AWS_LAMBDA_FUNCTION_NAME' in os.environ
    accept_encoding = request.headers.get('Accept-Encoding', '')
    if (
        not is_vercel
        and 'gzip' in accept_encoding
        and response.status_code < 300
        and not response.headers.get('Content-Encoding')
        and response.mimetype in (
            'text/html', 'text/css', 'text/javascript',
            'application/javascript', 'application/json', 'image/svg+xml'
        )
    ):
        response_data = response.get_data()
        if len(response_data) > 500:
            compressed_data = gzip.compress(response_data, compresslevel=6)
            response.set_data(compressed_data)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = len(compressed_data)
            response.headers['Vary'] = 'Accept-Encoding'

    return response


# Garantir inicialização do banco de dados na inicialização
init_db()

# ================= Rate Limiter Persistente em Banco (Janela Deslizante) =================
# Nota de arquitetura serverless: Em produção na nuvem (Vercel/Lambda), recomenda-se
# complementar este rate limiter em banco (tabela rate_limit) com um WAF/proxy de borda
# (como Cloudflare ou Akamai) para mitigar picos antes mesmo da invocação da função.


def _get_client_ip():
    vercel_ip = (request.headers.get('x-vercel-forwarded-for') or '').strip()
    if vercel_ip:
        return vercel_ip.split(',')[-1].strip()
    real_ip = (request.headers.get('x-real-ip') or '').strip()
    if real_ip:
        return real_ip
    xff = (request.headers.get('x-forwarded-for') or '').strip()
    if xff:
        return xff.split(',')[-1].strip()
    return request.remote_addr or '127.0.0.1'


def _check_email_rate_limit(endpoint_name, email, limit=10, window_seconds=60):
    if app.config.get('TESTING') or not email:
        return None
    email_hash = _hash_ip(email.strip().lower())
    key = f"{endpoint_name}:email:{email_hash}"
    if not rate_limiter.is_allowed(key, limit, window_seconds):
        resp = make_response(jsonify({
            'error': 'Muitas requisições para este e-mail. Por favor, aguarde alguns instantes.',
            'retry_after_seconds': window_seconds
        }), 429)
        resp.headers['Retry-After'] = str(window_seconds)
        return resp
    return None


def _hash_ip(ip):
    secret = str(app.secret_key or 'pertoja-dev-local-secret-key-2026').encode('utf-8')
    return hmac.new(secret, str(ip or '').encode('utf-8'), hashlib.sha256).hexdigest()[:32]


class DatabaseRateLimiter:
    """Limitador de requisições por janela deslizante persistido na tabela rate_limit (SQLite e PostgreSQL)."""

    def is_allowed(self, key, limit, window_seconds):
        now = time.time()
        cutoff = now - window_seconds
        purge_cutoff = now - 86400
        conn = get_db_connection()
        try:
            conn.execute('DELETE FROM rate_limit WHERE ts <= ?', (purge_cutoff,))
            conn.execute('DELETE FROM rate_limit WHERE rate_key = ? AND ts <= ?', (key, cutoff))
            row = conn.execute('SELECT COUNT(*) FROM rate_limit WHERE rate_key = ?', (key,)).fetchone()
            count = row[0] if row is not None else 0
            if count >= limit:
                conn.commit()
                return False
            conn.execute('INSERT INTO rate_limit (rate_key, ts) VALUES (?, ?)', (key, now))
            conn.commit()
            return True
        finally:
            conn.close()

    def reset(self):
        conn = get_db_connection()
        try:
            conn.execute('DELETE FROM rate_limit')
            conn.commit()
        finally:
            conn.close()


rate_limiter = DatabaseRateLimiter()


def rate_limit(limit, window_seconds=60):
    """Decorator de rate limit por IP (hash HMAC-SHA256) para proteção contra brute-force e abusos de API."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if app.config.get('TESTING'):
                return f(*args, **kwargs)
            ip_hash = _hash_ip(_get_client_ip())
            key = f"{request.endpoint or f.__name__}:{ip_hash}"
            if not rate_limiter.is_allowed(key, limit, window_seconds):
                resp = make_response(jsonify({
                    'error': 'Muitas requisições. Por favor, aguarde alguns instantes antes de tentar novamente.',
                    'retry_after_seconds': window_seconds
                }), 429)
                resp.headers['Retry-After'] = str(window_seconds)
                return resp
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def _row_get(row, key, default=None):
    """Acesso seguro a colunas em sqlite3.Row, HybridRow ou dict."""
    if row is None:
        return default
    if hasattr(row, 'get'):
        val = row.get(key, default)
        return val if val is not None else default
    try:
        if key in row.keys():
            val = row[key]
            return val if val is not None else default
    except Exception:
        pass
    return default


def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    finally:
        conn.close()
    if not user:
        session.clear()
        return None
    status_conta = _row_get(user, 'status_conta', 'ativo')
    if status_conta in ('bloqueado', 'anonimizado'):
        session.clear()
        return None
    db_sv = int(_row_get(user, 'session_version', 1) or 1)
    sess_sv = session.get('session_version')
    try:
        sess_sv_int = int(sess_sv) if sess_sv is not None else 1
    except (ValueError, TypeError):
        session.clear()
        return None
    if sess_sv_int != db_sv:
        session.clear()
        return None
    return user


def _require_active_account(user):
    status_conta = _row_get(user, 'status_conta', 'ativo')
    if status_conta != 'ativo':
        return jsonify({
            'error': 'Sua conta está temporariamente suspensa ou restrita. Envie um recurso em /api/account/appeal.'
        }), 403
    return None


def parse_positive_price(val, max_val=1000000.0):
    if isinstance(val, bool) or val is None or val == '':
        return None
    try:
        num = float(val)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(num) or num <= 0 or num > max_val:
        return None
    return round(num, 2)


# Helper de cálculo de distância euclidiana/haversine simplificada em km
def safe_coord(val, default=-23.5653, min_val=-90.0, max_val=90.0):
    if isinstance(val, bool) or val is None or val == '':
        return default
    try:
        f = float(val)
        if not math.isfinite(f) or f < min_val or f > max_val:
            return default
        return f
    except (ValueError, TypeError):
        return default


def calcular_distancia(lat1, lng1, lat2, lng2):
    try:
        if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
            return 0.0
        lat1, lng1, lat2, lng2 = float(lat1), float(lng1), float(lat2), float(lng2)
        d_lat = (lat2 - lat1) * 111.0
        d_lng = (lng2 - lng1) * (111.0 * math.cos(math.radians(lat1)))
        return math.sqrt(d_lat**2 + d_lng**2)
    except (ValueError, TypeError):
        return 0.0


# Helper para geocodificação de endereços no OpenStreetMap Nominatim com resolução multinível e cache
def geocode_address(address_str, street=None, neighborhood=None, city=None, state=None, fallback=None, precise_only=False):
    """
    Geocodifica endereço no OpenStreetMap Nominatim com tentativas progressivas e cache em banco.
    Candidatos PRECISOS (nível de rua) são tentados primeiro; candidatos APROXIMADOS
    (bairro/cidade) só são usados se precise_only=False e nunca são gravados no cache
    do endereço completo (evita fixar o ponto no centro da cidade).
    """
    cache_query = address_str.strip() if address_str and address_str.strip() else f"{street or ''}, {neighborhood or ''}, {city or ''} - {state or ''}".strip(' ,-')
    if cache_query:
        cached = get_cached_geocode(cache_query)
        if cached:
            return cached

    candidates = []  # lista de (texto, preciso)

    def add(text, precise):
        text = (text or '').strip(' ,-')
        if text and all(text != c[0] for c in candidates):
            candidates.append((text, precise))

    if address_str and address_str.strip():
        raw = address_str.strip()
        add(raw, True)
        raw_no_num = re.sub(r'\s+\d+\b', '', raw)
        if raw_no_num != raw:
            add(raw_no_num, True)

    if street and city:
        if neighborhood:
            add(f"{street}, {neighborhood}, {city} - {state or ''}, Brasil", True)
        add(f"{street}, {city} - {state or ''}, Brasil", True)

    if address_str and address_str.strip():
        parts = [p.strip() for p in re.split(r'[,–-]', address_str.strip()) if p.strip()]
        if len(parts) >= 3:
            street_clean = re.sub(r'\s+\d+\b', '', parts[0]).strip()
            add(f"{street_clean}, {parts[-1]}, Brasil", True)

    # Aproximados
    if neighborhood and city:
        add(f"{neighborhood}, {city} - {state or ''}, Brasil", False)
    if city:
        add(f"{city} - {state or ''}, Brasil", False)
    if state and not city:
        add(f"{state}, Brasil", False)
    if address_str and address_str.strip():
        parts = [p.strip() for p in re.split(r'[,–-]', address_str.strip()) if p.strip()]
        if len(parts) >= 3:
            add(f"{parts[-1]}, Brasil", False)

    headers = {'User-Agent': 'PertoJaMarketplace/2.0 (suporte@pertoja.com.br)'}
    for cand, precise in candidates:
        if precise_only and not precise:
            continue
        cached_cand = get_cached_geocode(cand)
        if cached_cand:
            return cached_cand
        try:
            url = f'https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(cand)}&limit=1'
            r = requests.get(url, headers=headers, timeout=3.0)
            if r.status_code == 200:
                res = r.json()
                if res and len(res) > 0:
                    lat_found = float(res[0]['lat'])
                    lng_found = float(res[0]['lon'])
                    save_cached_geocode(cand, lat_found, lng_found, origem='nominatim-v2')
                    if precise and cache_query and cand != cache_query:
                        save_cached_geocode(cache_query, lat_found, lng_found, origem='nominatim-v2')
                    return lat_found, lng_found
        except Exception:
            continue

    if fallback is not None:
        return fallback
    return None, None


# ================= Rotas para servir páginas estáticas =================


def _not_found_response():
    """Retorna 404.html se existir em STATIC_DIR, senão JSON 404 (sem fallback para index.html)."""
    page_404 = os.path.join(STATIC_DIR, '404.html')
    if os.path.isfile(page_404):
        return send_from_directory(STATIC_DIR, '404.html'), 404
    return jsonify({'error': 'Página não encontrada.'}), 404


@app.route('/')
def home():
    return send_from_directory(STATIC_DIR, 'index.html')


@app.route('/robots.txt')
def robots():
    return send_from_directory(STATIC_DIR, 'robots.txt', mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory(STATIC_DIR, 'sitemap.xml', mimetype='application/xml')


@app.route('/manifest.json')
def manifest():
    return send_from_directory(STATIC_DIR, 'manifest.json', mimetype='application/manifest+json')


@app.route('/termos')
@app.route('/termos.html')
def termos_page():
    return send_from_directory(STATIC_DIR, 'termos.html')


@app.route('/privacidade')
@app.route('/privacidade.html')
def privacidade_page():
    return send_from_directory(STATIC_DIR, 'privacidade.html')


@app.route('/<path:filename>')
def serve_static(filename):
    # Se uma rota /api/... cair aqui, retorna JSON 404
    clean_req = filename.lstrip('/')
    if clean_req == 'api' or clean_req.startswith('api/'):
        return jsonify({'error': 'Endpoint da API não encontrado.'}), 404

    if clean_req in ('', 'index', 'home'):
        return send_from_directory(STATIC_DIR, 'index.html')

    # Validação de path traversal via os.path.normpath dentro de os.path.abspath(STATIC_DIR)
    static_root = os.path.abspath(STATIC_DIR)
    normalized_rel = os.path.normpath(clean_req)
    if normalized_rel.startswith('..') or os.path.isabs(normalized_rel):
        return _not_found_response()

    target_path = os.path.abspath(os.path.join(static_root, normalized_rel))
    if not (target_path == static_root or target_path.startswith(static_root + os.sep)):
        return _not_found_response()

    # 1. Arquivo existente com extensão permitida
    if os.path.isfile(target_path):
        ext = os.path.splitext(target_path)[1].lower()
        if ext in ALLOWED_STATIC_EXTENSIONS:
            return send_from_directory(static_root, normalized_rel.replace('\\', '/'))
        return _not_found_response()

    # 2. URLs amigáveis sem extensão (ex: /pedido -> pedido.html, /login -> login.html)
    if not os.path.splitext(normalized_rel)[1]:
        html_rel = normalized_rel + '.html'
        html_target = os.path.abspath(os.path.join(static_root, html_rel))
        if html_target.startswith(static_root + os.sep) and os.path.isfile(html_target):
            return send_from_directory(static_root, html_rel.replace('\\', '/'))

    return _not_found_response()


@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Endpoint da API não encontrado.'}), 404
    return _not_found_response()


@app.errorhandler(500)
def handle_500(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Erro interno do servidor.'}), 500
    if os.path.isfile(os.path.join(STATIC_DIR, '404.html')):
        return send_from_directory(STATIC_DIR, '404.html'), 500
    return jsonify({'error': 'Erro interno do servidor.'}), 500


# ================= Health Check & Monitoramento =================


@app.route('/api/health', methods=['GET'])
def health_check():
    status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'database': 'connected',
        'engine': database.get_active_engine(),
        'version': '2.0.0',
        'environment': 'vercel' if os.environ.get('VERCEL') == '1' else 'standalone'
    }
    try:
        conn = database.get_db_connection()
        conn.execute('SELECT 1').fetchone()
        conn.close()
    except Exception as err:
        print(f"[health_check] database error: {err}", file=sys.stderr)
        status['status'] = 'degraded'
        status['database'] = 'unavailable'
        return jsonify(status), 503
    return jsonify(status), 200


# ================= Rotas de Endereço e Geocodificação =================


@app.route('/api/cep/<cep>', methods=['GET'])
@rate_limit(200, 60)
def consultar_cep(cep):
    clean_cep = re.sub(r'\D', '', cep)
    if len(clean_cep) != 8:
        return jsonify({'error': 'CEP inválido. Deve conter 8 dígitos numéricos.'}), 400

    data = None
    backup_coords = None

    # 1. Consulta dados cadastrais oficiais dos Correios via ViaCEP
    try:
        resp = requests.get(f'https://viacep.com.br/ws/{clean_cep}/json/', timeout=4)
        if resp.status_code == 200:
            v_data = resp.json()
            if not v_data.get('erro'):
                data = v_data
    except Exception:
        pass

    # 2. Se ViaCEP falhar, recorre à BrasilAPI v2 para obter logradouro, bairro e localidade
    if not data or not data.get('localidade'):
        try:
            r_brasil = requests.get(
                f'https://brasilapi.com.br/api/cep/v2/{clean_cep}',
                headers={'User-Agent': 'PertoJaMarketplace/2.0 (suporte@pertoja.com.br)'},
                timeout=3.5
            )
            if r_brasil.status_code == 200:
                b_json = r_brasil.json()
                coords = b_json.get('location', {}).get('coordinates', {})
                if coords.get('latitude') and coords.get('longitude'):
                    try:
                        backup_coords = (float(coords['latitude']), float(coords['longitude']))
                    except (ValueError, TypeError):
                        pass

                data = {
                    'cep': b_json.get('cep') or clean_cep,
                    'logradouro': b_json.get('street') or '',
                    'bairro': b_json.get('neighborhood') or '',
                    'localidade': b_json.get('city') or '',
                    'uf': b_json.get('state') or '',
                    'ibge': str(b_json.get('ibge', {}).get('city', '') if isinstance(b_json.get('ibge'), dict) else (b_json.get('ibge') or ''))
                }
        except Exception:
            pass

    if not data or data.get('erro'):
        return jsonify({'error': 'CEP não encontrado na base oficial dos Correios.'}), 404

    # 3. Geocodificação precisa a nível de rua/bairro via Nominatim multinível
    street = data.get('logradouro') or ''
    bairro = data.get('bairro') or ''
    city = data.get('localidade') or ''
    uf = data.get('uf') or ''

    address_full = f"{street}, {bairro}, {city} - {uf}".strip(', -')

    # 3a. Precisão de rua via Nominatim (somente candidatos com logradouro)
    lat, lng = (None, None)
    if street:
        lat, lng = geocode_address(
            address_str=address_full, street=street, neighborhood=bairro,
            city=city, state=uf, precise_only=True
        )

    # 3b. Coordenadas por CEP da BrasilAPI (mais precisas que o centro do bairro/cidade)
    if (lat is None or lng is None) and not backup_coords:
        try:
            r_b = requests.get(
                f'https://brasilapi.com.br/api/cep/v2/{clean_cep}',
                headers={'User-Agent': 'PertoJaMarketplace/2.0 (suporte@pertoja.com.br)'},
                timeout=3.0
            )
            if r_b.status_code == 200:
                c = r_b.json().get('location', {}).get('coordinates', {})
                if c.get('latitude') and c.get('longitude'):
                    backup_coords = (float(c['latitude']), float(c['longitude']))
        except Exception:
            pass
    if (lat is None or lng is None) and backup_coords:
        lat, lng = backup_coords

    # 3c. Último recurso: aproximação por bairro/cidade (sinalizada como aproximada)
    if lat is None or lng is None:
        lat, lng = geocode_address(
            address_str=address_full, street=street, neighborhood=bairro,
            city=city, state=uf
        )
        data['aproximado'] = lat is not None

    data['lat'] = lat
    data['lng'] = lng
    return jsonify(data)


@app.route('/api/geocode', methods=['GET'])
@rate_limit(60, 60)
def geocode_endpoint():
    query = request.args.get('address') or request.args.get('q') or ''
    street = (request.args.get('street') or '').strip() or None
    neighborhood = (request.args.get('neighborhood') or '').strip() or None
    city = (request.args.get('city') or '').strip() or None
    state = (request.args.get('state') or '').strip() or None
    if not query.strip() and not any([street, neighborhood, city, state]):
        return jsonify({'error': 'Parâmetro de endereço obrigatório.'}), 400
    lat, lng = geocode_address(
        query.strip(),
        street=street,
        neighborhood=neighborhood,
        city=city,
        state=state
    )
    if lat is None or lng is None:
        return jsonify({'error': 'Endereço não localizado no mapa.', 'lat': None, 'lng': None}), 404
    return jsonify({'lat': lat, 'lng': lng, 'query': query.strip()})


# ================= Rotas de Autenticação =================


@app.route('/api/auth/register', methods=['POST'])
@rate_limit(10, 60)
def register():
    data = request.get_json() or {}
    nome = str(data.get('nome') or '').strip()
    email = str(data.get('email') or '').strip().lower()
    senha = str(data.get('senha') or '')
    tipo = str(data.get('tipo') or 'cliente').strip()
    plano = str(data.get('plano') or 'basico').strip().lower()
    if plano not in ('basico', 'pro'):
        plano = 'basico'
    telefone = str(data.get('telefone') or '').strip()
    bio = str(data.get('bio') or '').strip()

    # Endereço real
    cep = str(data.get('cep') or '').strip()
    endereco = str(data.get('endereco') or '').strip()
    numero = str(data.get('numero') or '').strip()
    complemento = str(data.get('complemento') or '').strip()
    bairro = str(data.get('bairro') or '').strip()
    cidade = str(data.get('cidade') or '').strip()
    estado = str(data.get('estado') or '').strip()

    # Coordenadas
    raw_lat = data.get('lat')
    raw_lng = data.get('lng')

    if not nome or not email or not senha:
        return jsonify({'error': 'Nome, e-mail e senha são obrigatórios.'}), 400

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({'error': 'Formato de e-mail inválido.'}), 400

    if len(senha) < 6:
        return jsonify({'error': 'A senha deve conter no mínimo 6 caracteres.'}), 400

    if tipo not in ('cliente', 'prestador'):
        return jsonify({'error': 'Tipo de usuário inválido. Escolha cliente ou prestador.'}), 400

    aceite_termos = data.get('aceite_termos')
    if aceite_termos in (False, 'false', 'False', '0', 0):
        return jsonify({'error': 'É necessário aceitar os Termos de Uso e Política de Privacidade.'}), 400
    versao_termos = str(data.get('versao_termos') or '2026.1').strip()[:20]

    kyc_documento_tipo = str(data.get('kyc_documento_tipo') or 'RG').strip().upper()
    if kyc_documento_tipo not in ('RG', 'CIN', 'CNH'):
        kyc_documento_tipo = 'RG'
    registro_profissional = str(data.get('registro_profissional') or '').strip() or None
    if registro_profissional and not PROF_REG_REGEX.match(registro_profissional):
        return jsonify({'error': 'Registro profissional inválido. Utilize formato CREA, CFT, CRT, NR-10 ou CAU.'}), 400
    raw_cpf = str(data.get('cpf') or '').strip()
    cpf_limpo = re.sub(r'\D', '', raw_cpf) if raw_cpf else None
    if raw_cpf and len(cpf_limpo) != 11:
        return jsonify({'error': 'CPF inválido. Informe 11 dígitos numéricos.'}), 400

    # Se não passou coordenadas mas passou endereço, geocodifica
    if (raw_lat is None or raw_lat == '' or raw_lng is None or raw_lng == '') and (endereco or cep):
        busca = f"{endereco} {numero}, {bairro}, {cidade} - {estado}" if endereco else f"{cep}, Brasil"
        lat, lng = geocode_address(busca, street=endereco, neighborhood=bairro, city=cidade, state=estado)
        if lat is None or lng is None:
            lat, lng = -23.5653, -46.6517
    elif raw_lat is None or raw_lat == '' or raw_lng is None or raw_lng == '':
        lat, lng = -23.5653, -46.6517
    else:
        lat = safe_coord(raw_lat, -23.5653, -90.0, 90.0)
        lng = safe_coord(raw_lng, -46.6517, -180.0, 180.0)

    categoria = str(data.get('categoria') or '').strip()
    preco_inicial = data.get('preco_inicial')

    if tipo == 'prestador' and categoria and categoria not in CATEGORIAS_PERMITIDAS:
        return jsonify({'error': f'Categoria "{categoria}" não permitida pela plataforma.'}), 400

    kyc_tier = 2 if (tipo == 'prestador' and registro_profissional and categoria in CATEGORIAS_TECNICAS) else 1
    if tipo == 'prestador' and categoria in CATEGORIAS_TECNICAS and kyc_tier < 2:
        return jsonify({'error': 'Categorias técnicas (Elétrica/Encanamento) exigem registro profissional e KYC Tier 2.'}), 403

    conn = get_db_connection()
    try:
        user_exist = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if user_exist:
            return jsonify({'error': 'Este e-mail já está cadastrado.'}), 409

        senha_hash = generate_password_hash(senha)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (nome, email, senha_hash, tipo, plano, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng, kyc_tier, kyc_status, kyc_documento_tipo, registro_profissional, cpf, status_conta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'aprovado', ?, ?, ?, 'ativo')
        ''', (nome, email, senha_hash, tipo, plano, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng, kyc_tier, kyc_documento_tipo, registro_profissional, cpf_limpo))
        user_id = cursor.lastrowid

        if aceite_termos in (True, 'true', 'True', '1', 1):
            cursor.execute('''
                INSERT INTO user_consents (user_id, doc_type, doc_version, ip_hash)
                VALUES (?, 'termos_privacidade', ?, ?)
            ''', (user_id, versao_termos, _hash_ip(_get_client_ip())))

        # Se for prestador e informou categoria e preço inicial, cria o primeiro serviço com endereço real
        if tipo == 'prestador' and categoria:
            if preco_inicial is not None and preco_inicial != '':
                preco = parse_positive_price(preco_inicial)
                if preco is None:
                    conn.rollback()
                    return jsonify({'error': 'Preço inicial inválido.'}), 400
            else:
                preco = 100.0
            titulo_svc = f'Serviço profissional de {categoria}'
            desc_svc = bio or f'Atendimento especializado em {categoria} na região de {cidade or "São Paulo"}.'
            cursor.execute('''
                INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (user_id, titulo_svc, desc_svc, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng))

        conn.commit()

        # Criar sessão
        session.permanent = True
        session['user_id'] = user_id
        session['user_tipo'] = tipo
        session['user_nome'] = nome
        session['session_version'] = 1

        return jsonify({
            'message': 'Cadastro realizado com sucesso!',
            'user': {
                'id': user_id,
                'nome': nome,
                'email': email,
                'tipo': tipo,
                'plano': plano,
                'telefone': telefone,
                'cep': cep,
                'endereco': endereco,
                'numero': numero,
                'bairro': bairro,
                'cidade': cidade,
                'estado': estado,
                'lat': lat,
                'lng': lng,
                'kyc_tier': kyc_tier,
                'kyc_status': 'aprovado',
                'kyc_documento_tipo': kyc_documento_tipo,
                'registro_profissional': registro_profissional,
                'cpf': cpf_limpo,
                'status_conta': 'ativo'
            }
        }), 201
    except Exception as e:
        print(f"[register] error: {e}", file=sys.stderr)
        return jsonify({'error': 'Erro interno ao cadastrar usuário.'}), 500
    finally:
        conn.close()


@app.route('/api/auth/login', methods=['POST'])
@rate_limit(10, 60)
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    senha = data.get('senha', '')

    if not email or not senha:
        return jsonify({'error': 'E-mail e senha são obrigatórios.'}), 400

    rl_resp = _check_email_rate_limit('login', email, 10, 60)
    if rl_resp is not None:
        return rl_resp

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user['senha_hash'], senha):
        return jsonify({'error': 'Credenciais inválidas. Verifique seu e-mail e senha.'}), 401

    if _row_get(user, 'status_conta', 'ativo') in ('bloqueado', 'anonimizado'):
        return jsonify({'error': 'Conta bloqueada ou desativada.'}), 403

    session.permanent = True
    session['user_id'] = user['id']
    session['user_tipo'] = user['tipo']
    session['user_nome'] = user['nome']
    session['session_version'] = int(_row_get(user, 'session_version', 1) or 1)

    return jsonify({
        'message': 'Login realizado com sucesso!',
        'user': {
            'id': user['id'],
            'nome': user['nome'],
            'email': user['email'],
            'tipo': user['tipo'],
            'plano': _row_get(user, 'plano', 'basico'),
            'telefone': user['telefone'],
            'bio': user['bio'],
            'cep': user['cep'],
            'endereco': user['endereco'],
            'numero': user['numero'],
            'bairro': user['bairro'],
            'cidade': user['cidade'],
            'estado': user['estado'],
            'lat': user['lat'],
            'lng': user['lng'],
            'disponivel': bool(user['disponivel']),
            'kyc_tier': _row_get(user, 'kyc_tier', 1),
            'kyc_status': _row_get(user, 'kyc_status', 'aprovado'),
            'kyc_documento_tipo': _row_get(user, 'kyc_documento_tipo', 'RG'),
            'registro_profissional': _row_get(user, 'registro_profissional'),
            'status_conta': _row_get(user, 'status_conta', 'ativo')
        }
    })


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Sessão encerrada com sucesso.'})


@app.route('/api/auth/forgot-password', methods=['POST'])
@rate_limit(10, 60)
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip().lower()
    if email:
        rl_resp = _check_email_rate_limit('forgot_password', email, 10, 60)
        if rl_resp is not None:
            return rl_resp
        conn = get_db_connection()
        try:
            conn.execute('DELETE FROM password_reset_tokens WHERE expires_at < ?', (time.time() - 86400,))
            user = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if user:
                token = secrets.token_urlsafe(24)
                token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
                expires_at = time.time() + 1800
                conn.execute(
                    'INSERT INTO password_reset_tokens (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)',
                    (token_hash, user['id'], expires_at)
                )
            conn.commit()
        finally:
            conn.close()

    return jsonify({
        'message': 'Se o e-mail estiver cadastrado, as instruções de redefinição foram geradas.'
    }), 200


@app.route('/api/auth/reset-password', methods=['POST'])
@rate_limit(10, 60)
def reset_password():
    data = request.get_json(silent=True) or {}
    token = str(data.get('token') or '').strip()
    nova_senha = str(data.get('nova_senha') or '')

    if not token:
        return jsonify({'error': 'Token de redefinição obrigatório.'}), 400
    if len(nova_senha) < 6:
        return jsonify({'error': 'A nova senha deve conter no mínimo 6 caracteres.'}), 400

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT token, user_id, expires_at, used FROM password_reset_tokens WHERE token = ? OR token = ?',
            (token_hash, token)
        ).fetchone()
        if not row or int(_row_get(row, 'used', 0)) != 0 or float(row['expires_at']) <= time.time():
            return jsonify({'error': 'Token inválido ou expirado.'}), 400

        senha_hash = generate_password_hash(nova_senha)
        conn.execute('UPDATE users SET senha_hash = ?, session_version = COALESCE(session_version, 1) + 1 WHERE id = ?', (senha_hash, row['user_id']))
        conn.execute('UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0', (row['user_id'],))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'Senha redefinida com sucesso.'}), 200


@app.route('/api/auth/me', methods=['GET'])
def me():
    user = get_current_user()
    if not user:
        return jsonify({'authenticated': False}), 200

    return jsonify({
        'authenticated': True,
        'user': {
            'id': user['id'],
            'nome': user['nome'],
            'email': user['email'],
            'tipo': user['tipo'],
            'plano': _row_get(user, 'plano', 'basico'),
            'telefone': user['telefone'],
            'bio': user['bio'],
            'foto_url': user['foto_url'],
            'cep': user['cep'],
            'endereco': user['endereco'],
            'numero': user['numero'],
            'complemento': user['complemento'],
            'bairro': user['bairro'],
            'cidade': user['cidade'],
            'estado': user['estado'],
            'lat': user['lat'],
            'lng': user['lng'],
            'disponivel': bool(user['disponivel']),
            'avaliacao_media': user['avaliacao_media'],
            'total_avaliacoes': user['total_avaliacoes'],
            'kyc_tier': _row_get(user, 'kyc_tier', 1),
            'kyc_status': _row_get(user, 'kyc_status', 'aprovado'),
            'kyc_documento_tipo': _row_get(user, 'kyc_documento_tipo', 'RG'),
            'registro_profissional': _row_get(user, 'registro_profissional'),
            'status_conta': _row_get(user, 'status_conta', 'ativo')
        }
    })


# ================= Rotas de Perfil =================


@app.route('/api/profile', methods=['GET', 'PUT'])
def profile():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Acesso não autorizado. Faça login.'}), 401

    conn = get_db_connection()
    if request.method == 'GET':
        conn.close()
        return jsonify({
            'id': user['id'],
            'nome': user['nome'],
            'email': user['email'],
            'tipo': user['tipo'],
            'plano': _row_get(user, 'plano', 'basico'),
            'telefone': user['telefone'],
            'bio': user['bio'],
            'cep': user['cep'],
            'endereco': user['endereco'],
            'numero': user['numero'],
            'complemento': user['complemento'],
            'bairro': user['bairro'],
            'cidade': user['cidade'],
            'estado': user['estado'],
            'lat': user['lat'],
            'lng': user['lng'],
            'disponivel': bool(user['disponivel']),
            'avaliacao_media': user['avaliacao_media'],
            'total_avaliacoes': _row_get(user, 'total_avaliacoes', 0),
            'kyc_tier': _row_get(user, 'kyc_tier', 1),
            'kyc_status': _row_get(user, 'kyc_status', 'aprovado'),
            'kyc_documento_tipo': _row_get(user, 'kyc_documento_tipo', 'RG'),
            'registro_profissional': _row_get(user, 'registro_profissional'),
            'status_conta': _row_get(user, 'status_conta', 'ativo')
        })

    # PUT: Atualização de perfil
    data = request.get_json() or {}

    def _clean_str(val, fallback=''):
        if val is None:
            return str(fallback or '').strip()
        return str(val).strip()

    nome = _clean_str(data.get('nome'), user['nome'])
    telefone = _clean_str(data.get('telefone'), user['telefone'])
    bio = _clean_str(data.get('bio'), user['bio'])

    cep = _clean_str(data.get('cep'), user['cep'])
    endereco = _clean_str(data.get('endereco'), user['endereco'])
    numero = _clean_str(data.get('numero'), user['numero'])
    complemento = _clean_str(data.get('complemento'), user['complemento'])
    bairro = _clean_str(data.get('bairro'), user['bairro'])
    cidade = _clean_str(data.get('cidade'), user['cidade'])
    estado = _clean_str(data.get('estado'), user['estado'])

    raw_lat = data.get('lat')
    raw_lng = data.get('lng')

    # Se as coordenadas não vieram explícitas mas o endereço mudou, busca geocodificação
    if raw_lat is None or raw_lat == '' or raw_lng is None or raw_lng == '':
        if endereco:
            g_lat, g_lng = geocode_address(f"{endereco} {numero}, {bairro}, {cidade} - {estado}", street=endereco, neighborhood=bairro, city=cidade, state=estado)
            lat = g_lat if g_lat is not None else safe_coord(user['lat'], -23.5653)
            lng = g_lng if g_lng is not None else safe_coord(user['lng'], -46.6517)
        else:
            lat = safe_coord(user['lat'], -23.5653)
            lng = safe_coord(user['lng'], -46.6517)
    else:
        lat = safe_coord(raw_lat, safe_coord(user['lat'], -23.5653))
        lng = safe_coord(raw_lng, safe_coord(user['lng'], -46.6517))

    disponivel = 1 if data.get('disponivel', bool(user['disponivel'])) else 0

    conn.execute('''
        UPDATE users
        SET nome = ?, telefone = ?, bio = ?, cep = ?, endereco = ?, numero = ?, complemento = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?, disponivel = ?
        WHERE id = ?
    ''', (nome, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng, disponivel, user['id']))

    # Se for prestador, atualiza o endereço nos seus serviços para refletir a nova localização
    if user['tipo'] == 'prestador':
        conn.execute('''
            UPDATE services
            SET cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?
            WHERE prestador_id = ?
        ''', (cep, endereco, numero, bairro, cidade, estado, lat, lng, user['id']))

    conn.commit()
    conn.close()

    session['user_nome'] = nome

    return jsonify({'message': 'Perfil e localização atualizados com sucesso!'})


@app.route('/api/profile', methods=['DELETE'])
def delete_profile():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Acesso não autorizado. Faça login.'}), 401

    conn = get_db_connection()
    try:
        dispute_order = conn.execute(
            "SELECT id FROM orders WHERE (cliente_id = ? OR prestador_id = ?) AND status = 'em_disputa' LIMIT 1",
            (user['id'], user['id'])
        ).fetchone()
        if dispute_order:
            return jsonify({
                'error': 'Não é possível excluir a conta enquanto houver pedido em disputa aberta.'
            }), 409

        anon_email = f"anon_{user['id']}_{secrets.token_hex(4)}@anon.pertoja.local"
        unusable_hash = generate_password_hash(secrets.token_hex(32))
        conn.execute('''
            UPDATE users
            SET nome = 'Usuário Anonimizado',
                email = ?,
                senha_hash = ?,
                telefone = NULL,
                bio = NULL,
                foto_url = NULL,
                cep = NULL,
                endereco = NULL,
                numero = NULL,
                complemento = NULL,
                bairro = NULL,
                cidade = NULL,
                estado = NULL,
                lat = NULL,
                lng = NULL,
                cpf = NULL,
                registro_profissional = NULL,
                kyc_provider_ref = NULL,
                disponivel = 0,
                status_conta = 'anonimizado',
                session_version = COALESCE(session_version, 1) + 1
            WHERE id = ?
        ''', (anon_email, unusable_hash, user['id']))
        conn.execute('''
            UPDATE services
            SET ativo = 0,
                cep = NULL,
                endereco = NULL,
                numero = NULL,
                bairro = NULL,
                cidade = NULL,
                estado = NULL,
                lat = NULL,
                lng = NULL
            WHERE prestador_id = ?
        ''', (user['id'],))
        conn.execute('DELETE FROM password_reset_tokens WHERE user_id = ?', (user['id'],))
        conn.execute('DELETE FROM payment_methods WHERE user_id = ?', (user['id'],))
        conn.commit()
    finally:
        conn.close()

    session.clear()
    return jsonify({'message': 'Conta anonimizada e sessão encerrada conforme LGPD Art. 18.'}), 200


@app.route('/api/profile/export', methods=['GET'])
def export_profile_data():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Acesso não autorizado. Faça login.'}), 401

    conn = get_db_connection()
    try:
        user_dict = dict(user)
        user_dict.pop('senha_hash', None)
        services = [dict(r) for r in conn.execute('SELECT * FROM services WHERE prestador_id = ?', (user['id'],)).fetchall()]
        orders = [dict(r) for r in conn.execute(
            'SELECT * FROM orders WHERE cliente_id = ? OR prestador_id = ? ORDER BY criado_em DESC',
            (user['id'], user['id'])
        ).fetchall()]
        reviews = [dict(r) for r in conn.execute(
            'SELECT * FROM reviews WHERE cliente_id = ? OR prestador_id = ? ORDER BY criado_em DESC',
            (user['id'], user['id'])
        ).fetchall()]
        consents = [dict(r) for r in conn.execute(
            'SELECT * FROM user_consents WHERE user_id = ? ORDER BY accepted_at DESC',
            (user['id'],)
        ).fetchall()]
    finally:
        conn.close()

    return jsonify({
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'user': user_dict,
        'services': services,
        'orders': orders,
        'reviews': reviews,
        'consents': consents
    }), 200


@app.route('/api/kyc/verify', methods=['POST'])
@rate_limit(10, 60)
def verify_kyc():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Acesso não autorizado. Faça login.'}), 401
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    current_kyc_status = _row_get(user, 'kyc_status', 'aprovado')
    if current_kyc_status in ('em_revisao', 'reprovado'):
        return jsonify({'error': 'Verificação KYC em revisão ou reprovada. Aguarde análise da equipe.'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({'error': 'Payload de verificação KYC obrigatório.'}), 400

    raw_doc_tipo = data.get('kyc_documento_tipo') or data.get('documento_tipo')
    doc_tipo = str(raw_doc_tipo or '').strip().upper()
    if doc_tipo not in ('RG', 'CIN', 'CNH'):
        return jsonify({'error': 'Tipo de documento inválido ou ausente. Escolha RG, CIN ou CNH.'}), 400

    raw_reg = data.get('registro_profissional')
    if raw_reg is not None and str(raw_reg).strip():
        registro_prof = str(raw_reg).strip()
        if not PROF_REG_REGEX.match(registro_prof):
            return jsonify({'error': 'Registro profissional inválido. Utilize formato CREA, CFT, CRT, NR-10 ou CAU.'}), 400
    else:
        registro_prof = _row_get(user, 'registro_profissional')

    selfie_ok = (data.get('selfie_verificada') is True)
    homonimo = bool(data.get('homonimo'))
    raw_cpf = str(data.get('cpf') or '').strip()
    cpf_limpo = re.sub(r'\D', '', raw_cpf) if raw_cpf else None
    if raw_cpf and len(cpf_limpo) != 11:
        return jsonify({'error': 'CPF inválido. Informe 11 dígitos numéricos.'}), 400

    req_tier = data.get('tier')
    if req_tier is not None:
        if isinstance(req_tier, bool):
            return jsonify({'error': 'Tier KYC inválido.'}), 400
        try:
            req_tier = int(req_tier)
        except (ValueError, TypeError):
            return jsonify({'error': 'Tier KYC inválido.'}), 400
    else:
        req_tier = None

    has_valid_cpf_tier0 = (req_tier == 0 and cpf_limpo is not None and len(cpf_limpo) == 11)
    if not (selfie_ok or has_valid_cpf_tier0):
        return jsonify({'error': 'É necessário confirmar selfie_verificada=true ou informar CPF válido para Tier 0.'}), 400

    has_valid_reg = bool(registro_prof and PROF_REG_REGEX.match(str(registro_prof)))
    if selfie_ok and has_valid_reg and (req_tier is None or req_tier >= 2):
        tier = 2
    elif has_valid_cpf_tier0 and not selfie_ok:
        tier = 0
    elif req_tier == 0:
        tier = 0
    else:
        tier = 1

    kyc_status = 'em_revisao' if homonimo else 'aprovado'
    provider_ref = f"kyc-{user['id']}-{secrets.token_hex(4)}"
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE users
            SET kyc_tier = ?,
                kyc_status = ?,
                kyc_documento_tipo = ?,
                kyc_provider_ref = ?,
                kyc_verified_at = CURRENT_TIMESTAMP,
                registro_profissional = COALESCE(?, registro_profissional),
                cpf = COALESCE(?, cpf)
            WHERE id = ?
        ''', (tier, kyc_status, doc_tipo, provider_ref, registro_prof, cpf_limpo, user['id']))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Cadastro encaminhado para revisão humana (homônimo).' if homonimo else 'Verificação KYC concluída com sucesso.',
        'kyc_tier': tier,
        'kyc_status': kyc_status,
        'kyc_documento_tipo': doc_tipo,
        'kyc_provider_ref': provider_ref,
        'registro_profissional': registro_prof
    }), 200


# ================= Rotas de Serviços =================


@app.route('/api/services', methods=['GET'])
def list_services():
    cat = request.args.get('cat', 'Todos')
    query = request.args.get('query', '').strip().lower()
    user_lat = request.args.get('lat', type=float)
    user_lng = request.args.get('lng', type=float)
    radius = request.args.get('radius', default=15.0, type=float)
    if user_lat is not None and (not math.isfinite(user_lat) or user_lat < -90.0 or user_lat > 90.0):
        return jsonify({'error': 'Parâmetro lat inválido.'}), 400
    if user_lng is not None and (not math.isfinite(user_lng) or user_lng < -180.0 or user_lng > 180.0):
        return jsonify({'error': 'Parâmetro lng inválido.'}), 400
    if radius is not None and (not math.isfinite(radius) or radius < 0):
        return jsonify({'error': 'Parâmetro radius inválido.'}), 400
    order = (request.args.get('order') or 'distance').strip().lower()
    only_available = request.args.get('only_available', '').strip().lower() in ('1', 'true', 'yes')

    conn = get_db_connection()
    sql = '''
        SELECT 
            s.id AS service_id,
            s.titulo,
            s.descricao,
            s.categoria,
            s.preco,
            s.ativo,
            COALESCE(s.cep, u.cep) AS cep,
            COALESCE(s.endereco, u.endereco) AS endereco,
            COALESCE(s.numero, u.numero) AS numero,
            COALESCE(s.bairro, u.bairro) AS bairro,
            COALESCE(s.cidade, u.cidade) AS cidade,
            COALESCE(s.estado, u.estado) AS estado,
            COALESCE(s.lat, u.lat) AS lat,
            COALESCE(s.lng, u.lng) AS lng,
            u.id AS prestador_id,
            u.nome AS prestador_nome,
            u.telefone AS prestador_telefone,
            u.bio AS prestador_bio,
            u.avaliacao_media,
            u.total_avaliacoes,
            u.disponivel,
            COALESCE(u.plano, 'basico') AS plano,
            COALESCE(u.kyc_tier, 1) AS kyc_tier,
            COALESCE(u.kyc_status, 'aprovado') AS kyc_status,
            COALESCE(u.status_conta, 'ativo') AS status_conta
        FROM services s
        JOIN users u ON s.prestador_id = u.id
        WHERE s.ativo = 1 AND COALESCE(u.status_conta, 'ativo') = 'ativo'
    '''
    params = []

    if only_available:
        sql += ' AND u.disponivel = 1'

    if cat and cat != 'Todos':
        sql += ' AND LOWER(s.categoria) = LOWER(?)'
        params.append(cat)

    if query:
        sql += ' AND (LOWER(s.titulo) LIKE ? OR LOWER(s.descricao) LIKE ? OR LOWER(u.nome) LIKE ? OR LOWER(COALESCE(s.bairro, u.bairro)) LIKE ? OR LOWER(COALESCE(s.cidade, u.cidade)) LIKE ?)'
        like_q = f'%{query}%'
        params.extend([like_q, like_q, like_q, like_q, like_q])

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    # Coordenadas do cliente para cálculo de distância
    center_lat = user_lat if user_lat is not None else -23.5653
    center_lng = user_lng if user_lng is not None else -46.6517
    force_approx = (request.args.get('approx') == '1')
    session_user_id = session.get('user_id')

    def _deterministic_jitter(service_id):
        digest = hashlib.sha256(f"pertoja-jitter-{service_id}".encode('utf-8')).digest()
        # ~300m (~0.0025 graus)
        d_lat = ((digest[0] / 255.0) * 2.0 - 1.0) * 0.0025
        d_lng = ((digest[1] / 255.0) * 2.0 - 1.0) * 0.0025
        return d_lat, d_lng

    for r in rows:
        svc_lat = r['lat'] if r['lat'] is not None else -23.5653
        svc_lng = r['lng'] if r['lng'] is not None else -46.6517

        dist_km = calcular_distancia(center_lat, center_lng, svc_lat, svc_lng)
        if radius and dist_km > radius:
            continue

        # Algoritmo de score bayesiano (ET-03 / ET-12)
        v = int(_row_get(r, 'total_avaliacoes', 0) or 0)
        avg = float(_row_get(r, 'avaliacao_media', 4.5) or 4.5)
        nota_bayes = ((v * avg) + (5 * 4.5)) / (v + 5)
        score = 1000 * (1 - min(dist_km / 15.0, 1.0)) + (nota_bayes * 100) + (200 if r['disponivel'] else 0)

        is_owner = bool(session_user_id and int(session_user_id) == int(r['prestador_id']))
        is_approx = (not is_owner) or force_approx

        if is_approx:
            d_lat, d_lng = _deterministic_jitter(r['service_id'])
            out_lat = round(svc_lat + d_lat, 6)
            out_lng = round(svc_lng + d_lng, 6)
        else:
            out_lat = svc_lat
            out_lng = svc_lng

        # Formata endereço legível (ET-03: omite logradouro/número/CEP para não-donos ou approx=1)
        partes_end = []
        if not is_approx and r['endereco']:
            end_num = f"{r['endereco']}" + (f", {r['numero']}" if r['numero'] else '')
            partes_end.append(end_num)
        if r['bairro']:
            partes_end.append(r['bairro'])
        if r['cidade']:
            cid_uf = f"{r['cidade']}" + (f" - {r['estado']}" if r['estado'] else '')
            partes_end.append(cid_uf)

        endereco_formatado = " · ".join(partes_end) if partes_end else "São Paulo - SP"
        if is_approx:
            endereco_formatado = f"{endereco_formatado} (localização aproximada)"
        tel_out = r['prestador_telefone'] if not is_approx else _mask_phone(r['prestador_telefone'])

        results.append({
            'id': r['service_id'],
            'titulo': r['titulo'],
            'descricao': r['descricao'],
            'categoria': r['categoria'],
            'preco': r['preco'],
            'lat': out_lat,
            'lng': out_lng,
            'localizacao_aproximada': is_approx,
            'bairro': r['bairro'] or '',
            'cidade': r['cidade'] or 'São Paulo',
            'estado': r['estado'] or 'SP',
            'endereco_completo': endereco_formatado,
            'endereco': {
                'cep': '' if is_approx else (r['cep'] or ''),
                'logradouro': '' if is_approx else (r['endereco'] or ''),
                'numero': '' if is_approx else (r['numero'] or ''),
                'bairro': r['bairro'] or '',
                'cidade': r['cidade'] or 'São Paulo',
                'estado': r['estado'] or 'SP',
                'completo': endereco_formatado
            },
            'prestador': {
                'id': r['prestador_id'],
                'nome': r['prestador_nome'],
                'telefone': tel_out,
                'bio': r['prestador_bio'],
                'avaliacao': r['avaliacao_media'],
                'total_avaliacoes': r['total_avaliacoes'],
                'disponivel': bool(r['disponivel']),
                'plano': _row_get(r, 'plano', 'basico'),
                'kyc_tier': int(_row_get(r, 'kyc_tier', 1) or 1),
                'kyc_status': _row_get(r, 'kyc_status', 'aprovado'),
                'novo_no_pertoja': v < 5,
                'super_profissional': bool((r['avaliacao_media'] or 0) >= 4.8 and (r['total_avaliacoes'] or 0) >= 5),
                'lat': out_lat,
                'lng': out_lng
            },
            'distancia_km': round(dist_km, 1),
            'score': round(score),
            'score_detalhes': {
                'raio_max_km': 15.0,
                'nota_bayesiana': round(nota_bayes, 2),
                'novo_no_pertoja': v < 5
            }
        })

    if order == 'score':
        results.sort(key=lambda x: (-x['score'], x['distancia_km']))
    else:
        results.sort(key=lambda x: x['distancia_km'])
    return jsonify(results)


@app.route('/api/my-services', methods=['GET'])
def my_services():
    user = get_current_user()
    if not user or user['tipo'] != 'prestador':
        return jsonify({'error': 'Acesso exclusivo para prestadores de serviço.'}), 403

    conn = get_db_connection()
    include_all = request.args.get('all', '0') == '1'
    if include_all:
        services = conn.execute('''
            SELECT * FROM services WHERE prestador_id = ? ORDER BY criado_em DESC
        ''', (user['id'],)).fetchall()
    else:
        services = conn.execute('''
            SELECT * FROM services WHERE prestador_id = ? AND ativo = 1 ORDER BY criado_em DESC
        ''', (user['id'],)).fetchall()
    conn.close()

    return jsonify([dict(s) for s in services])


@app.route('/api/services', methods=['POST'])
def create_service():
    user = get_current_user()
    if not user or user['tipo'] != 'prestador':
        return jsonify({'error': 'Apenas prestadores podem cadastrar serviços.'}), 403

    if _row_get(user, 'status_conta', 'ativo') in ('suspenso_cautelar', 'bloqueado'):
        return jsonify({'error': 'Conta suspensa ou bloqueada não pode publicar serviços.'}), 403

    data = request.get_json() or {}
    titulo = str(data.get('titulo') or '').strip()[:120]
    descricao = str(data.get('descricao') or '').strip()[:2000]
    categoria = str(data.get('categoria') or '').strip()
    preco = data.get('preco')

    texto_combinado = f"{titulo} {descricao} {categoria}".lower()
    escopos_proibidos = (
        'escolta armada', 'arma de fogo',
        'gás alta pressão sem certificação', 'gas alta pressao sem certificacao',
        'ilícito', 'ilicito'
    )
    if any(p in texto_combinado for p in escopos_proibidos):
        return jsonify({'error': 'Escopo de serviço proibido pelas políticas de segurança do PertoJá.'}), 400

    if not titulo or not categoria or preco is None:
        return jsonify({'error': 'Título, categoria e preço são obrigatórios.'}), 400

    if categoria not in CATEGORIAS_PERMITIDAS:
        return jsonify({'error': f'Categoria "{categoria}" não permitida. Escolha entre: {", ".join(CATEGORIAS_PERMITIDAS)}.'}), 400

    kyc_status = _row_get(user, 'kyc_status', 'aprovado')
    kyc_tier = int(_row_get(user, 'kyc_tier', 1) or 1)
    exige_tier2 = bool(data.get('exige_kyc_tier2')) or (categoria in CATEGORIAS_TECNICAS)
    if kyc_status in ('reprovado', 'em_revisao') or (exige_tier2 and kyc_tier < 2):
        return jsonify({'error': 'Verificação KYC Tier 2 obrigatória para publicar este serviço.'}), 403

    # Dados de endereço do serviço (herda do prestador se não informados)
    cep = str(data.get('cep') or user['cep'] or '').strip()
    endereco = str(data.get('endereco') or user['endereco'] or '').strip()
    numero = str(data.get('numero') or user['numero'] or '').strip()
    bairro = str(data.get('bairro') or user['bairro'] or '').strip()
    cidade = str(data.get('cidade') or user['cidade'] or 'São Paulo').strip()
    estado = str(data.get('estado') or user['estado'] or 'SP').strip()
    lat = safe_coord(data.get('lat'), safe_coord(user['lat'], -23.5653, -90.0, 90.0), -90.0, 90.0)
    lng = safe_coord(data.get('lng'), safe_coord(user['lng'], -46.6517, -180.0, 180.0), -180.0, 180.0)

    if not titulo or not categoria or preco is None:
        return jsonify({'error': 'Título, categoria e preço são obrigatórios.'}), 400

    preco = parse_positive_price(preco)
    if preco is None:
        return jsonify({'error': 'O preço deve ser um valor numérico positivo válido.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    ''', (user['id'], titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng))
    conn.commit()
    service_id = cursor.lastrowid
    conn.close()

    return jsonify({'message': 'Anúncio publicado com sucesso com endereço real!', 'id': service_id}), 201


@app.route('/api/services/<int:service_id>', methods=['PUT'])
def update_service(service_id):
    user = get_current_user()
    if not user or user['tipo'] != 'prestador':
        return jsonify({'error': 'Apenas prestadores podem alterar serviços.'}), 403
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    conn = get_db_connection()
    try:
        service = conn.execute('SELECT * FROM services WHERE id = ?', (service_id,)).fetchone()
        if not service:
            return jsonify({'error': 'Serviço não encontrado.'}), 404

        if service['prestador_id'] != user['id']:
            return jsonify({'error': 'Você não tem permissão para alterar este serviço.'}), 403

        data = request.get_json() or {}
        if 'titulo' in data and not str(data.get('titulo') or '').strip():
            return jsonify({'error': 'Título não pode ser vazio.'}), 400
        titulo = str(data.get('titulo') or service['titulo']).strip()[:120]
        descricao = str(data.get('descricao') if data.get('descricao') is not None else (service['descricao'] or '')).strip()[:2000]
        categoria = str(data.get('categoria') or service['categoria']).strip()
        preco = data.get('preco', service['preco'])
        ativo = 1 if data.get('ativo', bool(service['ativo'])) else 0

        if any(k in data for k in ('titulo', 'descricao', 'categoria', 'exige_kyc_tier2')):
            texto_combinado = f"{titulo} {descricao} {categoria}".lower()
            escopos_proibidos = (
                'escolta armada', 'arma de fogo',
                'gás alta pressão sem certificação', 'gas alta pressao sem certificacao',
                'ilícito', 'ilicito'
            )
            if any(p in texto_combinado for p in escopos_proibidos):
                return jsonify({'error': 'Escopo de serviço proibido pelas políticas de segurança do PertoJá.'}), 400
            if categoria not in CATEGORIAS_PERMITIDAS:
                return jsonify({'error': f'Categoria "{categoria}" não permitida. Escolha entre: {", ".join(CATEGORIAS_PERMITIDAS)}.'}), 400
            kyc_status = _row_get(user, 'kyc_status', 'aprovado')
            kyc_tier = int(_row_get(user, 'kyc_tier', 1) or 1)
            exige_tier2 = bool(data.get('exige_kyc_tier2')) or (categoria in CATEGORIAS_TECNICAS)
            if kyc_status in ('reprovado', 'em_revisao') or (exige_tier2 and kyc_tier < 2):
                return jsonify({'error': 'Verificação KYC Tier 2 obrigatória para publicar este serviço.'}), 403

        cep = str(data.get('cep') or service['cep'] or user['cep'] or '').strip()
        endereco = str(data.get('endereco') or service['endereco'] or user['endereco'] or '').strip()
        numero = str(data.get('numero') or service['numero'] or user['numero'] or '').strip()
        bairro = str(data.get('bairro') or service['bairro'] or user['bairro'] or '').strip()
        cidade = str(data.get('cidade') or service['cidade'] or user['cidade'] or 'São Paulo').strip()
        estado = str(data.get('estado') or service['estado'] or user['estado'] or 'SP').strip()
        lat = safe_coord(data.get('lat'), safe_coord(service['lat'] or user['lat'], -23.5653, -90.0, 90.0), -90.0, 90.0)
        lng = safe_coord(data.get('lng'), safe_coord(service['lng'] or user['lng'], -46.6517, -180.0, 180.0), -180.0, 180.0)

        preco = parse_positive_price(preco)
        if preco is None:
            return jsonify({'error': 'Preço deve ser um valor positivo válido.'}), 400

        conn.execute('''
            UPDATE services
            SET titulo = ?, descricao = ?, categoria = ?, preco = ?, cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?, ativo = ?
            WHERE id = ?
        ''', (titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo, service_id))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'Serviço, endereço e preço atualizados com sucesso!'})


@app.route('/api/services/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    user = get_current_user()
    if not user or user['tipo'] != 'prestador':
        return jsonify({'error': 'Acesso não autorizado.'}), 403
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    conn = get_db_connection()
    service = conn.execute('SELECT * FROM services WHERE id = ?', (service_id,)).fetchone()
    if not service:
        conn.close()
        return jsonify({'error': 'Serviço não encontrado.'}), 404

    if service['prestador_id'] != user['id']:
        conn.close()
        return jsonify({'error': 'Acesso negado.'}), 403

    try:
        conn.execute('DELETE FROM services WHERE id = ?', (service_id,))
        conn.commit()
    except DBIntegrityError:
        # Se houver pedidos vinculados a este serviço, desativa para manter integridade dos pedidos
        conn.rollback()
        conn.execute('UPDATE services SET ativo = 0 WHERE id = ?', (service_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'Serviço excluído com sucesso.'})


# ================= Rotas de Pedidos / Chamados =================


@app.route('/api/orders', methods=['POST'])
@rate_limit(20, 60)
def create_order():
    user = get_current_user()
    if not user:
        return jsonify({
            'error': 'Autenticação obrigatória. Faça login para concluir o pedido.',
            'code': 'UNAUTHORIZED',
            'login_url': '/login.html?redirect=/pedido.html'
        }), 401

    if user['tipo'] != 'cliente':
        return jsonify({
            'error': 'Apenas clientes autenticados podem solicitar serviços. Prestadores de serviços não têm permissão para criar chamados.',
            'code': 'FORBIDDEN'
        }), 403

    if _row_get(user, 'status_conta', 'ativo') in ('suspenso_cautelar', 'bloqueado'):
        return jsonify({
            'error': 'Conta suspensa cautelarmente ou bloqueada não pode criar chamados.',
            'code': 'FORBIDDEN'
        }), 403

    if _row_get(user, 'kyc_status', 'aprovado') in ('em_revisao', 'reprovado'):
        return jsonify({
            'error': 'Conta em revisão cadastral (KYC) ou reprovada não pode criar chamados.',
            'code': 'FORBIDDEN'
        }), 403

    data = request.get_json() or {}

    aceite_termos = data.get('aceite_termos')
    if aceite_termos in (False, 'false', 'False', '0', 0):
        return jsonify({'error': 'É necessário aceitar os Termos de Uso e Política de Privacidade para criar o pedido.'}), 400

    # Blindagem contra requisições forjadas com cliente_id arbitrário
    if data.get('cliente_id') is not None:
        try:
            if int(data.get('cliente_id')) != int(user['id']):
                return jsonify({
                    'error': 'Tentativa de forjar cliente_id arbitrária detectada. O pedido só pode ser associado à sessão autenticada.',
                    'code': 'FORBIDDEN'
                }), 403
        except (ValueError, TypeError):
            return jsonify({'error': 'cliente_id inválido.', 'code': 'BAD_REQUEST'}), 400

    servico_id = data.get('servico_id')
    if not servico_id:
        return jsonify({'error': 'servico_id é obrigatório.', 'code': 'BAD_REQUEST'}), 400

    conn = get_db_connection()
    service = conn.execute('SELECT * FROM services WHERE id = ? AND ativo = 1', (servico_id,)).fetchone()
    if not service:
        conn.close()
        return jsonify({'error': 'Serviço selecionado não está disponível.', 'code': 'NOT_FOUND'}), 404

    # Prestador não pode solicitar seu próprio serviço
    if service['prestador_id'] == user['id']:
        conn.close()
        return jsonify({
            'error': 'Não é permitido solicitar seu próprio serviço.',
            'code': 'SELF_HIRE_NOT_ALLOWED'
        }), 400

    prestador = conn.execute('SELECT id, status_conta FROM users WHERE id = ?', (service['prestador_id'],)).fetchone()
    if not prestador or _row_get(prestador, 'status_conta', 'ativo') != 'ativo':
        conn.close()
        return jsonify({
            'error': 'Prestador indisponível ou suspenso no momento.',
            'code': 'PROVIDER_UNAVAILABLE'
        }), 403

    observacoes = str(data.get('observacoes') or '').strip()[:1000]
    complemento_cli = str(data.get('complemento') or _row_get(user, 'complemento', '')).strip()
    modalidade = str(data.get('modalidade') or 'imediato').strip().lower()
    if modalidade not in ('imediato', 'agendado'):
        modalidade = 'imediato'
    agendado_para = str(data.get('agendado_para') or '').strip() or None
    metodo_pagamento = str(data.get('metodo_pagamento') or 'escrow').strip().lower()
    if metodo_pagamento == 'escrow_local':
        metodo_pagamento = 'escrow'
    elif metodo_pagamento not in ('pix', 'cartao', 'boleto', 'escrow'):
        metodo_pagamento = 'escrow'
    codigo_confirmacao = f"{secrets.randbelow(9000) + 1000}"

    # Endereço onde o serviço será realizado (com fallbacks dos dados cadastrais do cliente)
    cep_cli = str(data.get('cep') or user['cep'] or '').strip()
    end_cli = str(data.get('endereco') or user['endereco'] or '').strip()
    num_cli = str(data.get('numero') or user['numero'] or '').strip()
    bairro_cli = str(data.get('bairro') or user['bairro'] or '').strip()
    cidade_cli = str(data.get('cidade') or user['cidade'] or 'São Paulo').strip()
    estado_cli = str(data.get('estado') or user['estado'] or 'SP').strip()

    user_lat_fallback = safe_coord(user['lat'], -23.5653, -90.0, 90.0)
    user_lng_fallback = safe_coord(user['lng'], -46.6517, -180.0, 180.0)
    lat_cliente = safe_coord(data.get('lat'), user_lat_fallback, -90.0, 90.0)
    lng_cliente = safe_coord(data.get('lng'), user_lng_fallback, -180.0, 180.0)

    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (
            cliente_id, prestador_id, servico_id, preco_total, observacoes,
            cep_cliente, endereco_cliente, numero_cliente, complemento_cliente,
            bairro_cliente, cidade_cliente, estado_cliente, lat_cliente, lng_cliente,
            modalidade, agendado_para, metodo_pagamento, pago, codigo_confirmacao, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'solicitado')
    ''', (
        user['id'], service['prestador_id'], service['id'], service['preco'], observacoes,
        cep_cli, end_cli, num_cli, complemento_cli,
        bairro_cli, cidade_cli, estado_cli, lat_cliente, lng_cliente,
        modalidade, agendado_para, metodo_pagamento, codigo_confirmacao
    ))
    conn.commit()
    order_id = cursor.lastrowid
    if aceite_termos in (True, 'true', 'True', '1', 1):
        conn.execute(
            "INSERT INTO user_consents (user_id, doc_type, doc_version, ip_hash) VALUES (?, 'pedido_escrow', ?, ?)",
            (user['id'], str(data.get('versao_termos') or '2026.1').strip()[:20], _hash_ip(_get_client_ip()))
        )
        conn.commit()
    conn.close()

    return jsonify({
        'message': 'Pedido solicitado com sucesso!',
        'order_id': order_id,
        'status': 'solicitado',
        'cliente_id': user['id'],
        'codigo_confirmacao': codigo_confirmacao,
        'modalidade': modalidade,
        'metodo_pagamento': metodo_pagamento
    }), 201


@app.route('/api/orders/<int:order_id>/pay', methods=['POST'])
def pay_order(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória para efetuar pagamento.', 'code': 'UNAUTHORIZED'}), 401

    if user['tipo'] != 'cliente':
        return jsonify({'error': 'Apenas clientes podem efetuar pagamento de pedidos.', 'code': 'FORBIDDEN'}), 403
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.', 'code': 'NOT_FOUND'}), 404

        if order['cliente_id'] != user['id']:
            return jsonify({'error': 'Sem permissão para pagar pedido de outro cliente.', 'code': 'FORBIDDEN'}), 403

        data = request.get_json(silent=True) or {}
        if _contains_forbidden_card_fields(data):
            return jsonify({'error': 'Dados brutos de cartão (PAN/CVV) não são permitidos.', 'code': 'PCI_VIOLATION'}), 400
        escrow_hold = bool(data.get('escrow_hold'))
        metodo_pagamento = str(data.get('metodo_pagamento') or _row_get(order, 'metodo_pagamento', 'escrow')).strip().lower()
        if metodo_pagamento not in ('pix', 'cartao', 'boleto', 'escrow'):
            metodo_pagamento = 'escrow'

        if order['status'] in ('em_disputa', 'cancelado'):
            return jsonify({'error': f"Não é possível efetuar pagamento de pedido com status '{order['status']}'."}), 400

        escrow_atual = _row_get(order, 'escrow_status', 'pendente')
        if int(_row_get(order, 'pago', 0) or 0) == 1 or escrow_atual in ('retido', 'aguardando_liberacao', 'liberado'):
            return jsonify({'error': 'Pagamento já efetuado ou pedido já em escrow/liberado.'}), 409

        amount_cents = max(1, int(round(float(_row_get(order, 'preco_total', 0.0) or 0.0) * 100)))
        cursor = conn.cursor()
        if (escrow_hold and order['status'] != 'finalizado') or order['status'] in ('solicitado', 'confirmado', 'em_transito'):
            cursor.execute('''
                UPDATE orders
                SET pago = 1, escrow_status = 'retido', metodo_pagamento = ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND pago = 0 AND status NOT IN ('finalizado', 'cancelado', 'em_disputa')
                  AND COALESCE(escrow_status, 'pendente') NOT IN ('retido', 'aguardando_liberacao', 'liberado')
            ''', (metodo_pagamento, order_id))
            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({'error': 'Pagamento já processado ou estado inválido.'}), 409
            _log_escrow_ledger(
                conn, order_id, 'escrow_hold', order['preco_total'], 'retido',
                f'Pagamento retido em Escrow ({metodo_pagamento})'
            )
            cursor.execute('''
                INSERT INTO payment_transactions (
                    public_id, order_id, user_id, gateway, method, status,
                    amount_cents, gateway_payment_id, escrow_synced, paid_at
                )
                VALUES (?, ?, ?, 'sandbox', ?, 'escrow_held', ?, ?, 1, CURRENT_TIMESTAMP)
            ''', (
                f"pay_{secrets.token_hex(12)}", order_id, user['id'], metodo_pagamento,
                amount_cents, f"sbx_legacy_{order_id}_{secrets.token_hex(6)}"
            ))
            conn.commit()
            return jsonify({
                'message': 'Pagamento retido em garantia (escrow) com sucesso!',
                'order_id': order_id,
                'status': order['status'],
                'pago': True,
                'escrow_status': 'retido',
                'metodo_pagamento': metodo_pagamento
            }), 200

        cursor.execute('''
            UPDATE orders 
            SET pago = 1, status = 'finalizado', escrow_status = 'liberado',
                confirmado_cliente = 1,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                released_at = CURRENT_TIMESTAMP,
                metodo_pagamento = ?, atualizado_em = CURRENT_TIMESTAMP 
            WHERE id = ? AND pago = 0 AND status NOT IN ('cancelado', 'em_disputa')
              AND COALESCE(escrow_status, 'pendente') NOT IN ('retido', 'aguardando_liberacao', 'liberado')
        ''', (metodo_pagamento, order_id))
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({'error': 'Pagamento já processado ou estado inválido.'}), 409
        _log_escrow_ledger(
            conn, order_id, 'escrow_release', order['preco_total'], 'liberado',
            f'Pagamento liberado na conclusão ({metodo_pagamento})'
        )
        cursor.execute('''
            INSERT INTO payment_transactions (
                public_id, order_id, user_id, gateway, method, status,
                amount_cents, gateway_payment_id, escrow_synced, paid_at
            )
            VALUES (?, ?, ?, 'sandbox', ?, 'released', ?, ?, 1, CURRENT_TIMESTAMP)
        ''', (
            f"pay_{secrets.token_hex(12)}", order_id, user['id'], metodo_pagamento,
            amount_cents, f"sbx_legacy_{order_id}_{secrets.token_hex(6)}"
        ))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Pagamento confirmado e pedido finalizado com sucesso!',
        'order_id': order_id,
        'status': 'finalizado',
        'escrow_status': 'liberado',
        'pago': True
    }), 200


@app.route('/api/orders', methods=['GET'])
def list_orders():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Acesso não autorizado.'}), 401

    conn = get_db_connection()
    if user['tipo'] == 'cliente':
        sql = '''
            SELECT 
                o.id AS order_id,
                o.status,
                o.preco_total,
                o.observacoes,
                o.complemento_cliente,
                o.modalidade,
                o.agendado_para,
                o.metodo_pagamento,
                o.pago,
                o.codigo_confirmacao,
                o.motivo_cancelamento,
                o.escrow_status,
                o.taxa_deslocamento,
                o.valor_estornado,
                o.share_token,
                o.confirmado_cliente,
                o.release_due_at,
                EXISTS(SELECT 1 FROM reviews r WHERE r.order_id = o.id AND COALESCE(r.autor_tipo, 'cliente') = 'cliente') AS ja_avaliado,
                o.criado_em,
                COALESCE(s.titulo, 'Serviço Solicitado') AS servico_titulo,
                COALESCE(s.categoria, 'Geral') AS servico_categoria,
                u.id AS prestador_id,
                COALESCE(u.nome, 'Profissional') AS prestador_nome,
                u.telefone AS prestador_telefone,
                COALESCE(s.endereco, u.endereco) AS prestador_endereco,
                COALESCE(s.numero, u.numero) AS prestador_numero,
                COALESCE(s.bairro, u.bairro) AS prestador_bairro,
                COALESCE(s.cidade, u.cidade) AS prestador_cidade,
                COALESCE(s.estado, u.estado) AS prestador_estado,
                COALESCE(s.lat, u.lat) AS prestador_lat,
                COALESCE(s.lng, u.lng) AS prestador_lng
            FROM orders o
            LEFT JOIN services s ON o.servico_id = s.id
            LEFT JOIN users u ON o.prestador_id = u.id
            WHERE o.cliente_id = ?
            ORDER BY o.criado_em DESC
        '''
        orders = conn.execute(sql, (user['id'],)).fetchall()
    else:
        # Prestador vê os pedidos recebidos com o endereço real do cliente
        sql = '''
            SELECT 
                o.id AS order_id,
                o.status,
                o.preco_total,
                o.observacoes,
                o.cep_cliente,
                o.endereco_cliente,
                o.numero_cliente,
                o.complemento_cliente,
                o.bairro_cliente,
                o.cidade_cliente,
                o.estado_cliente,
                o.lat_cliente,
                o.lng_cliente,
                o.modalidade,
                o.agendado_para,
                o.metodo_pagamento,
                o.pago,
                o.codigo_confirmacao,
                o.motivo_cancelamento,
                o.escrow_status,
                o.taxa_deslocamento,
                o.valor_estornado,
                o.share_token,
                o.confirmado_cliente,
                o.release_due_at,
                EXISTS(SELECT 1 FROM reviews r WHERE r.order_id = o.id AND COALESCE(r.autor_tipo, 'cliente') = 'prestador') AS ja_avaliado,
                o.criado_em,
                COALESCE(s.titulo, 'Serviço Solicitado') AS servico_titulo,
                COALESCE(s.categoria, 'Geral') AS servico_categoria,
                u.id AS cliente_id,
                COALESCE(u.nome, 'Cliente') AS cliente_nome,
                u.telefone AS cliente_telefone
            FROM orders o
            LEFT JOIN services s ON o.servico_id = s.id
            LEFT JOIN users u ON o.cliente_id = u.id
            WHERE o.prestador_id = ?
            ORDER BY o.criado_em DESC
        '''
        orders = conn.execute(sql, (user['id'],)).fetchall()

    counterpart_tipo = 'prestador' if user['tipo'] == 'cliente' else 'cliente'
    counterpart_reviews = {}
    order_ids = [o['order_id'] for o in orders]
    if order_ids:
        placeholders = ','.join(['?'] * len(order_ids))
        rev_rows = conn.execute(
            f"SELECT id, order_id, revealed_at, criado_em, replied_at, contestada FROM reviews WHERE order_id IN ({placeholders}) AND COALESCE(autor_tipo, 'cliente') = ?",
            (*order_ids, counterpart_tipo)
        ).fetchall()
        for rr in rev_rows:
            if _is_review_revealed(rr):
                counterpart_reviews[rr['order_id']] = {
                    'id': rr['id'],
                    'replied': _row_get(rr, 'replied_at') is not None,
                    'contestada': bool(int(_row_get(rr, 'contestada', 0) or 0)),
                }

    conn.close()
    mask_pii = request.args.get('mask_pii') == '1'
    result = []
    for o in orders:
        item = dict(o)
        item['ja_avaliado'] = bool(item.get('ja_avaliado'))
        item['confirmado_cliente'] = bool(int(item.get('confirmado_cliente') or 0))
        item['release_due_at'] = str(item['release_due_at']) if item.get('release_due_at') else None
        rev_info = counterpart_reviews.get(item['order_id'])
        item['cliente_review_id'] = rev_info['id'] if rev_info else None
        item['cliente_review_replied'] = bool(rev_info['replied']) if rev_info else False
        item['cliente_review_contestada'] = bool(rev_info['contestada']) if rev_info else False
        item['escrow_status'] = item.get('escrow_status') or 'pendente'
        item['taxa_deslocamento'] = float(item.get('taxa_deslocamento') or 0.0)
        item['valor_estornado'] = float(item.get('valor_estornado') or 0.0)
        item['em_disputa'] = (item.get('status') == 'em_disputa')

        if user['tipo'] == 'prestador':
            # ET-02 / ET-04 / ET-15: Prestador nunca recebe o PIN e telefone do cliente é sempre mascarado
            item['codigo_confirmacao'] = None
            item['pin_obrigatorio'] = True
            bairro = item.get('bairro_cliente') or ''
            cidade = item.get('cidade_cliente') or 'São Paulo'
            st = item.get('status')
            item['endereco_protegido'] = (st not in ('confirmado', 'em_transito', 'em_execucao'))
            item['endereco_cliente_resumo'] = f"{bairro}, {cidade}".strip(', ')
            item['cliente_telefone'] = _mask_phone(item.get('cliente_telefone'))
            if mask_pii or st not in ('confirmado', 'em_transito', 'em_execucao'):
                item['endereco_cliente'] = 'Protegido'
                item['numero_cliente'] = ''
                item['complemento_cliente'] = ''
                item['cep_cliente'] = ''
                item['lat_cliente'] = None
                item['lng_cliente'] = None
        else:
            # ET-04 / ET-15: Para cliente, endereço/coordenadas/telefone do prestador são sempre protegidos
            item['prestador_endereco'] = 'Protegido'
            item['prestador_numero'] = ''
            item['prestador_lat'] = None
            item['prestador_lng'] = None
            item['prestador_telefone'] = _mask_phone(item.get('prestador_telefone'))

        result.append(item)
    return jsonify(result)


@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
@rate_limit(30, 60)
def update_order_status(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Não autenticado.'}), 401

    data = request.get_json() or {}
    novo_status = data.get('status')
    motivo = str(data.get('motivo') or '').strip()[:500]
    valid_statuses = ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'finalizado', 'cancelado', 'em_disputa')
    if novo_status not in valid_statuses:
        return jsonify({'error': f'Status inválido. Escolha: {", ".join(valid_statuses)}'}), 400

    if _row_get(user, 'status_conta', 'ativo') != 'ativo' and novo_status != 'cancelado':
        return jsonify({'error': 'Conta suspensa cautelarmente ou bloqueada não pode avançar ou confirmar chamados.'}), 403

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404

        # Apenas o prestador designado ou o cliente da ordem podem alterar o status
        if user['tipo'] == 'prestador' and order['prestador_id'] != user['id']:
            return jsonify({'error': 'Sem permissão para alterar este pedido.'}), 403
        if user['tipo'] == 'cliente' and order['cliente_id'] != user['id']:
            return jsonify({'error': 'Sem permissão para alterar este pedido.'}), 403

        atual_status = order['status']
        if atual_status == 'cancelado':
            return jsonify({'error': 'Não é permitido alterar um pedido cancelado.'}), 400

        if novo_status == 'em_disputa':
            return jsonify({'error': 'Para abrir disputa, utilize POST /api/orders/<id>/dispute.'}), 400

        # ET-07: Grafo estrito de transições + papel do ator
        allowed_transitions = {
            'solicitado': {'confirmado', 'cancelado'},
            'confirmado': {'em_transito', 'cancelado'},
            'em_transito': {'em_execucao', 'cancelado'},
            'em_execucao': {'finalizado', 'cancelado'},
            'finalizado': {'finalizado'},
        }
        if atual_status not in allowed_transitions or novo_status not in allowed_transitions[atual_status]:
            return jsonify({'error': f'Transição inválida de {atual_status} para {novo_status}.'}), 400

        if novo_status in ('confirmado', 'em_transito', 'em_execucao') and user['tipo'] != 'prestador':
            return jsonify({'error': f'Apenas o prestador pode alterar o status para {novo_status}.'}), 403

        if atual_status == 'finalizado' and novo_status == 'finalizado' and user['tipo'] != 'cliente':
            return jsonify({'error': 'Apenas o cliente pode confirmar a conclusão do pedido finalizado.'}), 403

        if novo_status == 'cancelado' and not motivo:
            return jsonify({'error': 'Informe o motivo do cancelamento.'}), 400

        # ET-02 / ET-07: Validação obrigatória de PIN ao iniciar execução (trava após 5 tentativas, fail-closed)
        if novo_status == 'em_execucao':
            pin_tentativas = int(_row_get(order, 'pin_tentativas', 0) or 0)
            if pin_tentativas >= 5:
                return jsonify({'error': 'Limite de 5 tentativas de PIN excedido. Pedido bloqueado por segurança.'}), 429
            pin_esperado = str(_row_get(order, 'codigo_confirmacao', '') or '').strip()
            if not pin_esperado:
                return jsonify({'error': 'Código de confirmação (PIN) ausente no pedido.'}), 400
            pin_informado = str(data.get('codigo_confirmacao') or '').strip()
            if not pin_informado or pin_informado != pin_esperado:
                conn.execute(
                    'UPDATE orders SET pin_tentativas = COALESCE(pin_tentativas, 0) + 1, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?',
                    (order_id,)
                )
                conn.commit()
                return jsonify({
                    'error': 'Código de confirmação (PIN) obrigatório e deve corresponder ao informado pelo cliente.',
                    'pin_tentativas': pin_tentativas + 1
                }), 400

        escrow_status = _row_get(order, 'escrow_status', 'pendente')
        taxa_deslocamento = float(_row_get(order, 'taxa_deslocamento', 0.0) or 0.0)
        valor_estornado = float(_row_get(order, 'valor_estornado', 0.0) or 0.0)
        pago_int = int(_row_get(order, 'pago', 0) or 0)
        preco = float(_row_get(order, 'preco_total', 0.0) or 0.0)
        release_due_at = _row_get(order, 'release_due_at')
        confirmado_cli = int(_row_get(order, 'confirmado_cliente', 0) or 0)

        cursor = conn.cursor()
        if novo_status == 'cancelado':
            if atual_status == 'em_execucao' and pago_int == 1 and user['tipo'] == 'cliente':
                return jsonify({'error': 'Pedido em execução e já pago exige abertura de mediação (/dispute).'}), 400
            if pago_int == 1:
                if atual_status in ('em_transito', 'em_execucao') and user['tipo'] == 'cliente':
                    taxa_deslocamento = min(round(preco * 0.20, 2), 40.0)
                    valor_estornado = round(max(0.0, preco - taxa_deslocamento), 2)
                    escrow_status = 'estornado_parcial'
                else:
                    taxa_deslocamento = 0.0
                    valor_estornado = preco
                    escrow_status = 'estornado_total'
                _log_escrow_ledger(
                    conn, order_id, 'escrow_refund', valor_estornado, escrow_status,
                    f'Cancelamento ({atual_status}): {motivo}'
                )
            cursor.execute('''
                UPDATE orders 
                SET status = ?, motivo_cancelamento = ?, escrow_status = ?,
                    taxa_deslocamento = ?, valor_estornado = ?, atualizado_em = CURRENT_TIMESTAMP 
                WHERE id = ? AND status != 'cancelado'
            ''', (novo_status, motivo, escrow_status, taxa_deslocamento, valor_estornado, order_id))
            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({'error': 'Conflito ao atualizar status do pedido.'}), 409
        elif novo_status == 'finalizado':
            if user['tipo'] == 'cliente':
                if confirmado_cli == 1 or escrow_status == 'liberado':
                    return jsonify({'error': 'Conclusão do pedido já foi confirmada anteriormente.'}), 409
                if pago_int == 1:
                    escrow_status = 'liberado'
                    _log_escrow_ledger(
                        conn, order_id, 'escrow_release', preco, 'liberado',
                        'Confirmação de conclusão pelo cliente'
                    )
                else:
                    escrow_status = 'pendente'
                cursor.execute('''
                    UPDATE orders 
                    SET status = ?, escrow_status = ?, confirmado_cliente = 1,
                        completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                        released_at = CASE WHEN pago = 1 THEN CURRENT_TIMESTAMP ELSE released_at END,
                        atualizado_em = CURRENT_TIMESTAMP 
                    WHERE id = ? AND COALESCE(confirmado_cliente, 0) = 0 AND COALESCE(escrow_status, 'pendente') != 'liberado'
                ''', (novo_status, escrow_status, order_id))
                if cursor.rowcount != 1:
                    conn.rollback()
                    return jsonify({'error': 'Conclusão já confirmada.'}), 409
            else:
                if atual_status == 'finalizado':
                    return jsonify({'error': 'Pedido já finalizado.'}), 409
                if pago_int == 1:
                    release_due_at = (datetime.utcnow() + timedelta(hours=48)).strftime('%Y-%m-%d %H:%M:%S')
                    escrow_status = 'aguardando_liberacao'
                    _log_escrow_ledger(
                        conn, order_id, 'escrow_48h_window', preco, 'aguardando_liberacao',
                        f'Janela de liberação 48h iniciada até {release_due_at}'
                    )
                cursor.execute('''
                    UPDATE orders 
                    SET status = ?, escrow_status = ?,
                        completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                        release_due_at = COALESCE(?, release_due_at),
                        atualizado_em = CURRENT_TIMESTAMP 
                    WHERE id = ? AND status = 'em_execucao'
                ''', (novo_status, escrow_status, release_due_at, order_id))
                if cursor.rowcount != 1:
                    conn.rollback()
                    return jsonify({'error': 'Conflito ao finalizar pedido.'}), 409
        else:
            conn.execute('''
                UPDATE orders 
                SET status = ?, atualizado_em = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (novo_status, order_id))

        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': f'Status do pedido atualizado para {novo_status}.',
        'status': novo_status,
        'escrow_status': escrow_status,
        'taxa_deslocamento': taxa_deslocamento,
        'valor_estornado': valor_estornado,
        'release_due_at': str(release_due_at) if release_due_at else None
    })


@app.route('/api/orders/<int:order_id>/confirm-completion', methods=['POST'])
def confirm_order_completion(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401
    if user['tipo'] != 'cliente':
        return jsonify({'error': 'Apenas o cliente pode confirmar a conclusão do serviço.'}), 403
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if order['cliente_id'] != user['id']:
            return jsonify({'error': 'Sem permissão para confirmar este pedido.'}), 403
        if order['status'] not in ('em_execucao', 'finalizado'):
            return jsonify({'error': f"Pedido em status '{order['status']}' não pode ser confirmado."}), 400

        escrow_status = _row_get(order, 'escrow_status', 'pendente')
        confirmado_cli = int(_row_get(order, 'confirmado_cliente', 0) or 0)
        if confirmado_cli == 1 or escrow_status == 'liberado':
            return jsonify({'error': 'Conclusão do pedido já foi confirmada anteriormente.'}), 409

        pago_int = int(_row_get(order, 'pago', 0) or 0)
        if pago_int == 1:
            escrow_status = 'liberado'
            _log_escrow_ledger(
                conn, order_id, 'escrow_release', order['preco_total'], 'liberado',
                'Confirmação de conclusão via /confirm-completion'
            )
        else:
            escrow_status = 'pendente'

        cursor = conn.cursor()
        cursor.execute('''
            UPDATE orders
            SET status = 'finalizado',
                confirmado_cliente = 1,
                escrow_status = ?,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                released_at = CASE WHEN pago = 1 THEN CURRENT_TIMESTAMP ELSE released_at END,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND COALESCE(confirmado_cliente, 0) = 0 AND COALESCE(escrow_status, 'pendente') != 'liberado'
        ''', (escrow_status, order_id))
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({'error': 'Conclusão já confirmada anteriormente.'}), 409
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Conclusão confirmada e pagamento liberado com sucesso!',
        'order_id': order_id,
        'status': 'finalizado',
        'confirmado_cliente': True,
        'escrow_status': escrow_status
    }), 200


@app.route('/api/orders/<int:order_id>/dispute', methods=['POST'])
@rate_limit(10, 60)
def open_order_dispute(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    motivo = str(data.get('motivo') or '').strip()[:500]
    descricao = str(data.get('descricao') or data.get('evidencias') or '').strip()[:2000]
    if not motivo:
        return jsonify({'error': 'Informe o motivo da disputa.'}), 400

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para abrir disputa neste pedido.'}), 403
        if order['status'] == 'em_disputa':
            return jsonify({'error': 'Este pedido já possui disputa aberta.'}), 409
        if order['status'] not in ('confirmado', 'em_transito', 'em_execucao', 'finalizado'):
            return jsonify({'error': f"Não é possível abrir disputa para pedido com status '{order['status']}'."}), 400

        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO disputes (order_id, opened_by, motivo, descricao, status)
                VALUES (?, ?, ?, ?, 'aberta')
            ''', (order_id, user['id'], motivo, descricao))
        except DBIntegrityError:
            conn.rollback()
            return jsonify({'error': 'Já existe uma disputa aberta para este pedido.'}), 409
        dispute_id = cursor.lastrowid
        conn.execute('''
            UPDATE orders
            SET status = 'em_disputa', escrow_status = 'em_disputa', atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (order_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Disputa aberta com sucesso. O valor permanece retido em garantia durante a mediação.',
        'dispute_id': dispute_id,
        'order_id': order_id,
        'status': 'em_disputa',
        'escrow_status': 'em_disputa'
    }), 201


@app.route('/api/provider/financial-summary', methods=['GET'])
def provider_financial_summary():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401
    if user['tipo'] != 'prestador':
        return jsonify({'error': 'Acesso exclusivo para prestadores.'}), 403

    current_ym = datetime.utcnow().strftime('%Y-%m')
    plano = _row_get(user, 'plano', 'basico')
    taxa_percentual = 0.08 if plano == 'pro' else 0.12

    conn = get_db_connection()
    try:
        orders = conn.execute('''
            SELECT status, pago, preco_total, escrow_status, release_due_at, criado_em, completed_at
            FROM orders
            WHERE prestador_id = ?
        ''', (user['id'],)).fetchall()
    finally:
        conn.close()

    faturamento_bruto_mes = 0.0
    saldo_escrow_retido = 0.0
    escrow_aguardando_48h = 0.0
    total_liberado = 0.0
    now_utc = datetime.utcnow()

    for o in orders:
        preco = float(_row_get(o, 'preco_total', 0.0) or 0.0)
        status = _row_get(o, 'status', '')
        pago = int(_row_get(o, 'pago', 0) or 0)
        escrow_st = _row_get(o, 'escrow_status', 'pendente')
        ref_dt = str(_row_get(o, 'completed_at') or _row_get(o, 'criado_em') or '')

        if status == 'finalizado' and pago == 1:
            if ref_dt.startswith(current_ym):
                faturamento_bruto_mes += preco
            if escrow_st == 'liberado':
                total_liberado += preco
            elif escrow_st == 'aguardando_liberacao':
                due_dt = _parse_dt(_row_get(o, 'release_due_at'))
                if due_dt is not None and due_dt <= now_utc:
                    total_liberado += preco
                else:
                    saldo_escrow_retido += preco
                    escrow_aguardando_48h += preco
            else:
                saldo_escrow_retido += preco
        elif pago == 1 and status not in ('finalizado', 'cancelado') and escrow_st not in ('estornado_total', 'estornado_parcial'):
            saldo_escrow_retido += preco

    faturamento_bruto_mes = round(faturamento_bruto_mes, 2)
    saldo_escrow_retido = round(saldo_escrow_retido, 2)
    escrow_aguardando_48h = round(escrow_aguardando_48h, 2)
    total_liberado = round(total_liberado, 2)
    total_liberado_liquido = round(total_liberado * (1.0 - taxa_percentual), 2)
    isento_mensalidade = (plano == 'basico' and faturamento_bruto_mes <= 1800.0)

    return jsonify({
        'mes_referencia': current_ym,
        'plano': plano,
        'taxa_percentual': taxa_percentual,
        'faturamento_bruto_mes': faturamento_bruto_mes,
        'isento_mensalidade': isento_mensalidade,
        'saldo_escrow_retido': saldo_escrow_retido,
        'escrow_aguardando_48h': escrow_aguardando_48h,
        'total_liberado': total_liberado,
        'total_liberado_liquido': total_liberado_liquido
    }), 200


@app.route('/api/orders/<int:order_id>/review', methods=['POST'])
def review_order(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória para avaliar pedido.', 'code': 'UNAUTHORIZED'}), 401
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    raw_nota = data.get('nota')
    try:
        if isinstance(raw_nota, bool) or raw_nota is None:
            raise ValueError()
        nota_f = float(raw_nota)
        if not math.isfinite(nota_f) or nota_f < 1 or nota_f > 5 or nota_f != int(nota_f):
            raise ValueError()
        nota = int(nota_f)
    except (ValueError, TypeError):
        return jsonify({'error': 'A nota deve ser um número inteiro entre 1 e 5.'}), 400

    comentario = str(data.get('comentario') or '').strip()[:2000]

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.', 'code': 'NOT_FOUND'}), 404

        if user['tipo'] == 'cliente':
            if order['cliente_id'] != user['id']:
                return jsonify({'error': 'Sem permissão para avaliar pedido de outro cliente.', 'code': 'FORBIDDEN'}), 403
            autor_tipo = 'cliente'
            avaliado_id = order['prestador_id']
        elif user['tipo'] == 'prestador':
            if order['prestador_id'] != user['id']:
                return jsonify({'error': 'Sem permissão para avaliar pedido de outro prestador.', 'code': 'FORBIDDEN'}), 403
            autor_tipo = 'prestador'
            avaliado_id = order['cliente_id']
        else:
            return jsonify({'error': 'Tipo de usuário inválido.', 'code': 'FORBIDDEN'}), 403

        if order['status'] != 'finalizado':
            return jsonify({'error': 'Apenas pedidos finalizados podem ser avaliados.'}), 400

        existing = conn.execute(
            "SELECT id FROM reviews WHERE order_id = ? AND COALESCE(autor_tipo, 'cliente') = ?",
            (order_id, autor_tipo)
        ).fetchone()
        if existing:
            return jsonify({'error': 'Este pedido já foi avaliado por você.'}), 409

        # Captura estado anterior do avaliado antes de inserir (preserva seed total_avaliacoes=15)
        target_user = conn.execute(
            'SELECT avaliacao_media, total_avaliacoes FROM users WHERE id = ?',
            (avaliado_id,)
        ).fetchone()
        old_total = int(_row_get(target_user, 'total_avaliacoes', 0) or 0)
        old_media = float(_row_get(target_user, 'avaliacao_media', 5.0) or 5.0)
        prev_real_row = conn.execute(
            'SELECT COUNT(*) AS cnt FROM reviews WHERE avaliado_id = ? OR (avaliado_id IS NULL AND prestador_id = ?)',
            (avaliado_id, avaliado_id)
        ).fetchone()
        prev_real_count = int(_row_get(prev_real_row, 'cnt', 0) or 0)

        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO reviews (order_id, cliente_id, prestador_id, nota, comentario, autor_tipo, avaliado_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (order_id, order['cliente_id'], order['prestador_id'], nota, comentario, autor_tipo, avaliado_id))
        except DBIntegrityError:
            conn.rollback()
            return jsonify({'error': 'Este pedido já foi avaliado por você.'}), 409
        review_id = cursor.lastrowid

        if old_total > prev_real_count:
            novo_total = old_total + 1
            nova_media = round(((old_media * old_total) + nota) / novo_total, 2)
        else:
            stats = conn.execute(
                'SELECT AVG(nota) AS media, COUNT(*) AS total FROM reviews WHERE avaliado_id = ? OR (avaliado_id IS NULL AND prestador_id = ?)',
                (avaliado_id, avaliado_id)
            ).fetchone()
            nova_media = round(float(stats['media']), 2) if stats and stats['media'] is not None else nota
            novo_total = int(stats['total']) if stats and stats['total'] is not None else 1

        conn.execute(
            'UPDATE users SET avaliacao_media = ?, total_avaliacoes = ? WHERE id = ?',
            (nova_media, novo_total, avaliado_id)
        )

        other_tipo = 'prestador' if autor_tipo == 'cliente' else 'cliente'
        other_rev = conn.execute(
            "SELECT id FROM reviews WHERE order_id = ? AND COALESCE(autor_tipo, 'cliente') = ?",
            (order_id, other_tipo)
        ).fetchone()
        revealed = bool(other_rev)
        if revealed:
            conn.execute(
                'UPDATE reviews SET revealed_at = CURRENT_TIMESTAMP WHERE order_id = ?',
                (order_id,)
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Avaliação registrada com sucesso!',
        'review_id': review_id,
        'autor_tipo': autor_tipo,
        'avaliacao_media': nova_media,
        'total_avaliacoes': novo_total,
        'revealed': revealed
    }), 201


@app.route('/api/orders/<int:order_id>/reviews', methods=['GET'])
def get_order_reviews(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para visualizar avaliações deste pedido.'}), 403

        rows = conn.execute('SELECT * FROM reviews WHERE order_id = ? ORDER BY id ASC', (order_id,)).fetchall()
    finally:
        conn.close()

    minha_avaliacao = None
    contraparte_raw = None
    for r in rows:
        r_tipo = _row_get(r, 'autor_tipo', 'cliente') or 'cliente'
        if r_tipo == user['tipo']:
            minha_avaliacao = dict(r)
        else:
            contraparte_raw = r

    oculta_double_blind = False
    contraparte_avaliacao = None
    if contraparte_raw is not None:
        if _is_review_revealed(contraparte_raw):
            contraparte_avaliacao = dict(contraparte_raw)
        else:
            oculta_double_blind = True

    return jsonify({
        'order_id': order_id,
        'minha_avaliacao': minha_avaliacao,
        'contraparte_avaliacao': contraparte_avaliacao,
        'oculta_double_blind': oculta_double_blind
    }), 200


@app.route('/api/reviews/<int:review_id>/reply', methods=['POST'])
def reply_review(review_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    replica = str(data.get('replica') or '').strip()[:2000]
    if not replica:
        return jsonify({'error': 'Informe o texto da réplica.'}), 400

    conn = get_db_connection()
    try:
        rev = conn.execute('SELECT * FROM reviews WHERE id = ?', (review_id,)).fetchone()
        if not rev:
            return jsonify({'error': 'Avaliação não encontrada.'}), 404
        avaliado_id = _row_get(rev, 'avaliado_id') or rev['prestador_id']
        if int(avaliado_id) != int(user['id']):
            return jsonify({'error': 'Apenas o usuário avaliado pode publicar uma réplica.'}), 403
        if not _is_review_revealed(rev):
            return jsonify({'error': 'Avaliação ainda oculta pelo modo double-blind.'}), 403
        if _row_get(rev, 'replied_at') is not None:
            return jsonify({'error': 'Réplica já publicada e não pode ser editada.'}), 409

        conn.execute(
            'UPDATE reviews SET replica = ?, replied_at = CURRENT_TIMESTAMP WHERE id = ?',
            (replica, review_id)
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({'message': 'Réplica publicada com sucesso.', 'review_id': review_id, 'replica': replica}), 200


@app.route('/api/reviews/<int:review_id>/contest', methods=['POST'])
def contest_review(review_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    motivo = str(data.get('motivo') or '').strip()[:500]
    if not motivo:
        return jsonify({'error': 'Informe o motivo da contestação.'}), 400

    conn = get_db_connection()
    try:
        rev = conn.execute('SELECT * FROM reviews WHERE id = ?', (review_id,)).fetchone()
        if not rev:
            return jsonify({'error': 'Avaliação não encontrada.'}), 404
        avaliado_id = _row_get(rev, 'avaliado_id') or rev['prestador_id']
        if int(avaliado_id) != int(user['id']):
            return jsonify({'error': 'Apenas o usuário avaliado pode contestar esta avaliação.'}), 403
        if not _is_review_revealed(rev):
            return jsonify({'error': 'Avaliação ainda oculta pelo modo double-blind.'}), 403
        if int(_row_get(rev, 'contestada', 0) or 0) == 1:
            return jsonify({'error': 'Esta avaliação já foi contestada anteriormente.'}), 409

        conn.execute(
            "UPDATE reviews SET contestada = 1, motivo_contestacao = ?, status_moderacao = 'em_revisao' WHERE id = ?",
            (motivo, review_id)
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Contestação registrada e encaminhada para revisão.',
        'review_id': review_id,
        'status_moderacao': 'em_revisao'
    }), 200


@app.route('/api/orders/<int:order_id>/sos', methods=['POST'])
@rate_limit(10, 60)
def trigger_order_sos(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    descricao = str(data.get('descricao') or 'Acionamento de emergência SOS').strip()[:1000]
    tipo = str(data.get('tipo') or 'sos').strip()[:40]
    lat = safe_coord(data.get('lat'), safe_coord(user['lat'], -23.5653, -90.0, 90.0), -90.0, 90.0)
    lng = safe_coord(data.get('lng'), safe_coord(user['lng'], -46.6517, -180.0, 180.0), -180.0, 180.0)
    denunciar = bool(data.get('denunciar_contraparte'))

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para acionar SOS neste pedido.'}), 403
        if order['status'] in ('finalizado', 'cancelado'):
            return jsonify({'error': 'Não é possível acionar SOS para pedido já encerrado.'}), 400

        contraparte_id = order['prestador_id'] if user['id'] == order['cliente_id'] else order['cliente_id']
        pode_suspender = bool(denunciar and order['status'] in ('confirmado', 'em_transito', 'em_execucao'))
        inc_status = 'moderacao' if (denunciar and not pode_suspender) else 'aberto'

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO safety_incidents (order_id, reporter_id, reported_user_id, tipo, descricao, lat, lng, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, user['id'], contraparte_id if denunciar else None, tipo, descricao, lat, lng, inc_status))
        incident_id = cursor.lastrowid

        if pode_suspender:
            conn.execute(
                "UPDATE users SET status_conta = 'suspenso_cautelar' WHERE id = ? AND COALESCE(status_conta, 'ativo') = 'ativo'",
                (contraparte_id,)
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Alerta SOS registrado com prioridade máxima.',
        'incident_id': incident_id,
        'status': inc_status,
        'contraparte_suspensa': pode_suspender
    }), 201


@app.route('/api/orders/<int:order_id>/share-route', methods=['POST'])
def share_order_route(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para compartilhar rota deste pedido.'}), 403

        token = _row_get(order, 'share_token') or secrets.token_urlsafe(16)
        conn.execute('UPDATE orders SET share_token = ? WHERE id = ?', (token, order_id))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'share_token': token,
        'share_url': f'/api/shared-route/{token}'
    }), 200


@app.route('/api/shared-route/<token>', methods=['GET'])
def get_shared_route(token):
    conn = get_db_connection()
    try:
        row = conn.execute('''
            SELECT o.id AS order_id, o.status, o.bairro_cliente, o.cidade_cliente,
                   o.atualizado_em, s.titulo AS servico_titulo, u.nome AS prestador_nome
            FROM orders o
            LEFT JOIN services s ON o.servico_id = s.id
            LEFT JOIN users u ON o.prestador_id = u.id
            WHERE o.share_token = ?
        ''', (token,)).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({'error': 'Link de compartilhamento inválido ou expirado.'}), 404
    if row['status'] in ('finalizado', 'cancelado'):
        return jsonify({'error': 'Link de compartilhamento expirado pois o pedido foi encerrado.'}), 410

    return jsonify({
        'order_id': row['order_id'],
        'status': row['status'],
        'servico_titulo': row['servico_titulo'],
        'prestador_nome': row['prestador_nome'],
        'bairro_cliente': row['bairro_cliente'],
        'cidade_cliente': row['cidade_cliente'],
        'atualizado_em': str(row['atualizado_em'])
    }), 200


@app.route('/api/account/appeal', methods=['POST'])
def create_account_appeal():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    data = request.get_json(silent=True) or {}
    motivo = str(data.get('motivo') or '').strip()
    evidencias = str(data.get('evidencias') or '').strip()
    if not motivo:
        return jsonify({'error': 'Informe a justificativa do recurso.'}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO account_appeals (user_id, motivo, evidencias, status)
            VALUES (?, ?, ?, 'em_analise')
        ''', (user['id'], motivo, evidencias))
        appeal_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Recurso registrado para revisão humana.',
        'appeal_id': appeal_id,
        'status': 'em_analise'
    }), 201


@app.route('/api/orders/<int:order_id>/messages', methods=['GET', 'POST'])
@rate_limit(60, 60)
def order_messages(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para acessar o chat deste pedido.'}), 403

        if request.method == 'GET':
            rows = conn.execute('''
                SELECT m.id, m.order_id, m.sender_id, m.sender_tipo, m.mensagem, m.criado_em, u.nome AS sender_nome
                FROM order_messages m
                LEFT JOIN users u ON m.sender_id = u.id
                WHERE m.order_id = ?
                ORDER BY m.id ASC
            ''', (order_id,)).fetchall()
            return jsonify([dict(r) for r in rows]), 200

        if order['status'] in ('finalizado', 'cancelado'):
            return jsonify({'error': 'O chat é somente leitura após o encerramento do pedido.'}), 400

        acct_err = _require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        mensagem = str(data.get('mensagem') or '').strip()[:2000]
        if not mensagem:
            return jsonify({'error': 'A mensagem não pode estar vazia.'}), 400

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO order_messages (order_id, sender_id, sender_tipo, mensagem)
            VALUES (?, ?, ?, ?)
        ''', (order_id, user['id'], user['tipo'], mensagem))
        msg_id = cursor.lastrowid
        conn.commit()
        return jsonify({
            'id': msg_id,
            'order_id': order_id,
            'sender_id': user['id'],
            'sender_tipo': user['tipo'],
            'mensagem': mensagem
        }), 201
    finally:
        conn.close()


# ================= Sistema de Pagamentos Dual-Engine PCI-Safe =================

VALID_PAYMENT_GATEWAYS = ('sandbox', 'mercadopago', 'stripe', 'pagseguro')
VALID_PAYMENT_METHODS = ('pix', 'cartao', 'boleto', 'escrow')
FORBIDDEN_CARD_KEYS = {
    'card_number', 'pan', 'cvv', 'cvc', 'security_code', 'card_pan',
    'numero_cartao', 'codigo_seguranca'
}


def _contains_forbidden_card_fields(payload):
    """Rejeita recursivamente quaisquer chaves de PAN/CVV brutos (PCI-DSS)."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).strip().lower() in FORBIDDEN_CARD_KEYS:
                return True
            if _contains_forbidden_card_fields(v):
                return True
    elif isinstance(payload, list):
        for item in payload:
            if _contains_forbidden_card_fields(item):
                return True
    return False


def _compute_request_hash(payload_dict):
    canonical = json.dumps(payload_dict, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _extract_idempotency_key(data):
    key = request.headers.get('Idempotency-Key')
    if not key and isinstance(data, dict):
        key = data.get('idempotency_key')
    if key is None:
        return None
    key = str(key).strip()
    return key[:128] if key else None


def _check_idempotency(conn, user_id, scope, idempotency_key, request_hash):
    if not idempotency_key:
        return ('miss', None)
    row = conn.execute(
        'SELECT * FROM payment_idempotency_keys WHERE user_id = ? AND scope = ? AND idempotency_key = ?',
        (user_id, scope, idempotency_key)
    ).fetchone()
    if not row:
        return ('miss', None)
    if row['request_hash'] != request_hash:
        return ('conflict', None)
    if row['response_status'] is not None and row['response_body'] is not None:
        try:
            body = json.loads(row['response_body'])
        except Exception:
            body = {'status': 'ok'}
        return ('replay', (int(row['response_status']), body))
    return ('conflict', None)


def _save_idempotency(conn, user_id, scope, idempotency_key, request_hash, payment_id, response_status, response_body):
    if not idempotency_key:
        return None
    try:
        conn.execute('''
            INSERT INTO payment_idempotency_keys (
                user_id, scope, idempotency_key, request_hash, payment_id, response_status, response_body
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, scope, idempotency_key, request_hash, payment_id,
            int(response_status), json.dumps(response_body, ensure_ascii=False)
        ))
        return None
    except DBIntegrityError:
        conn.rollback()
        row = conn.execute(
            'SELECT * FROM payment_idempotency_keys WHERE user_id = ? AND scope = ? AND idempotency_key = ?',
            (user_id, scope, idempotency_key)
        ).fetchone()
        if row and row['request_hash'] == request_hash and row['response_status'] is not None:
            try:
                body = json.loads(row['response_body'])
            except Exception:
                body = response_body
            return ('replay', (int(row['response_status']), body))
        return ('conflict', None)


def _lookup_payment_tx(conn, payment_ref):
    ref = str(payment_ref or '').strip()
    if not ref:
        return None
    row = conn.execute('SELECT * FROM payment_transactions WHERE public_id = ?', (ref,)).fetchone()
    if row:
        return row
    if ref.isdigit():
        return conn.execute('SELECT * FROM payment_transactions WHERE id = ?', (int(ref),)).fetchone()
    return None


def _serialize_payment_tx(tx, is_provider=False):
    data = {
        'id': tx['id'],
        'payment_id': tx['public_id'],
        'public_id': tx['public_id'],
        'order_id': tx['order_id'],
        'user_id': tx['user_id'],
        'gateway': tx['gateway'],
        'method': tx['method'],
        'status': tx['status'],
        'amount_cents': int(tx['amount_cents']),
        'refunded_cents': int(_row_get(tx, 'refunded_cents', 0) or 0),
        'currency': _row_get(tx, 'currency', 'BRL'),
        'gateway_payment_id': _row_get(tx, 'gateway_payment_id'),
        'gateway_reference': _row_get(tx, 'gateway_reference'),
        'checkout_url': None if is_provider else _row_get(tx, 'checkout_url'),
        'pix_qr_code': None if is_provider else _row_get(tx, 'pix_qr_code'),
        'pix_qr_base64': None if is_provider else _row_get(tx, 'pix_qr_base64'),
        'boleto_barcode': _row_get(tx, 'boleto_barcode'),
        'boleto_digitable_line': _row_get(tx, 'boleto_digitable_line'),
        'boleto_url': None if is_provider else _row_get(tx, 'boleto_url'),
        'payment_method_id': None if is_provider else _row_get(tx, 'payment_method_id'),
        'escrow_synced': bool(int(_row_get(tx, 'escrow_synced', 0) or 0)),
        'failure_code': _row_get(tx, 'failure_code'),
        'failure_message': _row_get(tx, 'failure_message'),
        'expires_at': str(_row_get(tx, 'expires_at')) if _row_get(tx, 'expires_at') else None,
        'paid_at': str(_row_get(tx, 'paid_at')) if _row_get(tx, 'paid_at') else None,
        'criado_em': str(_row_get(tx, 'criado_em')) if _row_get(tx, 'criado_em') else None,
    }
    return data


def _settle_payment_and_sync_escrow(conn, payment, order):
    """Liquida pagamento de forma atômica e sincroniza estado de Escrow + razão."""
    order_id = order['id']
    payment_id = payment['id']
    method = _row_get(payment, 'method', 'escrow')
    preco = float(_row_get(order, 'preco_total', 0.0) or 0.0)

    if order['status'] in ('cancelado', 'em_disputa'):
        return (False, f"Pedido em status '{order['status']}' não pode ser liquidado.")

    cursor = conn.cursor()
    if order['status'] == 'finalizado':
        tx_status = 'released'
        new_escrow = 'liberado'
        cursor.execute('''
            UPDATE orders
            SET pago = 1, escrow_status = 'liberado', confirmado_cliente = 1,
                metodo_pagamento = ?, released_at = COALESCE(released_at, CURRENT_TIMESTAMP),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND pago = 0 AND status NOT IN ('cancelado', 'em_disputa')
        ''', (method, order_id))
        if cursor.rowcount != 1:
            return (False, 'Pedido já pago ou em estado inválido.')
        cursor.execute('''
            UPDATE payment_transactions
            SET status = 'released', escrow_synced = 1,
                paid_at = COALESCE(paid_at, CURRENT_TIMESTAMP),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND escrow_synced = 0
        ''', (payment_id,))
        if cursor.rowcount != 1:
            conn.rollback()
            return (False, 'Pagamento já sincronizado anteriormente.')
        _log_escrow_ledger(
            conn, order_id, 'escrow_release', preco, 'liberado',
            f'Pagamento liberado na conclusão ({method})'
        )
    else:
        tx_status = 'escrow_held'
        new_escrow = 'retido'
        cursor.execute('''
            UPDATE orders
            SET pago = 1, escrow_status = 'retido', metodo_pagamento = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND pago = 0 AND status NOT IN ('cancelado', 'em_disputa')
        ''', (method, order_id))
        if cursor.rowcount != 1:
            return (False, 'Pedido já pago ou em estado inválido.')
        cursor.execute('''
            UPDATE payment_transactions
            SET status = 'escrow_held', escrow_synced = 1,
                paid_at = COALESCE(paid_at, CURRENT_TIMESTAMP),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND escrow_synced = 0
        ''', (payment_id,))
        if cursor.rowcount != 1:
            conn.rollback()
            return (False, 'Pagamento já sincronizado anteriormente.')
        _log_escrow_ledger(
            conn, order_id, 'escrow_hold', preco, 'retido',
            f'Pagamento retido em Escrow ({method})'
        )
    return (True, {'status': tx_status, 'escrow_status': new_escrow})


@app.route('/api/payments/config', methods=['GET'])
@rate_limit(60, 60)
def get_payments_config():
    sandbox_enabled = is_sandbox_enabled()
    configs = list_gateway_configs()
    default_gateway = 'sandbox' if sandbox_enabled else next(
        (g['id'] for g in configs if g.get('configured')), 'mercadopago'
    )
    return jsonify({
        'default_gateway': default_gateway,
        'sandbox_enabled': sandbox_enabled,
        'gateways': configs
    }), 200


@app.route('/api/payments/methods', methods=['GET', 'POST'])
@rate_limit(30, 60)
def payment_methods_collection():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.', 'code': 'UNAUTHORIZED'}), 401

    conn = get_db_connection()
    try:
        if request.method == 'GET':
            rows = conn.execute('''
                SELECT id, public_id, gateway, brand, last4, exp_month, exp_year, holder_label, is_default, criado_em
                FROM payment_methods
                WHERE user_id = ? AND active = 1
                ORDER BY is_default DESC, id DESC
            ''', (user['id'],)).fetchall()
            return jsonify([dict(r) for r in rows]), 200

        acct_err = _require_active_account(user)
        if acct_err:
            return acct_err

        data = request.get_json(silent=True) or {}
        if _contains_forbidden_card_fields(data):
            return jsonify({'error': 'Dados brutos de cartão (PAN/CVV) não são permitidos.', 'code': 'PCI_VIOLATION'}), 400

        gateway = str(data.get('gateway') or 'sandbox').strip().lower()
        if gateway not in VALID_PAYMENT_GATEWAYS:
            return jsonify({'error': 'Gateway inválido.'}), 400
        if gateway == 'sandbox' and not is_sandbox_enabled():
            return jsonify({'error': 'Gateway sandbox desabilitado.'}), 403

        gateway_token = str(data.get('gateway_token') or '').strip()
        brand = str(data.get('brand') or '').strip()[:40]
        last4 = str(data.get('last4') or '').strip()
        holder_label = str(data.get('holder_label') or '').strip()[:80] or None
        gateway_customer_id = str(data.get('gateway_customer_id') or '').strip()[:120] or None
        is_default = 1 if data.get('is_default') else 0

        if not gateway_token or not brand or len(last4) != 4 or not last4.isdigit():
            return jsonify({'error': 'Token, bandeira e last4 (4 dígitos) são obrigatórios.'}), 400

        try:
            exp_month = int(data.get('exp_month'))
            exp_year = int(data.get('exp_year'))
        except (ValueError, TypeError):
            return jsonify({'error': 'Mês e ano de validade inválidos.'}), 400

        if not (1 <= exp_month <= 12) or exp_year < 2024:
            return jsonify({'error': 'Data de validade fora do intervalo permitido.'}), 400

        public_id = f"pm_{secrets.token_hex(12)}"
        cursor = conn.cursor()
        try:
            if is_default:
                cursor.execute('UPDATE payment_methods SET is_default = 0 WHERE user_id = ?', (user['id'],))
            cursor.execute('''
                INSERT INTO payment_methods (
                    public_id, user_id, gateway, gateway_customer_id, gateway_token,
                    brand, last4, exp_month, exp_year, holder_label, is_default, active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (
                public_id, user['id'], gateway, gateway_customer_id, gateway_token,
                brand, last4, exp_month, exp_year, holder_label, is_default
            ))
            method_id = cursor.lastrowid
            conn.commit()
        except DBIntegrityError:
            conn.rollback()
            return jsonify({'error': 'Método de pagamento já cadastrado para este gateway.'}), 409

        return jsonify({
            'id': method_id,
            'public_id': public_id,
            'gateway': gateway,
            'brand': brand,
            'last4': last4,
            'exp_month': exp_month,
            'exp_year': exp_year,
            'holder_label': holder_label,
            'is_default': bool(is_default)
        }), 201
    finally:
        conn.close()


@app.route('/api/payments/methods/<method_ref>', methods=['DELETE'])
@rate_limit(30, 60)
def delete_payment_method(method_ref):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.', 'code': 'UNAUTHORIZED'}), 401
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    conn = get_db_connection()
    try:
        ref = str(method_ref or '').strip()
        row = conn.execute('SELECT * FROM payment_methods WHERE public_id = ?', (ref,)).fetchone()
        if not row and ref.isdigit():
            row = conn.execute('SELECT * FROM payment_methods WHERE id = ?', (int(ref),)).fetchone()
        if not row or row['user_id'] != user['id']:
            return jsonify({'error': 'Método de pagamento não encontrado.'}), 404

        conn.execute('DELETE FROM payment_methods WHERE id = ? AND user_id = ?', (row['id'], user['id']))
        conn.commit()
        return jsonify({'message': 'Método de pagamento removido com sucesso.'}), 200
    finally:
        conn.close()


@app.route('/api/payments/intents', methods=['POST'])
@rate_limit(20, 60)
def create_payment_intent():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.', 'code': 'UNAUTHORIZED'}), 401
    if user['tipo'] != 'cliente':
        return jsonify({'error': 'Apenas clientes podem iniciar pagamentos.', 'code': 'FORBIDDEN'}), 403
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    if _contains_forbidden_card_fields(data):
        return jsonify({'error': 'Dados brutos de cartão (PAN/CVV) não são permitidos.', 'code': 'PCI_VIOLATION'}), 400

    try:
        order_id = int(data.get('order_id'))
    except (ValueError, TypeError):
        return jsonify({'error': 'order_id inválido.'}), 400

    gateway = str(data.get('gateway') or ('sandbox' if is_sandbox_enabled() else 'mercadopago')).strip().lower()
    if gateway not in VALID_PAYMENT_GATEWAYS:
        return jsonify({'error': 'Gateway de pagamento inválido.'}), 400
    if gateway == 'sandbox' and not is_sandbox_enabled():
        return jsonify({'error': 'Gateway sandbox desabilitado em produção.', 'code': 'SANDBOX_DISABLED'}), 403

    method = str(data.get('method') or data.get('metodo_pagamento') or 'pix').strip().lower()
    if method not in VALID_PAYMENT_METHODS:
        return jsonify({'error': 'Método de pagamento inválido.'}), 400

    payment_method_id = data.get('payment_method_id')
    if payment_method_id is not None:
        try:
            payment_method_id = int(payment_method_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'payment_method_id inválido.'}), 400

    idempotency_key = _extract_idempotency_key(data)

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if order['cliente_id'] != user['id']:
            return jsonify({'error': 'Sem permissão para pagar pedido de outro cliente.'}), 403
        if order['status'] in ('cancelado', 'em_disputa'):
            return jsonify({'error': f"Não é possível pagar pedido com status '{order['status']}'."}), 400

        escrow_atual = _row_get(order, 'escrow_status', 'pendente')
        if int(_row_get(order, 'pago', 0) or 0) == 1 or escrow_atual in ('retido', 'aguardando_liberacao', 'liberado'):
            return jsonify({'error': 'Pedido já pago ou em escrow.'}), 409

        amount_cents = int(round(float(_row_get(order, 'preco_total', 0.0) or 0.0) * 100))
        if amount_cents <= 0:
            return jsonify({'error': 'Valor do pedido inválido.'}), 400

        if data.get('amount_cents') is not None:
            try:
                client_cents = int(data.get('amount_cents'))
            except (ValueError, TypeError):
                return jsonify({'error': 'amount_cents inválido.'}), 400
            if client_cents != amount_cents:
                return jsonify({'error': 'Valor divergente do valor oficial do pedido.'}), 400

        if data.get('amount') is not None:
            try:
                client_amount_cents = int(round(float(data.get('amount')) * 100))
            except (ValueError, TypeError):
                return jsonify({'error': 'amount inválido.'}), 400
            if client_amount_cents != amount_cents:
                return jsonify({'error': 'Valor divergente do valor oficial do pedido.'}), 400

        payment_method_token = None
        if payment_method_id is not None:
            pm_row = conn.execute(
                'SELECT * FROM payment_methods WHERE id = ? AND user_id = ? AND active = 1',
                (payment_method_id, user['id'])
            ).fetchone()
            if not pm_row or pm_row['gateway'] != gateway:
                return jsonify({'error': 'Método de pagamento salvo não encontrado para este gateway.'}), 404
            payment_method_token = pm_row['gateway_token']

        req_hash = _compute_request_hash({
            'order_id': order_id,
            'gateway': gateway,
            'method': method,
            'amount_cents': amount_cents,
            'payment_method_id': payment_method_id,
        })
        idem_state, idem_payload = _check_idempotency(conn, user['id'], 'create_intent', idempotency_key, req_hash)
        if idem_state == 'conflict':
            return jsonify({'error': 'Chave de idempotência reutilizada com parâmetros diferentes.', 'code': 'IDEMPOTENCY_CONFLICT'}), 409
        if idem_state == 'replay':
            status_code, body = idem_payload
            return jsonify(body), status_code

        service_row = conn.execute(
            'SELECT titulo, descricao, categoria FROM services WHERE id = ?',
            (_row_get(order, 'servico_id'),)
        ).fetchone()
        item_title = _row_get(service_row, 'titulo', '') or f"Pedido PertoJá #{order_id}"
        item_description = _row_get(service_row, 'descricao', '') or f"Serviço contratado via PertoJá (Pedido #{order_id})"

        public_id = f"pay_{secrets.token_hex(12)}"
        raw_return = str(data.get('return_url') or '').strip()
        if not raw_return or raw_return.startswith('/'):
            rel_path = raw_return if raw_return.startswith('/') else f"/pedido.html?order_id={order_id}"
            base_url = os.environ.get('PAYMENT_RETURN_BASE_URL', '').strip().rstrip('/')
            if not base_url:
                req_root = (request.url_root or '').strip().rstrip('/')
                if req_root.startswith('https://') and 'localhost' not in req_root and '127.0.0.1' not in req_root:
                    base_url = req_root
            return_url = f"{base_url}{rel_path}" if base_url else rel_path
        else:
            return_url = raw_return

        payer_email = str(_row_get(user, 'email', '') or '').strip() or 'pagamentos@pertoja.com.br'
        payer = {
            'id': user['id'],
            'email': payer_email,
            'name': _row_get(user, 'nome', ''),
            'cpf': str(data.get('cpf') or _row_get(user, 'cpf', '') or ''),
            'telefone': _row_get(user, 'telefone', ''),
            'cep': _row_get(user, 'cep', '') or _row_get(order, 'cep_cliente', ''),
            'endereco': _row_get(user, 'endereco', '') or _row_get(order, 'endereco_cliente', ''),
            'numero': _row_get(user, 'numero', '') or _row_get(order, 'numero_cliente', ''),
            'bairro': _row_get(user, 'bairro', '') or _row_get(order, 'bairro_cliente', ''),
            'cidade': _row_get(user, 'cidade', '') or _row_get(order, 'cidade_cliente', ''),
            'estado': _row_get(user, 'estado', '') or _row_get(order, 'estado_cliente', ''),
        }

        try:
            adapter = get_payment_adapter(gateway)
            intent_res = adapter.create_intent(
                public_id=public_id,
                order_id=order_id,
                amount_cents=amount_cents,
                currency='BRL',
                method=method,
                description=f"Pedido PertoJá #{order_id}",
                payer=payer,
                return_url=return_url,
                payment_method_token=payment_method_token,
                metadata={
                    'order_id': order_id,
                    'user_id': user['id'],
                    'item_id': str(_row_get(order, 'servico_id') or order_id),
                    'item_title': item_title,
                    'item_description': item_description,
                    'category_id': 'services',
                },
            )
        except GatewayNotConfiguredError as exc:
            return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status
        except PaymentGatewayError as exc:
            return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status

        tx_status = intent_res.get('status') or 'requires_action'
        gateway_payment_id = intent_res.get('gateway_payment_id')
        gateway_reference = intent_res.get('gateway_reference')
        checkout_url = intent_res.get('checkout_url')
        pix_qr_code = intent_res.get('pix_qr_code')
        pix_qr_base64 = intent_res.get('pix_qr_base64')
        boleto_barcode = intent_res.get('boleto_barcode')
        boleto_digitable_line = intent_res.get('boleto_digitable_line')
        boleto_url = intent_res.get('boleto_url')
        expires_at = intent_res.get('expires_at') or None

        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO payment_transactions (
                    public_id, order_id, user_id, gateway, method, status,
                    amount_cents, currency, gateway_payment_id, gateway_reference,
                    checkout_url, pix_qr_code, pix_qr_base64,
                    boleto_barcode, boleto_digitable_line, boleto_url,
                    payment_method_id, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'BRL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                public_id, order_id, user['id'], gateway, method, tx_status,
                amount_cents, gateway_payment_id, gateway_reference,
                checkout_url, pix_qr_code, pix_qr_base64,
                boleto_barcode, boleto_digitable_line, boleto_url,
                payment_method_id, expires_at
            ))
            payment_id = cursor.lastrowid
        except DBIntegrityError:
            conn.rollback()
            return jsonify({'error': 'Transação duplicada detectada.'}), 409

        resp_body = {
            'payment_id': public_id,
            'id': payment_id,
            'order_id': order_id,
            'gateway': gateway,
            'method': method,
            'status': tx_status,
            'amount_cents': amount_cents,
            'currency': 'BRL',
            'checkout_url': checkout_url,
            'pix_qr_code': pix_qr_code,
            'pix_qr_base64': pix_qr_base64,
            'boleto_barcode': boleto_barcode,
            'boleto_digitable_line': boleto_digitable_line,
            'boleto_url': boleto_url,
            'expires_at': expires_at,
        }
        idem_race = _save_idempotency(
            conn, user['id'], 'create_intent', idempotency_key, req_hash, payment_id, 201, resp_body
        )
        if idem_race:
            race_state, race_payload = idem_race
            if race_state == 'conflict':
                return jsonify({'error': 'Conflito de idempotência.'}), 409
            return jsonify(race_payload[1]), race_payload[0]

        conn.commit()
        return jsonify(resp_body), 201
    finally:
        conn.close()


@app.route('/api/payments/order/<int:order_id>', methods=['GET'])
@rate_limit(60, 60)
def get_order_payments(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.', 'code': 'UNAUTHORIZED'}), 401

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para visualizar pagamentos deste pedido.'}), 403

        is_provider = (user['id'] == order['prestador_id'] and user['id'] != order['cliente_id'])
        rows = conn.execute(
            'SELECT * FROM payment_transactions WHERE order_id = ? ORDER BY id DESC',
            (order_id,)
        ).fetchall()
        return jsonify({
            'order_id': order_id,
            'pago': bool(int(_row_get(order, 'pago', 0) or 0)),
            'escrow_status': _row_get(order, 'escrow_status', 'pendente'),
            'metodo_pagamento': _row_get(order, 'metodo_pagamento', 'escrow'),
            'transactions': [_serialize_payment_tx(r, is_provider=is_provider) for r in rows]
        }), 200
    finally:
        conn.close()


@app.route('/api/payments/<payment_ref>', methods=['GET'])
@rate_limit(60, 60)
def get_payment_detail(payment_ref):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.', 'code': 'UNAUTHORIZED'}), 401

    conn = get_db_connection()
    try:
        tx = _lookup_payment_tx(conn, payment_ref)
        if not tx:
            return jsonify({'error': 'Pagamento não encontrado.'}), 404
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (tx['order_id'],)).fetchone()
        if not order or user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Pagamento não encontrado.'}), 404

        is_provider = (user['id'] == order['prestador_id'] and user['id'] != order['cliente_id'])
        return jsonify(_serialize_payment_tx(tx, is_provider=is_provider)), 200
    finally:
        conn.close()


@app.route('/api/payments/<payment_ref>/confirm', methods=['POST'])
@rate_limit(20, 60)
def confirm_payment_intent(payment_ref):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.', 'code': 'UNAUTHORIZED'}), 401
    if user['tipo'] != 'cliente':
        return jsonify({'error': 'Apenas o cliente pode confirmar o pagamento.'}), 403
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    idempotency_key = _extract_idempotency_key(data)
    simulate_outcome = str(data.get('simulate_outcome') or 'paid').strip().lower()
    if simulate_outcome not in ('paid', 'failed'):
        simulate_outcome = 'paid'

    conn = get_db_connection()
    try:
        tx = _lookup_payment_tx(conn, payment_ref)
        if not tx:
            return jsonify({'error': 'Pagamento não encontrado.'}), 404
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (tx['order_id'],)).fetchone()
        if not order or order['cliente_id'] != user['id']:
            return jsonify({'error': 'Pagamento não encontrado.'}), 404

        if tx['gateway'] == 'sandbox' and not is_sandbox_enabled():
            return jsonify({'error': 'Gateway sandbox desabilitado em produção.', 'code': 'SANDBOX_DISABLED'}), 403

        req_hash = _compute_request_hash({
            'payment_id': tx['id'],
            'simulate_outcome': simulate_outcome if tx['gateway'] == 'sandbox' else 'live',
        })
        idem_state, idem_payload = _check_idempotency(conn, user['id'], 'confirm_payment', idempotency_key, req_hash)
        if idem_state == 'conflict':
            return jsonify({'error': 'Chave de idempotência reutilizada com parâmetros diferentes.', 'code': 'IDEMPOTENCY_CONFLICT'}), 409
        if idem_state == 'replay':
            return jsonify(idem_payload[1]), idem_payload[0]

        if tx['status'] in ('escrow_held', 'released', 'paid') or int(_row_get(tx, 'escrow_synced', 0) or 0) == 1:
            return jsonify({'error': 'Pagamento já confirmado anteriormente.'}), 409
        if tx['status'] in ('failed', 'expired', 'cancelled', 'refunded', 'partially_refunded'):
            return jsonify({'error': f"Pagamento em estado terminal '{tx['status']}' não pode ser confirmado."}), 409

        try:
            adapter = get_payment_adapter(tx['gateway'])
            res = adapter.confirm_intent(
                gateway_payment_id=tx['gateway_payment_id'],
                method=tx['method'],
                simulate_outcome=simulate_outcome,
                gateway_reference=_row_get(tx, 'gateway_reference'),
                public_id=tx['public_id'],
            )
        except GatewayNotConfiguredError as exc:
            return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status
        except PaymentGatewayError as exc:
            return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status

        resolved_gw_pid = res.get('gateway_payment_id')
        resolved_gw_ref = res.get('gateway_reference')
        if resolved_gw_pid and resolved_gw_pid != _row_get(tx, 'gateway_payment_id'):
            fallback_ref = _row_get(tx, 'gateway_reference') or resolved_gw_ref or _row_get(tx, 'gateway_payment_id')
            conn.execute('''
                UPDATE payment_transactions
                SET gateway_payment_id = ?, gateway_reference = COALESCE(gateway_reference, ?),
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (resolved_gw_pid, fallback_ref, tx['id']))

        gw_status = res.get('status') or tx['status']
        if gw_status == 'paid':
            ok, settle_info = _settle_payment_and_sync_escrow(conn, tx, order)
            if not ok:
                conn.rollback()
                return jsonify({'error': settle_info}), 409
            resp_body = {
                'payment_id': tx['public_id'],
                'id': tx['id'],
                'order_id': order['id'],
                'status': settle_info['status'],
                'escrow_status': settle_info['escrow_status'],
                'pago': True,
            }
        elif gw_status in ('failed', 'expired', 'cancelled'):
            conn.execute('''
                UPDATE payment_transactions
                SET status = ?, failure_code = ?, failure_message = ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND escrow_synced = 0
            ''', (
                gw_status, res.get('failure_code'), res.get('failure_message'), tx['id']
            ))
            resp_body = {
                'payment_id': tx['public_id'],
                'id': tx['id'],
                'order_id': order['id'],
                'status': gw_status,
                'escrow_status': _row_get(order, 'escrow_status', 'pendente'),
                'pago': False,
            }
        else:
            resp_body = {
                'payment_id': tx['public_id'],
                'id': tx['id'],
                'order_id': order['id'],
                'status': gw_status,
                'escrow_status': _row_get(order, 'escrow_status', 'pendente'),
                'pago': bool(int(_row_get(order, 'pago', 0) or 0)),
            }

        idem_race = _save_idempotency(
            conn, user['id'], 'confirm_payment', idempotency_key, req_hash, tx['id'], 200, resp_body
        )
        if idem_race:
            race_state, race_payload = idem_race
            if race_state == 'conflict':
                return jsonify({'error': 'Conflito de idempotência.'}), 409
            return jsonify(race_payload[1]), race_payload[0]

        conn.commit()
        return jsonify(resp_body), 200
    finally:
        conn.close()


@app.route('/api/payments/<payment_ref>/refund', methods=['POST'])
@rate_limit(20, 60)
def refund_payment(payment_ref):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.', 'code': 'UNAUTHORIZED'}), 401
    if user['tipo'] != 'cliente':
        return jsonify({'error': 'Apenas o cliente pode solicitar estorno.'}), 403
    acct_err = _require_active_account(user)
    if acct_err:
        return acct_err

    data = request.get_json(silent=True) or {}
    idempotency_key = _extract_idempotency_key(data)
    reason = str(data.get('reason') or data.get('motivo') or '').strip()[:300]

    conn = get_db_connection()
    try:
        tx = _lookup_payment_tx(conn, payment_ref)
        if not tx:
            return jsonify({'error': 'Pagamento não encontrado.'}), 404
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (tx['order_id'],)).fetchone()
        if not order or order['cliente_id'] != user['id']:
            return jsonify({'error': 'Pagamento não encontrado.'}), 404

        escrow_atual = _row_get(order, 'escrow_status', 'pendente')
        if order['status'] in ('em_execucao', 'finalizado', 'em_disputa') or escrow_atual in (
            'liberado', 'aguardando_liberacao', 'em_disputa', 'congelado_disputa'
        ):
            return jsonify({'error': 'Estorno direto indisponível neste estágio do pedido; utilize a abertura de disputa.'}), 409
        if tx['status'] not in ('paid', 'escrow_held', 'partially_refunded'):
            return jsonify({'error': f"Pagamento em status '{tx['status']}' não pode ser estornado."}), 409

        already_refunded = int(_row_get(tx, 'refunded_cents', 0) or 0)
        remaining_cents = int(tx['amount_cents']) - already_refunded
        if remaining_cents <= 0:
            return jsonify({'error': 'Pagamento já foi totalmente estornado.'}), 409

        if data.get('amount_cents') is not None:
            try:
                requested_cents = int(data.get('amount_cents'))
            except (ValueError, TypeError):
                return jsonify({'error': 'amount_cents inválido.'}), 400
        elif data.get('amount') is not None:
            try:
                requested_cents = int(round(float(data.get('amount')) * 100))
            except (ValueError, TypeError):
                return jsonify({'error': 'amount inválido.'}), 400
        else:
            requested_cents = remaining_cents

        if requested_cents <= 0:
            return jsonify({'error': 'Valor de estorno deve ser positivo.'}), 400
        if requested_cents > remaining_cents:
            return jsonify({'error': 'Valor de estorno excede o saldo disponível.'}), 409

        req_hash = _compute_request_hash({
            'payment_id': tx['id'],
            'requested_cents': requested_cents,
            'reason': reason,
        })
        idem_state, idem_payload = _check_idempotency(conn, user['id'], 'refund_payment', idempotency_key, req_hash)
        if idem_state == 'conflict':
            return jsonify({'error': 'Chave de idempotência reutilizada com parâmetros diferentes.', 'code': 'IDEMPOTENCY_CONFLICT'}), 409
        if idem_state == 'replay':
            return jsonify(idem_payload[1]), idem_payload[0]

        cursor = conn.cursor()
        cursor.execute('''
            UPDATE payment_transactions
            SET refunded_cents = refunded_cents + ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ? AND (amount_cents - refunded_cents) >= ?
        ''', (requested_cents, tx['id'], requested_cents))
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({'error': 'Saldo insuficiente ou estorno concorrente em andamento.'}), 409

        refund_public_id = f"ref_{secrets.token_hex(12)}"
        try:
            adapter = get_payment_adapter(tx['gateway'])
            ref_res = adapter.refund_payment(
                gateway_payment_id=tx['gateway_payment_id'],
                amount_cents=requested_cents,
                reason=reason,
                idempotency_key=refund_public_id,
                full_refund=(requested_cents == int(tx['amount_cents']) and int(_row_get(tx, 'refunded_cents', 0) or 0) == 0),
            )
        except GatewayNotConfiguredError as exc:
            conn.rollback()
            return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status
        except PaymentGatewayError as exc:
            conn.rollback()
            return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status

        if ref_res.get('status') != 'succeeded':
            conn.rollback()
            return jsonify({'error': 'Estorno não foi aprovado pelo gateway.', 'code': 'REFUND_FAILED'}), 502

        refreshed_tx = conn.execute(
            'SELECT refunded_cents, amount_cents FROM payment_transactions WHERE id = ?',
            (tx['id'],)
        ).fetchone()
        total_refunded = int(refreshed_tx['refunded_cents'])
        is_full = total_refunded >= int(refreshed_tx['amount_cents'])
        new_tx_status = 'refunded' if is_full else 'partially_refunded'
        new_escrow_status = 'estornado_total' if is_full else 'estornado_parcial'
        gateway_refund_id = ref_res.get('gateway_refund_id')

        cursor.execute('''
            INSERT INTO payment_refunds (
                public_id, payment_id, order_id, requested_by, amount_cents, reason, status, gateway_refund_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 'succeeded', ?)
        ''', (refund_public_id, tx['id'], order['id'], user['id'], requested_cents, reason, gateway_refund_id))

        cursor.execute('''
            UPDATE payment_transactions
            SET status = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_tx_status, tx['id']))

        cursor.execute('''
            UPDATE orders
            SET escrow_status = ?, valor_estornado = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_escrow_status, round(total_refunded / 100.0, 2), order['id']))

        _log_escrow_ledger(
            conn, order['id'], 'escrow_refund', round(requested_cents / 100.0, 2), new_escrow_status,
            f"Estorno via {tx['gateway']}: {reason}" if reason else f"Estorno via {tx['gateway']}"
        )

        resp_body = {
            'refund_id': refund_public_id,
            'payment_id': tx['public_id'],
            'order_id': order['id'],
            'status': new_tx_status,
            'escrow_status': new_escrow_status,
            'refunded_cents': total_refunded,
            'requested_cents': requested_cents,
            'gateway_refund_id': gateway_refund_id,
        }
        idem_race = _save_idempotency(
            conn, user['id'], 'refund_payment', idempotency_key, req_hash, tx['id'], 200, resp_body
        )
        if idem_race:
            race_state, race_payload = idem_race
            if race_state == 'conflict':
                return jsonify({'error': 'Conflito de idempotência.'}), 409
            return jsonify(race_payload[1]), race_payload[0]

        conn.commit()
        return jsonify(resp_body), 200
    finally:
        conn.close()


@app.route('/api/webhooks/payments', methods=['POST'])
@app.route('/api/webhooks/payments/<gateway>', methods=['POST'])
@rate_limit(120, 60)
def payment_gateway_webhook(gateway=None):
    # Webhooks nunca acessam flask.session e verificam assinatura HMAC antes de qualquer escrita no banco.
    gw = (gateway or request.args.get('gateway') or request.headers.get('X-Payment-Gateway') or '').strip().lower()
    if gw not in VALID_PAYMENT_GATEWAYS:
        return jsonify({'error': 'Gateway de webhook inválido.'}), 400

    raw_body = request.get_data(cache=False) or b''
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    try:
        adapter = get_payment_adapter(gw)
        event = adapter.verify_webhook(raw_body=raw_body, headers=request.headers, query_params=request.args)
    except WebhookSignatureError as exc:
        return jsonify({'error': str(exc), 'code': exc.code}), 401
    except GatewayNotConfiguredError as exc:
        return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status
    except PaymentGatewayError as exc:
        return jsonify({'error': str(exc), 'code': exc.code}), exc.http_status

    event_id = str(event.get('event_id') or '').strip() or payload_hash
    event_type = str(event.get('event_type') or 'unknown').strip()
    gateway_payment_id = event.get('gateway_payment_id')
    gateway_reference = event.get('gateway_reference')
    event_public_id = event.get('public_id')
    mapped_status = event.get('mapped_status')
    payload_json = raw_body.decode('utf-8', errors='replace')

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO payment_webhooks (
                    gateway, event_id, event_type, gateway_payment_id,
                    signature_valid, processing_status, payload_hash, payload_json
                )
                VALUES (?, ?, ?, ?, 1, 'received', ?, ?)
            ''', (gw, event_id, event_type, gateway_payment_id, payload_hash, payload_json))
            webhook_id = cursor.lastrowid
        except DBIntegrityError:
            conn.rollback()
            return jsonify({'status': 'duplicate_ignored', 'event_id': event_id}), 200

        tx = None
        if gateway_payment_id:
            tx = conn.execute(
                'SELECT * FROM payment_transactions WHERE gateway = ? AND gateway_payment_id = ?',
                (gw, str(gateway_payment_id))
            ).fetchone()
        if not tx and gateway_reference:
            tx = conn.execute(
                'SELECT * FROM payment_transactions WHERE gateway = ? AND (gateway_reference = ? OR gateway_payment_id = ?)',
                (gw, str(gateway_reference), str(gateway_reference))
            ).fetchone()
        if not tx and gateway_payment_id:
            tx = conn.execute(
                'SELECT * FROM payment_transactions WHERE gateway = ? AND gateway_reference = ?',
                (gw, str(gateway_payment_id))
            ).fetchone()
        if not tx and event_public_id:
            tx = conn.execute(
                'SELECT * FROM payment_transactions WHERE gateway = ? AND public_id = ?',
                (gw, str(event_public_id))
            ).fetchone()
        if not tx and gateway_payment_id:
            tx = conn.execute(
                'SELECT * FROM payment_transactions WHERE gateway = ? AND public_id = ?',
                (gw, str(gateway_payment_id))
            ).fetchone()

        if not tx:
            conn.execute('''
                UPDATE payment_webhooks
                SET processing_status = 'ignored', processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (webhook_id,))
            conn.commit()
            return jsonify({'status': 'ignored', 'event_id': event_id}), 200

        if mapped_status == 'ignored':
            conn.execute('''
                UPDATE payment_webhooks
                SET processing_status = 'ignored', processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (webhook_id,))
            conn.commit()
            return jsonify({'status': 'ignored', 'event_id': event_id}), 200

        order = conn.execute('SELECT * FROM orders WHERE id = ?', (tx['order_id'],)).fetchone()
        if mapped_status == 'paid' and order:
            event_amount_cents = event.get('amount_cents')
            if event_amount_cents is not None and int(event_amount_cents) < int(tx['amount_cents']):
                conn.execute('''
                    UPDATE payment_webhooks
                    SET processing_status = 'ignored', error_message = 'Underpayment mismatch', processed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (webhook_id,))
                conn.commit()
                return jsonify({'status': 'amount_mismatch_ignored', 'event_id': event_id}), 200
            if gateway_payment_id and str(gateway_payment_id) != str(_row_get(tx, 'gateway_payment_id') or ''):
                fallback_ref = _row_get(tx, 'gateway_reference') or gateway_reference or _row_get(tx, 'gateway_payment_id')
                conn.execute('''
                    UPDATE payment_transactions
                    SET gateway_payment_id = ?, gateway_reference = COALESCE(gateway_reference, ?),
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (str(gateway_payment_id), fallback_ref, tx['id']))
            ok, _ = _settle_payment_and_sync_escrow(conn, tx, order)
            if not ok:
                conn.rollback()
                try:
                    conn.execute('''
                        INSERT INTO payment_webhooks (
                            gateway, event_id, event_type, gateway_payment_id,
                            signature_valid, processing_status, payload_hash, payload_json, processed_at
                        )
                        VALUES (?, ?, ?, ?, 1, 'ignored', ?, ?, CURRENT_TIMESTAMP)
                    ''', (gw, event_id, event_type, gateway_payment_id, payload_hash, payload_json))
                    conn.commit()
                except DBIntegrityError:
                    conn.rollback()
                return jsonify({'status': 'ignored', 'event_id': event_id}), 200
        elif mapped_status in ('failed', 'expired', 'cancelled'):
            conn.execute('''
                UPDATE payment_transactions
                SET status = ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ? AND escrow_synced = 0 AND status IN ('pending', 'requires_action', 'authorized')
            ''', (mapped_status, tx['id']))

        conn.execute('''
            UPDATE payment_webhooks
            SET processing_status = 'processed', processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (webhook_id,))
        conn.commit()
        return jsonify({'status': 'processed', 'event_id': event_id}), 200
    finally:
        conn.close()


# ================= Sistema de IA — Suporte e Descrições de Anúncios =================

_OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'http://localhost:3001/v1').rstrip('/')
_OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
_LLAMA_MODEL = os.environ.get('LLAMA_MODEL', 'gemini-3.8-flash')


def _get_llm_client():
    """Retorna um cliente OpenAI-compatible apontando para o FreeLLMAPI."""
    return openai.OpenAI(
        base_url=_OPENAI_BASE_URL,
        api_key=_OPENAI_API_KEY,
        max_retries=4,
    )


def _call_llm(messages, model, temperature, max_tokens):
    """Envia uma mensagem para o FreeLLMAPI e retorna o conteúdo da resposta."""
    client = _get_llm_client()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def _chat_system_prompt():
    return (
        'Você é o suporte ao cliente do PertoJá Marketplace. '
        'Responda de forma amigável, objetiva e útil em português do Brasil. '
        'Cubra serviços, agendamentos, pagamentos, KYC e a política de privacidade do site. '
        'Se não tiver certeza, oriente o usuário a procurar a seção de ajuda ou entrar em contato.'
    )


@app.route('/api/chat/support', methods=['POST'])
def chat_support():
    """Endpoint de suporte: o cliente pergunta e o LLM gera uma resposta.",
         """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    data = request.get_json(silent=True) or {}
    message = str(data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'A mensagem é obrigatória.'}), 400

    # Constrói um contexto opcional (lista de strings ou dicionário) para reforço
    context_parts = []
    raw_context = data.get('context')
    if raw_context is not None:
        if isinstance(raw_context, list):
            context_parts = [str(c) for c in raw_context if c]
        elif isinstance(raw_context, dict):
            context_parts.append(json.dumps(raw_context, ensure_ascii=False))
        elif raw_context:
            context_parts.append(str(raw_context))
    context_text = '\n'.join(context_parts)

    system_prompt = _chat_system_prompt()
    messages = [
        {'role': 'system', 'content': system_prompt},
    ]
    if context_text:
        messages.append({'role': 'user', 'content': 'Contexto adicional:\n' + context_text})
    messages.append({'role': 'user', 'content': message})

    try:
        reply = _call_llm(
            messages=messages,
            model=_LLAMA_MODEL,
            temperature=0.4,
            max_tokens=800,
        )
    except Exception:
        return jsonify({'error': 'Falha ao gerar resposta do suporte.'}), 500

    return jsonify({
        'reply': reply,
        'model': _LLAMA_MODEL,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }), 200


@app.route('/api/ads/generate-description', methods=['POST'])
def generate_ad_description():
    """Gera/ajusta uma descrição de anúncio a partir dos dados do serviço."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'O título é obrigatório.'}), 400

    category = str(data.get('category') or '').strip()
    description = str(data.get('description') or '').strip()
    price = data.get('price')
    service_type = str(data.get('service_type') or '').strip()
    extra = str(data.get('extra') or '').strip()

    # Monta o contexto para o LLM a partir dos campos informados
    parts = []
    if category:
        parts.append('Categoria: ' + category)
    if price is not None:
        try:
            parts.append('Preço: R$ ' + f'{float(price):.2f}')
        except (TypeError, ValueError):
            parts.append('Preço: informado')
    if service_type:
        parts.append('Tipo: ' + service_type)
    if description:
        parts.append('Descrição atual: ' + description)
    if extra:
        parts.append('Observações: ' + extra)
    context = '\n'.join(parts) if parts else ('Título: ' + title)

    system_prompt = (
        'Você é um gerador de anúncios (descriptions) para o PertoJá Marketplace. '
        'Escreva uma descrição vencedora de anúncio em português do Brasil, '
        'apropriada para um anúncio de serviço, com tom atraente, claro e profissional. '
        'Máximo de ~280 caracteres. Use palavras chamativas e benefícios do serviço. '
        'Não invente preços, cidades ou categorias que não foram informados. '
        'Se faltar informação essencial, use um tom genérico e neutro.'
    )
    prompt = 'Seu anúncio:\n\n' + context + '\n\nDescrição do anúncio (máx ~280 chars):'

    try:
        generated = _call_llm(
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt},
            ],
            model=_LLAMA_MODEL,
            temperature=0.35,
            max_tokens=600,
        )
    except Exception:
        return jsonify({'error': 'Falha ao gerar a descrição do anúncio.'}), 500

    return jsonify({
        'generated_description': generated,
        'model_used': _LLAMA_MODEL,
        'title': title,
        'category': category or None,
        'price': price,
        'service_type': service_type or None,
        'length': len(generated),
    }), 200


# ================= Inicialização do Servidor =================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Servidor PertoJá Marketplace Iniciado!")
    print("👉 Acesse a aplicação no seu navegador: http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
