"""Migrations SQL versionadas, criação de schema e retrocompatibilidade de tabelas."""

import os
import re
import sqlite3
import time

from werkzeug.security import generate_password_hash

from pertoja._compat import resolve_compat
from pertoja.db.connection import (
    MIGRATIONS_DIR,
    PG_DB_ERRORS,
    ensure_production_database,
    get_active_engine,
    get_db_connection,
    is_demo_seed_enabled,
)
from pertoja.db.schema_postgres import POSTGRES_SCHEMA_SQL
from pertoja.db.schema_sqlite import SQLITE_SCHEMA_SQL
from pertoja.db.seed import sincronizar_todos_prestadores
from pertoja.logging_config import get_logger

_logger = get_logger("pertoja.db.migrations")


def _table_exists(cursor, table_name: str, engine: str) -> bool:
    """Verifica se uma tabela já existe no banco ativo."""
    if engine == "postgresql":
        row = cursor.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ?",
            (table_name,),
        ).fetchone()
    else:
        row = cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone()
    return row is not None


def _ensure_migrations_table(cursor) -> None:
    """Garante a existência da tabela schema_migrations para controle de versão."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def list_migration_files() -> list[str]:
    """Lista em ordem alfabética os arquivos .sql em scripts/migrations/."""
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    files = [
        f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql") and os.path.isfile(os.path.join(MIGRATIONS_DIR, f))
    ]
    return sorted(files)


def run_migrations(conn=None, dry_run: bool = False) -> list[dict[str, str]]:
    """Executa migrations pendentes em scripts/migrations/*.sql ou apenas inspeciona em dry_run."""
    own_conn = conn is None
    if own_conn:
        conn_fn = resolve_compat("database", "get_db_connection", get_db_connection)
        conn = conn_fn()

    cursor = conn.cursor()
    engine = resolve_compat("database", "get_active_engine", get_active_engine)()
    report: list[dict[str, str]] = []
    migration_files = list_migration_files()

    if dry_run:
        applied_versions = set()
        if _table_exists(cursor, "schema_migrations", engine):
            rows = cursor.execute("SELECT version FROM schema_migrations").fetchall()
            applied_versions = {r["version"] for r in rows}
        for filename in migration_files:
            status = "already_applied" if filename in applied_versions else "pending"
            report.append({"version": filename, "status": status})
        if own_conn:
            conn.close()
        return report

    _ensure_migrations_table(cursor)
    conn.commit()

    rows = cursor.execute("SELECT version FROM schema_migrations").fetchall()
    applied_versions = {r["version"] for r in rows}

    for filename in migration_files:
        if filename in applied_versions:
            report.append({"version": filename, "status": "already_applied"})
            continue

        filepath = os.path.join(MIGRATIONS_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            sql_script = f.read()

        if sql_script.strip():
            if engine == "sqlite":
                sql_script = re.sub(
                    r"\bSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", sql_script, flags=re.IGNORECASE
                )
            cursor.executescript(sql_script)

        cursor.execute(
            "INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT (version) DO NOTHING",
            (filename,),
        )
        conn.commit()
        report.append({"version": filename, "status": "applied"})

    if own_conn:
        conn.close()
    return report


def _ensure_columns(conn, cursor, engine: str) -> None:
    """Garante defensivamente que colunas novas existam em bancos SQLite e PostgreSQL existentes."""
    real_type = "DOUBLE PRECISION" if engine == "postgresql" else "REAL"
    expected_columns = {
        "users": [
            ("plano", "TEXT DEFAULT 'basico'"),
            ("kyc_tier", "INTEGER DEFAULT 1"),
            ("kyc_status", "TEXT DEFAULT 'aprovado'"),
            ("kyc_documento_tipo", "TEXT DEFAULT 'RG'"),
            ("kyc_provider_ref", "TEXT"),
            ("kyc_verified_at", "TIMESTAMP"),
            ("registro_profissional", "TEXT"),
            ("cpf", "TEXT"),
            ("status_conta", "TEXT DEFAULT 'ativo'"),
            ("session_version", "INTEGER DEFAULT 1"),
        ],
        "orders": [
            ("complemento_cliente", "TEXT"),
            ("modalidade", "TEXT DEFAULT 'imediato'"),
            ("agendado_para", "TEXT"),
            ("metodo_pagamento", "TEXT DEFAULT 'escrow'"),
            ("pago", "INTEGER DEFAULT 0"),
            ("codigo_confirmacao", "TEXT"),
            ("motivo_cancelamento", "TEXT"),
            ("escrow_status", "TEXT DEFAULT 'pendente'"),
            ("taxa_deslocamento", f"{real_type} DEFAULT 0"),
            ("valor_estornado", f"{real_type} DEFAULT 0"),
            ("share_token", "TEXT"),
            ("completed_at", "TIMESTAMP"),
            ("released_at", "TIMESTAMP"),
            ("release_due_at", "TIMESTAMP"),
            ("confirmado_cliente", "INTEGER DEFAULT 0"),
            ("pin_tentativas", "INTEGER DEFAULT 0"),
        ],
        "reviews": [
            ("autor_tipo", "TEXT DEFAULT 'cliente'"),
            ("avaliado_id", "INTEGER"),
            ("replica", "TEXT"),
            ("replied_at", "TIMESTAMP"),
            ("contestada", "INTEGER DEFAULT 0"),
            ("motivo_contestacao", "TEXT"),
            ("status_moderacao", "TEXT DEFAULT 'visivel'"),
            ("revealed_at", "TIMESTAMP"),
        ],
    }

    for table, cols in expected_columns.items():
        if engine == "postgresql":
            for col_name, col_def in cols:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            conn.commit()
        else:
            info_rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
            existing_cols = set()
            for r in info_rows:
                try:
                    existing_cols.add(r["name"])
                except (KeyError, TypeError, IndexError):
                    existing_cols.add(r[1])
            for col_name, col_def in cols:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            conn.commit()


def _ensure_orders_status_check(conn, cursor, engine: str) -> None:
    """Garante que a constraint CHECK de orders.status aceite 'em_disputa' em bancos pré-ET."""
    if engine == "postgresql":
        try:
            row = cursor.execute(
                "SELECT pg_get_constraintdef(oid) AS cdef FROM pg_constraint "
                "WHERE conname = 'orders_status_check' AND conrelid = 'orders'::regclass"
            ).fetchone()
            cdef = row["cdef"] if row and hasattr(row, "keys") and "cdef" in row.keys() else (row[0] if row else "")
            if cdef and "'em_disputa'" in str(cdef):
                return
            cursor.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check")
            cursor.execute(
                "ALTER TABLE orders ADD CONSTRAINT orders_status_check "
                "CHECK (status IN ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'em_disputa', 'finalizado', 'cancelado'))"
            )
            conn.commit()
        except (ValueError, TypeError, RuntimeError, *PG_DB_ERRORS) as exc:
            _logger.warning(
                "Não foi possível atualizar constraint orders_status_check no PostgreSQL.",
                extra={"event": "orders_status_check_skip", "error_type": type(exc).__name__},
            )
            conn.rollback()
        return

    row = cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'orders'").fetchone()
    if not row:
        return
    table_sql = row["sql"] if hasattr(row, "keys") and "sql" in row.keys() else row[0]
    if not table_sql or "'em_disputa'" in table_sql:
        return

    info_rows = cursor.execute("PRAGMA table_info(orders)").fetchall()
    existing_cols = []
    for r in info_rows:
        try:
            existing_cols.append(r["name"])
        except (KeyError, TypeError, IndexError):
            existing_cols.append(r[1])

    new_orders_cols = [
        "id",
        "cliente_id",
        "prestador_id",
        "servico_id",
        "status",
        "preco_total",
        "observacoes",
        "cep_cliente",
        "endereco_cliente",
        "numero_cliente",
        "bairro_cliente",
        "cidade_cliente",
        "estado_cliente",
        "lat_cliente",
        "lng_cliente",
        "complemento_cliente",
        "modalidade",
        "agendado_para",
        "metodo_pagamento",
        "pago",
        "codigo_confirmacao",
        "motivo_cancelamento",
        "escrow_status",
        "taxa_deslocamento",
        "valor_estornado",
        "share_token",
        "completed_at",
        "released_at",
        "release_due_at",
        "confirmado_cliente",
        "pin_tentativas",
        "criado_em",
        "atualizado_em",
    ]
    copy_cols = [c for c in new_orders_cols if c in existing_cols]
    cols_csv = ", ".join(copy_cols)

    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute("""
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
    """)
    if copy_cols:
        cursor.execute(f"INSERT INTO orders__new ({cols_csv}) SELECT {cols_csv} FROM orders")
    cursor.execute("DROP TABLE orders")
    cursor.execute("ALTER TABLE orders__new RENAME TO orders")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_cliente ON orders(cliente_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_prestador ON orders(prestador_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()


def _get_table_columns(cursor, table_name: str, engine: str) -> set[str]:
    """Retorna o conjunto de nomes de colunas existentes em uma tabela."""
    if engine == "postgresql":
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ?",
            (table_name,),
        ).fetchall()
        cols = set()
        for r in rows:
            try:
                cols.add(r["column_name"])
            except (KeyError, TypeError, IndexError):
                cols.add(r[0])
        return cols
    info_rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    cols = set()
    for r in info_rows:
        try:
            cols.add(r["name"])
        except (KeyError, TypeError, IndexError):
            cols.add(r[1])
    return cols


def _retire_legacy_table(cursor, table_name: str, engine: str, ts_suffix: str) -> None:
    """Remove tabela legada vazia ou renomeia preservando dados sem colisão de índices/constraints."""
    row = cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}").fetchone()
    try:
        count = int(row["cnt"])
    except (KeyError, TypeError, IndexError):
        count = int(row[0]) if row else 0
    if count == 0:
        if engine == "postgresql":
            cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        else:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        return

    legacy_name = f"{table_name}_legacy_{ts_suffix}"
    cursor.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_name}")

    if engine == "postgresql":
        con_rows = cursor.execute(
            "SELECT c.conname FROM pg_constraint c "
            "JOIN pg_class cl ON c.conrelid = cl.oid "
            "JOIN pg_namespace n ON cl.relnamespace = n.oid "
            "WHERE n.nspname = 'public' AND cl.relname = ?",
            (legacy_name,),
        ).fetchall()
        for r in con_rows:
            try:
                conname = r["conname"]
            except (KeyError, TypeError, IndexError):
                conname = r[0]
            if conname and not str(conname).endswith(f"_legacy_{ts_suffix}"):
                new_con = f"{str(conname)[:40]}_legacy_{ts_suffix}"
                cursor.execute(f"ALTER TABLE {legacy_name} RENAME CONSTRAINT {conname} TO {new_con}")

        idx_rows = cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = ?",
            (legacy_name,),
        ).fetchall()
        for r in idx_rows:
            try:
                idx_name = r["indexname"]
            except (KeyError, TypeError, IndexError):
                idx_name = r[0]
            if idx_name and (str(idx_name).startswith("idx_pay_") or str(idx_name).startswith("idx_payment_")):
                new_idx = f"{str(idx_name)[:40]}_legacy_{ts_suffix}"
                cursor.execute(f"ALTER INDEX IF EXISTS {idx_name} RENAME TO {new_idx}")
    else:
        idx_rows = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND name NOT LIKE 'sqlite_autoindex_%'",
            (legacy_name,),
        ).fetchall()
        for r in idx_rows:
            try:
                idx_name = r["name"]
            except (KeyError, TypeError, IndexError):
                idx_name = r[0]
            if idx_name and (str(idx_name).startswith("idx_pay_") or str(idx_name).startswith("idx_payment_")):
                cursor.execute(f"DROP INDEX IF EXISTS {idx_name}")


def _cleanup_legacy_payment_tables(conn, cursor, engine: str) -> None:
    """Remove ou arquiva tabelas de pagamento legadas incompatíveis antes das migrations."""
    ts_suffix = str(int(time.time()))
    changed = False

    tx_exists = _table_exists(cursor, "payment_transactions", engine)
    tx_is_legacy = False
    if tx_exists:
        tx_cols = _get_table_columns(cursor, "payment_transactions", engine)
        tx_is_legacy = "amount_cents" not in tx_cols

    if tx_is_legacy:
        for extra_legacy in ("payment_tokens", "idempotency_keys", "payment_payment_refs"):
            if _table_exists(cursor, extra_legacy, engine):
                _retire_legacy_table(cursor, extra_legacy, engine, ts_suffix)
                changed = True

    legacy_checks = (
        ("payment_refunds", "payment_id"),
        ("payment_idempotency_keys", "scope"),
        ("payment_webhooks", "event_id"),
        ("payment_transactions", "amount_cents"),
        ("payment_methods", "gateway_token"),
    )
    for tbl_name, required_col in legacy_checks:
        if _table_exists(cursor, tbl_name, engine):
            cols = _get_table_columns(cursor, tbl_name, engine)
            if required_col not in cols:
                _retire_legacy_table(cursor, tbl_name, engine, ts_suffix)
                changed = True

    if changed:
        conn.commit()


def _seed_demo_accounts(conn, cursor) -> None:
    """Popula usuário cliente e catálogo demo quando ENABLE_DEMO_SEED=1 fora de produção."""
    cursor.execute("SELECT id FROM users WHERE email = ?", ("cliente@pertoja.com",))
    if not cursor.fetchone():
        pwd_hash = generate_password_hash("123456")
        cursor.execute(
            """
            INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng)
            VALUES (?, ?, ?, 'cliente', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "Ana Paula Silva",
                "cliente@pertoja.com",
                pwd_hash,
                "(11) 98765-4321",
                "Cliente residencial em busca de serviços locais de alta qualidade.",
                "01402-000",
                "Alameda Santos",
                "800",
                "Cerqueira César",
                "São Paulo",
                "SP",
                -23.5680,
                -46.6530,
            ),
        )
        conn.commit()

    sync_fn = resolve_compat("database", "sincronizar_todos_prestadores", sincronizar_todos_prestadores)
    sync_fn(conn)

    cursor.execute("""
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
    """)
    conn.commit()


def init_db() -> None:
    """Inicializa schema, colunas defensivas, migrations e seed demo opcional."""
    ensure_fn = resolve_compat("database", "ensure_production_database", ensure_production_database)
    engine_fn = resolve_compat("database", "get_active_engine", get_active_engine)
    conn_fn = resolve_compat("database", "get_db_connection", get_db_connection)
    ensure_cols_fn = resolve_compat("database", "_ensure_columns", _ensure_columns)
    run_mig_fn = resolve_compat("database", "run_migrations", run_migrations)

    ensure_fn()
    engine = engine_fn()
    conn = conn_fn()
    cursor = conn.cursor()

    try:
        if engine == "postgresql":
            cursor.execute("SELECT pg_advisory_lock(7391042)")
            conn.commit()

        _cleanup_legacy_payment_tables(conn, cursor, engine)

        core_tables = (
            "users",
            "services",
            "orders",
            "reviews",
            "geocode_cache",
            "user_consents",
            "disputes",
            "safety_incidents",
            "account_appeals",
            "order_messages",
            "escrow_ledger",
        )
        missing_core = any(not _table_exists(cursor, tbl, engine) for tbl in core_tables)

        if missing_core:
            schema_sql = POSTGRES_SCHEMA_SQL if engine == "postgresql" else SQLITE_SCHEMA_SQL
            cursor.executescript(schema_sql)
            conn.commit()

        ensure_cols_fn(conn, cursor, engine)
        _ensure_orders_status_check(conn, cursor, engine)
        run_mig_fn(conn=conn, dry_run=False)

        cursor.execute("DELETE FROM geocode_cache WHERE origem IN ('nominatim', 'seed')")
        conn.commit()

        if is_demo_seed_enabled():
            _seed_demo_accounts(conn, cursor)
    finally:
        if engine == "postgresql":
            try:
                conn.rollback()
            except (sqlite3.Error, RuntimeError, AttributeError, *PG_DB_ERRORS):
                pass
            try:
                cursor.execute("SELECT pg_advisory_unlock(7391042)")
                conn.commit()
            except (sqlite3.Error, RuntimeError, AttributeError, *PG_DB_ERRORS) as exc:
                _logger.warning(
                    "Falha ao liberar advisory lock do PostgreSQL após init_db.",
                    extra={"event": "pg_advisory_unlock_failed", "error_type": type(exc).__name__},
                )
        conn.close()
