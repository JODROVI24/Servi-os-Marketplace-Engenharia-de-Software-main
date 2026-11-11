# PertoJá – Marketplace de Serviços Locais Profissionais

Plataforma web completa desenvolvida para conectar clientes a profissionais e prestadores de serviços qualificados locais, com suporte a geolocalização em tempo real, rastreamento dinâmico, portais dedicados de autoatendimento e persistência com backend em Python Flask e banco de dados SQLite.

---

## 🚀 Como Executar o Projeto

### Pré-requisitos
* Python 3.10 ou superior (com `Flask` e `Pillow` instalados).

### Passo a Passo
1. No terminal, na raiz do projeto, execute o comando:
   ```bash
   python app.py
   ```
2. Abra o seu navegador e acesse:
   ```
   http://localhost:5000
   ```

---

## 👥 Portais e Funcionalidades

### 🛠️ Portal do Prestador de Serviços (`/portal-prestador.html`)
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

### 👤 Portal do Cliente (`/portal-cliente.html`)
* **Meus Dados Cadastrais:**
  * Edição de nome completo, telefone e observações de endereço/referência.
* **Histórico de Pedidos:**
  * Acompanhamento de todas as ordens solicitadas com dados do prestador e status em tempo real.
  * Atalho direto para monitorar a chegada do profissional no mapa interativo.

### 🗺️ Busca e Monitoramento no Mapa (`/pedido.html`)
* Filtros dinâmicos por categoria (Limpeza, Elétrica, Encanamento, Pintura, Jardinagem, Tecnologia e Marcenaria).
* Slider de raio de busca de 1 a 15 km com ajuste automático de zoom.
* Cálculo inteligente de pontuação (*Score*) ponderando proximidade, avaliação média e disponibilidade.
* Animação do prestador em trânsito com simulação de rede e modo de economia de bateria.

---

## 🔑 Credenciais de Demonstração (Seed Inicial)

O banco de dados SQLite (`marketplace.db`) já é inicializado automaticamente com os prestadores e serviços de exemplo:

| Perfil | E-mail | Senha Padrão | Especialidade |
| :--- | :--- | :--- | :--- |
| **Prestador** | `carlos@pertoja.com` | `123456` | Limpeza Residencial |
| **Prestador** | `joao@pertoja.com` | `123456` | Elétrica e Instalações |
| **Prestador** | `nina@pertoja.com` | `123456` | Marcenaria e Montagens |
| **Cliente** | `cliente@pertoja.com` | `123456` | Conta de Cliente |

*Você também pode criar novas contas a qualquer momento pela tela de [Cadastro](http://localhost:5000/cadastro.html).*

---

## 🧪 Testes Automatizados

A aplicação conta com uma suíte de testes de integração cobrindo fluxos de autenticação, permissões de acesso, CRUD de serviços e preços, atualização de perfil e pedidos.

Para executar os testes:
```bash
python .\Servi-os-Marketplace-Engenharia-de-Software-main\site_marketplace\test_app.py
```

---

## 🌐 Como Colocar o Site no Ar na Vercel

O projeto já está 100% configurado para deploy imediato na **Vercel** através de Serverless Functions Python (`@vercel/python`) com suporte a arquivos estáticos e banco SQLite em `/tmp`.

### Método 1: Deploy Rápido via GitHub (Recomendado)
1. **Suba este projeto para um repositório no seu GitHub**:
   - Crie um novo repositório no [GitHub](https://github.com/new).
   - Envie todos os arquivos do projeto (incluindo `vercel.json`, `api/index.py` e `requirements.txt`).
2. **Conecte à Vercel**:
   - Acesse [vercel.com](https://vercel.com) e faça login.
   - Clique em **"Add New..."** > **"Project"**.
   - Selecione o repositório que você acabou de subir no GitHub.
3. **Configuração de Variáveis de Ambiente (Opcional)**:
   - Em *Environment Variables*, você pode adicionar:
     - `SECRET_KEY`: Uma chave segura aleatória para encriptar as sessões dos usuários.
4. **Clique em "Deploy"**:
   - A Vercel construirá automaticamente a aplicação e gerará uma URL pública gratuita (ex: `https://meu-pertoja.vercel.app`).

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

> **💡 Nota sobre Persistência em Serverless:**  
> Por padrão na Vercel, o banco SQLite é alocado no diretório transitório `/tmp/marketplace.db`, gerando os dados de demonstração automaticamente. Para persistência permanente de produção mesmo após instâncias serverless recicladas, basta definir a variável de ambiente `DATABASE_URL` conectada a um PostgreSQL gratuito do **Neon** (`https://neon.tech`) ou **Supabase**.

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

1. **Correção de Falhas Críticas:**
   * Blindagem da inicialização do Leaflet no `script.js` para não quebrar em páginas sem mapa (como a home `index.html`).
   * Correção de seletores DOM que quebravam o script no `pedido.html`.
   * Alinhamento da categoria `Marcenaria` entre frontend e dados.
   * Correção da semântica HTML (tags `<footer>` movidas para dentro de `<body>`).
2. **Otimização de Performance:**
   * Compressão das imagens da pasta `img/` (redução de **13.5 MB para ~388 KB**, economia de >97% de largura de banda).
   * Remoção de bibliotecas externas pesadas em páginas que não as utilizam.
3. **Arquitetura & Segurança:**
   * Backend RESTful com Flask 3.1 e SQLite 3.
   * Criptografia de senhas com `Werkzeug.security` (`pbkdf2:sha256`).
   * Sessões HTTP seguras com controle de permissão (ex: clientes impedidos de alterar preços de prestadores).
