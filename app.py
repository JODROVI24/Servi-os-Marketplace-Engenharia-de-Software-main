import os
import re
import math
import secrets
import hashlib
import hmac
import requests
import gzip
import time
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import database
from database import (
    get_db_connection, init_db, get_cached_geocode, save_cached_geocode,
    DBIntegrityError, get_active_engine
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'public')

ALLOWED_STATIC_EXTENSIONS = {
    '.html', '.css', '.js', '.webp', '.jpg', '.png', '.svg', '.ico', '.woff2', '.woff'
}


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
    return 'pertoja-dev-local-secret-key-2026'


app = Flask(__name__, static_folder=STATIC_DIR)
app.secret_key = _resolve_secret_key()
app.config.update(
    TESTING=False,
    PERMANENT_SESSION_LIFETIME=43200,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=(os.environ.get('VERCEL') == '1' or os.environ.get('HTTPS') == '1')
)

# ================= Otimização de Performance, Caching e Segurança =================


@app.after_request
def add_performance_and_security_headers(response):
    # Cabeçalhos de Segurança HTTP (OWASP / WCAG)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(self)'

    # Políticas de Cache HTTP (Core Web Vitals)
    path = request.path
    if any(path.endswith(ext) for ext in ('.css', '.js', '.webp', '.jpg', '.png', '.svg', '.ico', '.woff2', '.woff')):
        response.headers['Cache-Control'] = 'public, max-age=604800, stale-while-revalidate=86400'
    elif path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    else:
        response.headers['Cache-Control'] = 'public, max-age=3600, must-revalidate'

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
    return request.headers.get('x-forwarded-for', request.remote_addr or '127.0.0.1').split(',')[0].strip()


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
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user


# Helper de cálculo de distância euclidiana/haversine simplificada em km
def safe_coord(val, default=-23.5653):
    if val is None or val == '':
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
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
        status['status'] = 'degraded'
        status['database'] = f'error: {str(err)}'
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

    # Se não passou coordenadas mas passou endereço, geocodifica
    if (raw_lat is None or raw_lat == '' or raw_lng is None or raw_lng == '') and (endereco or cep):
        busca = f"{endereco} {numero}, {bairro}, {cidade} - {estado}" if endereco else f"{cep}, Brasil"
        lat, lng = geocode_address(busca, street=endereco, neighborhood=bairro, city=cidade, state=estado)
        if lat is None or lng is None:
            lat, lng = -23.5653, -46.6517
    elif raw_lat is None or raw_lat == '' or raw_lng is None or raw_lng == '':
        lat, lng = -23.5653, -46.6517
    else:
        lat = safe_coord(raw_lat, -23.5653)
        lng = safe_coord(raw_lng, -46.6517)

    categoria = data.get('categoria', '').strip()
    preco_inicial = data.get('preco_inicial')

    conn = get_db_connection()
    try:
        user_exist = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if user_exist:
            return jsonify({'error': 'Este e-mail já está cadastrado.'}), 409

        senha_hash = generate_password_hash(senha)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (nome, email, senha_hash, tipo, plano, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng, kyc_tier, kyc_status, kyc_documento_tipo, registro_profissional, status_conta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'aprovado', ?, ?, 'ativo')
        ''', (nome, email, senha_hash, tipo, plano, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng, kyc_documento_tipo, registro_profissional))
        user_id = cursor.lastrowid

        cursor.execute('''
            INSERT INTO user_consents (user_id, doc_type, doc_version, ip_hash)
            VALUES (?, 'termos_privacidade', ?, ?)
        ''', (user_id, versao_termos, _hash_ip(_get_client_ip())))

        # Se for prestador e informou categoria e preço inicial, cria o primeiro serviço com endereço real
        if tipo == 'prestador' and categoria:
            try:
                preco = float(preco_inicial) if preco_inicial else 100.0
                if preco <= 0:
                    preco = 100.0
            except (ValueError, TypeError):
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
                'kyc_tier': 1,
                'kyc_status': 'aprovado',
                'kyc_documento_tipo': kyc_documento_tipo,
                'registro_profissional': registro_profissional,
                'status_conta': 'ativo'
            }
        }), 201
    except Exception as e:
        return jsonify({'error': f'Erro ao cadastrar usuário: {str(e)}'}), 500
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

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user['senha_hash'], senha):
        return jsonify({'error': 'Credenciais inválidas. Verifique seu e-mail e senha.'}), 401

    session.permanent = True
    session['user_id'] = user['id']
    session['user_tipo'] = user['tipo']
    session['user_nome'] = user['nome']

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
        conn.execute('UPDATE users SET senha_hash = ? WHERE id = ?', (senha_hash, row['user_id']))
        conn.execute('UPDATE password_reset_tokens SET used = 1 WHERE token = ?', (row['token'],))
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
        conn.execute('''
            UPDATE users
            SET nome = 'Usuário Anonimizado',
                email = ?,
                telefone = NULL,
                bio = NULL,
                foto_url = NULL,
                cep = NULL,
                endereco = NULL,
                numero = NULL,
                complemento = NULL,
                disponivel = 0,
                status_conta = 'bloqueado'
            WHERE id = ?
        ''', (anon_email, user['id']))
        conn.execute('UPDATE services SET ativo = 0 WHERE prestador_id = ?', (user['id'],))
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
def verify_kyc():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Acesso não autorizado. Faça login.'}), 401

    data = request.get_json(silent=True) or {}
    doc_tipo = str(data.get('kyc_documento_tipo') or data.get('documento_tipo') or _row_get(user, 'kyc_documento_tipo', 'RG')).strip().upper()
    if doc_tipo not in ('RG', 'CIN', 'CNH'):
        return jsonify({'error': 'Tipo de documento inválido. Escolha RG, CIN ou CNH.'}), 400

    registro_prof = str(data.get('registro_profissional') or _row_get(user, 'registro_profissional') or '').strip() or None
    selfie_ok = bool(data.get('selfie_verificada', True))
    tier = int(data.get('tier') or (2 if (registro_prof or selfie_ok) else 1))
    if tier < 1:
        tier = 1
    if tier > 2:
        tier = 2

    provider_ref = f"kyc-{user['id']}-{secrets.token_hex(4)}"
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE users
            SET kyc_tier = ?,
                kyc_status = 'aprovado',
                kyc_documento_tipo = ?,
                kyc_provider_ref = ?,
                kyc_verified_at = CURRENT_TIMESTAMP,
                registro_profissional = COALESCE(?, registro_profissional)
            WHERE id = ?
        ''', (tier, doc_tipo, provider_ref, registro_prof, user['id']))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Verificação KYC concluída com sucesso.',
        'kyc_tier': tier,
        'kyc_status': 'aprovado',
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
    is_authenticated = bool(session.get('user_id'))
    is_approx = (not is_authenticated) or (request.args.get('approx') == '1')

    def _mask_phone(phone):
        if not phone:
            return ''
        s = str(phone)
        if len(s) >= 4:
            return s[:-4] + '****'
        return '****'

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

        if is_approx:
            d_lat, d_lng = _deterministic_jitter(r['service_id'])
            out_lat = round(svc_lat + d_lat, 6)
            out_lng = round(svc_lng + d_lng, 6)
        else:
            out_lat = svc_lat
            out_lng = svc_lng

        # Formata endereço legível (ET-03: omite logradouro/número/CEP em consultas não autenticadas ou approx=1)
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
        tel_out = r['prestador_telefone'] if is_authenticated else _mask_phone(r['prestador_telefone'])

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
    titulo = str(data.get('titulo') or '').strip()
    descricao = str(data.get('descricao') or '').strip()
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

    kyc_status = _row_get(user, 'kyc_status', 'aprovado')
    kyc_tier = int(_row_get(user, 'kyc_tier', 1) or 1)
    if kyc_status == 'reprovado' or (data.get('exige_kyc_tier2') and kyc_tier < 2):
        return jsonify({'error': 'Verificação KYC insuficiente para publicar este serviço.'}), 403

    # Dados de endereço do serviço (herda do prestador se não informados)
    cep = str(data.get('cep') or user['cep'] or '').strip()
    endereco = str(data.get('endereco') or user['endereco'] or '').strip()
    numero = str(data.get('numero') or user['numero'] or '').strip()
    bairro = str(data.get('bairro') or user['bairro'] or '').strip()
    cidade = str(data.get('cidade') or user['cidade'] or 'São Paulo').strip()
    estado = str(data.get('estado') or user['estado'] or 'SP').strip()
    lat = safe_coord(data.get('lat'), safe_coord(user['lat'], -23.5653))
    lng = safe_coord(data.get('lng'), safe_coord(user['lng'], -46.6517))

    if not titulo or not categoria or preco is None:
        return jsonify({'error': 'Título, categoria e preço são obrigatórios.'}), 400

    try:
        preco = float(preco)
        if preco <= 0:
            raise ValueError()
    except ValueError:
        return jsonify({'error': 'O preço deve ser um valor numérico positivo.'}), 400

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

    conn = get_db_connection()
    service = conn.execute('SELECT * FROM services WHERE id = ?', (service_id,)).fetchone()
    if not service:
        conn.close()
        return jsonify({'error': 'Serviço não encontrado.'}), 404

    if service['prestador_id'] != user['id']:
        conn.close()
        return jsonify({'error': 'Você não tem permissão para alterar este serviço.'}), 403

    data = request.get_json() or {}
    titulo = str(data.get('titulo') or service['titulo']).strip()
    descricao = str(data.get('descricao') or service['descricao'] or '').strip()
    categoria = str(data.get('categoria') or service['categoria']).strip()
    preco = data.get('preco', service['preco'])
    ativo = 1 if data.get('ativo', bool(service['ativo'])) else 0

    cep = str(data.get('cep') or service['cep'] or user['cep'] or '').strip()
    endereco = str(data.get('endereco') or service['endereco'] or user['endereco'] or '').strip()
    numero = str(data.get('numero') or service['numero'] or user['numero'] or '').strip()
    bairro = str(data.get('bairro') or service['bairro'] or user['bairro'] or '').strip()
    cidade = str(data.get('cidade') or service['cidade'] or user['cidade'] or 'São Paulo').strip()
    estado = str(data.get('estado') or service['estado'] or user['estado'] or 'SP').strip()
    lat = safe_coord(data.get('lat'), safe_coord(service['lat'] or user['lat'], -23.5653))
    lng = safe_coord(data.get('lng'), safe_coord(service['lng'] or user['lng'], -46.6517))

    try:
        preco = float(preco)
        if preco <= 0:
            raise ValueError()
    except ValueError:
        conn.close()
        return jsonify({'error': 'Preço deve ser um valor positivo.'}), 400

    conn.execute('''
        UPDATE services
        SET titulo = ?, descricao = ?, categoria = ?, preco = ?, cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?, ativo = ?
        WHERE id = ?
    ''', (titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo, service_id))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Serviço, endereço e preço atualizados com sucesso!'})


@app.route('/api/services/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    user = get_current_user()
    if not user or user['tipo'] != 'prestador':
        return jsonify({'error': 'Acesso não autorizado.'}), 403

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

    observacoes = str(data.get('observacoes') or '').strip()
    complemento_cli = str(data.get('complemento') or _row_get(user, 'complemento', '')).strip()
    modalidade = str(data.get('modalidade') or 'imediato').strip().lower()
    if modalidade not in ('imediato', 'agendado'):
        modalidade = 'imediato'
    agendado_para = str(data.get('agendado_para') or '').strip() or None
    metodo_pagamento = str(data.get('metodo_pagamento') or 'escrow').strip().lower()
    if metodo_pagamento == 'escrow_local':
        metodo_pagamento = 'escrow'
    elif metodo_pagamento not in ('pix', 'cartao', 'escrow'):
        metodo_pagamento = 'escrow'
    codigo_confirmacao = f"{secrets.randbelow(9000) + 1000}"

    # Endereço onde o serviço será realizado (com fallbacks dos dados cadastrais do cliente)
    cep_cli = str(data.get('cep') or user['cep'] or '').strip()
    end_cli = str(data.get('endereco') or user['endereco'] or '').strip()
    num_cli = str(data.get('numero') or user['numero'] or '').strip()
    bairro_cli = str(data.get('bairro') or user['bairro'] or '').strip()
    cidade_cli = str(data.get('cidade') or user['cidade'] or 'São Paulo').strip()
    estado_cli = str(data.get('estado') or user['estado'] or 'SP').strip()

    user_lat_fallback = safe_coord(user['lat'], -23.5653)
    user_lng_fallback = safe_coord(user['lng'], -46.6517)
    lat_cliente = safe_coord(data.get('lat'), user_lat_fallback)
    lng_cliente = safe_coord(data.get('lng'), user_lng_fallback)

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

    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({'error': 'Pedido não encontrado.', 'code': 'NOT_FOUND'}), 404

    if order['cliente_id'] != user['id']:
        conn.close()
        return jsonify({'error': 'Sem permissão para pagar pedido de outro cliente.', 'code': 'FORBIDDEN'}), 403

    data = request.get_json(silent=True) or {}
    escrow_hold = bool(data.get('escrow_hold'))
    metodo_pagamento = str(data.get('metodo_pagamento') or _row_get(order, 'metodo_pagamento', 'escrow')).strip().lower()
    if metodo_pagamento not in ('pix', 'cartao', 'escrow'):
        metodo_pagamento = 'escrow'

    if escrow_hold:
        conn.execute('''
            UPDATE orders
            SET pago = 1, escrow_status = 'retido', metodo_pagamento = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (metodo_pagamento, order_id))
        conn.commit()
        current_status = order['status']
        conn.close()
        return jsonify({
            'message': 'Pagamento retido em garantia (escrow) com sucesso!',
            'order_id': order_id,
            'status': current_status,
            'pago': True,
            'escrow_status': 'retido',
            'metodo_pagamento': metodo_pagamento
        }), 200

    if order['status'] in ('em_disputa', 'cancelado'):
        conn.close()
        return jsonify({'error': f"Não é possível finalizar pagamento de pedido com status '{order['status']}'."}), 400

    conn.execute('''
        UPDATE orders 
        SET pago = 1, status = 'finalizado', escrow_status = 'liberado',
            completed_at = CURRENT_TIMESTAMP, released_at = CURRENT_TIMESTAMP,
            metodo_pagamento = ?, atualizado_em = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (metodo_pagamento, order_id))
    conn.commit()
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

    conn.close()
    mask_pii = request.args.get('mask_pii') == '1'
    result = []
    for o in orders:
        item = dict(o)
        item['ja_avaliado'] = bool(item.get('ja_avaliado'))
        item['escrow_status'] = item.get('escrow_status') or 'pendente'
        item['taxa_deslocamento'] = float(item.get('taxa_deslocamento') or 0.0)
        item['valor_estornado'] = float(item.get('valor_estornado') or 0.0)
        item['em_disputa'] = (item.get('status') == 'em_disputa')

        if user['tipo'] == 'prestador':
            # ET-02: Prestador nunca recebe o PIN de confirmação
            item['codigo_confirmacao'] = None
            item['pin_obrigatorio'] = True
            bairro = item.get('bairro_cliente') or ''
            cidade = item.get('cidade_cliente') or 'São Paulo'
            st = item.get('status')
            item['endereco_protegido'] = (st == 'solicitado')
            item['endereco_cliente_resumo'] = f"{bairro}, {cidade}".strip(', ')
            if mask_pii or st in ('solicitado', 'finalizado', 'cancelado'):
                item['endereco_cliente'] = 'Protegido'
                item['numero_cliente'] = ''
                item['complemento_cliente'] = ''
                item['cep_cliente'] = ''
                item['lat_cliente'] = None
                item['lng_cliente'] = None
                tel = str(item.get('cliente_telefone') or '')
                item['cliente_telefone'] = (tel[:-4] + '****') if len(tel) >= 4 else '****'
        else:
            st = item.get('status')
            if mask_pii or st in ('finalizado', 'cancelado'):
                item['prestador_endereco'] = 'Protegido'
                item['prestador_numero'] = ''
                item['prestador_lat'] = None
                item['prestador_lng'] = None
                tel = str(item.get('prestador_telefone') or '')
                item['prestador_telefone'] = (tel[:-4] + '****') if len(tel) >= 4 else '****'

        result.append(item)
    return jsonify(result)


@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Não autenticado.'}), 401

    data = request.get_json() or {}
    novo_status = data.get('status')
    motivo = str(data.get('motivo') or '').strip()
    valid_statuses = ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'finalizado', 'cancelado', 'em_disputa')
    if novo_status not in valid_statuses:
        return jsonify({'error': f'Status inválido. Escolha: {", ".join(valid_statuses)}'}), 400

    if _row_get(user, 'status_conta', 'ativo') in ('suspenso_cautelar', 'bloqueado') and novo_status in ('confirmado', 'em_transito', 'em_execucao'):
        return jsonify({'error': 'Conta suspensa cautelarmente ou bloqueada não pode aceitar ou avançar chamados.'}), 403

    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({'error': 'Pedido não encontrado.'}), 404

    # Apenas o prestador designado ou o cliente da ordem podem alterar o status
    if user['tipo'] == 'prestador' and order['prestador_id'] != user['id']:
        conn.close()
        return jsonify({'error': 'Sem permissão para alterar este pedido.'}), 403
    if user['tipo'] == 'cliente' and order['cliente_id'] != user['id']:
        conn.close()
        return jsonify({'error': 'Sem permissão para alterar este pedido.'}), 403

    atual_status = order['status']
    if atual_status in ('finalizado', 'cancelado') and novo_status != 'em_disputa' and novo_status != atual_status:
        conn.close()
        return jsonify({'error': f'Não é permitido regredir ou alterar um pedido já {atual_status}.'}), 400

    status_rank = {'solicitado': 0, 'confirmado': 1, 'em_transito': 2, 'em_execucao': 3, 'finalizado': 4}
    if atual_status in status_rank and novo_status in status_rank and status_rank[novo_status] < status_rank[atual_status]:
        conn.close()
        return jsonify({'error': f'Transição regressiva inválida de {atual_status} para {novo_status}.'}), 400

    # ET-02 / ET-07: Validação obrigatória de PIN ao iniciar execução
    if novo_status == 'em_execucao':
        pin_esperado = str(_row_get(order, 'codigo_confirmacao', '') or '').strip()
        if pin_esperado:
            pin_informado = str(data.get('codigo_confirmacao') or '').strip()
            if not pin_informado or pin_informado != pin_esperado:
                conn.close()
                return jsonify({'error': 'Código de confirmação (PIN) obrigatório e deve corresponder ao informado pelo cliente.'}), 400

    escrow_status = _row_get(order, 'escrow_status', 'pendente')
    taxa_deslocamento = float(_row_get(order, 'taxa_deslocamento', 0.0) or 0.0)
    valor_estornado = float(_row_get(order, 'valor_estornado', 0.0) or 0.0)

    if novo_status == 'cancelado':
        if int(_row_get(order, 'pago', 0) or 0) == 1:
            preco = float(_row_get(order, 'preco_total', 0.0) or 0.0)
            if atual_status in ('em_transito', 'em_execucao') and user['tipo'] == 'cliente':
                taxa_deslocamento = min(round(preco * 0.20, 2), 40.0)
                valor_estornado = round(max(0.0, preco - taxa_deslocamento), 2)
                escrow_status = 'estornado_parcial'
            else:
                taxa_deslocamento = 0.0
                valor_estornado = preco
                escrow_status = 'estornado_total'
        conn.execute('''
            UPDATE orders 
            SET status = ?, motivo_cancelamento = ?, escrow_status = ?,
                taxa_deslocamento = ?, valor_estornado = ?, atualizado_em = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (novo_status, motivo or _row_get(order, 'motivo_cancelamento'), escrow_status, taxa_deslocamento, valor_estornado, order_id))
    elif novo_status == 'finalizado':
        escrow_status = 'liberado'
        conn.execute('''
            UPDATE orders 
            SET status = ?, escrow_status = ?, completed_at = CURRENT_TIMESTAMP,
                released_at = CURRENT_TIMESTAMP, atualizado_em = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (novo_status, escrow_status, order_id))
    elif novo_status == 'em_disputa':
        escrow_status = 'em_disputa'
        conn.execute('''
            UPDATE orders 
            SET status = ?, escrow_status = ?, atualizado_em = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (novo_status, escrow_status, order_id))
    else:
        conn.execute('''
            UPDATE orders 
            SET status = ?, atualizado_em = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (novo_status, order_id))

    conn.commit()
    conn.close()

    return jsonify({
        'message': f'Status do pedido atualizado para {novo_status}.',
        'status': novo_status,
        'escrow_status': escrow_status,
        'taxa_deslocamento': taxa_deslocamento,
        'valor_estornado': valor_estornado
    })


@app.route('/api/orders/<int:order_id>/dispute', methods=['POST'])
def open_order_dispute(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    data = request.get_json(silent=True) or {}
    motivo = str(data.get('motivo') or '').strip()
    descricao = str(data.get('descricao') or data.get('evidencias') or '').strip()
    if not motivo:
        return jsonify({'error': 'Informe o motivo da disputa.'}), 400

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para abrir disputa neste pedido.'}), 403

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO disputes (order_id, opened_by, motivo, descricao, status)
            VALUES (?, ?, ?, ?, 'aberta')
        ''', (order_id, user['id'], motivo, descricao))
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
            SELECT status, pago, preco_total, escrow_status, criado_em, completed_at
            FROM orders
            WHERE prestador_id = ?
        ''', (user['id'],)).fetchall()
    finally:
        conn.close()

    faturamento_bruto_mes = 0.0
    saldo_escrow_retido = 0.0
    total_liberado = 0.0

    for o in orders:
        preco = float(_row_get(o, 'preco_total', 0.0) or 0.0)
        status = _row_get(o, 'status', '')
        pago = int(_row_get(o, 'pago', 0) or 0)
        escrow_st = _row_get(o, 'escrow_status', 'pendente')
        ref_dt = str(_row_get(o, 'completed_at') or _row_get(o, 'criado_em') or '')

        if status == 'finalizado':
            if ref_dt.startswith(current_ym):
                faturamento_bruto_mes += preco
            if pago == 1:
                total_liberado += preco
        elif pago == 1 and status not in ('finalizado', 'cancelado') and escrow_st != 'estornado_total':
            saldo_escrow_retido += preco

    faturamento_bruto_mes = round(faturamento_bruto_mes, 2)
    saldo_escrow_retido = round(saldo_escrow_retido, 2)
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
        'total_liberado': total_liberado,
        'total_liberado_liquido': total_liberado_liquido
    }), 200


@app.route('/api/orders/<int:order_id>/review', methods=['POST'])
def review_order(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória para avaliar pedido.', 'code': 'UNAUTHORIZED'}), 401

    data = request.get_json(silent=True) or {}
    raw_nota = data.get('nota')
    try:
        nota = float(raw_nota)
        if nota < 1 or nota > 5 or math.isnan(nota) or math.isinf(nota):
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'error': 'A nota deve ser um valor numérico entre 1 e 5.'}), 400

    comentario = str(data.get('comentario') or '').strip()

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
        cursor.execute('''
            INSERT INTO reviews (order_id, cliente_id, prestador_id, nota, comentario, autor_tipo, avaliado_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, order['cliente_id'], order['prestador_id'], nota, comentario, autor_tipo, avaliado_id))
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
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Avaliação registrada com sucesso!',
        'review_id': review_id,
        'autor_tipo': autor_tipo,
        'avaliacao_media': nova_media,
        'total_avaliacoes': novo_total
    }), 201


@app.route('/api/reviews/<int:review_id>/reply', methods=['POST'])
def reply_review(review_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    data = request.get_json(silent=True) or {}
    replica = str(data.get('replica') or '').strip()
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

    data = request.get_json(silent=True) or {}
    motivo = str(data.get('motivo') or '').strip()
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
def trigger_order_sos(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação obrigatória.'}), 401

    data = request.get_json(silent=True) or {}
    descricao = str(data.get('descricao') or 'Acionamento de emergência SOS').strip()
    tipo = str(data.get('tipo') or 'sos').strip()[:40]
    lat = safe_coord(data.get('lat'), safe_coord(user['lat'], -23.5653))
    lng = safe_coord(data.get('lng'), safe_coord(user['lng'], -46.6517))
    denunciar = bool(data.get('denunciar_contraparte'))

    conn = get_db_connection()
    try:
        order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': 'Pedido não encontrado.'}), 404
        if user['id'] not in (order['cliente_id'], order['prestador_id']):
            return jsonify({'error': 'Sem permissão para acionar SOS neste pedido.'}), 403

        contraparte_id = order['prestador_id'] if user['id'] == order['cliente_id'] else order['cliente_id']
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO safety_incidents (order_id, reporter_id, reported_user_id, tipo, descricao, lat, lng, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'aberto')
        ''', (order_id, user['id'], contraparte_id if denunciar else None, tipo, descricao, lat, lng))
        incident_id = cursor.lastrowid

        if denunciar:
            conn.execute("UPDATE users SET status_conta = 'suspenso_cautelar' WHERE id = ?", (contraparte_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'message': 'Alerta SOS registrado com prioridade máxima.',
        'incident_id': incident_id,
        'status': 'aberto',
        'contraparte_suspensa': denunciar
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

        data = request.get_json(silent=True) or {}
        mensagem = str(data.get('mensagem') or '').strip()
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


# ================= Inicialização do Servidor =================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Servidor PertoJá Marketplace Iniciado!")
    print("👉 Acesse a aplicação no seu navegador: http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
