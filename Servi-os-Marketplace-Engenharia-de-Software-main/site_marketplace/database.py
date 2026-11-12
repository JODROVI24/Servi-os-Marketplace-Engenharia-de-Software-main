import sqlite3
import os
from werkzeug.security import generate_password_hash

def _resolve_db_path():
    if 'MARKETPLACE_DB' in os.environ:
        return os.environ['MARKETPLACE_DB']

    # Se Vercel ou qualquer ambiente serverless estiver ativo
    is_serverless = (
        os.environ.get('VERCEL') == '1'
        or os.environ.get('VERCEL') == 'true'
        or 'AWS_LAMBDA_FUNCTION_NAME' in os.environ
        or 'VERCEL_REGION' in os.environ
        or 'NOW_REGION' in os.environ
    )
    if is_serverless:
        return '/tmp/marketplace.db'

    # Testa se o diretório local é gravável; se não for, usa /tmp
    local_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        test_file = os.path.join(local_dir, '.write_test')
        with open(test_file, 'w') as f:
            f.write('1')
        os.remove(test_file)
        return os.path.join(local_dir, 'marketplace.db')
    except (OSError, IOError, PermissionError):
        return '/tmp/marketplace.db'

DB_PATH = _resolve_db_path()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Criação das tabelas base
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            lat REAL DEFAULT -23.5653,
            lng REAL DEFAULT -46.6517,
            avaliacao_media REAL DEFAULT 5.0,
            total_avaliacoes INTEGER DEFAULT 0,
            disponivel INTEGER DEFAULT 1,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prestador_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            descricao TEXT,
            categoria TEXT NOT NULL,
            preco REAL NOT NULL,
            cep TEXT,
            endereco TEXT,
            numero TEXT,
            bairro TEXT,
            cidade TEXT,
            estado TEXT,
            lat REAL,
            lng REAL,
            ativo INTEGER DEFAULT 1,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(prestador_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            prestador_id INTEGER NOT NULL,
            servico_id INTEGER NOT NULL,
            status TEXT CHECK(status IN ('solicitado', 'confirmado', 'em_transito', 'em_execucao', 'finalizado', 'cancelado')) DEFAULT 'solicitado',
            preco_total REAL NOT NULL,
            observacoes TEXT,
            cep_cliente TEXT,
            endereco_cliente TEXT,
            numero_cliente TEXT,
            bairro_cliente TEXT,
            cidade_cliente TEXT,
            estado_cliente TEXT,
            lat_cliente REAL,
            lng_cliente REAL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cliente_id) REFERENCES users(id),
            FOREIGN KEY(prestador_id) REFERENCES users(id),
            FOREIGN KEY(servico_id) REFERENCES services(id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            cliente_id INTEGER NOT NULL,
            prestador_id INTEGER NOT NULL,
            nota REAL NOT NULL,
            comentario TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(cliente_id) REFERENCES users(id),
            FOREIGN KEY(prestador_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            origem TEXT DEFAULT 'nominatim',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Índices estratégicos para performance de busca e integridade
        CREATE INDEX IF NOT EXISTS idx_services_cat ON services(categoria);
        CREATE INDEX IF NOT EXISTS idx_services_prestador ON services(prestador_id);
        CREATE INDEX IF NOT EXISTS idx_services_ativo ON services(ativo);
        CREATE INDEX IF NOT EXISTS idx_services_coords ON services(lat, lng);
        CREATE INDEX IF NOT EXISTS idx_orders_cliente ON orders(cliente_id);
        CREATE INDEX IF NOT EXISTS idx_orders_prestador ON orders(prestador_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_tipo ON users(tipo);
    ''')
    conn.commit()

    # Migração defensiva para colunas de endereço caso já existisse o banco
    cursor.execute("PRAGMA table_info(users)")
    user_cols = [c[1] for c in cursor.fetchall()]
    for col_name, col_type in [
        ('cep', 'TEXT'), ('endereco', 'TEXT'), ('numero', 'TEXT'),
        ('complemento', 'TEXT'), ('bairro', 'TEXT'), ('cidade', 'TEXT'), ('estado', 'TEXT')
    ]:
        if col_name not in user_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")

    cursor.execute("PRAGMA table_info(services)")
    serv_cols = [c[1] for c in cursor.fetchall()]
    for col_name, col_type in [
        ('cep', 'TEXT'), ('endereco', 'TEXT'), ('numero', 'TEXT'),
        ('bairro', 'TEXT'), ('cidade', 'TEXT'), ('estado', 'TEXT'),
        ('lat', 'REAL'), ('lng', 'REAL')
    ]:
        if col_name not in serv_cols:
            cursor.execute(f"ALTER TABLE services ADD COLUMN {col_name} {col_type}")

    cursor.execute("PRAGMA table_info(orders)")
    ord_cols = [c[1] for c in cursor.fetchall()]
    for col_name, col_type in [
        ('cep_cliente', 'TEXT'), ('endereco_cliente', 'TEXT'), ('numero_cliente', 'TEXT'),
        ('bairro_cliente', 'TEXT'), ('cidade_cliente', 'TEXT'), ('estado_cliente', 'TEXT')
    ]:
        if col_name not in ord_cols:
            cursor.execute(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}")

    conn.commit()

    # Seed inicial e sincronização completa dos 35 prestadores por regiões de SP e Guarulhos
    cursor.execute("SELECT id FROM users WHERE email = 'cliente@pertoja.com'")
    if not cursor.fetchone():
        pwd_hash = generate_password_hash('123456')
        cursor.execute('''
            INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng)
            VALUES (?, ?, ?, 'cliente', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            'Ana Paula Silva', 'cliente@pertoja.com', pwd_hash, '(11) 98765-4321',
            'Cliente residencial em busca de serviços locais de alta qualidade.',
            '01402-000', 'Alameda Santos', '800', 'Cerqueira César', 'São Paulo', 'SP',
            -23.5680, -46.6530
        ))
        conn.commit()

    sincronizar_todos_prestadores(conn)
    conn.close()

PRESTADORES_SEED_35 = [
    # --- CENTRO DE SÃO PAULO (5 prestadores) ---
    ('Carlos Mendes', 'carlos@pertoja.com', '(11) 97111-2233', 'Limpeza residencial e comercial com 8 anos de experiência.', 'Limpeza', 'Limpeza residencial completa', 80.0, 4.8, '01310-100', 'Avenida Paulista', '1000', 'Bela Vista', 'São Paulo', 'SP', -23.5653, -46.6517, 1),
    ('Rafa Instalações', 'rafa@pertoja.com', '(11) 97444-5566', 'Instalação ágil de chuveiros, tomadas e luminárias.', 'Elétrica', 'Troca de chuveiro e tomadas elétricas', 90.0, 4.2, '01414-001', 'Rua Haddock Lobo', '800', 'Cerqueira César', 'São Paulo', 'SP', -23.5570, -46.6640, 1),
    ('Téo Suporte', 'teo@pertoja.com', '(11) 97888-9900', 'Técnico em informática e redes residenciais.', 'Tecnologia', 'Suporte técnico de computadores e redes Wi-Fi', 110.0, 4.4, '01228-000', 'Rua da Consolação', '2400', 'Consolação', 'São Paulo', 'SP', -23.5550, -46.6600, 1),
    ('Marcio Encanador Sé', 'marcio@pertoja.com', '(11) 97100-2211', 'Desentupimentos, sifões e conserto de válvulas de descarga.', 'Encanamento', 'Desentupimento e reparo de válvulas e sifões', 130.0, 4.6, '01001-000', 'Praça da Sé', '100', 'Sé', 'São Paulo', 'SP', -23.5505, -46.6333, 1),
    ('Helena Restaurações', 'helena@pertoja.com', '(11) 97100-3322', 'Restauração de portas, janelas e móveis antigos.', 'Marcenaria', 'Restauração de portas e móveis coloniais', 220.0, 4.9, '01223-000', 'Rua Baronesa de Itu', '350', 'Santa Cecília', 'São Paulo', 'SP', -23.5385, -46.6530, 1),

    # --- ZONA NORTE DE SÃO PAULO (5 prestadores) ---
    ('Beto Hidráulica', 'beto@pertoja.com', '(11) 97555-6677', 'Encanador especialista em caça-vazamentos e desentupimentos.', 'Encanamento', 'Conserto de vazamentos e desentupimento', 240.0, 4.7, '02011-000', 'Rua Voluntários da Pátria', '1500', 'Santana', 'São Paulo', 'SP', -23.5042, -46.6262, 1),
    ('Lucia Jardim & Verde', 'lucia@pertoja.com', '(11) 97200-4411', 'Paisagismo, adubação de solo e poda de gramados.', 'Jardinagem', 'Paisagismo, adubação e poda de gramados', 190.0, 4.8, '02305-000', 'Avenida Nova Cantareira', '1200', 'Tucuruvi', 'São Paulo', 'SP', -23.4795, -46.6080, 1),
    ('Valter Força Elétrica', 'valter@pertoja.com', '(11) 97200-5522', 'Manutenção elétrica preventiva, disjuntores e fiação.', 'Elétrica', 'Manutenção elétrica preventiva e disjuntores', 150.0, 4.5, '02511-000', 'Rua Doutor César', '400', 'Santana', 'São Paulo', 'SP', -23.5020, -46.6300, 1),
    ('Camila Clean ZN', 'camila@pertoja.com', '(11) 97200-6633', 'Faxina residencial caprichada e higienização de sofás.', 'Limpeza', 'Faxina residencial e higienização de sofás', 140.0, 4.9, '02518-000', 'Rua Casa Verde', '850', 'Casa Verde', 'São Paulo', 'SP', -23.5130, -46.6570, 1),
    ('Sergio Cores do Norte', 'sergio@pertoja.com', '(11) 97200-7744', 'Pintura residencial, fachadas e aplicação de grafiato.', 'Pintura', 'Pintura de fachadas e textura grafiato', 340.0, 4.6, '02167-000', 'Rua Curuçá', '600', 'Vila Maria', 'São Paulo', 'SP', -23.5120, -46.5950, 1),

    # --- ZONA SUL DE SÃO PAULO (5 prestadores) ---
    ('Marta Souza', 'marta@pertoja.com', '(11) 97222-3344', 'Especialista em faxina pesada e pós-obra.', 'Limpeza', 'Faxina pesada e higienização profunda', 170.0, 4.5, '04001-000', 'Rua Domingos de Morais', '500', 'Vila Mariana', 'São Paulo', 'SP', -23.5855, -46.6385, 1),
    ('Dona Flor', 'donaflor@pertoja.com', '(11) 97777-8899', 'Paisagista e especialista em corte, poda técnica e adubação.', 'Jardinagem', 'Jardinagem, poda e manutenção paisagística', 450.0, 5.0, '04538-133', 'Rua Bandeira Paulista', '700', 'Itaim Bibi', 'São Paulo', 'SP', -23.5840, -46.6780, 1),
    ('Eduardo Reparos Sul', 'eduardo@pertoja.com', '(11) 97300-1122', 'Instalação de spots LED, lustres e automação residencial.', 'Elétrica', 'Instalação de iluminação LED e tomadas inteligentes', 160.0, 4.7, '04523-010', 'Alameda dos Maracatins', '900', 'Moema', 'São Paulo', 'SP', -23.6060, -46.6620, 1),
    ('Renato Hidráulica Moema', 'renato@pertoja.com', '(11) 97300-2233', 'Instalação de duchas higiênicas, torneiras e pressurizadores.', 'Encanamento', 'Instalação de duchas, torneiras e pressurizadores', 180.0, 4.6, '04561-001', 'Rua Flórida', '1400', 'Brooklin', 'São Paulo', 'SP', -23.6090, -46.6910, 1),
    ('Claudio Móveis Planejados', 'claudio@pertoja.com', '(11) 97300-3344', 'Montagem, desmontagem e ajustes finos de armários embutidos.', 'Marcenaria', 'Montagem e ajuste de armários embutidos', 280.0, 4.8, '04743-000', 'Rua Doutor Antônio Bento', '650', 'Santo Amaro', 'São Paulo', 'SP', -23.6520, -46.7080, 1),

    # --- ZONA LESTE DE SÃO PAULO (5 prestadores) ---
    ('Nina Montagens', 'nina@pertoja.com', '(11) 97999-0011', 'Marcenaria fina, restauração de móveis e montagens de alta precisão.', 'Marcenaria', 'Marcenaria e montagem de móveis planejados', 260.0, 4.3, '03104-000', 'Rua da Mooca', '1500', 'Mooca', 'São Paulo', 'SP', -23.5535, -46.6020, 1),
    ('Rogério Eletro Leste', 'rogerio@pertoja.com', '(11) 97400-1155', 'Reforma de quadro de força e substituição de disjuntores.', 'Elétrica', 'Troca de fiação antiga e quadro elétrico', 200.0, 4.8, '03308-000', 'Rua Serra de Bragança', '850', 'Tatuapé', 'São Paulo', 'SP', -23.5390, -46.5740, 1),
    ('Priscila Brilho Total', 'priscila@pertoja.com', '(11) 97400-2266', 'Limpeza detalhada pré-mudança e pós-reforma.', 'Limpeza', 'Limpeza pós-obra e faxina comercial', 150.0, 4.7, '03332-000', 'Rua Emília Marengo', '400', 'Anália Franco', 'São Paulo', 'SP', -23.5550, -46.5680, 1),
    ('Tiago Desentupidora Penha', 'tiago@pertoja.com', '(11) 97400-3377', 'Localização eletrônica de vazamento e desentupimento com máquina.', 'Encanamento', 'Caça vazamento eletrônico e desentupimento de esgotos', 220.0, 4.5, '03634-000', 'Rua Betari', '300', 'Penha', 'São Paulo', 'SP', -23.5250, -46.5490, 1),
    ('Leandro Art Cobre', 'leandro@pertoja.com', '(11) 97400-4488', 'Pintura interna e externa, aplicação de massa corrida e látex.', 'Pintura', 'Pintura acrílica acetinada e esmalte sintético', 310.0, 4.9, '08210-040', 'Rua Américo Salvador Novelli', '250', 'Itaquera', 'São Paulo', 'SP', -23.5410, -46.4560, 1),

    # --- ZONA OESTE DE SÃO PAULO (5 prestadores) ---
    ('João Volts', 'joao@pertoja.com', '(11) 97333-4455', 'Eletricista certificado padrão industrial e residencial.', 'Elétrica', 'Reparo e manutenção de quadro elétrico', 210.0, 4.9, '05407-002', 'Rua Teodoro Sampaio', '1200', 'Pinheiros', 'São Paulo', 'SP', -23.5601, -46.6850, 1),
    ('Lia Cores', 'lia@pertoja.com', '(11) 97666-7788', 'Pintora profissional com acabamento premium para interiores.', 'Pintura', 'Pintura residencial e texturização de paredes', 380.0, 4.6, '05010-000', 'Rua Turiassu', '400', 'Perdizes', 'São Paulo', 'SP', -23.5320, -46.6710, 1),
    ('Vitor Green Garden', 'vitor@pertoja.com', '(11) 97500-1122', 'Implantação de jardins residenciais, verticais e poda de contenção.', 'Jardinagem', 'Corte de árvores autorizado e jardins verticais', 390.0, 4.8, '05435-000', 'Rua Fradique Coutinho', '1100', 'Vila Madalena', 'São Paulo', 'SP', -23.5580, -46.6930, 1),
    ('Bruno Redes & Tech', 'bruno@pertoja.com', '(11) 97500-2233', 'Montagem de rede Wi-Fi corporativa, roteadores e câmeras de segurança.', 'Tecnologia', 'Cabeamento estruturado e instalação de câmeras CFTV', 175.0, 4.7, '05075-000', 'Rua Doze de Outubro', '380', 'Lapa', 'São Paulo', 'SP', -23.5220, -46.7040, 1),
    ('Simone Limpeza Prime', 'simone@pertoja.com', '(11) 97500-3344', 'Higienização a seco de sofás, colchões, tapetes e vidraças.', 'Limpeza', 'Higienização de carpetes, estofados e vidros', 160.0, 4.9, '05501-000', 'Avenida Vital Brasil', '500', 'Butantã', 'São Paulo', 'SP', -23.5710, -46.7090, 1),

    # --- GUARULHOS (10 prestadores) ---
    ('Juliana Clean', 'juliana@pertoja.com', '(11) 97000-1122', 'Especialista em higienização e limpeza residencial em Guarulhos e região.', 'Limpeza', 'Limpeza e higienização residencial', 85.0, 4.9, '07141-430', 'Rua do Araújo', '150', 'Jardim Beirute', 'Guarulhos', 'SP', -23.4628, -46.5333, 1),
    ('Marcos Reparos', 'marcos@pertoja.com', '(11) 97000-3344', 'Eletricista residencial e predial com atendimento rápido em Guarulhos.', 'Elétrica', 'Instalação e reparos elétricos', 95.0, 4.7, '07010-010', 'Rua Dom Pedro II', '300', 'Centro', 'Guarulhos', 'SP', -23.4650, -46.5300, 1),
    ('Fabio Tintas', 'fabio@pertoja.com', '(11) 97000-5566', 'Pintura residencial fina, texturas e impermeabilização.', 'Pintura', 'Pintura residencial e texturização', 320.0, 4.8, '07055-000', 'Rua Treze de Maio', '450', 'Vila Galvão', 'Guarulhos', 'SP', -23.4560, -46.5450, 1),
    ('André Hidráulica Guarulhos', 'andre@pertoja.com', '(11) 97000-7788', 'Encanador 24h para emergências, desentupimentos e caça-vazamento.', 'Encanamento', 'Desentupimento rápido de pias e ralos', 190.0, 4.5, '07111-000', 'Avenida Tiradentes', '1200', 'Jardim Paraventi', 'Guarulhos', 'SP', -23.4540, -46.5210, 1),
    ('Fernanda Paisagismo Bosque', 'fernanda@pertoja.com', '(11) 97000-9900', 'Jardinagem ornamental, manutenção de vasos e podas de árvores.', 'Jardinagem', 'Manutenção de grama, plantas ornamentais e podas', 250.0, 4.9, '07115-000', 'Avenida Paulo Faccini', '1800', 'Macedo', 'Guarulhos', 'SP', -23.4600, -46.5160, 1),
    ('Rodrigo Móveis & Montagens', 'rodrigo@pertoja.com', '(11) 97000-1234', 'Montador profissional de móveis de magazines e planejados.', 'Marcenaria', 'Montagem de guarda-roupas, cozinhas e mesas', 210.0, 4.6, '07071-000', 'Rua Doutor Timóteo Penteado', '2200', 'Picanço', 'Guarulhos', 'SP', -23.4470, -46.5430, 1),
    ('Patricia Faxina & Cuidado', 'patricia@pertoja.com', '(11) 97000-2345', 'Diarista residencial de confiança com referências verificadas.', 'Limpeza', 'Diarista residencial e higienização completa', 130.0, 4.8, '07190-000', 'Rua Cônego Valadão', '800', 'Gopoúva', 'Guarulhos', 'SP', -23.4750, -46.5400, 1),
    ('Guilherme Soluções TI', 'guilherme@pertoja.com', '(11) 97000-3456', 'Configuração de redes, roteadores Wi-Fi mesh, formatação e backup.', 'Tecnologia', 'Instalação de roteadores mesh e reparo de PCs', 120.0, 4.7, '07170-350', 'Avenida Santos Dumont', '1500', 'Cumbica', 'Guarulhos', 'SP', -23.4510, -46.4680, 1),
    ('Lucas Eletricista Taboão', 'lucas@pertoja.com', '(11) 97000-4567', 'Instalação de chuveiros, troca de disjuntores e padrão Enel.', 'Elétrica', 'Padrão de entrada Enel e curto-circuito', 170.0, 4.4, '07140-010', 'Avenida Silvestre Pires de Freitas', '900', 'Taboão', 'Guarulhos', 'SP', -23.4310, -46.5020, 1),
    ('Marcelo Pinturas Aeroporto', 'marcelo@pertoja.com', '(11) 97000-5678', 'Pinturas residenciais e comerciais com acabamento liso e sem sujeira.', 'Pintura', 'Pintura predial, residencial e verniz de madeira', 350.0, 4.7, '07143-000', 'Estrada dos Morros', '450', 'Jardim Santa Emília', 'Guarulhos', 'SP', -23.4280, -46.4950, 1)
]

def sincronizar_todos_prestadores(conn):
    cursor = conn.cursor()
    pwd_hash = generate_password_hash('123456')

    for nome, email, tel, bio, cat, s_titulo, preco, rating, cep, end, num, bairro, cid, uf, lat, lng, disp in PRESTADORES_SEED_35:
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            cursor.execute('''
                INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng, avaliacao_media, total_avaliacoes, disponivel)
                VALUES (?, ?, ?, 'prestador', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 15, ?)
            ''', (nome, email, pwd_hash, tel, bio, cep, end, num, bairro, cid, uf, lat, lng, rating, disp))
            p_id = cursor.lastrowid
            cursor.execute('''
                INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (p_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng))
        else:
            # Preserva edições feitas pelo prestador (localização, preço, etc.).
            # Apenas garante que exista ao menos um serviço para o prestador de exemplo.
            p_id = row['id']
            has_service = cursor.execute("SELECT 1 FROM services WHERE prestador_id = ? LIMIT 1", (p_id,)).fetchone()
            if not has_service:
                cursor.execute('''
                    INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ''', (p_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng))

        # Pre-seed de cache de geocodificação para resiliência contra rate-limit do Nominatim
        cache_keys = [
            f"{end}, {bairro}, {cid} - {uf}".lower(),
            f"{end}, {bairro}, {cid} - {uf}, brasil".lower(),
            f"{end}, {cid} - {uf}, brasil".lower(),
            f"{end} {num}, {bairro}, {cid} - {uf}, brasil".lower(),
            f"{end} {num} {cid}".lower(),
            f"{bairro}, {cid} - {uf}, brasil".lower(),
        ]
        for ck in cache_keys:
            cursor.execute('''
                INSERT OR IGNORE INTO geocode_cache (query, lat, lng, origem)
                VALUES (?, ?, ?, 'seed')
            ''', (ck, lat, lng))

    # Entradas adicionais sem acento usadas em buscas rápidas
    extra_cache = [
        ('avenida paulista 1000 sao paulo', -23.5653, -46.6517),
        ('rua doutor olavo egidio, santana, sao paulo - sp', -23.5029, -46.6258),
        ('rua dr. olavo egídio, santana, são paulo - sp', -23.5029, -46.6258),
        ('rua doutor olavo egídio, santana, são paulo - sp', -23.5029, -46.6258),
    ]
    for q_str, c_lat, c_lng in extra_cache:
        cursor.execute('''
            INSERT OR IGNORE INTO geocode_cache (query, lat, lng, origem)
            VALUES (?, ?, ?, 'seed')
        ''', (q_str, c_lat, c_lng))

    conn.commit()

def get_cached_geocode(query):
    """Recupera coordenadas em cache para uma consulta de endereço."""
    if not query or not query.strip():
        return None
    normalized = query.strip().lower()
    try:
        conn = get_db_connection()
        row = conn.execute('SELECT lat, lng FROM geocode_cache WHERE query = ?', (normalized,)).fetchone()
        conn.close()
        if row:
            return float(row['lat']), float(row['lng'])
    except Exception:
        pass
    return None

def save_cached_geocode(query, lat, lng, origem='nominatim'):
    """Salva coordenadas em cache para consultas futuras."""
    if not query or lat is None or lng is None:
        return
    normalized = query.strip().lower()
    try:
        conn = get_db_connection()
        conn.execute('''
            INSERT OR REPLACE INTO geocode_cache (query, lat, lng, origem, criado_em)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (normalized, float(lat), float(lng), origem))
        conn.commit()
        conn.close()
    except Exception:
        pass

if __name__ == '__main__':
    init_db()
    print("Banco de dados SQLite inicializado e atualizado com endereços reais!")
