# Linha de Base (Baseline) – PertoJá Marketplace (Fase 0)

- **Data/Hora da coleta:** 2026-11-19 (horário local `-03:00`)
- **Branch de trabalho:** `melhorias`
- **Commit base (`main`):** `8bf633f` (`8bf633fd6e3e8a908c0fee02c23dede195a3a85e`)
- **URL de produção (Vercel):** `https://servi-os-marketplace-engenharia-de.vercel.app`

---

## 1. Ambiente Local (Tarefas 0.1 e 0.2)

| Item | Status / Versão | Observações |
|---|---|---|
| Git | `git version 2.56.1.windows.1` | Adicionado ao `PATH` do usuário (`scratch\tools\git\cmd`) |
| GitHub CLI | `gh` (`scratch\tools\gh\bin`) | Adicionado ao `PATH` do usuário e autenticado em `JODROVI24` |
| Branch `melhorias` | Criada a partir de `main` (`8bf633f`) | Branch isolada para execução das Fases 1–5 |
| Python + `.venv` | `Python 3.12.10` | `requirements-dev.txt` instalado; `python -m pip check`: `No broken requirements found.` |
| Node.js | `v22.14.0` | `npx` disponível |
| `.env` local | Criado a partir de `.env.example` | `SECRET_KEY` gerada com `secrets.token_hex(32)` (não versionado) |

---

## 2. Suítes de Testes (Baseline)

| Suíte | Comando | Resultado | Duração |
|---|---|---|---|
| Testes Python (`unittest`) | `.venv\Scripts\python.exe -m unittest discover -s tests -v` | **116/116 testes `OK`** (`test_app`, `test_payments`, `test_serverless_adversarial`) + `test_wsgi_api_adversarial.py` (`ALL ADVERSARIAL WSGI API TESTS PASSED SUCCESSFULLY!`) | `39.239 s` |
| Roteamento Vercel (`node`) | `node tests/test_vercel_routing_adversarial.js` | **Saída informativa (`exit 0`):** `[INFO] @vercel/routing-utils não instalado no ambiente global` (será habilitado na Fase 4.5 no CI) | `< 1 s` |

---

## 3. Latência e Cold Start na Vercel (Produção)

Medições realizadas com `curl.exe` contra `https://servi-os-marketplace-engenharia-de.vercel.app`:

- **Sondagem inicial em `/api/health` (cold start / wake-up):** a primeira tentativa com timeout de `15 s` expirou em **`15.119 ms`** (`O tempo limite da operação foi atingido`).
- **Sequência de 6 requisições subsequentes em `GET /api/health`:**
  - Resposta JSON confirmada: `{"database":"connected","engine":"postgresql","environment":"vercel","status":"healthy","version":"2.0.0"}`
  - **1ª requisição da série:** `1446.4 ms` (`HTTP 200`, `138 B`)
  - **Mínimo:** `1372.6 ms`
  - **Mediana (p50):** `1444.8 ms`
  - **p95:** `1718.2 ms`
  - **Máximo:** `1718.2 ms`
- **Sequência de 5 requisições em `GET /api/services` (baseline pré-Fase 2.5):**
  - **1ª requisição:** `1552.9 ms` (`HTTP 200`, `25034 B`)
  - **Mínimo:** `1517.5 ms`
  - **Mediana (p50):** `1552.9 ms`
  - **p95:** `1610.7 ms`
  - **Máximo:** `1610.7 ms`
- **Páginas HTML na Vercel (com `cleanUrls: true`):**
  - `GET /`: `HTTP 200` | `TTFB 313.5 ms` | `Total 315.8 ms` | `28833 B`
  - `GET /pedido`: `HTTP 200` | `TTFB 545.6 ms` | `Total 583.2 ms` | `38698 B` (obs.: `/pedido.html` retorna `HTTP 308` em `355.9 ms` por `cleanUrls`)
  - `GET /portal-cliente`: `HTTP 200` | `TTFB 515.0 ms` | `Total 572.7 ms` | `92822 B` (obs.: `/portal-cliente.html` retorna `HTTP 308` em `321.9 ms`)
  - `GET /portal-prestador`: `HTTP 200` | `TTFB 557.3 ms` | `Total 645.5 ms` | `143647 B` (obs.: `/portal-prestador.html` retorna `HTTP 308` em `431.4 ms`)

---

## 4. Web Vitals Reais (Chrome Headless + CDP, cache desabilitado)

### 4.1 Produção Vercel (`https://servi-os-marketplace-engenharia-de.vercel.app`)

| Página | TTFB (ms) | FCP (ms) | LCP (ms) | Elem. LCP | CLS | DCL (ms) | Load (ms) | Requests | Transf. (KB) | Erros Console / CSP |
|---|---|---|---|---|---|---|---|---|---|---|
| `/` (1ª carga sem warm DNS) | 42 | 3772 | 3772 | `H1` | 0.0570 | 4962 | 5486 | 24 | 1647.6 | 0 / 0 |
| `/` (2ª carga) | 56 | 1184 | 1184 | `H1` | **0.5687** | 1173 | 2669 | 24 | 1647.6 | 0 / 0 |
| `/pedido` (1ª carga) | 41 | 3576 | 3576 | `H1` | 0.0195 | 5507 | 7110 | 29 | 1614.0 | 0 / **1** |
| `/pedido` (2ª carga) | 59 | 672 | 672 | `H1` | 0.0205 | 1033 | 1922 | 30 | 1615.6 | 0 / **1** |

### 4.2 Servidor Local Flask (`http://127.0.0.1:5055`, portais autenticados com seed demo)

> Nota: na medição local, o script de sonda desabilitou `Accept-Encoding: gzip` no wrapper WSGI para contornar o bug de `direct_passthrough` descrito na seção 6.

| Página | TTFB (ms) | FCP (ms) | LCP (ms) | Elem. LCP | CLS | DCL (ms) | Load (ms) | Requests | Transf. (KB) | Erros Console / CSP |
|---|---|---|---|---|---|---|---|---|---|---|
| `/` | 104 | 1144 | 1144 | `H1` | **0.5687** | 1115 | 2144 | 25 | 1843.9 | 0 / 0 |
| `/pedido.html` | 2 | 872 | 872 | `H1` | 0.0195 | 1845 | 2186 | 31 | 1809.9 | 1 / **1** |
| `/portal-cliente.html` (autenticado `cliente@pertoja.com`) | 5 | 276 | 276 | `H2` | 0.0264 | 269 | 940 | 16 | 1504.1 | 0 / 0 |
| `/portal-prestador.html` (autenticado `carlos@pertoja.com`) | 4 | 288 | 288 | `H2` | **0.2043** | 278 | 572 | 19 | 1556.9 | 0 / 0 |

### 4.3 Lighthouse Scores (0–100) — Pendente de Coleta Manual no DevTools

A API pública do PageSpeed Insights retornou `HTTP 429 (Too Many Requests)` e o registro npm retornou `403`/`UNABLE_TO_VERIFY_LEAF_SIGNATURE` para `npx lighthouse`, impedindo a geração automatizada dos scores `0–100`. Para preencher antes da Fase 2.7, abra cada página no Chrome (`F12 -> Lighthouse -> Analyze page load`, modo Mobile/Desktop) e complete abaixo:

| Página | Performance | Accessibility | Best Practices | SEO | Observações |
|---|---|---|---|---|---|
| `/` (Home) | *Pendente* | *Pendente* | *Pendente* | *Pendente* | — |
| `/pedido` | *Pendente* | *Pendente* | *Pendente* | *Pendente* | — |
| `/portal-cliente` | *Pendente* | *Pendente* | *Pendente* | *Pendente* | Medir logado |
| `/portal-prestador` | *Pendente* | *Pendente* | *Pendente* | *Pendente* | Medir logado |

---

## 5. Inventário Estático de Código (Dívida Técnica)

### Tamanho dos arquivos principais
- `app.py`: **4.299 linhas**
- `database.py`: **1.771 linhas**
- `payment_adapters.py`: **1.551 linhas**
- `llm_client.py`: **1.544 linhas**
- `public/script.js`: **2.814 linhas**
- `public/auth.js`: **651 linhas**

### Frontend e Segurança
- **Páginas HTML em `public/*.html`:** `11` arquivos (`404.html`, `cadastro.html`, `como-funciona.html`, `index.html`, `login.html`, `pedido.html`, `portal-cliente.html`, `portal-prestador.html`, `privacidade.html`, `sobre-nos.html`, `termos.html`).
- **Uso de `cdn.tailwindcss.com`:** **`11 / 11` páginas HTML**.
- **Blocos `<script>` inline (sem `src=`):** **`20` blocos** no total (`como-funciona.html`: 3; `cadastro.html`, `index.html`, `login.html`, `pedido.html`, `portal-cliente.html`, `portal-prestador.html`, `sobre-nos.html`: 2 cada; `404.html`, `privacidade.html`, `termos.html`: 1 cada).
- **Ocorrências de `.innerHTML` em `public/`:** **`80` ocorrências** (`script.js`: 29, `portal-prestador.html`: 25, `portal-cliente.html`: 20, `auth.js`: 5, `como-funciona.html`: 1).

### Backend (`app.py`, `database.py`, `payment_adapters.py`, `llm_client.py`)
- **Blocos `except Exception`:** **`25` ocorrências** (`app.py`: 14, `database.py`: 8, `llm_client.py`: 3, `payment_adapters.py`: 0).
- **Chamadas `print(`:** **`7` ocorrências** (`app.py`: 6, `database.py`: 1, `payment_adapters.py`: 0, `llm_client.py`: 0).

---

## 6. Achados Adicionais Encontrados na Fase 0

1. **Bug de Gzip/Passthrough no Flask local (`app.py:195`):** fora da Vercel (`VERCEL != 1`), quando o navegador envia `Accept-Encoding: gzip`, `add_performance_and_security_headers` chama `response.get_data()` em respostas `send_from_directory()` com `direct_passthrough=True`, causando `RuntimeError: Attempted implicit sequence conversion but the response object is in direct passthrough mode` e retornando **HTTP 500** para arquivos estáticos em desenvolvimento local.
2. **Violação real de CSP em `/pedido`:** o SDK do Mercado Pago tenta conectar em `https://www.mercadolibre.com/jms/lgz/background/etid`, gerando bloqueio de `connect-src` no console.
3. **CLS elevado na Home e no Portal do Prestador:** `CLS = 0.5687` na Home (`/`) e `CLS = 0.2043` em `/portal-prestador.html` (meta pós-Fase 2: `< 0.1`), impactado pelo carregamento tardio do Tailwind CDN em runtime e layout shifts iniciais.

---

## 7. Status da Tarefa 0.4 (Banco PostgreSQL Dev e Prod)

- **Produção (`Vercel`):** **já conectado ao PostgreSQL** (confirmado via `GET /api/health` -> `"engine": "postgresql", "database": "connected"`).
- **Desenvolvimento local:** pendente de criação do projeto/branch dev no Neon ou Supabase pelo usuário e preenchimento de `DATABASE_URL=...` no `.env` local (atualmente operando com fallback SQLite `marketplace.db` em dev).
