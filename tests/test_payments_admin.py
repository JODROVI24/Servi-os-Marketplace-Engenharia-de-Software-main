import os
import re
import sys
import json
import hmac
import hashlib
import sqlite3
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import database
from werkzeug.security import generate_password_hash
from app import app
from payment_adapters import (
    get_gateway_adapter,
    create_hmac_signature,
    StripeAdapter,
    PagSeguroAdapter,
    MercadoPagoAdapter,
)


class TestPaymentsAndAdminSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        cls.temp_file.close()
        os.environ['MARKETPLACE_DB'] = cls.temp_file.name
        database.DB_PATH = cls.temp_file.name
        database.init_db()

        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            if not conn.execute("SELECT 1 FROM users WHERE email = ?", ('admin@pertoja.com',)).fetchone():
                cur.execute(
                    '''INSERT INTO users (nome, email, senha_hash, tipo, status_conta, kyc_status, session_version)
                       VALUES (?, ?, ?, 'admin', 'ativo', 'aprovado', 1)''',
                    ('Admin Master', 'admin@pertoja.com', generate_password_hash('admin123'))
                )
            if not conn.execute("SELECT 1 FROM users WHERE email = ?", ('cliente2@pertoja.com',)).fetchone():
                cur.execute(
                    '''INSERT INTO users (nome, email, senha_hash, tipo, status_conta, kyc_status, session_version)
                       VALUES (?, ?, ?, 'cliente', 'ativo', 'aprovado', 1)''',
                    ('=CMD|calc!A1 Cliente Dois', 'cliente2@pertoja.com', generate_password_hash('123456'))
                )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, 'temp_file') and os.path.exists(cls.temp_file.name):
                os.remove(cls.temp_file.name)
        except OSError:
            pass

    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret-payments-admin'
        self.client = app.test_client()

    def _login(self, email, senha):
        return self.client.post('/api/auth/login', json={'email': email, 'senha': senha})

    def test_01_postgres_ddl_and_migration_compatibility(self):
        # Nenhuma migration SQLite-only com AUTOINCREMENT deve existir (quebra PostgreSQL na Vercel)
        self.assertNotIn('AUTOINCREMENT', database.POSTGRES_SCHEMA_SQL.upper())
        for filename in database.list_migration_files():
            path = os.path.join(database.MIGRATIONS_DIR, filename)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            sql_no_comments = re.sub(r'--[^\n]*', '', content)
            self.assertNotIn(
                'AUTOINCREMENT',
                sql_no_comments.upper(),
                f'Migration {filename} contem AUTOINCREMENT incompativel com PostgreSQL'
            )

        # Executescript em wrapper PostgreSQL deve ignorar blocos apenas com comentarios/espacos
        executed = []

        class FakeRawCursor:
            description = None
            rowcount = 1

            def execute(self, sql, params=None):
                executed.append(sql)

            def fetchone(self):
                return None

            def close(self):
                pass

        wrapper = database.PostgresCursorWrapper(FakeRawCursor())
        wrapper.executescript("-- comentario com ; dentro\nCREATE TABLE IF NOT EXISTS x (id SERIAL PRIMARY KEY);\n-- fim;\n")
        self.assertEqual(len(executed), 1)
        self.assertIn('CREATE TABLE IF NOT EXISTS x', executed[0])

        # payment_payment_refs nao tem coluna id; INSERT nao deve anexar RETURNING id
        executed.clear()
        wrapper.execute("INSERT INTO payment_payment_refs (payment_id, order_id) VALUES (?, ?)", (1, 2))
        self.assertEqual(len(executed), 1)
        self.assertNotIn('RETURNING id', executed[0].upper())

    def test_02_sqlite_legacy_schema_self_heals_users_and_payments(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        old_db = database.DB_PATH
        old_seed = os.environ.get('ENABLE_DEMO_SEED')
        os.environ['ENABLE_DEMO_SEED'] = '0'
        try:
            # Simula DB antigo onde users nao aceitava admin e 007 antiga criou order_id NOT NULL
            raw = sqlite3.connect(tmp.name)
            raw.executescript('''
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    senha_hash TEXT NOT NULL,
                    tipo TEXT CHECK(tipo IN ('cliente', 'prestador')) NOT NULL
                );
                CREATE TABLE services (id INTEGER PRIMARY KEY AUTOINCREMENT, prestador_id INTEGER NOT NULL, titulo TEXT NOT NULL, categoria TEXT NOT NULL, preco REAL NOT NULL, lat REAL, lng REAL, ativo INTEGER DEFAULT 1, cidade TEXT);
                CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_id INTEGER NOT NULL, prestador_id INTEGER NOT NULL, servico_id INTEGER NOT NULL, status TEXT CHECK(status IN ('solicitado', 'finalizado')) DEFAULT 'solicitado', preco_total REAL NOT NULL);
                CREATE TABLE reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, cliente_id INTEGER NOT NULL, prestador_id INTEGER NOT NULL, nota REAL NOT NULL);
                CREATE TABLE geocode_cache (query TEXT PRIMARY KEY, lat REAL NOT NULL, lng REAL NOT NULL, origem TEXT DEFAULT 'nominatim', criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE user_consents (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, doc_type TEXT NOT NULL, doc_version TEXT NOT NULL);
                CREATE TABLE disputes (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, opened_by INTEGER NOT NULL, motivo TEXT NOT NULL, status TEXT DEFAULT 'aberta');
                CREATE TABLE safety_incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, reporter_id INTEGER NOT NULL);
                CREATE TABLE account_appeals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, motivo TEXT NOT NULL);
                CREATE TABLE order_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, sender_id INTEGER NOT NULL, sender_tipo TEXT NOT NULL, mensagem TEXT NOT NULL);
                CREATE TABLE escrow_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, tipo_evento TEXT NOT NULL);
                CREATE TABLE payment_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    payment_id INTEGER NOT NULL,
                    method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    amount REAL NOT NULL,
                    net_amount REAL NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                    FOREIGN KEY (payment_id) REFERENCES orders(id) ON DELETE CASCADE
                );
            ''')
            raw.close()

            database.DB_PATH = tmp.name
            database.init_db()

            conn = sqlite3.connect(tmp.name)
            conn.execute(
                "INSERT INTO users (nome, email, senha_hash, tipo) VALUES ('Adm', 'adm_mig@test.com', 'h', 'admin')"
            )
            conn.execute(
                "INSERT INTO payment_transactions (user_id, order_id, payment_id, method, status, amount, net_amount) VALUES (1, NULL, NULL, 'pix', 'pending', 50.0, 46.0)"
            )
            conn.execute(
                "INSERT INTO notifications (admin_id, tipo, mensagem, destinatario_tipo) VALUES (1, 'info', 'ok', 'all')"
            )
            conn.commit()
            conn.close()
        finally:
            database.DB_PATH = old_db
            if old_seed is None:
                os.environ.pop('ENABLE_DEMO_SEED', None)
            else:
                os.environ['ENABLE_DEMO_SEED'] = old_seed
            try:
                os.remove(tmp.name)
            except OSError:
                pass

    def test_03_payments_create_idempotency_status_idor_and_refund(self):
        # 1. Sem autenticacao -> 401
        res_unauth = self.client.post('/api/payments', json={'amount': 100.0})
        self.assertEqual(res_unauth.status_code, 401)

        # 2. Cliente cria pedido real + pagamento vinculado
        self.assertEqual(self._login('cliente@pertoja.com', '123456').status_code, 200)
        services = json.loads(self.client.get('/api/services?radius=0').data)
        svc = next(s for s in services if s['prestador']['nome'] == 'Marta Souza')
        res_ord = self.client.post('/api/orders', json={'servico_id': svc['id'], 'lat': -23.56, 'lng': -46.65})
        self.assertEqual(res_ord.status_code, 201)
        order_id = json.loads(res_ord.data)['order_id']

        # Rejeita valores/metodos invalidos
        self.assertEqual(self.client.post('/api/payments', json={'amount': 'abc'}).status_code, 400)
        self.assertEqual(self.client.post('/api/payments', json={'amount': 50, 'method': 'crypto'}).status_code, 400)
        self.assertEqual(self.client.post('/api/payments', json={'amount': 50, 'gateway': 'unknown'}).status_code, 400)

        # Pagamento cartao com idempotency key (deve suportar repeticao + recompra com mesmo metodo)
        res_pay = self.client.post(
            '/api/payments',
            json={'amount': 120.5, 'method': 'cartao', 'gateway': 'stripe', 'order_id': order_id, 'idempotency_key': 'idem-pay-1'}
        )
        self.assertEqual(res_pay.status_code, 201)
        pay_data = json.loads(res_pay.data)
        txn_id = pay_data['id']
        self.assertEqual(pay_data['amount'], 120.5)
        self.assertEqual(pay_data['status'], 'captured')

        # Replay idempotente
        res_replay = self.client.post(
            '/api/payments',
            json={'amount': 120.5, 'method': 'cartao', 'gateway': 'stripe', 'order_id': order_id, 'idempotency_key': 'idem-pay-1'}
        )
        self.assertEqual(res_replay.status_code, 200)
        self.assertEqual(json.loads(res_replay.data)['id'], txn_id)

        # Segundo pagamento com o mesmo metodo nao pode estourar UNIQUE(user_id, payment_method)
        res_pay2 = self.client.post(
            '/api/payments',
            json={'amount': 80.0, 'method': 'cartao', 'gateway': 'mercadopago'}
        )
        self.assertEqual(res_pay2.status_code, 201)

        # Dono consulta status -> 200
        self.assertEqual(self.client.get(f'/api/payments/{txn_id}/status').status_code, 200)

        # Outro cliente tenta consultar -> 403 (IDOR bloqueado)
        self.assertEqual(self._login('cliente2@pertoja.com', '123456').status_code, 200)
        self.assertEqual(self.client.get(f'/api/payments/{txn_id}/status').status_code, 403)

        # Prestador NAO vinculado ao pedido tenta consultar ou reembolsar -> 403
        self.assertEqual(self._login('carlos@pertoja.com', '123456').status_code, 200)
        self.assertEqual(self.client.get(f'/api/payments/{txn_id}/status').status_code, 403)
        self.assertEqual(self.client.post(f'/api/payments/{txn_id}/refund', json={}).status_code, 403)

        # Prestador dono do pedido (Marta) consulta -> 200 e reembolsa -> 200 (atualiza status no banco)
        self.assertEqual(self._login('marta@pertoja.com', '123456').status_code, 200)
        self.assertEqual(self.client.get(f'/api/payments/{txn_id}/status').status_code, 200)
        res_ref = self.client.post(f'/api/payments/{txn_id}/refund', json={})
        self.assertEqual(res_ref.status_code, 200)
        self.assertEqual(json.loads(self.client.get(f'/api/payments/{txn_id}/status').data)['status'], 'refunded')
        # Reembolso duplicado -> 400
        self.assertEqual(self.client.post(f'/api/payments/{txn_id}/refund', json={}).status_code, 400)

    def test_04_webhook_signature_enforcement_and_isolation(self):
        # Sem secret configurado, webhook DEVE rejeitar com 401 (sem bypass!)
        for k in ('STRIPE_WEBHOOK_SECRET', 'PAGSEGURO_WEBHOOK_SECRET', 'PAGSEGURO_TOKEN', 'MERCADOPAGO_WEBHOOK_SECRET', 'MERCADOPAGO_ACCESS_TOKEN'):
            os.environ.pop(k, None)

        res_nosig = self.client.post('/api/webhooks/payments', headers={'X-Gateway': 'mercadopago'}, json={'id': '123'})
        self.assertEqual(res_nosig.status_code, 401)
        res_pag_nosig = self.client.post('/api/webhooks/payments', headers={'X-Gateway': 'pagseguro'}, json={'id': '123'})
        self.assertEqual(res_pag_nosig.status_code, 401)
        res_bad_gw = self.client.post('/api/webhooks/payments', headers={'X-Gateway': 'invalid_gw'}, json={})
        self.assertEqual(res_bad_gw.status_code, 400)

        # Cria pagamento pix pendente para reconciliar via webhook autenticado Stripe
        self.assertEqual(self._login('cliente@pertoja.com', '123456').status_code, 200)
        res_pay = self.client.post('/api/payments', json={'amount': 45.0, 'method': 'pix', 'gateway': 'stripe'})
        self.assertEqual(res_pay.status_code, 201)
        pay_data = json.loads(res_pay.data)
        txn_id = pay_data['id']
        gw_id = pay_data['gateway_id']

        os.environ['STRIPE_WEBHOOK_SECRET'] = 'whsec_test_secret_123'
        try:
            body = json.dumps({'type': 'charge.succeeded', 'status': 'succeeded', 'data': {'object': {'id': gw_id}}})
            # Assinatura errada -> 401
            self.assertEqual(
                self.client.post(
                    '/api/webhooks/payments',
                    data=body,
                    content_type='application/json',
                    headers={'X-Gateway': 'stripe', 'Stripe-Signature': 'deadbeef'}
                ).status_code,
                401
            )
            # Assinatura HMAC valida -> 200 e status vira captured
            sig = create_hmac_signature(body, 'whsec_test_secret_123')
            res_ok = self.client.post(
                '/api/webhooks/payments',
                data=body,
                content_type='application/json',
                headers={'X-Gateway': 'stripe', 'Stripe-Signature': sig}
            )
            self.assertEqual(res_ok.status_code, 200)
            res_status = self.client.get(f'/api/payments/{txn_id}/status')
            self.assertEqual(json.loads(res_status.data)['status'], 'captured')
        finally:
            os.environ.pop('STRIPE_WEBHOOK_SECRET', None)

        # Adapters nao compartilham estado mutavel global entre requisicoes
        mp1 = get_gateway_adapter('mercadopago')
        mp2 = get_gateway_adapter('mercadopago')
        mp1.config_return_urls(success_url='https://a.example.com/ok')
        self.assertIsNone(mp2.get_return_urls_config()['success_url'])
        self.assertTrue(StripeAdapter().format_gateway_response({'status': 'succeeded'})['success'])

    def test_05_admin_rbac_crud_sqli_csv_and_notifications(self):
        # Nao autenticado -> 401; Cliente/Prestador -> 403
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/admin/metrics').status_code, 401)
        self._login('cliente@pertoja.com', '123456')
        self.assertEqual(self.client.get('/api/admin/metrics').status_code, 403)
        self.assertEqual(self.client.get('/api/admin/users').status_code, 403)

        # Admin login -> 200 e acesso total
        res_adm = self._login('admin@pertoja.com', 'admin123')
        self.assertEqual(res_adm.status_code, 200)
        admin_id = json.loads(res_adm.data)['user']['id']

        res_metrics = self.client.get('/api/admin/metrics')
        self.assertEqual(res_metrics.status_code, 200)
        metrics = json.loads(res_metrics.data)
        self.assertGreaterEqual(metrics['usuarios']['admins'], 1)
        self.assertGreater(metrics['faturamento']['bruto'], 0.0)

        # SQL injection em order_by/order_dir nao causa erro nem injecao
        for ep in ('/api/admin/users', '/api/admin/services', '/api/admin/orders', '/api/admin/payments'):
            res_sqli = self.client.get(f"{ep}?order_by=id;DROP TABLE users;--&order_dir=DESC;SELECT 1")
            self.assertEqual(res_sqli.status_code, 200, f'Falha de whitelist em {ep}')

        # Admin cria novo usuario e edita/desativa (nao bloqueia outros usuarios!)
        res_cu = self.client.post('/api/admin/users', json={
            'nome': 'Operador Novo',
            'email': 'opfin@pertoja.com',
            'senha': 'password123',
            'tipo': 'operador_financeiro'
        })
        self.assertEqual(res_cu.status_code, 201)
        new_uid = json.loads(res_cu.data)['id']
        self.assertEqual(json.loads(res_cu.data)['status_conta'], 'ativo')

        res_uu = self.client.put(f'/api/admin/users/{new_uid}', json={'nome': 'Operador Editado', 'status_conta': 'suspenso_cautelar'})
        self.assertEqual(res_uu.status_code, 200)
        self.assertEqual(json.loads(res_uu.data)['nome'], 'Operador Editado')
        self.assertEqual(json.loads(res_uu.data)['status_conta'], 'suspenso_cautelar')

        # Auto-edicao/exclusao admin continua bloqueada com 403
        self.assertEqual(self.client.put(f'/api/admin/users/{admin_id}', json={'nome': 'Self'}).status_code, 403)
        self.assertEqual(self.client.delete(f'/api/admin/users/{admin_id}').status_code, 403)
        self.assertEqual(self.client.delete(f'/api/admin/users/{new_uid}').status_code, 200)

        # CRUD de servicos (sem erro sqlite3.Row assignment)
        res_cs = self.client.post('/api/admin/services', json={
            'titulo': 'Servico Admin Teste',
            'categoria': 'Limpeza',
            'preco': 199.9,
            'prestador_id': 2
        })
        self.assertEqual(res_cs.status_code, 201)
        svc_id = json.loads(res_cs.data)['id']
        res_us = self.client.put(f'/api/admin/services/{svc_id}', json={'titulo': 'Servico Admin Editado', 'preco': 210.0})
        self.assertEqual(res_us.status_code, 200)
        self.assertEqual(json.loads(res_us.data)['preco'], 210.0)
        self.assertEqual(self.client.delete(f'/api/admin/services/{svc_id}').status_code, 200)

        # Export CSV: orders (criado_em), payments, users (sanitizado contra CSV injection) e metrics
        for rtype in ('orders', 'payments', 'users', 'metrics'):
            res_exp = self.client.get(f'/api/admin/reports/export?type={rtype}&format=csv')
            self.assertEqual(res_exp.status_code, 200, f'Falha CSV para type={rtype}')
            if rtype == 'users':
                body_csv = res_exp.data.decode('utf-8')
                self.assertIn("'=CMD|calc!A1 Cliente Dois", body_csv)

        # Notificacoes administrativas
        res_cn = self.client.post('/api/admin/notifications', json={
            'mensagem': 'Manutenção programada às 23h',
            'tipo': 'warning',
            'destinatario_tipo': 'all'
        })
        self.assertEqual(res_cn.status_code, 201)
        res_gn = self.client.get('/api/admin/notifications')
        self.assertEqual(res_gn.status_code, 200)
        self.assertGreaterEqual(len(json.loads(res_gn.data)), 1)


if __name__ == '__main__':
    unittest.main()
