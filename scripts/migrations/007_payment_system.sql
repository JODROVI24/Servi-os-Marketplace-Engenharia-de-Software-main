-- Migration 007: Sistema de Pagamentos Dual-Engine PCI-Safe
-- Compativel com PostgreSQL e SQLite (SERIAL PRIMARY KEY convertido em run_migrations)

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
