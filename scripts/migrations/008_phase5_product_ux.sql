-- Migration 008: Fase 5 - Verificacao de e-mail, OTP de telefone e rastreamento GPS real
-- Compativel com PostgreSQL e SQLite (SERIAL PRIMARY KEY convertido em run_migrations)

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    used INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_verif_user ON email_verification_tokens(user_id);

CREATE TABLE IF NOT EXISTS phone_otp_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    telefone TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    canal TEXT DEFAULT 'sms',
    expires_at DOUBLE PRECISION NOT NULL,
    attempts INTEGER DEFAULT 0,
    used INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_phone_otp_user ON phone_otp_tokens(user_id);
