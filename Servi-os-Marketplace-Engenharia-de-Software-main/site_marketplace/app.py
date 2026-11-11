import os
import re
import math
import hashlib
import sqlite3
import requests
import gzip
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
STATIC_DIR = os.path.join(BASE_DIR, 'index')


def _load_dotenv():
    """Carrega variáveis de arquivos .env locais sem expor credenciais no código."""
    for env_dir in (ROOT_DIR, BASE_DIR):
        env_path = os.path.join(env_dir, '.env')
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

app = Flask(__name__, static_folder=STATIC_DIR)
app.secret_key = os.environ.get('SECRET_KEY') or hashlib.sha256(BASE_DIR.encode('utf-8')).hexdigest()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=(os.environ.get('VERCEL') == '1')
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

    # Compressão Gzip automática se suportada pelo cliente
    accept_encoding = request.headers.get('Accept-Encoding', '')
    if ('gzip' in accept_encoding and 
        response.status_code < 300 and 
        not response.headers.get('Content-Encoding') and 
        response.mimetype in ('text/html', 'text/css', 'text/javascript', 'application/javascript', 'application/json', 'image/svg+xml')):
        
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

# Helper para geocodificação de endereços no OpenStreetMap Nominatim com resolução multinível
def geocode_address(address_str, street=None, neighborhood=None, city=None, state=None, fallback=None):
    """
    Geocodifica endereço no OpenStreetMap Nominatim com tentativas progressivas:
    1. Endereço completo (com logradouro, bairro, cidade, estado)
    2. Logradouro + Cidade + Estado (sem bairro, eliminando a principal causa de falhas no OSM Brasil)
    3. Bairro + Cidade + Estado
    4. Cidade + Estado (garante ao menos a centralização na cidade correta)
    5. fallback explicitamente fornecido (None por padrão)
    """
    candidates = []

    # Monta candidatos por componentes estruturados se fornecidos
    if street and city:
        if neighborhood:
            candidates.append(f"{street}, {neighborhood}, {city} - {state or ''}, Brasil".strip(' ,-'))
        candidates.append(f"{street}, {city} - {state or ''}, Brasil".strip(' ,-'))
    if neighborhood and city:
        candidates.append(f"{neighborhood}, {city} - {state or ''}, Brasil".strip(' ,-'))
    if city:
        candidates.append(f"{city} - {state or ''}, Brasil".strip(' ,-'))
    if state and not city:
        candidates.append(f"{state}, Brasil".strip(' ,-'))

    # Se uma string de busca livre foi passada
    if address_str and address_str.strip():
        raw = address_str.strip()
        if raw not in candidates:
            candidates.insert(0, raw)
        parts = [p.strip() for p in re.split(r'[,–-]', raw) if p.strip()]
        if len(parts) >= 3:
            simplified = f"{parts[0]}, {parts[-1]}, Brasil"
            if simplified not in candidates:
                candidates.append(simplified)
            city_only = f"{parts[-1]}, Brasil"
            if city_only not in candidates:
                candidates.append(city_only)

    headers = {'User-Agent': 'PertoJaMarketplace/2.0 (suporte@pertoja.com.br)'}
    for cand in candidates:
        if not cand:
            continue
        try:
            url = f'https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(cand)}&limit=1'
            r = requests.get(url, headers=headers, timeout=3.0)
            if r.status_code == 200:
                res = r.json()
                if res and len(res) > 0:
                    return float(res[0]['lat']), float(res[0]['lon'])
        except Exception:
            continue

    if fallback is not None:
        return fallback
    return None, None

# ================= Rotas para servir páginas estáticas =================

@app.route('/')
def home():
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/robots.txt')
def robots():
    return send_from_directory(STATIC_DIR, 'robots.txt', mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory(STATIC_DIR, 'sitemap.xml', mimetype='application/xml')

@app.route('/<path:filename>')
def serve_static(filename):
    file_path = os.path.join(STATIC_DIR, filename)
    if os.path.isfile(file_path):
        return send_from_directory(STATIC_DIR, filename)
    if os.path.isfile(os.path.join(STATIC_DIR, '404.html')):
        return send_from_directory(STATIC_DIR, '404.html'), 404
    return send_from_directory(STATIC_DIR, 'index.html'), 404

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Endpoint da API não encontrado.'}), 404
    if os.path.isfile(os.path.join(STATIC_DIR, '404.html')):
        return send_from_directory(STATIC_DIR, '404.html'), 404
    return send_from_directory(STATIC_DIR, 'index.html'), 404

@app.errorhandler(500)
def handle_500(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Erro interno do servidor.'}), 500
    if os.path.isfile(os.path.join(STATIC_DIR, '404.html')):
        return send_from_directory(STATIC_DIR, '404.html'), 500
    return jsonify({'error': 'Erro interno do servidor.'}), 500

# ================= Rotas de Endereço e Geocodificação =================

@app.route('/api/cep/<cep>', methods=['GET'])
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

    lat, lng = geocode_address(
        address_str=f"{street}, {bairro}, {city} - {uf}".strip(', -'),
        street=street,
        neighborhood=bairro,
        city=city,
        state=uf
    )

    # 4. Caso a rua não esteja indexada no Nominatim, usa coordenadas de contingência da BrasilAPI se disponíveis
    if (lat is None or lng is None) and backup_coords:
        lat, lng = backup_coords

    data['lat'] = lat
    data['lng'] = lng
    return jsonify(data)

@app.route('/api/geocode', methods=['GET'])
def geocode_endpoint():
    query = request.args.get('address') or request.args.get('q') or ''
    if not query.strip():
        return jsonify({'error': 'Parâmetro de endereço obrigatório.'}), 400
    lat, lng = geocode_address(query.strip())
    if lat is None or lng is None:
        return jsonify({'error': 'Endereço não localizado no mapa.', 'lat': None, 'lng': None}), 404
    return jsonify({'lat': lat, 'lng': lng, 'query': query.strip()})

# ================= Rotas de Autenticação =================

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    nome = str(data.get('nome') or '').strip()
    email = str(data.get('email') or '').strip().lower()
    senha = str(data.get('senha') or '')
    tipo = str(data.get('tipo') or 'cliente').strip()
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
            INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, complemento, bairro, cidade, estado, lat, lng))
        user_id = cursor.lastrowid

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
                'telefone': telefone,
                'cep': cep,
                'endereco': endereco,
                'numero': numero,
                'bairro': bairro,
                'cidade': cidade,
                'estado': estado,
                'lat': lat,
                'lng': lng
            }
        }), 201
    except Exception as e:
        return jsonify({'error': f'Erro ao cadastrar usuário: {str(e)}'}), 500
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
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
            'disponivel': bool(user['disponivel'])
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Sessão encerrada com sucesso.'})

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
            'total_avaliacoes': user['total_avaliacoes']
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
            'avaliacao_media': user['avaliacao_media']
        })

    # PUT: Atualização de perfil
    data = request.get_json() or {}
    nome = data.get('nome', user['nome']).strip()
    telefone = data.get('telefone', user['telefone']).strip()
    bio = data.get('bio', user['bio']).strip()
    
    cep = data.get('cep', user['cep'] or '').strip()
    endereco = data.get('endereco', user['endereco'] or '').strip()
    numero = data.get('numero', user['numero'] or '').strip()
    complemento = data.get('complemento', user['complemento'] or '').strip()
    bairro = data.get('bairro', user['bairro'] or '').strip()
    cidade = data.get('cidade', user['cidade'] or '').strip()
    estado = data.get('estado', user['estado'] or '').strip()

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

# ================= Rotas de Serviços =================

@app.route('/api/services', methods=['GET'])
def list_services():
    cat = request.args.get('cat', 'Todos')
    query = request.args.get('query', '').strip().lower()
    user_lat = request.args.get('lat', type=float)
    user_lng = request.args.get('lng', type=float)
    radius = request.args.get('radius', default=15.0, type=float)

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
            u.disponivel
        FROM services s
        JOIN users u ON s.prestador_id = u.id
        WHERE s.ativo = 1
    '''
    params = []

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

    for r in rows:
        svc_lat = r['lat'] if r['lat'] is not None else -23.5653
        svc_lng = r['lng'] if r['lng'] is not None else -46.6517

        dist_km = calcular_distancia(center_lat, center_lng, svc_lat, svc_lng)
        if radius and dist_km > radius:
            continue
        
        # Algoritmo de score
        score = 1000 * (1 - min(dist_km / 15.0, 1.0)) + (r['avaliacao_media'] * 100) + (200 if r['disponivel'] else 0)

        # Formata endereço legível
        partes_end = []
        if r['endereco']:
            end_num = f"{r['endereco']}" + (f", {r['numero']}" if r['numero'] else '')
            partes_end.append(end_num)
        if r['bairro']:
            partes_end.append(r['bairro'])
        if r['cidade']:
            cid_uf = f"{r['cidade']}" + (f" - {r['estado']}" if r['estado'] else '')
            partes_end.append(cid_uf)
        
        endereco_formatado = " · ".join(partes_end) if partes_end else "São Paulo - SP"

        results.append({
            'id': r['service_id'],
            'titulo': r['titulo'],
            'descricao': r['descricao'],
            'categoria': r['categoria'],
            'preco': r['preco'],
            'lat': svc_lat,
            'lng': svc_lng,
            'bairro': r['bairro'] or '',
            'cidade': r['cidade'] or 'São Paulo',
            'estado': r['estado'] or 'SP',
            'endereco_completo': endereco_formatado,
            'endereco': {
                'cep': r['cep'] or '',
                'logradouro': r['endereco'] or '',
                'numero': r['numero'] or '',
                'bairro': r['bairro'] or '',
                'cidade': r['cidade'] or 'São Paulo',
                'estado': r['estado'] or 'SP',
                'completo': endereco_formatado
            },
            'prestador': {
                'id': r['prestador_id'],
                'nome': r['prestador_nome'],
                'telefone': r['prestador_telefone'],
                'bio': r['prestador_bio'],
                'avaliacao': r['avaliacao_media'],
                'total_avaliacoes': r['total_avaliacoes'],
                'disponivel': bool(r['disponivel']),
                'lat': svc_lat,
                'lng': svc_lng
            },
            'distancia_km': round(dist_km, 1),
            'score': round(score)
        })

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

    data = request.get_json() or {}
    titulo = str(data.get('titulo') or '').strip()
    descricao = str(data.get('descricao') or '').strip()
    categoria = str(data.get('categoria') or '').strip()
    preco = data.get('preco')

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
    except sqlite3.IntegrityError:
        # Se houver pedidos vinculados a este serviço, desativa para manter integridade dos pedidos
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

    data = request.get_json() or {}
    
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
        INSERT INTO orders (cliente_id, prestador_id, servico_id, preco_total, observacoes, cep_cliente, endereco_cliente, numero_cliente, bairro_cliente, cidade_cliente, estado_cliente, lat_cliente, lng_cliente, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'solicitado')
    ''', (user['id'], service['prestador_id'], service['id'], service['preco'], observacoes, cep_cli, end_cli, num_cli, bairro_cli, cidade_cli, estado_cli, lat_cliente, lng_cliente))
    conn.commit()
    order_id = cursor.lastrowid
    conn.close()

    return jsonify({
        'message': 'Pedido solicitado com sucesso!',
        'order_id': order_id,
        'status': 'solicitado',
        'cliente_id': user['id']
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

    conn.execute('''
        UPDATE orders 
        SET status = 'finalizado', atualizado_em = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (order_id,))
    conn.commit()
    conn.close()

    return jsonify({
        'message': 'Pagamento confirmado e pedido finalizado com sucesso!',
        'order_id': order_id,
        'status': 'finalizado'
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
                o.bairro_cliente,
                o.cidade_cliente,
                o.estado_cliente,
                o.lat_cliente,
                o.lng_cliente,
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
    return jsonify([dict(o) for o in orders])

@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Não autenticado.'}), 401

    data = request.get_json() or {}
    novo_status = data.get('status')
    valid_statuses = ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'finalizado', 'cancelado')
    if novo_status not in valid_statuses:
        return jsonify({'error': f'Status inválido. Escolha: {", ".join(valid_statuses)}'}), 400

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

    conn.execute('''
        UPDATE orders 
        SET status = ?, atualizado_em = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (novo_status, order_id))
    conn.commit()
    conn.close()

    return jsonify({'message': f'Status do pedido atualizado para {novo_status}.', 'status': novo_status})

# ================= Inicialização do Servidor =================

if __name__ == '__main__':
    print("🚀 Servidor PertoJá Marketplace rodando em http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
