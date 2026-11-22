"""Schema DDL inicial para PostgreSQL."""

POSTGRES_SCHEMA_SQL = """
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
"""
