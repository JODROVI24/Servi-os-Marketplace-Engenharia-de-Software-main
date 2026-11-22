"""Helpers de criação/limpeza de tabelas auxiliares para migrations."""

import time


def table_exists(cursor, table_name: str, engine: str) -> bool:
    """Verifica se uma tabela já existe no banco ativo."""
    if engine == "postgresql":
        row = cursor.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ?",
            (table_name,),
        ).fetchone()
    else:
        row = cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone()
    return row is not None


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


def cleanup_legacy_payment_tables(conn, cursor, engine: str) -> None:
    """Remove ou arquiva tabelas de pagamento legadas incompatíveis antes das migrations."""
    ts_suffix = str(int(time.time()))
    changed = False

    tx_exists = table_exists(cursor, "payment_transactions", engine)
    tx_is_legacy = False
    if tx_exists:
        tx_cols = _get_table_columns(cursor, "payment_transactions", engine)
        tx_is_legacy = "amount_cents" not in tx_cols

    if tx_is_legacy:
        for extra_legacy in ("payment_tokens", "idempotency_keys", "payment_payment_refs"):
            if table_exists(cursor, extra_legacy, engine):
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
        if table_exists(cursor, tbl_name, engine):
            cols = _get_table_columns(cursor, tbl_name, engine)
            if required_col not in cols:
                _retire_legacy_table(cursor, tbl_name, engine, ts_suffix)
                changed = True

    if changed:
        conn.commit()


def ensure_phase5_tables(conn, cursor, engine: str) -> None:
    """Garante idempotentemente as tabelas da Fase 5 em bancos pré-existentes."""
    pk_def = "SERIAL PRIMARY KEY" if engine == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real_type = "DOUBLE PRECISION" if engine == "postgresql" else "REAL"

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            expires_at {real_type} NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_verif_user ON email_verification_tokens(user_id)")

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS phone_otp_tokens (
            id {pk_def},
            user_id INTEGER NOT NULL,
            telefone TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            canal TEXT DEFAULT 'sms',
            expires_at {real_type} NOT NULL,
            attempts INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_phone_otp_user ON phone_otp_tokens(user_id)")
    conn.commit()
