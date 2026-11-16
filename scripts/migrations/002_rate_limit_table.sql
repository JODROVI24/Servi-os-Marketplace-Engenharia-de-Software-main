-- Migration 002: Tabela de rate limiting persistente (compatível com SQLite e PostgreSQL)
CREATE TABLE IF NOT EXISTS rate_limit (
    rate_key TEXT NOT NULL,
    ts DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_key_ts ON rate_limit(rate_key, ts);
