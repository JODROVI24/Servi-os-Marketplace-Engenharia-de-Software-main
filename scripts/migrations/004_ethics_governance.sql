-- Migration 004: Tabelas de Governança Ética, Consentimentos, Disputas, Segurança e Chat
-- Compatível com PostgreSQL (SERIAL PRIMARY KEY) e SQLite (traduzido automaticamente para INTEGER PRIMARY KEY AUTOINCREMENT em run_migrations()).
-- As colunas novas em users/orders/reviews e a atualização da constraint CHECK de orders.status são aplicadas de forma idempotente em database.py (_ensure_columns / _ensure_orders_status_check).
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

CREATE INDEX IF NOT EXISTS idx_user_consents_user ON user_consents(user_id);
CREATE INDEX IF NOT EXISTS idx_disputes_order ON disputes(order_id);
CREATE INDEX IF NOT EXISTS idx_safety_incidents_order ON safety_incidents(order_id);
CREATE INDEX IF NOT EXISTS idx_account_appeals_user ON account_appeals(user_id);
CREATE INDEX IF NOT EXISTS idx_order_messages_order ON order_messages(order_id);
