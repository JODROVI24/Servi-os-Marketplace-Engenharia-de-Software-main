import os
import re
import sqlite3
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

# Defensive import of psycopg2
try:
    import psycopg2
    from psycopg2 import extras
    from psycopg2 import IntegrityError as _Psycopg2IntegrityError
    HAS_PSYCOPG2 = True
except ImportError:
    psycopg2 = None
    extras = None
    _Psycopg2IntegrityError = None
    HAS_PSYCOPG2 = False


# Unified DBIntegrityError catching both SQLite and PostgreSQL integrity errors
class _FallbackPsycopg2IntegrityError(Exception):
    """Fallback exception class when psycopg2 is not installed."""
    pass


if _Psycopg2IntegrityError is not None:
    Psycopg2IntegrityError = _Psycopg2IntegrityError
else:
    Psycopg2IntegrityError = _FallbackPsycopg2IntegrityError

DBIntegrityError = (sqlite3.IntegrityError, Psycopg2IntegrityError)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS_DIR = os.path.join(BASE_DIR, 'scripts', 'migrations')


def _load_dotenv_defensive():
    """Carrega variáveis de ambiente de arquivos .env locais se presentes."""
    env_file = os.path.join(BASE_DIR, '.env')
    if os.path.isfile(env_file):
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


_load_dotenv_defensive()


def resolve_database_url():
    """
    Resolve e normaliza a URL de conexão com banco de dados a partir das variáveis de ambiente.
    Ordem de prioridade:
    1. DATABASE_URL
    2. POSTGRES_URL (Vercel Postgres pooled)
    3. POSTGRES_URL_NON_POOLING (Vercel Postgres direct)

    Normaliza esquema: postgres:// -> postgresql://
    Aplica sslmode=require para conexões remotas se não configurado.
    Retorna tupla: (normalized_url, engine_name) onde engine_name é 'postgresql' ou 'sqlite'.
    """
    raw_url = (
        os.environ.get('DATABASE_URL')
        or os.environ.get('POSTGRES_URL')
        or os.environ.get('POSTGRES_URL_NON_POOLING')
    )
    if not raw_url or not raw_url.strip():
        return None, 'sqlite'

    url = raw_url.strip()
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]

    if not url.startswith('postgresql://'):
        raise RuntimeError(
            'DATABASE_URL inválida: apenas URLs PostgreSQL (postgresql:// ou postgres://) são suportadas.'
        )

    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname or ''
    is_local = hostname in ('localhost', '127.0.0.1', '')

    query_params = dict(urllib.parse.parse_qsl(parsed.query))
    if not is_local and 'sslmode' not in query_params:
        query_params['sslmode'] = 'require'
        new_query = urllib.parse.urlencode(query_params)
        url = urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            new_query,
            parsed.fragment
        ))

    return url, 'postgresql'


def get_active_engine():
    """Retorna o nome do motor de banco ativo ('postgresql' ou 'sqlite')."""
    _, engine = resolve_database_url()
    return engine


def is_production_env():
    """Retorna True quando executando em ambiente de produção (VERCEL=1/true ou FLASK_ENV=production)."""
    vercel_flag = str(os.environ.get('VERCEL', '')).strip().lower()
    flask_env = str(os.environ.get('FLASK_ENV', '')).strip().lower()
    return vercel_flag in ('1', 'true') or flask_env == 'production'


def is_demo_seed_enabled():
    """
    Contas e dados de demonstração são desabilitados por padrão ('0')
    e estritamente proibidos em ambiente de produção.
    """
    if is_production_env():
        return False
    return str(os.environ.get('ENABLE_DEMO_SEED', '0')).strip().lower() in ('1', 'true', 'yes')


def ensure_production_database():
    """
    Em produção (VERCEL=1 ou FLASK_ENV=production), exige PostgreSQL configurado
    e proíbe fallback silencioso para SQLite efêmero em /tmp.
    """
    if not is_production_env():
        return
    url, engine = resolve_database_url()
    if engine != 'postgresql' or not url:
        raise RuntimeError(
            'DATABASE_URL (ou POSTGRES_URL / POSTGRES_URL_NON_POOLING) com PostgreSQL é obrigatória em produção '
            '(VERCEL=1 ou FLASK_ENV=production). Fallback para SQLite em /tmp não é permitido em produção.'
        )


def _resolve_db_path():
    """
    Resolve o caminho do banco SQLite.
    Usa /tmp/marketplace.db APENAS quando um ambiente serverless
    (VERCEL, AWS_LAMBDA_FUNCTION_NAME, VERCEL_REGION ou NOW_REGION) está ativo.
    Em ambientes locais, utiliza sempre o arquivo 'marketplace.db' na raiz do projeto.
    """
    if 'MARKETPLACE_DB' in os.environ and os.environ['MARKETPLACE_DB'].strip():
        return os.environ['MARKETPLACE_DB'].strip()

    is_serverless = (
        os.environ.get('VERCEL') in ('1', 'true')
        or 'AWS_LAMBDA_FUNCTION_NAME' in os.environ
        or 'VERCEL_REGION' in os.environ
        or 'NOW_REGION' in os.environ
    )
    if is_serverless:
        return '/tmp/marketplace.db'

    return os.path.join(BASE_DIR, 'marketplace.db')


DB_PATH = _resolve_db_path()


def _normalizar_query(texto):
    """
    Normaliza consultas de endereço para chave de cache de geocodificação:
    - remove espaços no início e fim;
    - converte para minúsculas;
    - remove acentos via decomposição NFD e filtragem ASCII;
    - remove número residencial isolado para maior reaproveitamento de cache (ET-10);
    - colapsa múltiplos espaços em um único espaço.
    """
    if not texto:
        return ''
    sem_acentos = unicodedata.normalize('NFD', str(texto)).encode('ascii', 'ignore').decode('ascii').lower()
    sem_numero = re.sub(r'(?<=[a-z\s]),?\s+\b\d{1,5}\b(?=\s*(?:,|$|-))', '', sem_acentos)
    return re.sub(r'\s+', ' ', sem_numero).strip()


def translate_placeholders(sql):
    """
    Converte marcadores posicionais SQLite '?' para marcadores PostgreSQL '%s',
    preservando caracteres '?' contidos dentro de literais de string ('...' ou "...").
    """
    if not sql or '?' not in sql:
        return sql

    result = []
    in_single_quote = False
    in_double_quote = False
    escape = False
    i = 0
    n = len(sql)

    while i < n:
        char = sql[i]
        if escape:
            result.append(char)
            escape = False
            i += 1
            continue

        if char == '\\':
            result.append(char)
            escape = True
            i += 1
            continue

        if char == "'" and not in_double_quote:
            # Trata escape SQL de aspa simples duplicada ('')
            if in_single_quote and i + 1 < n and sql[i + 1] == "'":
                result.append("''")
                i += 2
                continue
            in_single_quote = not in_single_quote
            result.append(char)
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(char)
            i += 1
            continue

        if char == '?' and not in_single_quote and not in_double_quote:
            result.append('%s')
            i += 1
            continue

        result.append(char)
        i += 1

    return ''.join(result)


class HybridRow:
    """
    Representação híbrida de linha de banco compatível com sqlite3.Row e DictCursor.
    Suporta:
    - row['coluna']
    - row[0] (indexação inteira)
    - dict(row)
    - 'coluna' in row
    - row.get('coluna', default)
    - iteração sobre chaves
    """
    def __init__(self, data_dict, data_tuple=None):
        self._data_dict = dict(data_dict) if data_dict is not None else {}
        if data_tuple is not None:
            self._data_tuple = tuple(data_tuple)
        else:
            self._data_tuple = tuple(self._data_dict.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data_tuple[key]
        return self._data_dict[key]

    def __iter__(self):
        return iter(self._data_dict)

    def __len__(self):
        return len(self._data_dict)

    def __contains__(self, key):
        return key in self._data_dict

    def keys(self):
        return self._data_dict.keys()

    def values(self):
        return self._data_dict.values()

    def items(self):
        return self._data_dict.items()

    def get(self, key, default=None):
        return self._data_dict.get(key, default)

    def __repr__(self):
        return f"<HybridRow {self._data_dict!r}>"

    def __eq__(self, other):
        if isinstance(other, HybridRow):
            return self._data_dict == other._data_dict
        if isinstance(other, dict):
            return self._data_dict == other
        if isinstance(other, (tuple, list)):
            return self._data_tuple == tuple(other)
        return False


class PostgresCursorWrapper:
    """
    Cursor wrapper transparente para PostgreSQL:
    - Traduz '?' para '%s'
    - Anexa 'RETURNING id' em INSERTs para tabelas com chave primária id
    - Popula cursor.lastrowid
    - Retorna linhas encapsuladas em HybridRow (acesso por chave e por índice numérico)
    """
    def __init__(self, raw_cursor):
        self._cursor = raw_cursor
        self.lastrowid = None

    @property
    def description(self):
        return getattr(self._cursor, 'description', None)

    @property
    def rowcount(self):
        return getattr(self._cursor, 'rowcount', -1)

    def _wrap_row(self, raw_row):
        if raw_row is None:
            return None
        if isinstance(raw_row, HybridRow):
            return raw_row
        if isinstance(raw_row, dict):
            return HybridRow(raw_row, tuple(raw_row.values()))
        if hasattr(raw_row, '_asdict'):
            return HybridRow(raw_row._asdict(), raw_row)
        if hasattr(raw_row, 'keys'):
            d = {k: raw_row[k] for k in raw_row.keys()}
            return HybridRow(d, tuple(raw_row))
        if self._cursor and getattr(self._cursor, 'description', None):
            col_names = [desc[0] for desc in self._cursor.description]
            d = dict(zip(col_names, raw_row))
            return HybridRow(d, tuple(raw_row))
        if isinstance(raw_row, (list, tuple)):
            d = {f"col_{idx}": val for idx, val in enumerate(raw_row)}
            return HybridRow(d, tuple(raw_row))
        return raw_row

    def execute(self, sql, params=None):
        clean_sql = sql.strip()
        upper_sql = clean_sql.upper()

        needs_returning = False
        is_insert = upper_sql.startswith('INSERT INTO') or upper_sql.startswith('INSERT')
        has_returning = 'RETURNING' in upper_sql
        is_no_id_table = any(t in upper_sql for t in ('GEOCODE_CACHE', 'RATE_LIMIT', 'SCHEMA_MIGRATIONS', 'PASSWORD_RESET_TOKENS'))

        if is_insert and not has_returning and not is_no_id_table:
            needs_returning = True
            sql_to_run = clean_sql.rstrip().rstrip(';') + ' RETURNING id'
        else:
            sql_to_run = sql

        translated_sql = translate_placeholders(sql_to_run)

        if params is not None:
            self._cursor.execute(translated_sql, params)
        else:
            self._cursor.execute(translated_sql)

        if needs_returning:
            try:
                ret_row = self._cursor.fetchone()
                if ret_row is not None:
                    if isinstance(ret_row, dict) or hasattr(ret_row, '__getitem__'):
                        try:
                            self.lastrowid = ret_row['id']
                        except (KeyError, TypeError, IndexError):
                            self.lastrowid = ret_row[0]
                    else:
                        self.lastrowid = getattr(ret_row, 'id', None)
            except Exception:
                pass

        return self

    def executescript(self, script):
        for raw_stmt in script.split(';'):
            stmt = raw_stmt.strip()
            if not stmt:
                continue
            has_sql = any(
                line.strip() and not line.strip().startswith('--')
                for line in stmt.splitlines()
            )
            if has_sql:
                self.execute(stmt)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._wrap_row(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [self._wrap_row(r) for r in rows]

    def fetchmany(self, size=None):
        if size is not None:
            rows = self._cursor.fetchmany(size)
        else:
            rows = self._cursor.fetchmany()
        return [self._wrap_row(r) for r in rows]

    def close(self):
        return self._cursor.close()

    def __iter__(self):
        for r in self._cursor:
            yield self._wrap_row(r)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class PostgresConnectionWrapper:
    """
    Connection wrapper transparente para PostgreSQL:
    - Suporta conn.execute(sql, params) retornando cursor adaptado
    - Suporta conn.cursor(), conn.commit(), conn.rollback(), conn.close()
    - Suporta conn.executescript(script)
    - Suporta context manager
    """
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self, *args, **kwargs):
        raw_cur = self._conn.cursor(*args, **kwargs)
        return PostgresCursorWrapper(raw_cur)

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script):
        cur = self.cursor()
        cur.executescript(script)
        return cur

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def _connect_postgres(url):
    if not HAS_PSYCOPG2:
        raise ImportError(
            "psycopg2 é necessário para conectar ao PostgreSQL. "
            "Instale psycopg2-binary>=2.9.9 ou use o fallback SQLite local."
        )
    cursor_factory = extras.DictCursor if extras else None
    conn = psycopg2.connect(url, cursor_factory=cursor_factory)
    return PostgresConnectionWrapper(conn)


def get_db_connection():
    url, engine = resolve_database_url()
    if engine == 'postgresql' and url:
        return _connect_postgres(url)

    ensure_production_database()

    # Fallback transparente para SQLite local (apenas desenvolvimento/testes)
    db_abs = os.path.abspath(DB_PATH)
    parent_dir = os.path.dirname(db_abs)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


POSTGRES_SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    tipo TEXT CHECK(tipo IN ('cliente', 'prestador')) NOT NULL,
    telefone TEXT,
    bio TEXT,
    foto_url TEXT,
    cep TEXT,
    endereco TEXT,
    numero TEXT,
    complemento TEXT,
    bairro TEXT,
    cidade TEXT,
    estado TEXT,
    lat DOUBLE PRECISION DEFAULT -23.5653,
    lng DOUBLE PRECISION DEFAULT -46.6517,
    avaliacao_media DOUBLE PRECISION DEFAULT 5.0,
    total_avaliacoes INTEGER DEFAULT 0,
    disponivel INTEGER DEFAULT 1,
    plano TEXT DEFAULT 'basico',
    kyc_tier INTEGER DEFAULT 1,
    kyc_status TEXT DEFAULT 'aprovado',
    kyc_documento_tipo TEXT DEFAULT 'RG',
    kyc_provider_ref TEXT,
    kyc_verified_at TIMESTAMP,
    registro_profissional TEXT,
    cpf TEXT,
    status_conta TEXT DEFAULT 'ativo',
    session_version INTEGER DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    prestador_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    descricao TEXT,
    categoria TEXT NOT NULL,
    preco DOUBLE PRECISION NOT NULL,
    cep TEXT,
    endereco TEXT,
    numero TEXT,
    bairro TEXT,
    cidade TEXT,
    estado TEXT,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    ativo INTEGER DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(prestador_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    prestador_id INTEGER NOT NULL,
    servico_id INTEGER NOT NULL,
    status TEXT CHECK(status IN ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'finalizado', 'cancelado', 'em_disputa')) DEFAULT 'solicitado',
    preco_total DOUBLE PRECISION NOT NULL,
    observacoes TEXT,
    cep_cliente TEXT,
    endereco_cliente TEXT,
    numero_cliente TEXT,
    bairro_cliente TEXT,
    cidade_cliente TEXT,
    estado_cliente TEXT,
    lat_cliente DOUBLE PRECISION,
    lng_cliente DOUBLE PRECISION,
    complemento_cliente TEXT,
    modalidade TEXT DEFAULT 'imediato',
    agendado_para TEXT,
    metodo_pagamento TEXT DEFAULT 'escrow',
    pago INTEGER DEFAULT 0,
    codigo_confirmacao TEXT,
    motivo_cancelamento TEXT,
    escrow_status TEXT DEFAULT 'pendente',
    taxa_deslocamento DOUBLE PRECISION DEFAULT 0,
    valor_estornado DOUBLE PRECISION DEFAULT 0,
    share_token TEXT,
    completed_at TIMESTAMP,
    released_at TIMESTAMP,
    release_due_at TIMESTAMP,
    confirmado_cliente INTEGER DEFAULT 0,
    pin_tentativas INTEGER DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(cliente_id) REFERENCES users(id),
    FOREIGN KEY(prestador_id) REFERENCES users(id),
    FOREIGN KEY(servico_id) REFERENCES services(id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    prestador_id INTEGER NOT NULL,
    nota DOUBLE PRECISION NOT NULL,
    comentario TEXT,
    autor_tipo TEXT DEFAULT 'cliente',
    avaliado_id INTEGER,
    replica TEXT,
    replied_at TIMESTAMP,
    contestada INTEGER DEFAULT 0,
    motivo_contestacao TEXT,
    status_moderacao TEXT DEFAULT 'visivel',
    revealed_at TIMESTAMP,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id),
    FOREIGN KEY(cliente_id) REFERENCES users(id),
    FOREIGN KEY(prestador_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_consents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    doc_version TEXT NOT NULL,
    ip_hash TEXT,
    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS disputes (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    opened_by INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    descricao TEXT,
    status TEXT DEFAULT 'aberta',
    resolucao TEXT,
    valor_estornado DOUBLE PRECISION DEFAULT 0,
    taxa_deslocamento DOUBLE PRECISION DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolvido_em TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(opened_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS safety_incidents (
    id SERIAL PRIMARY KEY,
    order_id INTEGER,
    reporter_id INTEGER NOT NULL,
    reported_user_id INTEGER,
    tipo TEXT DEFAULT 'sos',
    descricao TEXT,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    status TEXT DEFAULT 'aberto',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE SET NULL,
    FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS account_appeals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    evidencias TEXT,
    status TEXT DEFAULT 'em_analise',
    resposta TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    analisado_em TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS order_messages (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    sender_tipo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS escrow_ledger (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    tipo_evento TEXT NOT NULL,
    valor DOUBLE PRECISION DEFAULT 0,
    status_escrow TEXT,
    observacao TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    query TEXT PRIMARY KEY,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    origem TEXT DEFAULT 'nominatim',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rate_limit (
    rate_key TEXT NOT NULL,
    ts DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    used INTEGER DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS payment_methods (
    id SERIAL PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    gateway TEXT NOT NULL CHECK(gateway IN ('sandbox', 'mercadopago', 'stripe', 'pagseguro')),
    gateway_customer_id TEXT,
    gateway_token TEXT NOT NULL,
    brand TEXT NOT NULL,
    last4 TEXT NOT NULL CHECK(length(last4) = 4),
    exp_month INTEGER NOT NULL CHECK(exp_month >= 1 AND exp_month <= 12),
    exp_year INTEGER NOT NULL CHECK(exp_year >= 2024),
    holder_label TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pay_methods_user ON payment_methods(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_methods_user_gw_tok ON payment_methods(user_id, gateway, gateway_token);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id SERIAL PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    order_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    gateway TEXT NOT NULL CHECK(gateway IN ('sandbox', 'mercadopago', 'stripe', 'pagseguro')),
    method TEXT NOT NULL CHECK(method IN ('pix', 'cartao', 'boleto', 'escrow')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'requires_action', 'authorized', 'paid', 'escrow_held', 'released', 'refunded', 'partially_refunded', 'failed', 'expired', 'cancelled')),
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    refunded_cents INTEGER NOT NULL DEFAULT 0 CHECK(refunded_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'BRL',
    gateway_payment_id TEXT,
    gateway_reference TEXT,
    checkout_url TEXT,
    pix_qr_code TEXT,
    pix_qr_base64 TEXT,
    boleto_barcode TEXT,
    boleto_digitable_line TEXT,
    boleto_url TEXT,
    payment_method_id INTEGER,
    escrow_synced INTEGER NOT NULL DEFAULT 0,
    failure_code TEXT,
    failure_message TEXT,
    metadata_json TEXT,
    expires_at TIMESTAMP,
    paid_at TIMESTAMP,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(payment_method_id) REFERENCES payment_methods(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pay_tx_order ON payment_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_pay_tx_user ON payment_transactions(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_tx_gw_pid ON payment_transactions(gateway, gateway_payment_id) WHERE gateway_payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS payment_idempotency_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    payment_id INTEGER,
    response_status INTEGER,
    response_body TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(payment_id) REFERENCES payment_transactions(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_idem_user_scope_key ON payment_idempotency_keys(user_id, scope, idempotency_key);

CREATE TABLE IF NOT EXISTS payment_webhooks (
    id SERIAL PRIMARY KEY,
    gateway TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    gateway_payment_id TEXT,
    signature_valid INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'received' CHECK(processing_status IN ('received', 'processed', 'ignored', 'failed')),
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    error_message TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_webhooks_gw_event ON payment_webhooks(gateway, event_id);

CREATE TABLE IF NOT EXISTS payment_refunds (
    id SERIAL PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    payment_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    requested_by INTEGER,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'succeeded', 'failed')),
    gateway_refund_id TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(payment_id) REFERENCES payment_transactions(id) ON DELETE CASCADE,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pay_refunds_payment ON payment_refunds(payment_id);
CREATE INDEX IF NOT EXISTS idx_pay_refunds_order ON payment_refunds(order_id);
'''

SQLITE_SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    tipo TEXT CHECK(tipo IN ('cliente', 'prestador')) NOT NULL,
    telefone TEXT,
    bio TEXT,
    foto_url TEXT,
    cep TEXT,
    endereco TEXT,
    numero TEXT,
    complemento TEXT,
    bairro TEXT,
    cidade TEXT,
    estado TEXT,
    lat REAL DEFAULT -23.5653,
    lng REAL DEFAULT -46.6517,
    avaliacao_media REAL DEFAULT 5.0,
    total_avaliacoes INTEGER DEFAULT 0,
    disponivel INTEGER DEFAULT 1,
    plano TEXT DEFAULT 'basico',
    kyc_tier INTEGER DEFAULT 1,
    kyc_status TEXT DEFAULT 'aprovado',
    kyc_documento_tipo TEXT DEFAULT 'RG',
    kyc_provider_ref TEXT,
    kyc_verified_at TIMESTAMP,
    registro_profissional TEXT,
    cpf TEXT,
    status_conta TEXT DEFAULT 'ativo',
    session_version INTEGER DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prestador_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    descricao TEXT,
    categoria TEXT NOT NULL,
    preco REAL NOT NULL,
    cep TEXT,
    endereco TEXT,
    numero TEXT,
    bairro TEXT,
    cidade TEXT,
    estado TEXT,
    lat REAL,
    lng REAL,
    ativo INTEGER DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(prestador_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    prestador_id INTEGER NOT NULL,
    servico_id INTEGER NOT NULL,
    status TEXT CHECK(status IN ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'finalizado', 'cancelado', 'em_disputa')) DEFAULT 'solicitado',
    preco_total REAL NOT NULL,
    observacoes TEXT,
    cep_cliente TEXT,
    endereco_cliente TEXT,
    numero_cliente TEXT,
    bairro_cliente TEXT,
    cidade_cliente TEXT,
    estado_cliente TEXT,
    lat_cliente REAL,
    lng_cliente REAL,
    complemento_cliente TEXT,
    modalidade TEXT DEFAULT 'imediato',
    agendado_para TEXT,
    metodo_pagamento TEXT DEFAULT 'escrow',
    pago INTEGER DEFAULT 0,
    codigo_confirmacao TEXT,
    motivo_cancelamento TEXT,
    escrow_status TEXT DEFAULT 'pendente',
    taxa_deslocamento REAL DEFAULT 0,
    valor_estornado REAL DEFAULT 0,
    share_token TEXT,
    completed_at TIMESTAMP,
    released_at TIMESTAMP,
    release_due_at TIMESTAMP,
    confirmado_cliente INTEGER DEFAULT 0,
    pin_tentativas INTEGER DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(cliente_id) REFERENCES users(id),
    FOREIGN KEY(prestador_id) REFERENCES users(id),
    FOREIGN KEY(servico_id) REFERENCES services(id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    cliente_id INTEGER NOT NULL,
    prestador_id INTEGER NOT NULL,
    nota REAL NOT NULL,
    comentario TEXT,
    autor_tipo TEXT DEFAULT 'cliente',
    avaliado_id INTEGER,
    replica TEXT,
    replied_at TIMESTAMP,
    contestada INTEGER DEFAULT 0,
    motivo_contestacao TEXT,
    status_moderacao TEXT DEFAULT 'visivel',
    revealed_at TIMESTAMP,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id),
    FOREIGN KEY(cliente_id) REFERENCES users(id),
    FOREIGN KEY(prestador_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    doc_version TEXT NOT NULL,
    ip_hash TEXT,
    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    opened_by INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    descricao TEXT,
    status TEXT DEFAULT 'aberta',
    resolucao TEXT,
    valor_estornado REAL DEFAULT 0,
    taxa_deslocamento REAL DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolvido_em TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(opened_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS safety_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    reporter_id INTEGER NOT NULL,
    reported_user_id INTEGER,
    tipo TEXT DEFAULT 'sos',
    descricao TEXT,
    lat REAL,
    lng REAL,
    status TEXT DEFAULT 'aberto',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE SET NULL,
    FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS account_appeals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    evidencias TEXT,
    status TEXT DEFAULT 'em_analise',
    resposta TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    analisado_em TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS order_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    sender_tipo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS escrow_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    tipo_evento TEXT NOT NULL,
    valor REAL DEFAULT 0,
    status_escrow TEXT,
    observacao TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    query TEXT PRIMARY KEY,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    origem TEXT DEFAULT 'nominatim',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rate_limit (
    rate_key TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS payment_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    gateway TEXT NOT NULL CHECK(gateway IN ('sandbox', 'mercadopago', 'stripe', 'pagseguro')),
    gateway_customer_id TEXT,
    gateway_token TEXT NOT NULL,
    brand TEXT NOT NULL,
    last4 TEXT NOT NULL CHECK(length(last4) = 4),
    exp_month INTEGER NOT NULL CHECK(exp_month >= 1 AND exp_month <= 12),
    exp_year INTEGER NOT NULL CHECK(exp_year >= 2024),
    holder_label TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pay_methods_user ON payment_methods(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_methods_user_gw_tok ON payment_methods(user_id, gateway, gateway_token);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    order_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    gateway TEXT NOT NULL CHECK(gateway IN ('sandbox', 'mercadopago', 'stripe', 'pagseguro')),
    method TEXT NOT NULL CHECK(method IN ('pix', 'cartao', 'boleto', 'escrow')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'requires_action', 'authorized', 'paid', 'escrow_held', 'released', 'refunded', 'partially_refunded', 'failed', 'expired', 'cancelled')),
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    refunded_cents INTEGER NOT NULL DEFAULT 0 CHECK(refunded_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'BRL',
    gateway_payment_id TEXT,
    gateway_reference TEXT,
    checkout_url TEXT,
    pix_qr_code TEXT,
    pix_qr_base64 TEXT,
    boleto_barcode TEXT,
    boleto_digitable_line TEXT,
    boleto_url TEXT,
    payment_method_id INTEGER,
    escrow_synced INTEGER NOT NULL DEFAULT 0,
    failure_code TEXT,
    failure_message TEXT,
    metadata_json TEXT,
    expires_at TIMESTAMP,
    paid_at TIMESTAMP,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(payment_method_id) REFERENCES payment_methods(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pay_tx_order ON payment_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_pay_tx_user ON payment_transactions(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_tx_gw_pid ON payment_transactions(gateway, gateway_payment_id) WHERE gateway_payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS payment_idempotency_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    payment_id INTEGER,
    response_status INTEGER,
    response_body TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(payment_id) REFERENCES payment_transactions(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_idem_user_scope_key ON payment_idempotency_keys(user_id, scope, idempotency_key);

CREATE TABLE IF NOT EXISTS payment_webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gateway TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    gateway_payment_id TEXT,
    signature_valid INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'received' CHECK(processing_status IN ('received', 'processed', 'ignored', 'failed')),
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    error_message TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_webhooks_gw_event ON payment_webhooks(gateway, event_id);

CREATE TABLE IF NOT EXISTS payment_refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    payment_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    requested_by INTEGER,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'succeeded', 'failed')),
    gateway_refund_id TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(payment_id) REFERENCES payment_transactions(id) ON DELETE CASCADE,
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pay_refunds_payment ON payment_refunds(payment_id);
CREATE INDEX IF NOT EXISTS idx_pay_refunds_order ON payment_refunds(order_id);
'''


def _table_exists(cursor, table_name, engine):
    """Verifica se uma tabela já existe no banco ativo."""
    if engine == 'postgresql':
        row = cursor.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ?",
            (table_name,)
        ).fetchone()
    else:
        row = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,)
        ).fetchone()
    return row is not None


def _ensure_migrations_table(cursor):
    """Garante a existência da tabela schema_migrations para controle de versão."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


def list_migration_files():
    """Lista em ordem alfabética os arquivos .sql em scripts/migrations/."""
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    files = [
        f for f in os.listdir(MIGRATIONS_DIR)
        if f.endswith('.sql') and os.path.isfile(os.path.join(MIGRATIONS_DIR, f))
    ]
    return sorted(files)


def run_migrations(conn=None, dry_run=False):
    """
    Executa migrations pendentes de scripts/migrations/*.sql registrando em schema_migrations.
    Quando dry_run=True, apenas inspeciona e retorna o relatório sem alterar o banco.
    Retorna lista de dicionários com status de cada arquivo.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_db_connection()

    cursor = conn.cursor()
    engine = get_active_engine()
    report = []

    migration_files = list_migration_files()

    if dry_run:
        applied_versions = set()
        if _table_exists(cursor, 'schema_migrations', engine):
            rows = cursor.execute("SELECT version FROM schema_migrations").fetchall()
            applied_versions = {r['version'] for r in rows}
        for filename in migration_files:
            status = 'already_applied' if filename in applied_versions else 'pending'
            report.append({'version': filename, 'status': status})
        if own_conn:
            conn.close()
        return report

    _ensure_migrations_table(cursor)
    conn.commit()

    rows = cursor.execute("SELECT version FROM schema_migrations").fetchall()
    applied_versions = {r['version'] for r in rows}

    for filename in migration_files:
        if filename in applied_versions:
            report.append({'version': filename, 'status': 'already_applied'})
            continue

        filepath = os.path.join(MIGRATIONS_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            sql_script = f.read()

        if sql_script.strip():
            if engine == 'sqlite':
                sql_script = re.sub(
                    r'\bSERIAL\s+PRIMARY\s+KEY\b',
                    'INTEGER PRIMARY KEY AUTOINCREMENT',
                    sql_script,
                    flags=re.IGNORECASE
                )
            cursor.executescript(sql_script)

        cursor.execute(
            "INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT (version) DO NOTHING",
            (filename,)
        )
        conn.commit()
        report.append({'version': filename, 'status': 'applied'})

    if own_conn:
        conn.close()
    return report


def _ensure_columns(conn, cursor, engine):
    """Garante defensivamente que colunas novas existam em bancos SQLite e PostgreSQL já existentes."""
    real_type = 'DOUBLE PRECISION' if engine == 'postgresql' else 'REAL'
    expected_columns = {
        'users': [
            ('plano', "TEXT DEFAULT 'basico'"),
            ('kyc_tier', 'INTEGER DEFAULT 1'),
            ('kyc_status', "TEXT DEFAULT 'aprovado'"),
            ('kyc_documento_tipo', "TEXT DEFAULT 'RG'"),
            ('kyc_provider_ref', 'TEXT'),
            ('kyc_verified_at', 'TIMESTAMP'),
            ('registro_profissional', 'TEXT'),
            ('cpf', 'TEXT'),
            ('status_conta', "TEXT DEFAULT 'ativo'"),
            ('session_version', 'INTEGER DEFAULT 1'),
        ],
        'orders': [
            ('complemento_cliente', 'TEXT'),
            ('modalidade', "TEXT DEFAULT 'imediato'"),
            ('agendado_para', 'TEXT'),
            ('metodo_pagamento', "TEXT DEFAULT 'escrow'"),
            ('pago', 'INTEGER DEFAULT 0'),
            ('codigo_confirmacao', 'TEXT'),
            ('motivo_cancelamento', 'TEXT'),
            ('escrow_status', "TEXT DEFAULT 'pendente'"),
            ('taxa_deslocamento', f'{real_type} DEFAULT 0'),
            ('valor_estornado', f'{real_type} DEFAULT 0'),
            ('share_token', 'TEXT'),
            ('completed_at', 'TIMESTAMP'),
            ('released_at', 'TIMESTAMP'),
            ('release_due_at', 'TIMESTAMP'),
            ('confirmado_cliente', 'INTEGER DEFAULT 0'),
            ('pin_tentativas', 'INTEGER DEFAULT 0'),
        ],
        'reviews': [
            ('autor_tipo', "TEXT DEFAULT 'cliente'"),
            ('avaliado_id', 'INTEGER'),
            ('replica', 'TEXT'),
            ('replied_at', 'TIMESTAMP'),
            ('contestada', 'INTEGER DEFAULT 0'),
            ('motivo_contestacao', 'TEXT'),
            ('status_moderacao', "TEXT DEFAULT 'visivel'"),
            ('revealed_at', 'TIMESTAMP'),
        ],
    }

    for table, cols in expected_columns.items():
        if engine == 'postgresql':
            for col_name, col_def in cols:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            conn.commit()
        else:
            info_rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
            existing_cols = set()
            for r in info_rows:
                try:
                    existing_cols.add(r['name'])
                except (KeyError, TypeError, IndexError):
                    existing_cols.add(r[1])
            for col_name, col_def in cols:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            conn.commit()


def _ensure_orders_status_check(conn, cursor, engine):
    """Garante que a constraint CHECK de orders.status aceite 'em_disputa' em bancos pré-ET."""
    if engine == 'postgresql':
        try:
            row = cursor.execute(
                "SELECT pg_get_constraintdef(oid) AS cdef FROM pg_constraint "
                "WHERE conname = 'orders_status_check' AND conrelid = 'orders'::regclass"
            ).fetchone()
            cdef = row['cdef'] if row and hasattr(row, 'keys') and 'cdef' in row.keys() else (row[0] if row else '')
            if cdef and "'em_disputa'" in str(cdef):
                return
            cursor.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check")
            cursor.execute(
                "ALTER TABLE orders ADD CONSTRAINT orders_status_check "
                "CHECK (status IN ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'em_disputa', 'finalizado', 'cancelado'))"
            )
            conn.commit()
        except Exception:
            conn.rollback()
        return

    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
    ).fetchone()
    if not row:
        return
    table_sql = row['sql'] if hasattr(row, 'keys') and 'sql' in row.keys() else row[0]
    if not table_sql or "'em_disputa'" in table_sql:
        return

    info_rows = cursor.execute("PRAGMA table_info(orders)").fetchall()
    existing_cols = []
    for r in info_rows:
        try:
            existing_cols.append(r['name'])
        except (KeyError, TypeError, IndexError):
            existing_cols.append(r[1])

    new_orders_cols = [
        'id', 'cliente_id', 'prestador_id', 'servico_id', 'status', 'preco_total',
        'observacoes', 'cep_cliente', 'endereco_cliente', 'numero_cliente',
        'bairro_cliente', 'cidade_cliente', 'estado_cliente', 'lat_cliente',
        'lng_cliente', 'complemento_cliente', 'modalidade', 'agendado_para',
        'metodo_pagamento', 'pago', 'codigo_confirmacao', 'motivo_cancelamento',
        'escrow_status', 'taxa_deslocamento', 'valor_estornado', 'share_token',
        'completed_at', 'released_at', 'release_due_at', 'confirmado_cliente',
        'pin_tentativas', 'criado_em', 'atualizado_em'
    ]
    copy_cols = [c for c in new_orders_cols if c in existing_cols]
    cols_csv = ', '.join(copy_cols)

    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute('''
        CREATE TABLE orders__new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            prestador_id INTEGER NOT NULL,
            servico_id INTEGER NOT NULL,
            status TEXT CHECK(status IN ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'finalizado', 'cancelado', 'em_disputa')) DEFAULT 'solicitado',
            preco_total REAL NOT NULL,
            observacoes TEXT,
            cep_cliente TEXT,
            endereco_cliente TEXT,
            numero_cliente TEXT,
            bairro_cliente TEXT,
            cidade_cliente TEXT,
            estado_cliente TEXT,
            lat_cliente REAL,
            lng_cliente REAL,
            complemento_cliente TEXT,
            modalidade TEXT DEFAULT 'imediato',
            agendado_para TEXT,
            metodo_pagamento TEXT DEFAULT 'escrow',
            pago INTEGER DEFAULT 0,
            codigo_confirmacao TEXT,
            motivo_cancelamento TEXT,
            escrow_status TEXT DEFAULT 'pendente',
            taxa_deslocamento REAL DEFAULT 0,
            valor_estornado REAL DEFAULT 0,
            share_token TEXT,
            completed_at TIMESTAMP,
            released_at TIMESTAMP,
            release_due_at TIMESTAMP,
            confirmado_cliente INTEGER DEFAULT 0,
            pin_tentativas INTEGER DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cliente_id) REFERENCES users(id),
            FOREIGN KEY(prestador_id) REFERENCES users(id),
            FOREIGN KEY(servico_id) REFERENCES services(id)
        )
    ''')
    if copy_cols:
        cursor.execute(f"INSERT INTO orders__new ({cols_csv}) SELECT {cols_csv} FROM orders")
    cursor.execute("DROP TABLE orders")
    cursor.execute("ALTER TABLE orders__new RENAME TO orders")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_cliente ON orders(cliente_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_prestador ON orders(prestador_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()


def _get_table_columns(cursor, table_name, engine):
    """Retorna o conjunto de nomes de colunas existentes em uma tabela."""
    if engine == 'postgresql':
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ?",
            (table_name,)
        ).fetchall()
        cols = set()
        for r in rows:
            try:
                cols.add(r['column_name'])
            except (KeyError, TypeError, IndexError):
                cols.add(r[0])
        return cols
    info_rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    cols = set()
    for r in info_rows:
        try:
            cols.add(r['name'])
        except (KeyError, TypeError, IndexError):
            cols.add(r[1])
    return cols


def _retire_legacy_table(cursor, table_name, engine, ts_suffix):
    """Remove tabela legada vazia ou renomeia para <table>_legacy_<ts> preservando dados e evitando colisão de índices/constraints."""
    row = cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}").fetchone()
    try:
        count = int(row['cnt'])
    except (KeyError, TypeError, IndexError):
        count = int(row[0]) if row else 0
    if count == 0:
        if engine == 'postgresql':
            cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        else:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        return

    legacy_name = f"{table_name}_legacy_{ts_suffix}"
    cursor.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_name}")

    if engine == 'postgresql':
        con_rows = cursor.execute(
            "SELECT c.conname FROM pg_constraint c "
            "JOIN pg_class cl ON c.conrelid = cl.oid "
            "JOIN pg_namespace n ON cl.relnamespace = n.oid "
            "WHERE n.nspname = 'public' AND cl.relname = ?",
            (legacy_name,)
        ).fetchall()
        for r in con_rows:
            try:
                conname = r['conname']
            except (KeyError, TypeError, IndexError):
                conname = r[0]
            if conname and not str(conname).endswith(f"_legacy_{ts_suffix}"):
                new_con = f"{str(conname)[:40]}_legacy_{ts_suffix}"
                cursor.execute(f"ALTER TABLE {legacy_name} RENAME CONSTRAINT {conname} TO {new_con}")

        idx_rows = cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = ?",
            (legacy_name,)
        ).fetchall()
        for r in idx_rows:
            try:
                idx_name = r['indexname']
            except (KeyError, TypeError, IndexError):
                idx_name = r[0]
            if idx_name and (str(idx_name).startswith('idx_pay_') or str(idx_name).startswith('idx_payment_')):
                new_idx = f"{str(idx_name)[:40]}_legacy_{ts_suffix}"
                cursor.execute(f"ALTER INDEX IF EXISTS {idx_name} RENAME TO {new_idx}")
    else:
        idx_rows = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND name NOT LIKE 'sqlite_autoindex_%'",
            (legacy_name,)
        ).fetchall()
        for r in idx_rows:
            try:
                idx_name = r['name']
            except (KeyError, TypeError, IndexError):
                idx_name = r[0]
            if idx_name and (str(idx_name).startswith('idx_pay_') or str(idx_name).startswith('idx_payment_')):
                cursor.execute(f"DROP INDEX IF EXISTS {idx_name}")


def _cleanup_legacy_payment_tables(conn, cursor, engine):
    """
    Remove ou renomeia tabelas de pagamento legadas incompatíveis (ex.: de commits revertidos)
    antes da criação do schema 007_payment_system.
    """
    ts_suffix = str(int(time.time()))
    changed = False

    tx_exists = _table_exists(cursor, 'payment_transactions', engine)
    tx_is_legacy = False
    if tx_exists:
        tx_cols = _get_table_columns(cursor, 'payment_transactions', engine)
        tx_is_legacy = 'amount_cents' not in tx_cols

    if tx_is_legacy:
        for extra_legacy in ('payment_tokens', 'idempotency_keys', 'payment_payment_refs'):
            if _table_exists(cursor, extra_legacy, engine):
                _retire_legacy_table(cursor, extra_legacy, engine, ts_suffix)
                changed = True

    legacy_checks = (
        ('payment_refunds', 'payment_id'),
        ('payment_idempotency_keys', 'scope'),
        ('payment_webhooks', 'event_id'),
        ('payment_transactions', 'amount_cents'),
        ('payment_methods', 'gateway_token'),
    )
    for tbl_name, required_col in legacy_checks:
        if _table_exists(cursor, tbl_name, engine):
            cols = _get_table_columns(cursor, tbl_name, engine)
            if required_col not in cols:
                _retire_legacy_table(cursor, tbl_name, engine, ts_suffix)
                changed = True

    if changed:
        conn.commit()


def init_db():
    ensure_production_database()
    engine = get_active_engine()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Serializa cold starts simultâneos no PostgreSQL evitando corrida em CREATE TABLE IF NOT EXISTS (pg_type_typname_nsp_index)
        if engine == 'postgresql':
            cursor.execute("SELECT pg_advisory_lock(7391042)")
            conn.commit()

        # Limpeza/arquivamento defensivo de tabelas de pagamento legadas incompatíveis antes de schema_sql / migrations
        _cleanup_legacy_payment_tables(conn, cursor, engine)

        # Verifica se as tabelas principais já existem antes de executar o schema inicial
        core_tables = (
            'users', 'services', 'orders', 'reviews', 'geocode_cache',
            'user_consents', 'disputes', 'safety_incidents', 'account_appeals', 'order_messages', 'escrow_ledger'
        )
        missing_core = any(not _table_exists(cursor, tbl, engine) for tbl in core_tables)

        if missing_core:
            schema_sql = POSTGRES_SCHEMA_SQL if engine == 'postgresql' else SQLITE_SCHEMA_SQL
            cursor.executescript(schema_sql)
            conn.commit()

        # Garantia defensiva de colunas novas em bancos já existentes
        _ensure_columns(conn, cursor, engine)

        # Garantia defensiva da constraint CHECK de orders.status ('em_disputa') em bancos pré-ET
        _ensure_orders_status_check(conn, cursor, engine)

        # Executa migrations versionadas pendentes (scripts/migrations/*.sql)
        run_migrations(conn=conn, dry_run=False)

        # Remove cache legado (podia associar endereço completo ao centro da cidade/bairro)
        cursor.execute("DELETE FROM geocode_cache WHERE origem IN ('nominatim', 'seed')")
        conn.commit()

        # Seed inicial e sincronização completa dos prestadores (desabilitado por padrão e proibido em produção)
        if is_demo_seed_enabled():
            cursor.execute("SELECT id FROM users WHERE email = ?", ('cliente@pertoja.com',))
            if not cursor.fetchone():
                pwd_hash = generate_password_hash('123456')
                cursor.execute('''
                    INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng)
                    VALUES (?, ?, ?, 'cliente', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'Ana Paula Silva', 'cliente@pertoja.com', pwd_hash, '(11) 98765-4321',
                    'Cliente residencial em busca de serviços locais de alta qualidade.',
                    '01402-000', 'Alameda Santos', '800', 'Cerqueira César', 'São Paulo', 'SP',
                    -23.5680, -46.6530
                ))
                conn.commit()

            sincronizar_todos_prestadores(conn)

            # Migração defensiva ET-09: garante Tier 2 e registro profissional para prestadores seed de Elétrica/Encanamento
            cursor.execute('''
                UPDATE users
                SET kyc_tier = 2,
                    registro_profissional = COALESCE(registro_profissional, 'CFT/CREA-SEED')
                WHERE tipo = 'prestador'
                  AND email LIKE '%@pertoja.com'
                  AND COALESCE(kyc_tier, 1) < 2
                  AND EXISTS (
                      SELECT 1 FROM services s
                      WHERE s.prestador_id = users.id
                        AND s.categoria IN ('Elétrica', 'Encanamento')
                  )
            ''')
            conn.commit()
    finally:
        if engine == 'postgresql':
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                cursor.execute("SELECT pg_advisory_unlock(7391042)")
                conn.commit()
            except Exception:
                pass
        conn.close()


PRESTADORES_SEED_35 = [
    # --- CENTRO DE SÃO PAULO (5 prestadores) ---
    ('Carlos Mendes', 'carlos@pertoja.com', '(11) 97111-2233', 'Limpeza residencial e comercial com 8 anos de experiência.', 'Limpeza', 'Limpeza residencial completa', 80.0, 4.8, '01310-100', 'Avenida Paulista', '1000', 'Bela Vista', 'São Paulo', 'SP', -23.5653, -46.6517, 1),
    ('Rafa Instalações', 'rafa@pertoja.com', '(11) 97444-5566', 'Instalação ágil de chuveiros, tomadas e luminárias.', 'Elétrica', 'Troca de chuveiro e tomadas elétricas', 90.0, 4.2, '01414-001', 'Rua Haddock Lobo', '800', 'Cerqueira César', 'São Paulo', 'SP', -23.5570, -46.6640, 1),
    ('Téo Suporte', 'teo@pertoja.com', '(11) 97888-9900', 'Técnico em informática e redes residenciais.', 'Tecnologia', 'Suporte técnico de computadores e redes Wi-Fi', 110.0, 4.4, '01228-000', 'Rua da Consolação', '2400', 'Consolação', 'São Paulo', 'SP', -23.5550, -46.6600, 1),
    ('Marcio Encanador Sé', 'marcio@pertoja.com', '(11) 97100-2211', 'Desentupimentos, sifões e conserto de válvulas de descarga.', 'Encanamento', 'Desentupimento e reparo de válvulas e sifões', 130.0, 4.6, '01001-000', 'Praça da Sé', '100', 'Sé', 'São Paulo', 'SP', -23.5505, -46.6333, 1),
    ('Helena Restaurações', 'helena@pertoja.com', '(11) 97100-3322', 'Restauração de portas, janelas e móveis antigos.', 'Marcenaria', 'Restauração de portas e móveis coloniais', 220.0, 4.9, '01223-000', 'Rua Baronesa de Itu', '350', 'Santa Cecília', 'São Paulo', 'SP', -23.5385, -46.6530, 1),

    # --- ZONA NORTE DE SÃO PAULO (5 prestadores) ---
    ('Beto Hidráulica', 'beto@pertoja.com', '(11) 97555-6677', 'Encanador especialista em caça-vazamentos e desentupimentos.', 'Encanamento', 'Conserto de vazamentos e desentupimento', 240.0, 4.7, '02011-000', 'Rua Voluntários da Pátria', '1500', 'Santana', 'São Paulo', 'SP', -23.5042, -46.6262, 1),
    ('Lucia Jardim & Verde', 'lucia@pertoja.com', '(11) 97200-4411', 'Paisagismo, adubação de solo e poda de gramados.', 'Jardinagem', 'Paisagismo, adubação e poda de gramados', 190.0, 4.8, '02305-000', 'Avenida Nova Cantareira', '1200', 'Tucuruvi', 'São Paulo', 'SP', -23.4795, -46.6080, 1),
    ('Valter Força Elétrica', 'valter@pertoja.com', '(11) 97200-5522', 'Manutenção elétrica preventiva, disjuntores e fiação.', 'Elétrica', 'Manutenção elétrica preventiva e disjuntores', 150.0, 4.5, '02511-000', 'Rua Doutor César', '400', 'Santana', 'São Paulo', 'SP', -23.5020, -46.6300, 1),
    ('Camila Clean ZN', 'camila@pertoja.com', '(11) 97200-6633', 'Faxina residencial caprichada e higienização de sofás.', 'Limpeza', 'Faxina residencial e higienização de sofás', 140.0, 4.9, '02518-000', 'Rua Casa Verde', '850', 'Casa Verde', 'São Paulo', 'SP', -23.5130, -46.6570, 1),
    ('Sergio Cores do Norte', 'sergio@pertoja.com', '(11) 97200-7744', 'Pintura residencial, fachadas e aplicação de grafiato.', 'Pintura', 'Pintura de fachadas e textura grafiato', 340.0, 4.6, '02167-000', 'Rua Curuçá', '600', 'Vila Maria', 'São Paulo', 'SP', -23.5120, -46.5950, 1),

    # --- ZONA SUL DE SÃO PAULO (5 prestadores) ---
    ('Marta Souza', 'marta@pertoja.com', '(11) 97222-3344', 'Especialista em faxina pesada e pós-obra.', 'Limpeza', 'Faxina pesada e higienização profunda', 170.0, 4.5, '04001-000', 'Rua Domingos de Morais', '500', 'Vila Mariana', 'São Paulo', 'SP', -23.5855, -46.6385, 1),
    ('Dona Flor', 'donaflor@pertoja.com', '(11) 97777-8899', 'Paisagista e especialista em corte, poda técnica e adubação.', 'Jardinagem', 'Jardinagem, poda e manutenção paisagística', 450.0, 5.0, '04538-133', 'Rua Bandeira Paulista', '700', 'Itaim Bibi', 'São Paulo', 'SP', -23.5840, -46.6780, 1),
    ('Eduardo Reparos Sul', 'eduardo@pertoja.com', '(11) 97300-1122', 'Instalação de spots LED, lustres e automação residencial.', 'Elétrica', 'Instalação de iluminação LED e tomadas inteligentes', 160.0, 4.7, '04523-010', 'Alameda dos Maracatins', '900', 'Moema', 'São Paulo', 'SP', -23.6060, -46.6620, 1),
    ('Renato Hidráulica Moema', 'renato@pertoja.com', '(11) 97300-2233', 'Instalação de duchas higiênicas, torneiras e pressurizadores.', 'Encanamento', 'Instalação de duchas, torneiras e pressurizadores', 180.0, 4.6, '04561-001', 'Rua Flórida', '1400', 'Brooklin', 'São Paulo', 'SP', -23.6090, -46.6910, 1),
    ('Claudio Móveis Planejados', 'claudio@pertoja.com', '(11) 97300-3344', 'Montagem, desmontagem e ajustes finos de armários embutidos.', 'Marcenaria', 'Montagem e ajuste de armários embutidos', 280.0, 4.8, '04743-000', 'Rua Doutor Antônio Bento', '650', 'Santo Amaro', 'São Paulo', 'SP', -23.6520, -46.7080, 1),

    # --- ZONA LESTE DE SÃO PAULO (5 prestadores) ---
    ('Nina Montagens', 'nina@pertoja.com', '(11) 97999-0011', 'Marcenaria fina, restauração de móveis e montagens de alta precisão.', 'Marcenaria', 'Marcenaria e montagem de móveis planejados', 260.0, 4.3, '03104-000', 'Rua da Mooca', '1500', 'Mooca', 'São Paulo', 'SP', -23.5535, -46.6020, 1),
    ('Rogério Eletro Leste', 'rogerio@pertoja.com', '(11) 97400-1155', 'Reforma de quadro de força e substituição de disjuntores.', 'Elétrica', 'Troca de fiação antiga e quadro elétrico', 200.0, 4.8, '03308-000', 'Rua Serra de Bragança', '850', 'Tatuapé', 'São Paulo', 'SP', -23.5390, -46.5740, 1),
    ('Priscila Brilho Total', 'priscila@pertoja.com', '(11) 97400-2266', 'Limpeza detalhada pré-mudança e pós-reforma.', 'Limpeza', 'Limpeza pós-obra e faxina comercial', 150.0, 4.7, '03332-000', 'Rua Emília Marengo', '400', 'Anália Franco', 'São Paulo', 'SP', -23.5550, -46.5680, 1),
    ('Tiago Desentupidora Penha', 'tiago@pertoja.com', '(11) 97400-3377', 'Localização eletrônica de vazamento e desentupimento com máquina.', 'Encanamento', 'Caça vazamento eletrônico e desentupimento de esgotos', 220.0, 4.5, '03634-000', 'Rua Betari', '300', 'Penha', 'São Paulo', 'SP', -23.5250, -46.5490, 1),
    ('Leandro Art Cobre', 'leandro@pertoja.com', '(11) 97400-4488', 'Pintura interna e externa, aplicação de massa corrida e látex.', 'Pintura', 'Pintura acrílica acetinada e esmalte sintético', 310.0, 4.9, '08210-040', 'Rua Américo Salvador Novelli', '250', 'Itaquera', 'São Paulo', 'SP', -23.5410, -46.4560, 1),

    # --- ZONA OESTE DE SÃO PAULO (5 prestadores) ---
    ('João Volts', 'joao@pertoja.com', '(11) 97333-4455', 'Eletricista certificado padrão industrial e residencial.', 'Elétrica', 'Reparo e manutenção de quadro elétrico', 210.0, 4.9, '05407-002', 'Rua Teodoro Sampaio', '1200', 'Pinheiros', 'São Paulo', 'SP', -23.5601, -46.6850, 1),
    ('Lia Cores', 'lia@pertoja.com', '(11) 97666-7788', 'Pintora profissional com acabamento premium para interiores.', 'Pintura', 'Pintura residencial e texturização de paredes', 380.0, 4.6, '05010-000', 'Rua Turiassu', '400', 'Perdizes', 'São Paulo', 'SP', -23.5320, -46.6710, 1),
    ('Vitor Green Garden', 'vitor@pertoja.com', '(11) 97500-1122', 'Implantação de jardins residenciais, verticais e poda de contenção.', 'Jardinagem', 'Corte de árvores autorizado e jardins verticais', 390.0, 4.8, '05435-000', 'Rua Fradique Coutinho', '1100', 'Vila Madalena', 'São Paulo', 'SP', -23.5580, -46.6930, 1),
    ('Bruno Redes & Tech', 'bruno@pertoja.com', '(11) 97500-2233', 'Montagem de rede Wi-Fi corporativa, roteadores e câmeras de segurança.', 'Tecnologia', 'Cabeamento estruturado e instalação de câmeras CFTV', 175.0, 4.7, '05075-000', 'Rua Doze de Outubro', '380', 'Lapa', 'São Paulo', 'SP', -23.5220, -46.7040, 1),
    ('Simone Limpeza Prime', 'simone@pertoja.com', '(11) 97500-3344', 'Higienização a seco de sofás, colchões, tapetes e vidraças.', 'Limpeza', 'Higienização de carpetes, estofados e vidros', 160.0, 4.9, '05501-000', 'Avenida Vital Brasil', '500', 'Butantã', 'São Paulo', 'SP', -23.5710, -46.7090, 1),

    # --- GUARULHOS (10 prestadores) ---
    ('Juliana Clean', 'juliana@pertoja.com', '(11) 97000-1122', 'Especialista em higienização e limpeza residencial em Guarulhos e região.', 'Limpeza', 'Limpeza e higienização residencial', 85.0, 4.9, '07141-430', 'Rua do Araújo', '150', 'Jardim Beirute', 'Guarulhos', 'SP', -23.4628, -46.5333, 1),
    ('Marcos Reparos', 'marcos@pertoja.com', '(11) 97000-3344', 'Eletricista residencial e predial com atendimento rápido em Guarulhos.', 'Elétrica', 'Instalação e reparos elétricos', 95.0, 4.7, '07010-010', 'Rua Dom Pedro II', '300', 'Centro', 'Guarulhos', 'SP', -23.4650, -46.5300, 1),
    ('Fabio Tintas', 'fabio@pertoja.com', '(11) 97000-5566', 'Pintura residencial fina, texturas e impermeabilização.', 'Pintura', 'Pintura residencial e texturização', 320.0, 4.8, '07055-000', 'Rua Treze de Maio', '450', 'Vila Galvão', 'Guarulhos', 'SP', -23.4560, -46.5450, 1),
    ('André Hidráulica Guarulhos', 'andre@pertoja.com', '(11) 97000-7788', 'Encanador 24h para emergências, desentupimentos e caça-vazamento.', 'Encanamento', 'Desentupimento rápido de pias e ralos', 190.0, 4.5, '07111-000', 'Avenida Tiradentes', '1200', 'Jardim Paraventi', 'Guarulhos', 'SP', -23.4540, -46.5210, 1),
    ('Fernanda Paisagismo Bosque', 'fernanda@pertoja.com', '(11) 97000-9900', 'Jardinagem ornamental, manutenção de vasos e podas de árvores.', 'Jardinagem', 'Manutenção de grama, plantas ornamentais e podas', 250.0, 4.9, '07115-000', 'Avenida Paulo Faccini', '1800', 'Macedo', 'Guarulhos', 'SP', -23.4600, -46.5160, 1),
    ('Rodrigo Móveis & Montagens', 'rodrigo@pertoja.com', '(11) 97000-1234', 'Montador profissional de móveis de magazines e planejados.', 'Marcenaria', 'Montagem de guarda-roupas, cozinhas e mesas', 210.0, 4.6, '07071-000', 'Rua Doutor Timóteo Penteado', '2200', 'Picanço', 'Guarulhos', 'SP', -23.4470, -46.5430, 1),
    ('Patricia Faxina & Cuidado', 'patricia@pertoja.com', '(11) 97000-2345', 'Diarista residencial de confiança com referências verificadas.', 'Limpeza', 'Diarista residencial e higienização completa', 130.0, 4.8, '07190-000', 'Rua Cônego Valadão', '800', 'Gopoúva', 'Guarulhos', 'SP', -23.4750, -46.5400, 1),
    ('Guilherme Soluções TI', 'guilherme@pertoja.com', '(11) 97000-3456', 'Configuração de redes, roteadores Wi-Fi mesh, formatação e backup.', 'Tecnologia', 'Instalação de roteadores mesh e reparo de PCs', 120.0, 4.7, '07170-350', 'Avenida Santos Dumont', '1500', 'Cumbica', 'Guarulhos', 'SP', -23.4510, -46.4680, 1),
    ('Lucas Eletricista Taboão', 'lucas@pertoja.com', '(11) 97000-4567', 'Instalação de chuveiros, troca de disjuntores e padrão Enel.', 'Elétrica', 'Padrão de entrada Enel e curto-circuito', 170.0, 4.4, '07140-010', 'Avenida Silvestre Pires de Freitas', '900', 'Taboão', 'Guarulhos', 'SP', -23.4310, -46.5020, 1),
    ('Marcelo Pinturas Aeroporto', 'marcelo@pertoja.com', '(11) 97000-5678', 'Pinturas residenciais e comerciais com acabamento liso e sem sujeira.', 'Pintura', 'Pintura predial, residencial e verniz de madeira', 350.0, 4.7, '07143-000', 'Estrada dos Morros', '450', 'Jardim Santa Emília', 'Guarulhos', 'SP', -23.4280, -46.4950, 1)
]


def sincronizar_todos_prestadores(conn):
    if is_production_env():
        return
    cursor = conn.cursor()

    # Otimização para serverless cold-starts: se já existem 35 prestadores, pula batch redundante
    count_row = cursor.execute("SELECT COUNT(*) FROM users WHERE tipo = 'prestador'").fetchone()
    if count_row is not None:
        try:
            count = count_row[0]
        except (IndexError, TypeError):
            count = getattr(count_row, 'count', 0)
        if count >= 35:
            return

    pwd_hash = generate_password_hash('123456')

    for nome, email, tel, bio, cat, s_titulo, preco, rating, cep, end, num, bairro, cid, uf, lat, lng, disp in PRESTADORES_SEED_35:
        kyc_tier_seed = 2 if cat in ('Elétrica', 'Encanamento') else 1
        reg_prof_seed = 'CFT/CREA-SEED' if cat in ('Elétrica', 'Encanamento') else None
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            cursor.execute('''
                INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng, avaliacao_media, total_avaliacoes, disponivel, kyc_tier, kyc_status, registro_profissional, status_conta)
                VALUES (?, ?, ?, 'prestador', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 15, ?, ?, 'aprovado', ?, 'ativo')
            ''', (nome, email, pwd_hash, tel, bio, cep, end, num, bairro, cid, uf, lat, lng, rating, disp, kyc_tier_seed, reg_prof_seed))
            p_id = cursor.lastrowid
            cursor.execute('''
                INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (p_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng))
        else:
            # Preserva edições feitas pelo prestador (localização, preço, etc.).
            # Apenas garante que exista ao menos um serviço para o prestador de exemplo.
            p_id = row['id']
            has_service = cursor.execute("SELECT 1 FROM services WHERE prestador_id = ? LIMIT 1", (p_id,)).fetchone()
            if not has_service:
                cursor.execute('''
                    INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ''', (p_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng))
    conn.commit()


def get_cached_geocode(query):
    """
    Recupera coordenadas em cache para uma consulta de endereço normalizada,
    respeitando TTL de 30 dias.

    Nota serverless (T-004): Quando VERCEL ou AWS_LAMBDA_FUNCTION_NAME estiver ativo,
    NÃO se deve usar um cache SQLite local separado se o motor ativo for 'postgresql'.
    get_db_connection() roteia automaticamente para a tabela 'geocode_cache' no
    PostgreSQL sempre que get_active_engine() == 'postgresql', e utiliza SQLite
    (DB_PATH) apenas quando o motor ativo for 'sqlite'.
    """
    normalized = _normalizar_query(query)
    if not normalized:
        return None
    conn = None
    try:
        conn = get_db_connection()
        row = conn.execute('SELECT lat, lng, criado_em FROM geocode_cache WHERE query = ?', (normalized,)).fetchone()
        if row:
            try:
                criado_em = row['criado_em']
            except (KeyError, IndexError, TypeError):
                criado_em = None
            if criado_em is not None:
                if isinstance(criado_em, str):
                    try:
                        dt = datetime.fromisoformat(criado_em.replace('Z', '+00:00')).replace(tzinfo=None)
                    except ValueError:
                        dt = datetime.utcnow()
                elif isinstance(criado_em, datetime):
                    dt = criado_em.replace(tzinfo=None)
                else:
                    dt = datetime.utcnow()
                if datetime.utcnow() - dt > timedelta(days=30):
                    conn.execute('DELETE FROM geocode_cache WHERE query = ?', (normalized,))
                    conn.commit()
                    return None
            return float(row['lat']), float(row['lng'])
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return None


def save_cached_geocode(query, lat, lng, origem='nominatim'):
    """
    Salva coordenadas em cache para consultas futuras utilizando SQL padrão upsert:
    ON CONFLICT (query) DO UPDATE compatível tanto com SQLite (>=3.24) quanto com PostgreSQL (>=9.5).

    Quando VERCEL ou AWS_LAMBDA_FUNCTION_NAME está ativo e o motor é PostgreSQL
    (get_active_engine() == 'postgresql'), grava diretamente na tabela 'geocode_cache'
    do PostgreSQL (nunca em um arquivo SQLite local separado); em SQLite, usa DB_PATH.
    """
    normalized = _normalizar_query(query)
    if not normalized or lat is None or lng is None:
        return
    try:
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO geocode_cache (query, lat, lng, origem, criado_em)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (query) DO UPDATE SET
                lat = excluded.lat,
                lng = excluded.lng,
                origem = excluded.origem,
                criado_em = CURRENT_TIMESTAMP
        ''', (normalized, float(lat), float(lng), origem))
        conn.commit()
        conn.close()
    except Exception:
        pass


if __name__ == '__main__':
    init_db()
    active_engine = get_active_engine()
    print(f"Banco de dados inicializado com sucesso utilizando o motor: {active_engine}")
