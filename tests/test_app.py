import unittest
import json
import os
import sys

# Garante importação correta a partir da raiz do repositório
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from app import app
from database import init_db

class TestMarketplaceFull(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        import database
        cls.temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        cls.temp_file.close()
        os.environ['MARKETPLACE_DB'] = cls.temp_file.name
        database.DB_PATH = cls.temp_file.name
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, 'temp_file') and os.path.exists(cls.temp_file.name):
                os.remove(cls.temp_file.name)
        except OSError:
            pass

    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret-suite'
        self.client = app.test_client()

    def test_01_static_pages_load(self):
        pages = ['/', '/index.html', '/pedido.html', '/login.html', '/cadastro.html', '/portal-prestador.html', '/portal-cliente.html', '/como-funciona.html', '/sobre-nos.html']
        for page in pages:
            res = self.client.get(page)
            self.assertEqual(res.status_code, 200, f'Falha ao carregar página {page}')
            res.close()

    def test_02_categoria_marcenaria_sync(self):
        res = self.client.get('/api/services?cat=Marcenaria')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertGreater(len(data), 0)
        marcenaria = next((s for s in data if s['categoria'] == 'Marcenaria' and 'Nina' in s['prestador']['nome']), None)
        self.assertIsNotNone(marcenaria, 'Serviço de Marcenaria da Nina não foi encontrado na API')
        self.assertIn('Nina', marcenaria['prestador']['nome'])

    def test_03_fluxo_completo_prestador_servico_preco(self):
        # 1. Login com o prestador padrão Carlos
        res_login = self.client.post('/api/auth/login', json={
            'email': 'carlos@pertoja.com',
            'senha': '123456'
        })
        self.assertEqual(res_login.status_code, 200)
        user = json.loads(res_login.data)['user']
        self.assertEqual(user['tipo'], 'prestador')

        # 2. Consultar meus serviços
        res_servicos = self.client.get('/api/my-services')
        self.assertEqual(res_servicos.status_code, 200)
        servicos = json.loads(res_servicos.data)
        self.assertGreater(len(servicos), 0)
        servico_original = servicos[0]
        servico_id = servico_original['id']

        # 3. Alterar o preço do serviço
        novo_preco = 115.50
        res_update = self.client.put(f'/api/services/{servico_id}', json={
            'titulo': servico_original['titulo'],
            'descricao': 'Higienização e limpeza completa com produtos inclusos.',
            'categoria': servico_original['categoria'],
            'preco': novo_preco,
            'ativo': True
        })
        self.assertEqual(res_update.status_code, 200)

        # 4. Verificar na listagem pública se o novo preço foi refletido
        res_public = self.client.get('/api/services?radius=0')
        public_data = json.loads(res_public.data)
        servico_publico = next(s for s in public_data if s['id'] == servico_id)
        self.assertEqual(servico_publico['preco'], novo_preco)

        # 5. Alterar perfil do prestador
        res_perfil = self.client.put('/api/profile', json={
            'nome': 'Carlos Mendes Atualizado',
            'telefone': '(11) 98888-7777',
            'bio': 'Profissional com mais de 10 anos de experiência.',
            'lat': -23.4650,
            'lng': -46.5350,
            'disponivel': True
        })
        self.assertEqual(res_perfil.status_code, 200)

        res_me = self.client.get('/api/auth/me')
        self.assertEqual(json.loads(res_me.data)['user']['nome'], 'Carlos Mendes Atualizado')

    def test_04_fluxo_completo_cliente_e_ordem_de_servico(self):
        # 1. Login com o cliente padrão
        res_login = self.client.post('/api/auth/login', json={
            'email': 'cliente@pertoja.com',
            'senha': '123456'
        })
        self.assertEqual(res_login.status_code, 200)
        user = json.loads(res_login.data)['user']
        self.assertEqual(user['tipo'], 'cliente')

        # 2. Atualizar perfil do cliente
        res_perfil = self.client.put('/api/profile', json={
            'nome': 'Ana Paula Silva Atualizada',
            'telefone': '(11) 97777-6666',
            'bio': 'Rua das Flores, 123 - Apto 40'
        })
        self.assertEqual(res_perfil.status_code, 200)

        # 3. Pegar um serviço público para contratar
        res_public = self.client.get('/api/services')
        servico_alvo = json.loads(res_public.data)[0]

        # 4. Criar ordem de serviço
        res_order = self.client.post('/api/orders', json={
            'servico_id': servico_alvo['id'],
            'observacoes': 'Favor trazer nota fiscal.',
            'lat': -23.4628,
            'lng': -46.5333
        })
        self.assertEqual(res_order.status_code, 201)
        order_id = json.loads(res_order.data)['order_id']

        # 5. Listar ordens do cliente
        res_my_orders = self.client.get('/api/orders')
        self.assertEqual(res_my_orders.status_code, 200)
        orders = json.loads(res_my_orders.data)
        minha_ordem = next(o for o in orders if o['order_id'] == order_id)
        self.assertEqual(minha_ordem['status'], 'solicitado')

        # 6. Atualizar status da ordem
        res_status = self.client.patch(f'/api/orders/{order_id}/status', json={'status': 'confirmado'})
        self.assertEqual(res_status.status_code, 200)

        res_status2 = self.client.patch(f'/api/orders/{order_id}/status', json={'status': 'finalizado'})
        self.assertEqual(res_status2.status_code, 200)

    def test_05_consulta_cep_e_geocodificacao(self):
        # 1. Consulta CEP de São Paulo (Avenida Paulista)
        res_cep = self.client.get('/api/cep/01310100')
        self.assertEqual(res_cep.status_code, 200)
        data_cep = json.loads(res_cep.data)
        self.assertIn('Paulista', data_cep.get('logradouro', ''))
        self.assertEqual(data_cep.get('uf'), 'SP')
        self.assertIsNotNone(data_cep.get('lat'))
        self.assertIsNotNone(data_cep.get('lng'))

        # 2. Consulta CEP de Guarulhos (Rua do Araújo - 07141430)
        res_guarulhos = self.client.get('/api/cep/07141430')
        self.assertEqual(res_guarulhos.status_code, 200)
        data_g = json.loads(res_guarulhos.data)
        self.assertEqual(data_g.get('localidade'), 'Guarulhos')
        self.assertIsNotNone(data_g.get('lat'))
        self.assertIsNotNone(data_g.get('lng'))
        # Garante que não foi retornado o fallback estático de SP (-23.5653, -46.6517)
        self.assertNotAlmostEqual(data_g.get('lat'), -23.5653, places=3)
        self.assertAlmostEqual(data_g.get('lat'), -23.46, delta=0.08)

        # 3. Busca de serviços próximos a Guarulhos com raio de 8 km
        res_serv_g = self.client.get(f"/api/services?radius=8&lat={data_g['lat']}&lng={data_g['lng']}")
        self.assertEqual(res_serv_g.status_code, 200)
        servicos_g = json.loads(res_serv_g.data)
        self.assertTrue(len(servicos_g) > 0)
        nomes_prestadores = [s['prestador']['nome'] for s in servicos_g]
        self.assertIn('Juliana Clean', nomes_prestadores)

        # 4. Consulta CEP de Santana (Rua Dr. Olavo Egídio - 02037000) próximo ao Beto
        res_santana = self.client.get('/api/cep/02037000')
        self.assertEqual(res_santana.status_code, 200)
        data_s = json.loads(res_santana.data)
        self.assertEqual(data_s.get('bairro'), 'Santana')
        self.assertAlmostEqual(data_s.get('lat'), -23.50, delta=0.03)
        self.assertAlmostEqual(data_s.get('lng'), -46.625, delta=0.03)

        res_serv_s = self.client.get(f"/api/services?radius=8&lat={data_s['lat']}&lng={data_s['lng']}")
        self.assertEqual(res_serv_s.status_code, 200)
        servicos_s = json.loads(res_serv_s.data)
        self.assertTrue(len(servicos_s) > 0)
        self.assertEqual(servicos_s[0]['prestador']['nome'], 'Beto Hidráulica')
        self.assertLess(servicos_s[0]['distancia_km'], 1.0)

        # 5. CEP inválido / inexistente
        res_invalido = self.client.get('/api/cep/00000000')
        self.assertEqual(res_invalido.status_code, 404)

        # 5. Geocodificação Nominatim
        res_geo = self.client.get('/api/geocode?q=Avenida+Paulista+1000+Sao+Paulo')
        self.assertEqual(res_geo.status_code, 200)
        data_geo = json.loads(res_geo.data)
        self.assertIn('lat', data_geo)
        self.assertIn('lng', data_geo)

    def test_06_cadastro_e_anuncio_prestador_com_endereco_real(self):
        import uuid
        unique_email = f"prestador_{uuid.uuid4().hex[:6]}@teste.com"

        # 1. Cadastro com endereço completo
        res_reg = self.client.post('/api/auth/register', json={
            'nome': 'Marceneiro do Bixiga',
            'email': unique_email,
            'senha': 'senha123teste',
            'telefone': '(11) 98765-4321',
            'tipo': 'prestador',
            'bio': 'Especialista em restauração de móveis clássicos.',
            'cep': '01310-100',
            'endereco': 'Avenida Paulista',
            'numero': '1578',
            'complemento': 'Conj 201',
            'bairro': 'Bela Vista',
            'cidade': 'São Paulo',
            'estado': 'SP',
            'lat': -23.5615,
            'lng': -46.6559
        })
        self.assertEqual(res_reg.status_code, 201)

        # 2. Criar novo serviço / anúncio
        res_svc = self.client.post('/api/services', json={
            'titulo': 'Restauração de Móveis de Madeira Nobre',
            'descricao': 'Restauração artesanal no local ou em oficina.',
            'categoria': 'Marcenaria',
            'preco': 320.00,
            'cep': '01310-100',
            'endereco': 'Avenida Paulista',
            'numero': '1578',
            'bairro': 'Bela Vista',
            'cidade': 'São Paulo',
            'estado': 'SP',
            'lat': -23.5615,
            'lng': -46.6559
        })
        self.assertEqual(res_svc.status_code, 201)
        svc_data = json.loads(res_svc.data)
        novo_servico_id = svc_data['id']

        # 3. Verificar listagem pública: o serviço deve conter o endereço real formatado
        res_public = self.client.get(f'/api/services?cat=Marcenaria')
        self.assertEqual(res_public.status_code, 200)
        servicos = json.loads(res_public.data)
        meu_anuncio = next((s for s in servicos if s['id'] == novo_servico_id), None)
        self.assertIsNotNone(meu_anuncio, 'Anúncio publicado não apareceu na lista de serviços!')
        self.assertIn('Avenida Paulista', meu_anuncio['endereco']['logradouro'])
        self.assertIn('Bela Vista', meu_anuncio['bairro'])
        self.assertEqual(meu_anuncio['cidade'], 'São Paulo')
        self.assertAlmostEqual(meu_anuncio['lat'], -23.5615, places=3)
        self.assertAlmostEqual(meu_anuncio['lng'], -46.6559, places=3)

    def test_07_pedido_com_endereco_real_do_cliente(self):
        # 1. Login com cliente
        self.client.post('/api/auth/login', json={
            'email': 'cliente@pertoja.com',
            'senha': '123456'
        })

        # 2. Atualizar endereço do cliente
        self.client.put('/api/profile', json={
            'nome': 'Ana Paula Silva',
            'telefone': '(11) 97777-6666',
            'cep': '01414-001',
            'endereco': 'Rua Haddock Lobo',
            'numero': '595',
            'complemento': 'Apto 12',
            'bairro': 'Cerqueira César',
            'cidade': 'São Paulo',
            'estado': 'SP',
            'lat': -23.5580,
            'lng': -46.6620
        })

        # 3. Buscar serviço e criar pedido
        res_svc = self.client.get('/api/services')
        servico = json.loads(res_svc.data)[0]

        res_order = self.client.post('/api/orders', json={
            'servico_id': servico['id'],
            'observacoes': 'Favor tocar o interfone 12.',
            'endereco': 'Rua Haddock Lobo',
            'numero': '595',
            'bairro': 'Cerqueira César',
            'cidade': 'São Paulo',
            'estado': 'SP',
            'lat': -23.5580,
            'lng': -46.6620
        })
        self.assertEqual(res_order.status_code, 201)
        order_id = json.loads(res_order.data)['order_id']

        # 4. Login com o prestador do serviço para checar o pedido recebido com endereço
        self.client.post('/api/auth/login', json={
            'email': servico['prestador']['email'] if 'email' in servico['prestador'] else 'carlos@pertoja.com',
            'senha': '123456'
        })
        res_prest_orders = self.client.get('/api/orders')
        self.assertEqual(res_prest_orders.status_code, 200)
        pedidos_recebidos = json.loads(res_prest_orders.data)
        pedido = next((p for p in pedidos_recebidos if p['order_id'] == order_id), None)
        if pedido:
            self.assertEqual(pedido['endereco_cliente'], 'Rua Haddock Lobo')
            self.assertEqual(pedido['bairro_cliente'], 'Cerqueira César')

    def test_08_order_edge_cases_coordinates_fallback(self):
        # 1. Login com cliente
        self.client.post('/api/auth/login', json={'email': 'cliente@pertoja.com', 'senha': '123456'})

        # 2. Criar pedido passando explicitamente lat: None e lng: None
        res_order = self.client.post('/api/orders', json={
            'servico_id': 1,
            'observacoes': 'Teste de robustez coordenadas nulas',
            'lat': None,
            'lng': None
        })
        self.assertEqual(res_order.status_code, 201)
        data = json.loads(res_order.data)
        self.assertIn('order_id', data)

        # 3. Criar pedido com coordenadas como strings inválidas
        res_order2 = self.client.post('/api/orders', json={
            'servico_id': 1,
            'observacoes': 'Teste de robustez coordenadas string',
            'lat': '',
            'lng': 'invalido'
        })
        self.assertEqual(res_order2.status_code, 201)

    def test_09_profile_and_service_defensive_updates(self):
        # 1. Login com prestador
        self.client.post('/api/auth/login', json={'email': 'carlos@pertoja.com', 'senha': '123456'})

        # 2. Atualizar perfil com coordenadas vazias/inválidas
        res_prof = self.client.put('/api/profile', json={
            'nome': 'Carlos Mendes Resiliente',
            'lat': '',
            'lng': 'invalido'
        })
        self.assertEqual(res_prof.status_code, 200)

        # 3. Criar serviço com preço e coordenadas defensivas
        res_svc = self.client.post('/api/services', json={
            'titulo': 'Serviço com Coordenadas Resilientes',
            'categoria': 'Limpeza',
            'preco': 150.0,
            'lat': None,
            'lng': ''
        })
        self.assertEqual(res_svc.status_code, 201)
        svc_id = json.loads(res_svc.data)['id']

        # 4. Atualizar serviço com valores de borda
        res_up = self.client.put(f'/api/services/{svc_id}', json={
            'titulo': 'Serviço Atualizado Resiliente',
            'categoria': 'Limpeza',
            'preco': 160.0,
            'lat': None,
            'lng': None
        })
        self.assertEqual(res_up.status_code, 200)

    def test_10_my_services_filtering_and_soft_delete(self):
        # 1. Login com prestador Carlos
        self.client.post('/api/auth/login', json={'email': 'carlos@pertoja.com', 'senha': '123456'})

        # 2. Criar novo serviço temporário
        res_create = self.client.post('/api/services', json={
            'titulo': 'Serviço Temporário para Exclusão',
            'categoria': 'Limpeza',
            'preco': 99.0
        })
        self.assertEqual(res_create.status_code, 201)
        temp_svc_id = json.loads(res_create.data)['id']

        # 3. Excluir o serviço criado (sem ordens -> delete físico)
        res_del = self.client.delete(f'/api/services/{temp_svc_id}')
        self.assertEqual(res_del.status_code, 200)

        # 4. Verificar que não aparece mais em my-services
        res_list = self.client.get('/api/my-services')
        ids_ativos = [s['id'] for s in json.loads(res_list.data)]
        self.assertNotIn(temp_svc_id, ids_ativos)

    def test_11_performance_security_and_seo_routes(self):
        # 1. SEO: robots.txt
        res_robots = self.client.get('/robots.txt')
        self.assertEqual(res_robots.status_code, 200)
        self.assertIn('User-agent: *', res_robots.data.decode('utf-8'))
        self.assertIn('sitemap.xml', res_robots.data.decode('utf-8'))

        # 2. SEO: sitemap.xml
        res_sitemap = self.client.get('/sitemap.xml')
        self.assertEqual(res_sitemap.status_code, 200)
        sitemap_str = res_sitemap.data.decode('utf-8')
        self.assertIn('<urlset', sitemap_str)
        self.assertIn('pedido.html', sitemap_str)

        # 3. Resiliência: Custom 404 Error Handler
        res_404 = self.client.get('/pagina-inexistente-123456.html')
        self.assertEqual(res_404.status_code, 404)
        self.assertIn('404', res_404.data.decode('utf-8'))
        self.assertIn('PertoJá', res_404.data.decode('utf-8'))

        # 4. Segurança de Frontend: Cabeçalhos HTTP OWASP
        res_home = self.client.get('/')
        self.assertEqual(res_home.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res_home.headers.get('X-Frame-Options'), 'SAMEORIGIN')
        self.assertIn('strict-origin', res_home.headers.get('Referrer-Policy', ''))

        # 5. Performance / Caching headers
        res_api = self.client.get('/api/services')
        self.assertIn('no-store', res_api.headers.get('Cache-Control', ''))

        res_static = self.client.get('/style.css')
        self.assertIn('public', res_static.headers.get('Cache-Control', ''))
        self.assertIn('max-age', res_static.headers.get('Cache-Control', ''))

    def test_12_blindagem_autenticacao_checkout(self):
        # Garante logout prévio
        self.client.post('/api/auth/logout')

        # 1. Usuário Deslogado: Tentativa direta contra POST /api/orders
        res_anon = self.client.post('/api/orders', json={
            'servico_id': 1,
            'observacoes': 'Tentativa anônima'
        })
        self.assertEqual(res_anon.status_code, 401, 'Usuário anônimo deveria receber 401 Unauthorized')
        data_anon = json.loads(res_anon.data)
        self.assertEqual(data_anon.get('code'), 'UNAUTHORIZED')
        self.assertIn('login_url', data_anon)

        # 2. Usuário Deslogado: Tentativa com injeção forjada de cliente_id
        res_anon_forged = self.client.post('/api/orders', json={
            'cliente_id': 2,
            'servico_id': 1
        })
        self.assertEqual(res_anon_forged.status_code, 401)
        self.assertEqual(json.loads(res_anon_forged.data).get('code'), 'UNAUTHORIZED')

        # 3. Usuário Prestador Autenticado: Tentativa de solicitar serviço (não permitido para prestador)
        self.client.post('/api/auth/login', json={'email': 'carlos@pertoja.com', 'senha': '123456'})
        res_prest = self.client.post('/api/orders', json={
            'servico_id': 1,
            'observacoes': 'Prestador tentando criar chamado'
        })
        self.assertEqual(res_prest.status_code, 403, 'Prestador deveria receber 403 Forbidden ao tentar solicitar serviço')
        data_prest = json.loads(res_prest.data)
        self.assertEqual(data_prest.get('code'), 'FORBIDDEN')

        # 4. Usuário Cliente Autenticado: Tentativa de criar pedido forjando cliente_id de outro usuário
        self.client.post('/api/auth/login', json={'email': 'cliente@pertoja.com', 'senha': '123456'})
        res_forged_cli = self.client.post('/api/orders', json={
            'cliente_id': 9999,
            'servico_id': 1,
            'observacoes': 'Tentativa de forjar cliente_id'
        })
        self.assertEqual(res_forged_cli.status_code, 403, 'Tentativa de forjar cliente_id deve ser rejeitada com 403')

        # 5. Usuário Cliente Autenticado: Criação legítima de pedido
        res_order = self.client.post('/api/orders', json={
            'servico_id': 1,
            'observacoes': 'Pedido legítimo de cliente autenticado'
        })
        self.assertEqual(res_order.status_code, 201)
        data_order = json.loads(res_order.data)
        order_id = data_order['order_id']
        self.assertEqual(data_order['status'], 'solicitado')

        # 6. Expiração de Sessão / Logout durante o fluxo
        self.client.post('/api/auth/logout')
        res_expired = self.client.post('/api/orders', json={'servico_id': 1})
        self.assertEqual(res_expired.status_code, 401, 'Após logout, tentativa de pedido deve retornar 401')

        # 7. Pagamento de Pedido: Bloqueio para usuário não autenticado
        res_pay_anon = self.client.post(f'/api/orders/{order_id}/pay')
        self.assertEqual(res_pay_anon.status_code, 401)

        # 8. Pagamento de Pedido: Bloqueio para prestador de serviços
        self.client.post('/api/auth/login', json={'email': 'carlos@pertoja.com', 'senha': '123456'})
        res_pay_prest = self.client.post(f'/api/orders/{order_id}/pay')
        self.assertEqual(res_pay_prest.status_code, 403)

        # 9. Pagamento de Pedido: Confirmação bem-sucedida pelo cliente dono da ordem
        self.client.post('/api/auth/login', json={'email': 'cliente@pertoja.com', 'senha': '123456'})
        res_pay_owner = self.client.post(f'/api/orders/{order_id}/pay')
        self.assertEqual(res_pay_owner.status_code, 200)
        data_pay = json.loads(res_pay_owner.data)
        self.assertEqual(data_pay['status'], 'finalizado')

    def test_13_healthcheck_endpoint(self):
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')
        self.assertEqual(data.get('engine'), 'sqlite')
        self.assertIn('timestamp', data)
        self.assertIn('version', data)

    def test_14_geocode_cache_hit_and_store(self):
        from database import save_cached_geocode, get_cached_geocode
        from app import geocode_address

        query = "Avenida Paulista 1578, Bela Vista, São Paulo - SP"
        lat_mock, lng_mock = -23.5614, -46.6559

        # Salva em cache
        save_cached_geocode(query, lat_mock, lng_mock, origem='unit-test')
        cached = get_cached_geocode(query)
        self.assertIsNotNone(cached)
        self.assertAlmostEqual(cached[0], lat_mock, places=4)
        self.assertAlmostEqual(cached[1], lng_mock, places=4)

        # geocode_address deve resolver a partir do cache sem requisição externa
        resolved_lat, resolved_lng = geocode_address(query)
        self.assertAlmostEqual(resolved_lat, lat_mock, places=4)
        self.assertAlmostEqual(resolved_lng, lng_mock, places=4)

    def test_15_rate_limiter_logic(self):
        from app import rate_limiter
        rate_limiter.reset()

        # Testa o limitador por janela deslizante
        key = "test_user_ip"
        limit = 3
        window = 10

        self.assertTrue(rate_limiter.is_allowed(key, limit, window))
        self.assertTrue(rate_limiter.is_allowed(key, limit, window))
        self.assertTrue(rate_limiter.is_allowed(key, limit, window))
        # Quarta requisição deve ser bloqueada
        self.assertFalse(rate_limiter.is_allowed(key, limit, window))

        # Testa comportamento de endpoint com rate limit ativo (desabilitando TESTING temporariamente)
        try:
            app.config['TESTING'] = False
            rate_limiter.reset()
            # 10 tentativas permitidas por minuto no login
            for _ in range(10):
                self.client.post('/api/auth/login', json={'email': 'inexistente@pertoja.com', 'senha': 'errada'})

            # 11ª tentativa deve retornar HTTP 429 Too Many Requests com header Retry-After
            res_blocked = self.client.post('/api/auth/login', json={'email': 'inexistente@pertoja.com', 'senha': 'errada'})
            self.assertEqual(res_blocked.status_code, 429)
            self.assertIn('Retry-After', res_blocked.headers)
            data_blocked = json.loads(res_blocked.data)
            self.assertIn('error', data_blocked)
            self.assertIn('retry_after_seconds', data_blocked)
        finally:
            app.config['TESTING'] = True
            rate_limiter.reset()

    def test_16_pwa_manifest_and_icons(self):
        res = self.client.get('/manifest.json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('name', data)
        self.assertIn('short_name', data)
        self.assertIn('icons', data)
        self.assertGreaterEqual(len(data['icons']), 2)

    def test_17_dual_engine_placeholder_translation(self):
        from database import translate_placeholders
        # Basic translation
        self.assertEqual(
            translate_placeholders("SELECT * FROM users WHERE email = ?"),
            "SELECT * FROM users WHERE email = %s"
        )
        # Multi-parameter translation
        self.assertEqual(
            translate_placeholders("INSERT INTO t (a, b, c) VALUES (?, ?, ?)"),
            "INSERT INTO t (a, b, c) VALUES (%s, %s, %s)"
        )
        # Preservation of string literals containing question marks
        self.assertEqual(
            translate_placeholders("SELECT * FROM t WHERE query = 'Qual o preço?' AND id = ?"),
            "SELECT * FROM t WHERE query = 'Qual o preço?' AND id = %s"
        )
        # Pass-through when no placeholders present
        self.assertEqual(translate_placeholders("SELECT 1"), "SELECT 1")

    def test_18_postgres_adapter_returning_id_and_lastrowid(self):
        from unittest.mock import MagicMock
        from database import PostgresConnectionWrapper, PostgresCursorWrapper

        raw_cursor = MagicMock()
        raw_cursor.fetchone.return_value = {'id': 105}
        raw_conn = MagicMock()
        raw_conn.cursor.return_value = raw_cursor

        wrapped_conn = PostgresConnectionWrapper(raw_conn)
        cursor = wrapped_conn.execute("INSERT INTO orders (cliente_id, servico_id) VALUES (?, ?)", (1, 2))

        # Verify SQL sent to postgres includes RETURNING id
        executed_sql, executed_params = raw_cursor.execute.call_args[0]
        self.assertIn("RETURNING id", executed_sql)
        self.assertIn("%s", executed_sql)
        self.assertNotIn("?", executed_sql)
        self.assertEqual(executed_params, (1, 2))
        # Verify cursor.lastrowid populated from returned dict
        self.assertEqual(cursor.lastrowid, 105)

        # Verify non-INSERT does not append RETURNING id
        raw_cursor.reset_mock()
        wrapped_conn.execute("UPDATE services SET preco = ? WHERE id = ?", (150.0, 10))
        up_sql, _ = raw_cursor.execute.call_args[0]
        self.assertNotIn("RETURNING id", up_sql)

    def test_19_unified_db_integrity_error_handling(self):
        import sqlite3
        from database import DBIntegrityError, Psycopg2IntegrityError

        # 1. Catches sqlite3.IntegrityError
        caught_sqlite = False
        try:
            raise sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        except DBIntegrityError:
            caught_sqlite = True
        self.assertTrue(caught_sqlite)

        # 2. Catches psycopg2.IntegrityError
        caught_pg = False
        try:
            raise Psycopg2IntegrityError("duplicate key value violates unique constraint")
        except DBIntegrityError:
            caught_pg = True
        self.assertTrue(caught_pg)

        # 3. Soft-delete fallback in delete_service() on DBIntegrityError
        # Login prestador
        self.client.post('/api/auth/login', json={'email': 'carlos@pertoja.com', 'senha': '123456'})
        # Create service
        res_svc = self.client.post('/api/services', json={
            'titulo': 'Serviço para Teste Integridade',
            'categoria': 'Limpeza',
            'preco': 100.0
        })
        svc_id = json.loads(res_svc.data)['id']

        # Login cliente and create order referencing service
        self.client.post('/api/auth/login', json={'email': 'cliente@pertoja.com', 'senha': '123456'})
        self.client.post('/api/orders', json={'servico_id': svc_id, 'observacoes': 'Pedido teste integridade'})

        # Login prestador back and delete service -> foreign key triggers DBIntegrityError -> soft delete (ativo = 0)
        self.client.post('/api/auth/login', json={'email': 'carlos@pertoja.com', 'senha': '123456'})
        res_del = self.client.delete(f'/api/services/{svc_id}')
        self.assertEqual(res_del.status_code, 200)

        # Service should no longer be active in public listings
        res_list = self.client.get('/api/services')
        ids = [s['id'] for s in json.loads(res_list.data)]
        self.assertNotIn(svc_id, ids)

    def test_20_sqlite_fallback_and_environment_url_resolution(self):
        from database import resolve_database_url, get_active_engine
        from unittest.mock import patch

        # 1. Fallback to SQLite when no URL configured
        with patch.dict(os.environ, {}, clear=True):
            url, engine = resolve_database_url()
            self.assertIsNone(url)
            self.assertEqual(engine, 'sqlite')

        # 2. Normalization of postgres:// to postgresql:// and sslmode enforcement
        with patch.dict(os.environ, {'DATABASE_URL': 'postgres://user:pass@ep-cool.us-east-1.aws.neon.tech/neondb'}):
            url, engine = resolve_database_url()
            self.assertTrue(url.startswith('postgresql://'))
            self.assertIn('sslmode=require', url)
            self.assertEqual(engine, 'postgresql')

        # 3. Fallback to POSTGRES_URL / POSTGRES_URL_NON_POOLING
        with patch.dict(os.environ, {'POSTGRES_URL_NON_POOLING': 'postgres://user:pass@host/db'}, clear=True):
            url, engine = resolve_database_url()
            self.assertTrue(url.startswith('postgresql://'))
            self.assertEqual(engine, 'postgresql')

    def test_21_geocode_cache_upsert_on_conflict(self):
        from database import save_cached_geocode, get_cached_geocode

        query = "Praça da Sé, São Paulo"
        save_cached_geocode(query, -23.5500, -46.6330, origem='test1')
        self.assertEqual(get_cached_geocode(query), (-23.5500, -46.6330))

        # Upsert with new coordinates must update existing row without raising error
        save_cached_geocode(query, -23.5505, -46.6335, origem='test2')
        self.assertEqual(get_cached_geocode(query), (-23.5505, -46.6335))

    def test_22_healthcheck_dual_engine_structure(self):
        from unittest.mock import patch, MagicMock

        # 1. Under SQLite
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')
        self.assertEqual(data.get('engine'), 'sqlite')

        # 2. Under Mocked PostgreSQL
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (1,)
        mock_conn.execute.return_value = mock_cur
        with patch('database.get_active_engine', return_value='postgresql'), \
             patch('database.get_db_connection', return_value=mock_conn):
            res_pg = self.client.get('/api/health')
            self.assertEqual(res_pg.status_code, 200)
            data_pg = json.loads(res_pg.data)
            self.assertEqual(data_pg.get('engine'), 'postgresql')
            self.assertEqual(data_pg.get('status'), 'healthy')

    def test_23_provider_seeding_optimization(self):
        import database
        from unittest.mock import MagicMock
        conn = database.get_db_connection()

        # Pre-condition: 35 providers exist in real DB
        count = conn.execute("SELECT COUNT(*) FROM users WHERE tipo = 'prestador'").fetchone()[0]
        self.assertGreaterEqual(count, 35)

        # Verify real database execution skips batch updates cleanly
        database.sincronizar_todos_prestadores(conn)
        conn.close()

        # Verify with mock that only 1 query (COUNT) runs when provider count >= 35
        mock_cursor = MagicMock()
        mock_cursor.execute.return_value.fetchone.return_value = (35,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        database.sincronizar_todos_prestadores(mock_conn)

        # Only the initial COUNT check query was executed; batch updates skipped
        self.assertEqual(mock_cursor.execute.call_count, 1)
        executed_sql = mock_cursor.execute.call_args[0][0]
        self.assertIn("SELECT COUNT(*)", executed_sql)

    def test_24_services_order_by_score(self):
        res_dist = self.client.get('/api/services?order=distance')
        self.assertEqual(res_dist.status_code, 200)
        dist_list = json.loads(res_dist.data)
        self.assertGreater(len(dist_list), 1)
        self.assertEqual(
            [s['distancia_km'] for s in dist_list],
            sorted(s['distancia_km'] for s in dist_list)
        )

        res_score = self.client.get('/api/services?order=score')
        self.assertEqual(res_score.status_code, 200)
        score_list = json.loads(res_score.data)
        self.assertGreater(len(score_list), 1)
        self.assertEqual(
            [(s['score'], -s['distancia_km']) for s in score_list],
            sorted(((s['score'], -s['distancia_km']) for s in score_list), reverse=True)
        )

    def test_25_geocode_query_normalization(self):
        from database import _normalizar_query, save_cached_geocode, get_cached_geocode
        self.assertEqual(
            _normalizar_query("  São   Paulo,  Avenida   Paulista  "),
            "sao paulo, avenida paulista"
        )
        save_cached_geocode("Praça da Sé, 100   São Paulo", -23.5505, -46.6333, origem='norm-test')
        cached = get_cached_geocode("  praca da se, 100 sao   paulo ")
        self.assertIsNotNone(cached)
        self.assertAlmostEqual(cached[0], -23.5505, places=4)

    def test_26_static_path_traversal_and_404(self):
        res_trav = self.client.get('/../../etc/passwd')
        self.assertEqual(res_trav.status_code, 404)

        res_missing = self.client.get('/rota-que-nao-existe-abc')
        self.assertEqual(res_missing.status_code, 404)

        res_friendly = self.client.get('/pedido')
        self.assertEqual(res_friendly.status_code, 200)

    def test_27_resolve_db_path_local_vs_serverless(self):
        import database
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            local_path = database._resolve_db_path()
            self.assertFalse(local_path.startswith('/tmp'))
            self.assertTrue(local_path.endswith('marketplace.db'))

        with patch.dict(os.environ, {'VERCEL': '1'}, clear=True):
            self.assertEqual(database._resolve_db_path(), '/tmp/marketplace.db')

        with patch.dict(os.environ, {'AWS_LAMBDA_FUNCTION_NAME': 'fn'}, clear=True):
            self.assertEqual(database._resolve_db_path(), '/tmp/marketplace.db')

if __name__ == '__main__':
    unittest.main()
