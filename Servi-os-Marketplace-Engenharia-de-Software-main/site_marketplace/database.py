import sqlite3
import os
from werkzeug.security import generate_password_hash

# Suporte ao ambiente Vercel (onde apenas /tmp é gravável) ou ambiente local/testes
if os.environ.get('VERCEL') == '1':
    DB_PATH = '/tmp/marketplace.db'
elif 'MARKETPLACE_DB' in os.environ:
    DB_PATH = os.environ['MARKETPLACE_DB']
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'marketplace.db')

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

    # Seed inicial se tabela users estiver vazia
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        seed_data(conn)
    else:
        # Atualiza endereços dos usuários seed que possam estar vazios
        atualizar_enderecos_existentes(conn)

    conn.close()

def atualizar_enderecos_existentes(conn):
    cursor = conn.cursor()
    # Verifica se o prestador Carlos Mendes já tem CEP cadastrado
    cursor.execute("SELECT id, cep FROM users WHERE email = 'carlos@pertoja.com'")
    row = cursor.fetchone()
    if row and not row['cep']:
        enderecos_reais = {
            'carlos@pertoja.com': ('01310-100', 'Avenida Paulista', '1000', 'Bela Vista', 'São Paulo', 'SP', -23.5653, -46.6517),
            'marta@pertoja.com': ('04001-000', 'Rua Domingos de Morais', '500', 'Vila Mariana', 'São Paulo', 'SP', -23.5855, -46.6385),
            'joao@pertoja.com': ('05407-002', 'Rua Teodoro Sampaio', '1200', 'Pinheiros', 'São Paulo', 'SP', -23.5601, -46.6850),
            'rafa@pertoja.com': ('01414-001', 'Rua Haddock Lobo', '800', 'Cerqueira César', 'São Paulo', 'SP', -23.5570, -46.6640),
            'beto@pertoja.com': ('02011-000', 'Rua Voluntários da Pátria', '1500', 'Santana', 'São Paulo', 'SP', -23.5042, -46.6262),
            'lia@pertoja.com': ('05010-000', 'Rua Turiassu', '400', 'Perdizes', 'São Paulo', 'SP', -23.5320, -46.6710),
            'donaflor@pertoja.com': ('04538-133', 'Rua Bandeira Paulista', '700', 'Itaim Bibi', 'São Paulo', 'SP', -23.5840, -46.6780),
            'teo@pertoja.com': ('01228-000', 'Rua da Consolação', '2400', 'Consolação', 'São Paulo', 'SP', -23.5550, -46.6600),
            'nina@pertoja.com': ('03104-000', 'Rua da Mooca', '1500', 'Mooca', 'São Paulo', 'SP', -23.5535, -46.6020),
            'cliente@pertoja.com': ('01402-000', 'Alameda Santos', '800', 'Cerqueira César', 'São Paulo', 'SP', -23.5680, -46.6530)
        }
        for email, (cep, end, num, bairro, cid, uf, lat, lng) in enderecos_reais.items():
            cursor.execute('''
                UPDATE users
                SET cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?
                WHERE email = ?
            ''', (cep, end, num, bairro, cid, uf, lat, lng, email))

            # Atualiza também nos serviços desse prestador
            cursor.execute('''
                UPDATE services
                SET cep = ?, endereco = ?, numero = ?, bairro = ?, cidade = ?, estado = ?, lat = ?, lng = ?
                WHERE prestador_id = (SELECT id FROM users WHERE email = ?)
            ''', (cep, end, num, bairro, cid, uf, lat, lng, email))
        conn.commit()

    # Verifica se os prestadores de Guarulhos já existem na base; caso contrário, insere-os
    cursor.execute("SELECT id FROM users WHERE email = 'juliana@pertoja.com'")
    if not cursor.fetchone():
        pwd_hash = generate_password_hash('123456')
        guarulhos_prestadores = [
            ('Juliana Clean', 'juliana@pertoja.com', '(11) 97000-1122', 'Especialista em higienização e limpeza residencial em Guarulhos e região.', 'Limpeza', 'Limpeza e higienização residencial', 85.0, 4.9, '07141-430', 'Rua do Araújo', '150', 'Jardim Beirute', 'Guarulhos', 'SP', -23.4628, -46.5333, 1),
            ('Marcos Reparos', 'marcos@pertoja.com', '(11) 97000-3344', 'Eletricista residencial e predial com atendimento rápido em Guarulhos.', 'Elétrica', 'Instalação e reparos elétricos', 95.0, 4.7, '07010-010', 'Rua Dom Pedro II', '300', 'Centro', 'Guarulhos', 'SP', -23.4650, -46.5300, 1),
            ('Fabio Tintas', 'fabio@pertoja.com', '(11) 97000-5566', 'Pintura residencial fina, texturas e impermeabilização.', 'Pintura', 'Pintura residencial e texturização', 320.0, 4.8, '07055-000', 'Rua Treze de Maio', '450', 'Vila Galvão', 'Guarulhos', 'SP', -23.4560, -46.5450, 1)
        ]
        for nome, email, tel, bio, cat, s_titulo, preco, rating, cep, end, num, bairro, cid, uf, lat, lng, disp in guarulhos_prestadores:
            cursor.execute('''
                INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng, avaliacao_media, total_avaliacoes, disponivel)
                VALUES (?, ?, ?, 'prestador', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 12, ?)
            ''', (nome, email, pwd_hash, tel, bio, cep, end, num, bairro, cid, uf, lat, lng, rating, disp))
            p_id = cursor.lastrowid
            cursor.execute('''
                INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (p_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng))
        conn.commit()

def seed_data(conn):
    cursor = conn.cursor()
    pwd_hash = generate_password_hash('123456')

    # Cliente de exemplo com endereço real na Alameda Santos, SP
    cursor.execute('''
        INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng)
        VALUES (?, ?, ?, 'cliente', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        'Ana Paula Silva', 'cliente@pertoja.com', pwd_hash, '(11) 98765-4321',
        'Cliente residencial em busca de serviços locais de alta qualidade.',
        '01402-000', 'Alameda Santos', '800', 'Cerqueira César', 'São Paulo', 'SP',
        -23.5680, -46.6530
    ))

    prestadores_seed = [
        ('Carlos Mendes', 'carlos@pertoja.com', '(11) 97111-2233', 'Limpeza residencial e comercial com 8 anos de experiência.', 'Limpeza', 'Limpeza residencial completa', 80.0, 4.8, '01310-100', 'Avenida Paulista', '1000', 'Bela Vista', 'São Paulo', 'SP', -23.5653, -46.6517, 1),
        ('Marta Souza', 'marta@pertoja.com', '(11) 97222-3344', 'Especialista em faxina pesada e pós-obra.', 'Limpeza', 'Faxina pesada e higienização profunda', 170.0, 4.5, '04001-000', 'Rua Domingos de Morais', '500', 'Vila Mariana', 'São Paulo', 'SP', -23.5855, -46.6385, 1),
        ('João Volts', 'joao@pertoja.com', '(11) 97333-4455', 'Eletricista certificado padrão industrial e residencial.', 'Elétrica', 'Reparo e manutenção de quadro elétrico', 210.0, 4.9, '05407-002', 'Rua Teodoro Sampaio', '1200', 'Pinheiros', 'São Paulo', 'SP', -23.5601, -46.6850, 1),
        ('Rafa Instalações', 'rafa@pertoja.com', '(11) 97444-5566', 'Instalação ágil de chuveiros, tomadas e luminárias.', 'Elétrica', 'Troca de chuveiro e tomadas elétricas', 90.0, 4.2, '01414-001', 'Rua Haddock Lobo', '800', 'Cerqueira César', 'São Paulo', 'SP', -23.5570, -46.6640, 1),
        ('Beto Hidráulica', 'beto@pertoja.com', '(11) 97555-6677', 'Encanador especialista em caça-vazamentos e desentupimentos.', 'Encanamento', 'Conserto de vazamentos e desentupimento', 240.0, 4.7, '02011-000', 'Rua Voluntários da Pátria', '1500', 'Santana', 'São Paulo', 'SP', -23.5042, -46.6262, 1),
        ('Lia Cores', 'lia@pertoja.com', '(11) 97666-7788', 'Pintora profissional com acabamento premium para interiores.', 'Pintura', 'Pintura residencial e texturização de paredes', 380.0, 4.6, '05010-000', 'Rua Turiassu', '400', 'Perdizes', 'São Paulo', 'SP', -23.5320, -46.6710, 1),
        ('Dona Flor', 'donaflor@pertoja.com', '(11) 97777-8899', 'Paisagista e especialista em corte, poda técnica e adubação.', 'Jardinagem', 'Jardinagem, poda e manutenção paisagística', 450.0, 5.0, '04538-133', 'Rua Bandeira Paulista', '700', 'Itaim Bibi', 'São Paulo', 'SP', -23.5840, -46.6780, 1),
        ('Téo Suporte', 'teo@pertoja.com', '(11) 97888-9900', 'Técnico em informática e redes residenciais.', 'Tecnologia', 'Suporte técnico de computadores e redes Wi-Fi', 110.0, 4.4, '01228-000', 'Rua da Consolação', '2400', 'Consolação', 'São Paulo', 'SP', -23.5550, -46.6600, 0),
        ('Nina Montagens', 'nina@pertoja.com', '(11) 97999-0011', 'Marcenaria fina, restauração de móveis e montagens de alta precisão.', 'Marcenaria', 'Marcenaria e montagem de móveis planejados', 260.0, 4.3, '03104-000', 'Rua da Mooca', '1500', 'Mooca', 'São Paulo', 'SP', -23.5535, -46.6020, 1),
        ('Juliana Clean', 'juliana@pertoja.com', '(11) 97000-1122', 'Especialista em higienização e limpeza residencial em Guarulhos e região.', 'Limpeza', 'Limpeza e higienização residencial', 85.0, 4.9, '07141-430', 'Rua do Araújo', '150', 'Jardim Beirute', 'Guarulhos', 'SP', -23.4628, -46.5333, 1),
        ('Marcos Reparos', 'marcos@pertoja.com', '(11) 97000-3344', 'Eletricista residencial e predial com atendimento rápido em Guarulhos.', 'Elétrica', 'Instalação e reparos elétricos', 95.0, 4.7, '07010-010', 'Rua Dom Pedro II', '300', 'Centro', 'Guarulhos', 'SP', -23.4650, -46.5300, 1),
        ('Fabio Tintas', 'fabio@pertoja.com', '(11) 97000-5566', 'Pintura residencial fina, texturas e impermeabilização.', 'Pintura', 'Pintura residencial e texturização', 320.0, 4.8, '07055-000', 'Rua Treze de Maio', '450', 'Vila Galvão', 'Guarulhos', 'SP', -23.4560, -46.5450, 1)
    ]

    for nome, email, tel, bio, cat, s_titulo, preco, rating, cep, end, num, bairro, cid, uf, lat, lng, disp in prestadores_seed:
        cursor.execute('''
            INSERT INTO users (nome, email, senha_hash, tipo, telefone, bio, cep, endereco, numero, bairro, cidade, estado, lat, lng, avaliacao_media, total_avaliacoes, disponivel)
            VALUES (?, ?, ?, 'prestador', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 15, ?)
        ''', (nome, email, pwd_hash, tel, bio, cep, end, num, bairro, cid, uf, lat, lng, rating, disp))
        prestador_id = cursor.lastrowid

        cursor.execute('''
            INSERT INTO services (prestador_id, titulo, descricao, categoria, preco, cep, endereco, numero, bairro, cidade, estado, lat, lng, ativo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (prestador_id, s_titulo, bio, cat, preco, cep, end, num, bairro, cid, uf, lat, lng))

    conn.commit()

if __name__ == '__main__':
    init_db()
    print("Banco de dados SQLite inicializado e atualizado com endereços reais!")
