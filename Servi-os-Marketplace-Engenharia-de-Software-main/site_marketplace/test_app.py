import unittest
import json
import os
import sys

# Garante importação correta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

if __name__ == '__main__':
    unittest.main()
