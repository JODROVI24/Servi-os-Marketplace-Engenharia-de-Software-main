-- Migration 007: Modelagem de Dados de Pagamentos, Tokens PCI, Idempotencia e Razao Escrow
-- Adiciona: payment_tokens, payment_methods, payment_webhooks, idempotency_keys,
-- payment_transactions, e atualiza escrow_ledger para vincular payment_id
-- Estados de pagamento: pending, authorized, captured, failed, refunded

-- Payment tokens: armazena tokens de cartão, NEVER armazena PAN/CVV
CREATE TABLE IF NOT EXISTS payment_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    gateway_token TEXT NOT NULL UNIQUE,  -- token do gateway (Stripe, PagSeguro, Mercado Pago)
    brand TEXT,                          -- mastercard, visa, etc.
    last4 TEXT,                          -- ultimos 4 digitos
    exp_month INTEGER,
    exp_year INTEGER,
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, gateway_token)
);

-- Payment methods: métodos de pagamento elegíveis (cartao, boleto, pix, transferencia)
CREATE TABLE IF NOT EXISTS payment_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    payment_method TEXT NOT NULL CHECK(payment_method IN ('cartao', 'boleto', 'pix', 'transferencia')),
    payment_token_id INTEGER,
    config TEXT,                          -- JSON com config do método (last4, exp, qr_code, etc.)
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (payment_token_id) REFERENCES payment_tokens(id) ON DELETE SET NULL,
    UNIQUE (user_id, payment_method)
);

CREATE INDEX IF NOT EXISTS idx_payment_methods_user ON payment_methods(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_tokens_user ON payment_tokens(user_id);

-- Payment webhooks: registra e valida webhooks de gateways externas
CREATE TABLE IF NOT EXISTS payment_webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    gateway TEXT NOT NULL CHECK(gateway IN ('stripe', 'pagseguro', 'mercadopago')),
    endpoint_name TEXT NOT NULL,
    signing_secret TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_payment_webhooks_user ON payment_webhooks(user_id);

-- Idempotency keys: garante que chamadas repetidas retornem o mesmo resultado
CREATE TABLE IF NOT EXISTS idempotency_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_hash TEXT NOT NULL UNIQUE,
    controller TEXT NOT NULL,
    action TEXT NOT NULL,
    user_id INTEGER,
    response_data TEXT,                   -- JSON de resposta retida
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_request_hash ON idempotency_keys(request_hash);

-- Payment transactions: histórico de transações de pagamento
CREATE TABLE IF NOT EXISTS payment_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    payment_id INTEGER NOT NULL,
    method TEXT NOT NULL CHECK(method IN ('cartao', 'boleto', 'pix', 'transferencia')),
    gateway TEXT,
    gateway_payment_id TEXT,
    gateway_status TEXT,
    gateway_event TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending', 'authorized', 'captured', 'failed', 'refunded', 'disputed')),
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'BRL',
    fee REAL DEFAULT 0,
    net_amount REAL NOT NULL,
    idempotency_key_id INTEGER,
    source_ip TEXT,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (payment_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (idempotency_key_id) REFERENCES idempotency_keys(id) ON DELETE SET NULL,
    CHECK (amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_user ON payment_transactions(payment_id);

-- Update escrow_ledger to link to payment_id for better reconciliation
-- No ALTER COLUMN for idempotency; use separate table tracking for backward compat
CREATE TABLE IF NOT EXISTS payment_payment_refs (
    payment_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    payment_method TEXT,
    status_initial TEXT,
    status_final TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (payment_id) REFERENCES payment_transactions(id) ON DELETE CASCADE
);

-- Drop old indexes that may conflict (if this migration is applied to an existing DB)
-- Note: SQLite doesn't support DROP INDEX in a transaction, so this is safest in 
-- a separate migration step or handled at app level.
