# PertoJá – Marketplace de Serviços Locais Profissionais

Plataforma web completa desenvolvida para conectar clientes a profissionais e prestadores de serviços qualificados locais, com suporte a geolocalização em tempo real, rastreamento dinâmico, portais dedicados de autoatendimento e persistência com backend em Python Flask utilizando **PostgreSQL obrigatório em produção** (Neon / Supabase) e **SQLite apenas para desenvolvimento local e testes**.

---

## 🚀 Como Executar o Projeto

### Pré-requisitos
* **Python 3.11 ou superior** (dependências declaradas em `pyproject.toml` e travadas em `uv.lock` / `requirements*.txt`).
* **Node.js 20 ou superior** (utilizado para compilar o Tailwind CSS local em `public/dist/app.css` e rodar lint/testes JS).

### Passo a Passo
1. **Instalar dependências**:
   ```bash
   # Python (com uv ou pip)
   pip install -r requirements-dev.txt
   # ou: uv sync --frozen --extra dev

   # Node.js (CSS Tailwind + lint/testes frontend)
   npm ci
   npm run build
   ```
2. **Configurar variáveis de ambiente**:
   Copie o arquivo `.env.example` para `.env` na raiz do projeto e ajuste os valores para o seu ambiente local (nunca faça commit do `.env` real):
   ```env
   SECRET_KEY=exemplo_chave_secreta_gerada_com_secrets_token_hex
   MARKETPLACE_DB=marketplace.db
   # Opcional em dev (obrigatório em produção):
   # DATABASE_URL=postgresql://usuario:senha@ep-exemplo.us-east-1.aws.neon.tech/neondb?sslmode=require
   ```
   Para gerar uma `SECRET_KEY` forte (mínimo de 32 caracteres):
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **Executar localmente**:
   ```bash
   python app.py
   ```
4. Abra o seu navegador e acesse:
   ```
   http://localhost:5000
   ```

---

## ⚙️ Variáveis de Ambiente

| Variável | Categoria | Obrigatória em Produção | Descrição |
| :--- | :--- | :---: | :--- |
| `SECRET_KEY` | Segurança | **Sim** | Chave de assinatura das sessões Flask (**mínimo 32 caracteres**). A aplicação recusa iniciar em produção se ausente ou fraca. |
| `DATABASE_URL` / `POSTGRES_URL` / `POSTGRES_URL_NON_POOLING` | Banco de Dados | **Sim** | URI PostgreSQL (Neon/Supabase). Em produção (`VERCEL=1` ou `FLASK_ENV=production`), o fallback para SQLite é bloqueado. |
| `FLASK_ENV` | Runtime | Recomendada | Define `production` em produção para ativar guardrails de banco, `SECRET_KEY` e cookies seguros. |
| `ENABLE_DEMO_SEED` | Segurança / Dev | Não (`0` padrão) | Popula usuários/serviços demo apenas localmente (`1`). **Proibido em produção**. |
| `MARKETPLACE_DB` | Banco Local | Não | Caminho do SQLite em desenvolvimento/testes (`marketplace.db` padrão; ignorado/bloqueado em produção). |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` (ou `KV_REST_API_*`) | Rate Limiting | Recomendada | Backend distribuído Redis REST para rate limit sem queries no Postgres (fallback automático em memória em dev). |
| `PAYMENT_RETURN_BASE_URL` | Pagamentos | Não | URL pública base usada para retornos de checkout e webhooks HTTPS. |
| `MERCADOPAGO_ACCESS_TOKEN` / `MERCADOPAGO_PUBLIC_KEY` / `MERCADOPAGO_WEBHOOK_SECRET` | Pagamentos | Não | Credenciais do adaptador Mercado Pago (PIX, Cartão e Boleto). |
| `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` / `STRIPE_WEBHOOK_SECRET` | Pagamentos | Não | Credenciais do adaptador Stripe. |
| `PAGSEGURO_TOKEN` / `PAGSEGURO_WEBHOOK_SECRET` | Pagamentos | Não | Credenciais do adaptador PagSeguro. |
| `ENABLE_PAYMENT_SANDBOX` | Pagamentos | Não | Habilita gateway simulado (`1` em dev por padrão; `0` em produção). |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `LLM_MODEL` | LLM / Chat | Não | Chaves opcionais para provedores cloud de IA (com failover e FAQ offline local). |

---

## 👥 Portais e Funcionalidades

### 🛠️ Portal do Prestador de Serviços (`/portal-prestador`)
* **Gestão de Serviços e Preços:**
  * Cadastro de novos serviços com título, descrição, categoria e preço.
  * **Alteração de preços em tempo real** (com formatação monetária R$).
  * Pausar ou reativar serviços conforme conveniência.
  * Exclusão de serviços do catálogo.
* **Disponibilidade no Mapa:**
  * Alternador de status (Disponível / Indisponível) com reflexo imediato no mapa de busca dos clientes.
* **Gestão de Chamados Recebidos:**
  * Visualização de solicitações enviadas pelos clientes.
  * Atualização de status da ordem (*Confirmar Atendimento*, *A Caminho*, *Em Execução*, *Finalizado*).
* **Edição de Perfil:**
  * Alteração de nome, telefone/WhatsApp, biografia profissional e coordenadas GPS base.

### 👤 Portal do Cliente (`/portal-cliente`)
* **Meus Dados Cadastrais:**
  * Edição de nome completo, telefone e observações de endereço/referência.
* **Histórico de Pedidos:**
  * Acompanhamento de todas as ordens solicitadas com dados do prestador e status em tempo real.
  * Atalho direto para monitorar a chegada do profissional no mapa interativo.

### 🗺️ Busca e Monitoramento no Mapa (`/pedido`)
* Filtros dinâmicos por categoria (Limpeza, Elétrica, Encanamento, Pintura, Jardinagem, Tecnologia e Marcenaria).
* Slider de raio de busca de 1 a 15 km com ajuste automático de zoom.
* Cálculo inteligente de pontuação (*Score*) ponderando proximidade, avaliação média e disponibilidade.
* Acompanhamento de trajeto e atualização de status do atendimento.

---

## 🔑 Credenciais de Demonstração (Somente Ambiente Local)

Por segurança, o seed de contas de demonstração vem **desabilitado por padrão (`ENABLE_DEMO_SEED=0`)** e é **estritamente proibido em produção (`VERCEL=1` ou `FLASK_ENV=production`)**.

Para popular contas de exemplo **apenas no seu ambiente local de desenvolvimento**, defina `ENABLE_DEMO_SEED=1` no seu `.env` local antes de inicializar o banco (novas contas cadastradas pela interface/API exigem política de senha forte com mínimo de **10 caracteres** e checagem k-anonymity contra senhas vazadas no HIBP):

| Perfil | E-mail (somente local) | Senha Local | Especialidade |
| :--- | :--- | :--- | :--- |
| **Prestador** | `carlos@pertoja.com` | `123456` | Limpeza Residencial |
| **Prestador** | `joao@pertoja.com` | `123456` | Elétrica e Instalações |
| **Prestador** | `nina@pertoja.com` | `123456` | Marcenaria e Montagens |
| **Cliente** | `cliente@pertoja.com` | `123456` | Conta de Cliente |

*Você também pode criar novas contas a qualquer momento pela tela de [Cadastro](http://localhost:5000/cadastro).*

---

## 🧪 Testes Automatizados, Qualidade e Segurança (CI Local)

A aplicação conta com suíte de testes de integração, unitários, adversariais WSGI/Vercel, lint estático e auditorias de vulnerabilidades executados automaticamente no GitHub Actions (`.github/workflows/ci.yml`):

```bash
# Lint e checagem de formatação Python
ruff check .
ruff format --check .

# Suíte de testes Python (unittest) e cobertura mínima de 80% (pytest-cov)
python -m unittest discover -s tests -v
pytest --cov --cov-fail-under=80

# Build de CSS, lint anti-XSS + ESLint e testes de roteamento Vercel
npm run build
npm run lint:js
npm run test:routing

# Auditorias de segurança das dependências
pip-audit -r requirements.txt
npm audit --audit-level=moderate
```

Para executar migrations do banco manualmente ou simular (`--dry-run`):
```bash
python -m scripts.migrate --dry-run
python -m scripts.migrate
```

---

## 🌐 Como Colocar o Site no Ar na Vercel

O projeto está configurado para deploy na **Vercel** através de Serverless Functions Python (`@vercel/python`) com persistência obrigatória em **PostgreSQL** (Neon ou Supabase).

### Método 1: Deploy Rápido via GitHub (Recomendado)
1. **Suba este projeto para um repositório no seu GitHub**:
   - Envie todos os arquivos do projeto (incluindo `vercel.json`, `api/index.py`, `pyproject.toml`, `uv.lock` e `requirements.txt`).
2. **Conecte à Vercel**:
   - Acesse [vercel.com](https://vercel.com) e faça login.
   - Clique em **"Add New..."** > **"Project"** e importe o repositório.
3. **Configuração Obrigatória de Variáveis de Ambiente (Produção/Preview)**:
   Em **Settings > Environment Variables**, configure obrigatoriamente:
   - `SECRET_KEY`: chave aleatória forte com **no mínimo 32 caracteres** (`python -c "import secrets; print(secrets.token_hex(32))"`). A aplicação recusa iniciar em produção se ausente ou menor que 32 caracteres.
   - `DATABASE_URL` (ou `POSTGRES_URL` / `POSTGRES_URL_NON_POOLING` injetada pela integração Neon/Vercel Postgres): string de conexão PostgreSQL. **Em produção (`VERCEL=1` ou `FLASK_ENV=production`), o fallback para SQLite `/tmp` é bloqueado** e a aplicação falha ao iniciar se não houver PostgreSQL configurado.
   - `ENABLE_DEMO_SEED=0`: mantém contas de demonstração desativadas (em produção, o seed também é bloqueado no código).
4. **Configurando PostgreSQL no Neon ou Supabase**:
   - **Neon (via Vercel Storage/Marketplace ou [neon.tech](https://neon.tech)):**
     1. Crie um banco Postgres (ex.: integração **Neon** direto no projeto da Vercel) para injetar `DATABASE_URL` e `POSTGRES_URL` nos ambientes **Production** e **Preview**.
     2. Para aplicar schema e migrations manualmente antes do tráfego, exporte `DATABASE_URL` com `?sslmode=require` e execute:
        ```bash
        python -m scripts.migrate --dry-run
        python -m scripts.migrate
        ```
   - **Supabase (opcional para dev ou Postgres gerenciado):**
     1. Copie a URI do **Session Pooler (IPv4)** (`aws-0-<regiao>.pooler.supabase.com:5432`) com `?sslmode=require` para compatibilidade IPv4/serverless.
     2. Defina `DATABASE_URL` no `.env` (dev) ou na Vercel e rode `python -m scripts.migrate`.
   - Ao subir na Vercel, `GET /api/health` deve retornar `"database": "connected"` e `"engine": "postgresql"`, preservando dados entre redeploys.
5. **Clique em "Deploy"**:
   - A Vercel executará `npm run build`, publicará `public/` e empacotará `api/index.py` com as dependências e arquivos de runtime configurados em `vercel.json`.

### Método 2: Deploy via Vercel CLI (Terminal)
Se tiver o Node.js e o Vercel CLI instalados:
```bash
# Instala o CLI globalmente
npm i -g vercel

# Na raiz do projeto, faz login e deploy
vercel login
vercel

# Para promover diretamente para produção:
vercel --prod
```

> **💡 Nota sobre Persistência e Rate Limiting em Serverless:**  
> Em desenvolvimento local e testes automatizados, o sistema usa SQLite (`marketplace.db`) quando `DATABASE_URL` não está definida. Em produção (`VERCEL=1` ou `FLASK_ENV=production`), PostgreSQL via `DATABASE_URL` / `POSTGRES_URL` (**Neon** ou **Supabase**) é **obrigatório** para garantir integridade e sobrevivência dos dados entre instâncias recicladas e redeploys.  
> O rate limiting da API utiliza **Upstash Redis REST** (`UPSTASH_REDIS_REST_URL` e `UPSTASH_REDIS_REST_TOKEN`, ou `KV_REST_API_URL` e `KV_REST_API_TOKEN` via Vercel KV) com fallback automático em memória (`InMemoryRateLimiter`), eliminando queries SQL `DELETE/SELECT/INSERT` por requisição no banco relacional; em produção de alto tráfego, recomenda-se complementar com WAF/proxy de borda (como **Vercel Firewall**, **Cloudflare** ou **Akamai**).

---

## 📍 Funcionalidades de Endereço Real & Geolocalização (Vida Real)

1. **Auto-preenchimento por CEP (ViaCEP):**
   * Ao digitar o CEP em qualquer formulário (cadastro, portal do prestador ou portal do cliente), a aplicação consulta a API oficial do ViaCEP e preenche automaticamente Logradouro, Bairro, Cidade e UF.
2. **Geocodificação Automática (OpenStreetMap Nominatim):**
   * Converte instantaneamente o endereço em coordenadas precisas de latitude e longitude sem custos de API.
3. **Localização por GPS:**
   * Botão *"Usar GPS Atual"* que utiliza a API de geolocalização do navegador para posicionamento instantâneo.
4. **Exibição do Endereço Real:**
   * Os anúncios dos prestadores exibem o endereço legível (ex: *Avenida Paulista, 1000 · Bela Vista · São Paulo - SP*).
   * O mapa interativo do Leaflet mostra o marcador na posição exata do profissional.
   * Os pedidos recebidos pelo prestador informam o endereço e ponto de referência exatos onde o cliente solicitou o atendimento.

---

## 🛡️ Arquitetura, Performance e Melhorias Implementadas

1. **Correção de Falhas Críticas:**
   * Blindagem da inicialização do Leaflet no `script.js` para não quebrar em páginas sem mapa (como a home `index.html`).
   * Correção de seletores DOM que quebravam o script no `pedido.html`.
   * Alinhamento da categoria `Marcenaria` entre frontend e dados.
   * Correção da semântica HTML (tags `<footer>` movidas para dentro de `<body>`).
2. **Otimização de Performance:**
   * Migração do Tailwind CSS de CDN para build local minificado (`public/dist/app.css`).
   * Imagens otimizadas em WebP com fallback JPG (`<picture>`), dimensões explícitas e `fetchpriority="high"` no hero.
   * Rate limiting em Upstash Redis REST (sem `DELETE` em banco por requisição).
3. **Arquitetura & Segurança:**
   * Backend RESTful com Flask 3, **PostgreSQL obrigatório em produção** e SQLite local para desenvolvimento/testes.
   * `SECRET_KEY` forte obrigatória em produção, política de senha (10+ caracteres + HIBP k-anonymity), proteção CSRF (`Origin`/`Referer` + double-submit cookie), CSP rígida sem `'unsafe-inline'` em `script-src` e auditoria XSS estática (`check_xss_lint.js` + ESLint `no-unsanitized`).
   * Criptografia de senhas com `Werkzeug.security` (`pbkdf2:sha256`) e sessões HTTP seguras com `session_version` e controle de permissão por perfil.
