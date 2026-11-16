-- Migration 001: Índices iniciais de desempenho para services, orders e users
CREATE INDEX IF NOT EXISTS idx_services_cat ON services(categoria);
CREATE INDEX IF NOT EXISTS idx_services_prestador ON services(prestador_id);
CREATE INDEX IF NOT EXISTS idx_services_ativo ON services(ativo);
CREATE INDEX IF NOT EXISTS idx_services_coords ON services(lat, lng);
CREATE INDEX IF NOT EXISTS idx_orders_cliente ON orders(cliente_id);
CREATE INDEX IF NOT EXISTS idx_orders_prestador ON orders(prestador_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_tipo ON users(tipo);
