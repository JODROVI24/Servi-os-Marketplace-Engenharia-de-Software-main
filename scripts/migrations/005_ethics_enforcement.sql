-- Migration 005: Enforcement do Código de Ética (Escrow Ledger + Colunas ET-03/04/07/08/09/13)
-- Compatível com PostgreSQL (SERIAL PRIMARY KEY) e SQLite (traduzido automaticamente para INTEGER PRIMARY KEY AUTOINCREMENT em run_migrations()).
-- As colunas novas em users (cpf), orders (release_due_at, confirmado_cliente, pin_tentativas) e reviews (revealed_at)
-- são aplicadas de forma idempotente em database.py (_ensure_columns).

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

CREATE INDEX IF NOT EXISTS idx_escrow_ledger_order ON escrow_ledger(order_id);
