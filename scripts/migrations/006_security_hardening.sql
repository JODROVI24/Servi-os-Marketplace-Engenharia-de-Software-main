-- Migration 006: Hardening de Segurança (Índices únicos em reviews/disputes e session_version)
-- Compatível com PostgreSQL e SQLite.
-- A coluna session_version em users é aplicada de forma idempotente em database.py (_ensure_columns).

DELETE FROM reviews
WHERE id NOT IN (
    SELECT MIN(id) FROM reviews GROUP BY order_id, autor_tipo
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_order_author ON reviews(order_id, autor_tipo);

DELETE FROM disputes
WHERE status = 'aberta'
  AND id NOT IN (
      SELECT MIN(id) FROM disputes WHERE status = 'aberta' GROUP BY order_id
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_disputes_active_order ON disputes(order_id) WHERE status = 'aberta';
