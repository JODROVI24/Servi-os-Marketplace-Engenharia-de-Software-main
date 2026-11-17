-- Migration 008: Tabela de Notificacoes Administrativas e Indices Complementares
-- Idempotente para bancos que ja aplicaram versoes anteriores da migration 007.

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
CREATE INDEX IF NOT EXISTS idx_payment_transactions_gateway_id ON payment_transactions(gateway_payment_id);
