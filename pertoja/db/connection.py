"""Conexão, detecção de motor PostgreSQL/SQLite e adaptadores de cursor/linha."""

import os
import re
import sqlite3
import unicodedata
import urllib.parse

from pertoja._compat import resolve_compat
from pertoja.config import REPO_ROOT, is_production_runtime, load_dotenv
from pertoja.logging_config import get_logger

_logger = get_logger("pertoja.db.connection")

# Importação defensiva do psycopg2 para ambientes com ou sem driver PostgreSQL
try:
    import psycopg2
    from psycopg2 import IntegrityError as _Psycopg2IntegrityError
    from psycopg2 import extras

    HAS_PSYCOPG2 = True
    PG_DB_ERRORS: tuple[type[BaseException], ...] = (psycopg2.Error,)
except ImportError:
    psycopg2 = None
    extras = None
    _Psycopg2IntegrityError = None
    HAS_PSYCOPG2 = False
    PG_DB_ERRORS = ()


class _FallbackPsycopg2IntegrityError(Exception):
    """Exceção substituta quando psycopg2 não está instalado."""


Psycopg2IntegrityError = (
    _Psycopg2IntegrityError if _Psycopg2IntegrityError is not None else _FallbackPsycopg2IntegrityError
)
DBIntegrityError = (sqlite3.IntegrityError, Psycopg2IntegrityError)

BASE_DIR = REPO_ROOT
MIGRATIONS_DIR = os.path.join(BASE_DIR, "scripts", "migrations")

load_dotenv()


def resolve_database_url() -> tuple[str | None, str]:
    """Resolve e normaliza a URL de conexão com banco a partir das variáveis de ambiente."""
    raw_url = (
        os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRES_URL_NON_POOLING")
    )
    if not raw_url or not raw_url.strip():
        return None, "sqlite"

    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if not url.startswith("postgresql://"):
        raise RuntimeError(
            "DATABASE_URL inválida: apenas URLs PostgreSQL (postgresql:// ou postgres://) são suportadas."
        )

    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname or ""
    is_local = hostname in ("localhost", "127.0.0.1", "")

    query_params = dict(urllib.parse.parse_qsl(parsed.query))
    if not is_local and "sslmode" not in query_params:
        query_params["sslmode"] = "require"
        new_query = urllib.parse.urlencode(query_params)
        url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

    return url, "postgresql"


def get_active_engine() -> str:
    """Retorna o nome do motor de banco ativo ('postgresql' ou 'sqlite')."""
    _, engine = resolve_database_url()
    return engine


def is_production_env() -> bool:
    """Retorna True quando executando em ambiente de produção (VERCEL=1 ou FLASK_ENV=production)."""
    return is_production_runtime()


def is_demo_seed_enabled() -> bool:
    """Contas demo são desabilitadas por padrão ('0') e estritamente proibidas em produção."""
    if is_production_env():
        return False
    return str(os.environ.get("ENABLE_DEMO_SEED", "0")).strip().lower() in ("1", "true", "yes")


def ensure_production_database() -> None:
    """Em produção, exige PostgreSQL configurado e proíbe fallback para SQLite em /tmp."""
    if not is_production_env():
        return
    url, engine = resolve_database_url()
    if engine != "postgresql" or not url:
        raise RuntimeError(
            "DATABASE_URL (ou POSTGRES_URL / POSTGRES_URL_NON_POOLING) com PostgreSQL é obrigatória em produção "
            "(VERCEL=1 ou FLASK_ENV=production). Fallback para SQLite em /tmp não é permitido em produção."
        )


def _resolve_db_path() -> str:
    """Resolve o caminho do banco SQLite (usa /tmp apenas em ambiente serverless)."""
    if "MARKETPLACE_DB" in os.environ and os.environ["MARKETPLACE_DB"].strip():
        return os.environ["MARKETPLACE_DB"].strip()

    is_serverless = (
        os.environ.get("VERCEL") in ("1", "true")
        or "AWS_LAMBDA_FUNCTION_NAME" in os.environ
        or "VERCEL_REGION" in os.environ
        or "NOW_REGION" in os.environ
    )
    if is_serverless:
        return "/tmp/marketplace.db"

    return os.path.join(BASE_DIR, "marketplace.db")


DB_PATH = _resolve_db_path()


def _normalizar_query(texto: str) -> str:
    """Normaliza consulta de endereço para chave canônica do cache de geocodificação."""
    if not texto:
        return ""
    sem_acentos = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode("ascii").lower()
    sem_numero = re.sub(r"(?<=[a-z\s]),?\s+\b\d{1,5}\b(?=\s*(?:,|$|-))", "", sem_acentos)
    return re.sub(r"\s+", " ", sem_numero).strip()


def translate_placeholders(sql: str) -> str:
    """Converte '?' para '%s' em SQL, preservando '?' dentro de literais string."""
    if not sql or "?" not in sql:
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

        if char == "\\":
            result.append(char)
            escape = True
            i += 1
            continue

        if char == "'" and not in_double_quote:
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

        if char == "?" and not in_single_quote and not in_double_quote:
            result.append("%s")
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result)


class HybridRow:
    """Linha de banco compatível com sqlite3.Row (índice + chave) e dict (.get/in)."""

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
    """Cursor wrapper para PostgreSQL com tradução de placeholders e RETURNING id."""

    def __init__(self, raw_cursor):
        self._cursor = raw_cursor
        self.lastrowid = None

    @property
    def description(self):
        return getattr(self._cursor, "description", None)

    @property
    def rowcount(self):
        return getattr(self._cursor, "rowcount", -1)

    def _wrap_row(self, raw_row):
        if raw_row is None:
            return None
        if isinstance(raw_row, HybridRow):
            return raw_row
        if isinstance(raw_row, dict):
            return HybridRow(raw_row, tuple(raw_row.values()))
        if hasattr(raw_row, "_asdict"):
            return HybridRow(raw_row._asdict(), raw_row)
        if hasattr(raw_row, "keys"):
            d = {k: raw_row[k] for k in raw_row.keys()}
            return HybridRow(d, tuple(raw_row))
        if self._cursor and getattr(self._cursor, "description", None):
            col_names = [desc[0] for desc in self._cursor.description]
            d = dict(zip(col_names, raw_row, strict=False))
            return HybridRow(d, tuple(raw_row))
        if isinstance(raw_row, (list, tuple)):
            d = {f"col_{idx}": val for idx, val in enumerate(raw_row)}
            return HybridRow(d, tuple(raw_row))
        return raw_row

    def execute(self, sql: str, params=None):
        clean_sql = sql.strip()
        upper_sql = clean_sql.upper()

        needs_returning = False
        is_insert = upper_sql.startswith("INSERT INTO") or upper_sql.startswith("INSERT")
        has_returning = "RETURNING" in upper_sql
        is_no_id_table = any(
            t in upper_sql for t in ("GEOCODE_CACHE", "RATE_LIMIT", "SCHEMA_MIGRATIONS", "PASSWORD_RESET_TOKENS")
        )

        if is_insert and not has_returning and not is_no_id_table:
            needs_returning = True
            sql_to_run = clean_sql.rstrip().rstrip(";") + " RETURNING id"
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
                    if isinstance(ret_row, dict) or hasattr(ret_row, "__getitem__"):
                        try:
                            self.lastrowid = ret_row["id"]
                        except (KeyError, TypeError, IndexError):
                            self.lastrowid = ret_row[0]
                    else:
                        self.lastrowid = getattr(ret_row, "id", None)
            except (TypeError, KeyError, IndexError, AttributeError, *PG_DB_ERRORS) as exc:
                _logger.debug(
                    "RETURNING id indisponível após INSERT.",
                    extra={"event": "postgres_returning_skip", "error_type": type(exc).__name__},
                )

        return self

    def executescript(self, script: str):
        for raw_stmt in script.split(";"):
            stmt = raw_stmt.strip()
            if not stmt:
                continue
            has_sql = any(line.strip() and not line.strip().startswith("--") for line in stmt.splitlines())
            if has_sql:
                self.execute(stmt)
        return self

    def fetchone(self):
        return self._wrap_row(self._cursor.fetchone())

    def fetchall(self):
        return [self._wrap_row(r) for r in self._cursor.fetchall()]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
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
    """Connection wrapper para PostgreSQL com API compatível com sqlite3.Connection."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self, *args, **kwargs):
        return PostgresCursorWrapper(self._conn.cursor(*args, **kwargs))

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script: str):
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


def _connect_postgres(url: str) -> PostgresConnectionWrapper:
    has_pg = resolve_compat("database", "HAS_PSYCOPG2", HAS_PSYCOPG2)
    pg_mod = resolve_compat("database", "psycopg2", psycopg2)
    ext_mod = resolve_compat("database", "extras", extras)
    if not has_pg or pg_mod is None:
        raise ImportError(
            "psycopg2 é necessário para conectar ao PostgreSQL. "
            "Instale psycopg2-binary>=2.9.9 ou use o fallback SQLite local."
        )
    cursor_factory = ext_mod.DictCursor if ext_mod else None
    conn = pg_mod.connect(url, cursor_factory=cursor_factory)
    return PostgresConnectionWrapper(conn)


def get_db_connection():
    """Abre conexão com PostgreSQL (se configurado) ou SQLite local em desenvolvimento."""
    url, engine = resolve_database_url()
    if engine == "postgresql" and url:
        return _connect_postgres(url)

    ensure_fn = resolve_compat("database", "ensure_production_database", ensure_production_database)
    ensure_fn()

    active_db_path = resolve_compat("database", "DB_PATH", DB_PATH)
    db_abs = os.path.abspath(active_db_path)
    parent_dir = os.path.dirname(db_abs)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(active_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
