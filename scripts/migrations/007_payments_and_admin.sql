-- Migration 007: Modelagem de Dados de Pagamentos, Tokens PCI, Idempotencia e Notificacoes
-- Compativel com PostgreSQL (SERIAL PRIMARY KEY / DOUBLE PRECISION) e SQLite (traduzido em run_migrations).
-- Estados de pagamento: pending, authorized, captured, failed, refunded, disputed

CREATE TABLE IF NOT EXISTS payment_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    gateway_token TEXT NOT NULL UNIQUE,
    brand TEXT,
    last4 TEXT,
    exp_month INTEGER,
    exp_year INTEGER,
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, gateway_token)
);

CREATE TABLE IF NOT EXISTS payment_methods (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    payment_method TEXT NOT NULL CHECK(payment_method IN ('cartao', 'boleto', 'pix', 'transferencia')),
    payment_token_id INTEGER,
    config TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (payment_token_id) REFERENCES payment_tokens(id) ON DELETE SET NULL,
    UNIQUE (user_id, payment_method)
);

CREATE INDEX IF NOT EXISTS idx_payment_methods_user ON payment_methods(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_tokens_user ON payment_tokens(user_id);

CREATE TABLE IF NOT EXISTS payment_webhooks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    gateway TEXT NOT NULL CHECK(gateway IN ('stripe', 'pagseguro', 'mercadopago')),
    endpoint_name TEXT NOT NULL,
    signing_secret TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_payment_webhooks_user ON payment_webhooks(user_id);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id SERIAL PRIMARY KEY,
    request_hash TEXT NOT NULL UNIQUE,
    controller TEXT NOT NULL,
    action TEXT NOT NULL,
    user_id INTEGER,
    response_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_request_hash ON idempotency_keys(request_hash);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    order_id INTEGER,
    payment_id INTEGER,
    method TEXT NOT NULL CHECK(method IN ('cartao', 'boleto', 'pix', 'transferencia')),
    gateway TEXT,
    gateway_payment_id TEXT,
    gateway_status TEXT,
    gateway_event TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending', 'authorized', 'captured', 'failed', 'refunded', 'disputed')),
    amount DOUBLE PRECISION NOT NULL,
    currency TEXT DEFAULT 'BRL',
    fee DOUBLE PRECISION DEFAULT 0,
    net_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    idempotency_key_id INTEGER,
    source_ip TEXT,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
    FOREIGN KEY (idempotency_key_id) REFERENCES idempotency_keys(id) ON DELETE SET NULL,
    CHECK (amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_user ON payment_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_order ON payment_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_gateway_id ON payment_transactions(gateway_payment_id);

CREATE TABLE IF NOT EXISTS payment_payment_refs (
    payment_id INTEGER PRIMARY KEY,
    order_id INTEGER,
    payment_method TEXT,
    status_initial TEXT,
    status_final TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (payment_id) REFERENCES payment_transactions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    admin_id INTEGER,
    tipo TEXT DEFAULT 'info',
    mensagem TEXT NOT NULL,
    destinatario_tipo TEXT DEFAULT 'all',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_criado_em ON notifications(criado_em);
