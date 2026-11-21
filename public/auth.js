// auth.js - Gerenciamento global de autenticação, CSRF, navegação e localização do PertoJá

const PERTOJA_CSRF_COOKIE = 'csrf_token';

function obterCsrfToken() {
  if (typeof document === 'undefined' || !document.cookie) return '';
  const pairs = document.cookie.split(';');
  for (let i = 0; i < pairs.length; i += 1) {
    const idx = pairs[i].indexOf('=');
    if (idx === -1) continue;
    const key = pairs[i].slice(0, idx).trim();
    if (key === PERTOJA_CSRF_COOKIE) {
      const rawVal = pairs[i].slice(idx + 1).trim();
      try {
        return decodeURIComponent(rawVal);
      } catch (_) {
        return rawVal;
      }
    }
  }
  return '';
}

function garantirHeadersCsrf(headersInit) {
  const headers = new Headers(headersInit || undefined);
  const token = obterCsrfToken();
  if (token && !headers.has('X-CSRF-Token')) {
    headers.set('X-CSRF-Token', token);
  }
  return headers;
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function sanitizarUrlSegura(url, fallback = '#') {
  if (typeof url !== 'string') return fallback;
  const trimmed = url.trim();
  if (!trimmed || /[\u0000-\u001F\u007F\\]/.test(trimmed)) return fallback;
  if (trimmed.startsWith('//')) return fallback;
  if (/^(javascript|data|vbscript):/i.test(trimmed)) return fallback;
  try {
    const base = (typeof window !== 'undefined' && window.location && window.location.origin)
      ? window.location.origin
      : 'https://pertoja.invalid';
    const parsed = new URL(trimmed, base);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return fallback;
    if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
      return trimmed.startsWith('/') ? (parsed.pathname + parsed.search + parsed.hash) : trimmed;
    }
    return parsed.href;
  } catch (_) {
    return fallback;
  }
}

function salvarConteudoBotao(btn) {
  if (!btn) return [];
  return Array.from(btn.childNodes).map((n) => n.cloneNode(true));
}

function restaurarConteudoBotao(btn, snapshot) {
  if (!btn || !Array.isArray(snapshot)) return;
  btn.replaceChildren(...snapshot.map((n) => n.cloneNode(true)));
}

if (typeof window !== 'undefined') {
  window.escapeHtml = escapeHtml;
  window.sanitizarUrlSegura = sanitizarUrlSegura;
  window.salvarConteudoBotao = salvarConteudoBotao;
  window.restaurarConteudoBotao = restaurarConteudoBotao;
}

(function instalarFetchCsrfWrapper() {
  if (typeof window === 'undefined' || typeof window.fetch !== 'function' || window.__pertojaCsrfFetchInstalled) {
    return;
  }
  const originalFetch = window.fetch.bind(window);
  window.__pertojaCsrfFetchInstalled = true;
  window.fetch = async function fetchComCsrf(input, init) {
    const rawUrl = typeof input === 'string'
      ? input
      : (input instanceof URL ? input.href : (input && typeof input === 'object' && input.url ? input.url : ''));
    const method = String((init && init.method) || (input && typeof input === 'object' && !(input instanceof URL) && input.method) || 'GET').toUpperCase();

    let isSameOrigin = false;
    let targetPath = '';
    try {
      const parsed = new URL(rawUrl, window.location.origin);
      isSameOrigin = parsed.origin === window.location.origin;
      targetPath = parsed.pathname || '';
    } catch (_) {
      isSameOrigin = false;
    }

    if (isSameOrigin && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      if (!obterCsrfToken() && targetPath !== '/api/auth/csrf') {
        try {
          await originalFetch('/api/auth/csrf', { credentials: 'same-origin' });
        } catch (_) {}
      }
      const baseHeaders = (init && init.headers)
        || (input && typeof input === 'object' && !(input instanceof URL) ? input.headers : undefined);
      const nextInit = Object.assign({}, init || {});
      nextInit.headers = garantirHeadersCsrf(baseHeaders);
      return originalFetch(input, nextInit);
    }

    return originalFetch(input, init);
  };
}());

const PERTOJA_MIN_PASSWORD_LENGTH = 10;

function validarPoliticaSenhaLocal(senha, rotulo = 'A senha') {
  const valor = String(senha || '');
  if (valor.length < PERTOJA_MIN_PASSWORD_LENGTH) {
    return {
      valid: false,
      code: 'PASSWORD_TOO_SHORT',
      message: `${rotulo} deve conter no mínimo ${PERTOJA_MIN_PASSWORD_LENGTH} caracteres. Evite senhas fáceis ou já expostas em vazamentos.`,
    };
  }
  return { valid: true, code: null, message: '' };
}

let _usuarioLogadoPromessa = null;
let _usuarioLogadoAtual = null;

async function obterUsuarioLogado(forcar = false) {
  if (!forcar && _usuarioLogadoPromessa) {
    return _usuarioLogadoPromessa;
  }
  _usuarioLogadoPromessa = (async () => {
    try {
      const res = await fetch('/api/auth/me');
      if (!res.ok) {
        _usuarioLogadoAtual = null;
        return null;
      }
      const data = await res.json();
      _usuarioLogadoAtual = data.authenticated ? data.user : null;
      return _usuarioLogadoAtual;
    } catch (e) {
      console.warn('Backend API offline ou indisponível:', e);
      _usuarioLogadoAtual = null;
      return null;
    }
  })();
  return _usuarioLogadoPromessa;
}

async function atualizarNavegacao() {
  const user = await obterUsuarioLogado();
  const nav = document.querySelector('.menu-principal');
  if (!nav) return;

  // Remove botões de autenticação anteriores se houver
  const authLinks = nav.querySelectorAll('.link-auth');
  authLinks.forEach(el => el.remove());

  if (user) {
    const portalUrl = user.tipo === 'prestador' ? 'portal-prestador.html' : 'portal-cliente.html';
    const portalNome = user.tipo === 'prestador' ? 'Painel Prestador' : 'Meu Portal';
    
    const portalLink = document.createElement('a');
    portalLink.href = portalUrl;
    portalLink.className = 'link-auth destaque-portal';
    const primeiroNome = String(user.nome || '').trim().split(/\s+/)[0] || 'Usuário';
    portalLink.textContent = `👤 ${portalNome} (${primeiroNome})`;
    nav.appendChild(portalLink);

    const logoutLink = document.createElement('a');
    logoutLink.href = '#';
    logoutLink.className = 'link-auth';
    logoutLink.textContent = 'Sair';
    logoutLink.onclick = async (e) => {
      e.preventDefault();
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
      } catch (err) {}
      ['pertoja_pending_order', 'pertoja_active_order_id', 'pertoja_search_loc'].forEach((k) => {
        try { localStorage.removeItem(k); } catch (_) {}
        try { sessionStorage.removeItem(k); } catch (_) {}
      });
      window.location.href = 'index.html';
    };
    nav.appendChild(logoutLink);
  } else {
    const loginLink = document.createElement('a');
    loginLink.href = 'login.html';
    loginLink.className = 'link-auth';
    loginLink.textContent = 'Entrar';
    nav.appendChild(loginLink);

    const cadastroLink = document.createElement('a');
    cadastroLink.href = 'cadastro.html';
    cadastroLink.className = 'link-auth btn-cadastrar-topo';
    cadastroLink.textContent = 'Cadastrar';
    nav.appendChild(cadastroLink);
  }
}

function inicializarDrawerNavegacao() {
  const btnHamburguer = document.getElementById('btnHamburguer') || document.querySelector('.menu-hamburguer');
  const btnFechar = document.getElementById('btnFecharDrawer') || document.querySelector('.drawer-fechar');
  const backdrop = document.getElementById('drawerBackdrop') || document.querySelector('.drawer-backdrop');
  const navDrawer = document.querySelector('.menu-principal');

  if (!navDrawer || navDrawer.dataset.drawerInit) return;
  navDrawer.dataset.drawerInit = 'true';

  if (!navDrawer.querySelector('.drawer-legal-links')) {
    const legalWrap = document.createElement('div');
    legalWrap.className = 'drawer-legal-links';
    const linkTermos = document.createElement('a');
    linkTermos.href = '/termos.html';
    linkTermos.textContent = 'Termos & Ética';
    const linkPrivacidade = document.createElement('a');
    linkPrivacidade.href = '/privacidade.html';
    linkPrivacidade.textContent = 'Privacidade LGPD';
    legalWrap.replaceChildren(linkTermos, linkPrivacidade);
    navDrawer.appendChild(legalWrap);
  }

  // Garante que ícones decorativos dentro dos botões sejam ocultados para tecnologias assistivas
  if (btnHamburguer) {
    const icon = btnHamburguer.querySelector('.material-symbols-outlined');
    if (icon && !icon.hasAttribute('aria-hidden')) icon.setAttribute('aria-hidden', 'true');
  }
  if (btnFechar) {
    const icon = btnFechar.querySelector('.material-symbols-outlined');
    if (icon && !icon.hasAttribute('aria-hidden')) icon.setAttribute('aria-hidden', 'true');
  }

  let scrollYAntesDeAbrir = 0;

  function abrirDrawer() {
    if (navDrawer.classList.contains('aberto')) return;
    scrollYAntesDeAbrir = window.scrollY || window.pageYOffset || document.documentElement.scrollTop || 0;
    navDrawer.classList.add('aberto');
    navDrawer.setAttribute('aria-modal', 'true');
    if (backdrop) {
      backdrop.classList.add('aberto');
      backdrop.setAttribute('aria-hidden', 'false');
    }
    if (btnHamburguer) {
      btnHamburguer.setAttribute('aria-expanded', 'true');
    }
    document.body.classList.add('drawer-aberto');
    if (btnFechar) {
      btnFechar.focus({ preventScroll: true });
    } else {
      const first = navDrawer.querySelector('button:not([disabled]), a[href]:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
      if (first) first.focus({ preventScroll: true });
    }
  }

  function fecharDrawer(options = {}) {
    if (!navDrawer.classList.contains('aberto')) return;
    const shouldRestoreFocus = options.restoreFocus ?? (document.activeElement && navDrawer.contains(document.activeElement));
    navDrawer.classList.remove('aberto');
    navDrawer.removeAttribute('aria-modal');
    if (backdrop) {
      backdrop.classList.remove('aberto');
      backdrop.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('drawer-aberto');
    if (scrollYAntesDeAbrir > 0) {
      window.scrollTo(0, scrollYAntesDeAbrir);
    }
    if (btnHamburguer) {
      btnHamburguer.setAttribute('aria-expanded', 'false');
      if (shouldRestoreFocus && window.getComputedStyle(btnHamburguer).display !== 'none') {
        btnHamburguer.focus({ preventScroll: true });
      }
    }
    if (scrollYAntesDeAbrir > 0) {
      window.scrollTo(0, scrollYAntesDeAbrir);
    }
    setTimeout(() => {
      if (window.map && typeof window.map.invalidateSize === 'function') window.map.invalidateSize();
      if (window.mapInstance && typeof window.mapInstance.invalidateSize === 'function') window.mapInstance.invalidateSize();
    }, 250);
  }

  if (btnHamburguer) {
    btnHamburguer.addEventListener('click', (e) => {
      e.stopPropagation();
      if (navDrawer.classList.contains('aberto')) {
        fecharDrawer();
      } else {
        abrirDrawer();
      }
    });
  }

  if (btnFechar) {
    btnFechar.addEventListener('click', (e) => {
      e.stopPropagation();
      fecharDrawer({ restoreFocus: true });
    });
  }

  if (backdrop) {
    backdrop.addEventListener('click', () => {
      fecharDrawer({ restoreFocus: true });
    });
  }

  // Fechar ao pressionar a tecla Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && navDrawer.classList.contains('aberto')) {
      fecharDrawer({ restoreFocus: true });
    }
  });

  // Focus trap acessível e abrangente dentro do drawer quando aberto
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab' || !navDrawer.classList.contains('aberto')) return;
    const focusable = Array.from(navDrawer.querySelectorAll(
      'button:not([disabled]), a[href]:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ));
    if (!focusable.length) return;
    const firstElement = focusable[0];
    const lastElement = focusable[focusable.length - 1];

    if (!navDrawer.contains(document.activeElement)) {
      e.preventDefault();
      if (e.shiftKey) {
        lastElement.focus({ preventScroll: true });
      } else {
        firstElement.focus({ preventScroll: true });
      }
    } else if (e.shiftKey && document.activeElement === firstElement) {
      e.preventDefault();
      lastElement.focus({ preventScroll: true });
    } else if (!e.shiftKey && document.activeElement === lastElement) {
      e.preventDefault();
      firstElement.focus({ preventScroll: true });
    }
  });

  // Fechar ao clicar em qualquer link de navegação dentro do menu
  navDrawer.addEventListener('click', (e) => {
    const link = e.target.closest('a');
    if (link && navDrawer.classList.contains('aberto')) {
      fecharDrawer();
    }
  });

  // Fechar automaticamente ao redimensionar além do breakpoint mobile (768px)
  const mobileMedia = window.matchMedia('(max-width: 768px)');
  const handleMediaChange = (e) => {
    if (!e.matches && navDrawer.classList.contains('aberto')) {
      fecharDrawer({ restoreFocus: false });
    }
  };
  if (mobileMedia.addEventListener) {
    mobileMedia.addEventListener('change', handleMediaChange);
  } else if (mobileMedia.addListener) {
    mobileMedia.addListener(handleMediaChange);
  }

  window.addEventListener('resize', () => {
    if (!mobileMedia.matches && navDrawer.classList.contains('aberto')) {
      fecharDrawer({ restoreFocus: false });
    }
  });
}

// ==================== PA-05: Pill de Localização no Header & Modal/Bottom Sheet ====================
const PERTOJA_LOC_STORAGE_KEY = 'pertoja_search_loc';
let _locModalLastFocus = null;
let _locPendente = null;

function formatarCepExibicao(cep) {
  const digits = String(cep || '').replace(/\D/g, '');
  if (digits.length === 8) {
    return `${digits.slice(0, 5)}-${digits.slice(5)}`;
  }
  return String(cep || '').trim();
}

function lerLocalizacaoSalva() {
  try {
    const raw = localStorage.getItem(PERTOJA_LOC_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && (parsed.label || parsed.cep || (parsed.lat != null && parsed.lng != null))) {
      return parsed;
    }
    return null;
  } catch (e) {
    return null;
  }
}

function formatarResumoUsuario(user) {
  if (!user) return '';
  const bairro = String(user.bairro || '').trim();
  const cep = formatarCepExibicao(user.cep || '');
  const endereco = String(user.endereco || '').trim();
  if (bairro && cep) return `${bairro} · ${cep}`;
  if (bairro) return bairro;
  if (endereco && cep) return `${endereco} · ${cep}`;
  if (endereco) return endereco;
  if (cep) return cep;
  return '';
}

function atualizarPillEnderecoHeader(locOverride) {
  const btn = document.getElementById('btnEnderecoHeader');
  if (!btn) return;
  const textSpan = btn.querySelector('.header-loc-pill-text');
  if (!textSpan) return;

  const saved = locOverride || lerLocalizacaoSalva();
  let label = '';
  if (saved) {
    if (saved.label && saved.cep && !String(saved.label).includes(saved.cep)) {
      label = `${saved.label} · ${formatarCepExibicao(saved.cep)}`;
    } else {
      label = saved.label || formatarCepExibicao(saved.cep) || 'Localização definida';
    }
  } else if (_usuarioLogadoAtual) {
    label = formatarResumoUsuario(_usuarioLogadoAtual);
  }

  textSpan.textContent = label || 'Definir endereço';
}

function estaEmPaginaPedido() {
  const path = (window.location.pathname || '').toLowerCase();
  return path.endsWith('/pedido.html') || path.endsWith('pedido.html');
}

function confirmarLocalizacaoHeader(loc, redirecionarParaPedido = false) {
  if (!loc || loc.lat == null || loc.lng == null) return;
  const payload = {
    lat: Number(loc.lat),
    lng: Number(loc.lng),
    label: String(loc.label || '').trim() || 'Localização selecionada',
    cep: String(loc.cep || '').replace(/\D/g, '')
  };
  try {
    localStorage.setItem(PERTOJA_LOC_STORAGE_KEY, JSON.stringify(payload));
  } catch (e) {
    console.warn('Não foi possível salvar localização:', e);
  }
  atualizarPillEnderecoHeader(payload);
  window.dispatchEvent(new CustomEvent('pertoja:location-changed', { detail: payload }));
  fecharModalEnderecoHeader();

  if (redirecionarParaPedido && !estaEmPaginaPedido()) {
    window.location.href = '/pedido.html';
  }
}

function fecharModalEnderecoHeader(restoreFocus = true) {
  const modal = document.getElementById('modalEnderecoHeader');
  if (!modal) return;
  modal.style.display = 'none';
  modal.setAttribute('aria-hidden', 'true');
  if (restoreFocus && _locModalLastFocus && typeof _locModalLastFocus.focus === 'function') {
    _locModalLastFocus.focus({ preventScroll: true });
  }
  _locModalLastFocus = null;
}

function garantirModalEnderecoHeader() {
  let modal = document.getElementById('modalEnderecoHeader');
  if (modal) return modal;

  modal = document.createElement('div');
  modal.id = 'modalEnderecoHeader';
  modal.className = 'modal-backdrop';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-labelledby', 'modalEnderecoHeaderTitulo');
  modal.setAttribute('aria-hidden', 'true');
  modal.style.display = 'none';

  const emPedido = estaEmPaginaPedido();
  modal.innerHTML = `
    <div class="modal-conteudo">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px;">
        <h2 id="modalEnderecoHeaderTitulo" style="font-size:1.15rem;font-weight:800;color:var(--ink);margin:0;">
          Endereço de atendimento
        </h2>
        <button type="button" id="btnFecharModalEndereco" class="btn-neutral" style="min-height:36px;padding:6px 12px;" aria-label="Fechar janela de endereço">
          <span class="material-symbols-outlined" aria-hidden="true" style="font-size:18px;">close</span>
        </button>
      </div>
      <p style="font-size:0.88rem;color:#10243e;opacity:0.85;margin-bottom:14px;">
        Informe seu CEP ou endereço para calcular distâncias e encontrar profissionais perto de você.
      </p>

      <form id="formBuscaEnderecoHeader" style="display:flex;gap:8px;margin-bottom:12px;">
        <label for="inputBuscaEnderecoHeader" class="sr-only" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);">CEP ou endereço</label>
        <input type="text" id="inputBuscaEnderecoHeader" class="input-form tabular-nums" placeholder="Digite CEP (ex: 01310-100) ou endereço" autocomplete="postal-code" style="flex:1;margin:0;" />
        <button type="submit" id="btnBuscarEnderecoHeader" class="btn" style="min-height:42px;padding:0 18px;border-radius:12px;font-weight:800;">Buscar</button>
      </form>

      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px;">
        <button type="button" id="btnGpsEnderecoHeader" class="btn-neutral" style="flex:1;min-width:160px;">
          <span class="material-symbols-outlined" aria-hidden="true" style="font-size:18px;">my_location</span>
          Usar meu GPS atual
        </button>
        <button type="button" id="btnEnderecoCadastradoHeader" class="btn-neutral" style="flex:1;min-width:180px;display:none;">
          <span class="material-symbols-outlined" aria-hidden="true" style="font-size:18px;">home</span>
          Usar meu endereço cadastrado
        </button>
      </div>

      <div id="statusEnderecoHeader" aria-live="polite" style="display:none;margin-bottom:12px;"></div>

      <div id="acoesConfirmacaoEnderecoHeader" style="display:none;flex-wrap:wrap;gap:8px;justify-content:flex-end;margin-top:12px;padding-top:12px;border-top:1px solid var(--road);">
        <button type="button" id="btnConfirmarEnderecoHeader" class="btn" style="min-height:42px;padding:0 18px;border-radius:9999px;font-weight:800;">
          Confirmar localização
        </button>
        <button type="button" id="btnVerProfissionaisProximos" class="btn2" style="min-height:42px;padding:0 18px;border-radius:9999px;font-weight:800;">
          Ver profissionais próximos
        </button>
      </div>
    </div>
  `;
  if (emPedido) {
    const btnHide = modal.querySelector('#btnVerProfissionaisProximos');
    if (btnHide) btnHide.style.display = 'none';
  }

  document.body.appendChild(modal);

  const btnFechar = modal.querySelector('#btnFecharModalEndereco');
  const formBusca = modal.querySelector('#formBuscaEnderecoHeader');
  const inputBusca = modal.querySelector('#inputBuscaEnderecoHeader');
  const btnBuscar = modal.querySelector('#btnBuscarEnderecoHeader');
  const btnGps = modal.querySelector('#btnGpsEnderecoHeader');
  const btnCadastrado = modal.querySelector('#btnEnderecoCadastradoHeader');
  const statusBox = modal.querySelector('#statusEnderecoHeader');
  const acoesBox = modal.querySelector('#acoesConfirmacaoEnderecoHeader');
  const btnConfirmar = modal.querySelector('#btnConfirmarEnderecoHeader');
  const btnVerProximos = modal.querySelector('#btnVerProfissionaisProximos');

  function mostrarStatus(msg, tipo = 'info') {
    statusBox.style.display = 'block';
    if (tipo === 'erro') {
      statusBox.className = 'alerta-erro';
      statusBox.style.marginBottom = '12px';
    } else {
      statusBox.className = '';
      statusBox.style.padding = '10px 14px';
      statusBox.style.borderRadius = '12px';
      statusBox.style.fontSize = '0.88rem';
      statusBox.style.fontWeight = '600';
      statusBox.style.background = tipo === 'ok' ? 'var(--ok-soft)' : 'var(--sea-soft)';
      statusBox.style.color = 'var(--ink)';
      statusBox.style.border = '1px solid var(--road)';
    }
    statusBox.textContent = msg;
  }

  function definirPendente(loc, msgSucesso) {
    _locPendente = loc;
    mostrarStatus(msgSucesso, 'ok');
    acoesBox.style.display = 'flex';
  }

  btnFechar.addEventListener('click', () => fecharModalEnderecoHeader(true));
  modal.addEventListener('click', (e) => {
    if (e.target === modal) fecharModalEnderecoHeader(true);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.style.display !== 'none') {
      fecharModalEnderecoHeader(true);
    }
  });

  formBusca.addEventListener('submit', async (e) => {
    e.preventDefault();
    const raw = (inputBusca.value || '').trim();
    if (!raw) {
      mostrarStatus('Digite um CEP válido ou endereço completo.', 'erro');
      return;
    }

    const digits = raw.replace(/\D/g, '');
    const pareceCep = digits.length === 8 && /^[\d\s.-]+$/.test(raw);
    _locPendente = null;
    acoesBox.style.display = 'none';
    mostrarStatus('Buscando localização...', 'info');

    if (btnBuscar) {
      btnBuscar.classList.add('is-loading');
      btnBuscar.disabled = true;
      btnBuscar.textContent = 'Buscando...';
    }

    try {
      if (pareceCep) {
        const res = await fetch(`/api/cep/${digits}`);
        const data = await res.json();
        if (!res.ok || data.error || data.lat == null || data.lng == null) {
          mostrarStatus(data.error || 'CEP não localizado no mapa. Tente informar rua e cidade.', 'erro');
          return;
        }
        const partes = [data.bairro || data.logradouro, data.localidade].filter(Boolean);
        const labelBase = partes.join(', ') || 'CEP localizado';
        const cepFmt = formatarCepExibicao(digits);
        definirPendente(
          { lat: Number(data.lat), lng: Number(data.lng), label: `${labelBase} · ${cepFmt}`, cep: digits },
          `Localizado: ${[data.logradouro, data.bairro, data.localidade, data.uf].filter(Boolean).join(', ')} (${cepFmt})`
        );
      } else {
        const res = await fetch(`/api/geocode?q=${encodeURIComponent(raw)}`);
        const data = await res.json();
        if (!res.ok || data.error || data.lat == null || data.lng == null) {
          mostrarStatus(data.error || 'Endereço não localizado. Tente incluir bairro e cidade.', 'erro');
          return;
        }
        definirPendente(
          { lat: Number(data.lat), lng: Number(data.lng), label: raw, cep: '' },
          `Endereço localizado: ${raw}`
        );
      }
    } catch (err) {
      mostrarStatus('Erro de conexão ao buscar endereço. Tente novamente.', 'erro');
    } finally {
      if (btnBuscar) {
        btnBuscar.classList.remove('is-loading');
        btnBuscar.disabled = false;
        btnBuscar.textContent = 'Buscar';
      }
    }
  });

  btnGps.addEventListener('click', () => {
    if (!navigator.geolocation) {
      mostrarStatus('Geolocalização não suportada neste navegador.', 'erro');
      return;
    }
    _locPendente = null;
    acoesBox.style.display = 'none';
    mostrarStatus('Obtendo sua posição via GPS...', 'info');
    const origGpsNodes = salvarConteudoBotao(btnGps);
    btnGps.classList.add('is-loading');
    btnGps.disabled = true;
    btnGps.textContent = 'Obtendo GPS...';
    const restoreGpsBtn = () => {
      btnGps.classList.remove('is-loading');
      btnGps.disabled = false;
      restaurarConteudoBotao(btnGps, origGpsNodes);
    };
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        restoreGpsBtn();
        const loc = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          label: 'Minha localização (GPS)',
          cep: ''
        };
        definirPendente(loc, 'Localização GPS obtida com sucesso!');
      },
      () => {
        restoreGpsBtn();
        mostrarStatus('Não foi possível obter seu GPS. Verifique as permissões ou digite seu CEP.', 'erro');
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  });

  btnCadastrado.addEventListener('click', () => {
    const u = _usuarioLogadoAtual;
    if (!u || u.lat == null || u.lng == null) {
      mostrarStatus('Seu cadastro ainda não possui coordenadas salvas.', 'erro');
      return;
    }
    const resumo = formatarResumoUsuario(u) || 'Meu endereço cadastrado';
    confirmarLocalizacaoHeader({
      lat: Number(u.lat),
      lng: Number(u.lng),
      label: resumo,
      cep: u.cep || ''
    }, false);
  });

  btnConfirmar.addEventListener('click', () => {
    if (_locPendente) {
      confirmarLocalizacaoHeader(_locPendente, false);
    }
  });

  if (btnVerProximos) {
    btnVerProximos.addEventListener('click', () => {
      if (_locPendente) {
        confirmarLocalizacaoHeader(_locPendente, true);
      } else {
        fecharModalEnderecoHeader(false);
        window.location.href = '/pedido.html';
      }
    });
  }

  return modal;
}

async function abrirModalEnderecoHeader() {
  _locModalLastFocus = document.activeElement;
  const modal = garantirModalEnderecoHeader();
  const btnCadastrado = modal.querySelector('#btnEnderecoCadastradoHeader');
  const inputBusca = modal.querySelector('#inputBuscaEnderecoHeader');

  const user = _usuarioLogadoAtual || await obterUsuarioLogado();
  if (btnCadastrado) {
    btnCadastrado.style.display = (user && user.lat != null && user.lng != null) ? 'inline-flex' : 'none';
  }

  modal.style.display = 'flex';
  modal.setAttribute('aria-hidden', 'false');
  if (inputBusca) {
    setTimeout(() => inputBusca.focus({ preventScroll: true }), 20);
  }
}

async function inicializarHeaderLocalizacao() {
  const header = document.querySelector('header.site-header');
  if (!header) return;

  let btn = document.getElementById('btnEnderecoHeader');
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'btnEnderecoHeader';
    btn.className = 'header-loc-pill';
    btn.setAttribute('aria-label', 'Definir ou alterar endereço de atendimento');
    const locIcon = document.createElement('span');
    locIcon.className = 'material-symbols-outlined';
    locIcon.setAttribute('aria-hidden', 'true');
    locIcon.textContent = 'location_on';
    const locText = document.createElement('span');
    locText.className = 'header-loc-pill-text';
    locText.textContent = 'Definir endereço';
    btn.replaceChildren(locIcon, locText);

    const btnHamburguer = document.getElementById('btnHamburguer') || header.querySelector('.menu-hamburguer');
    if (btnHamburguer && btnHamburguer.parentNode === header) {
      header.insertBefore(btn, btnHamburguer);
    } else {
      header.appendChild(btn);
    }

    btn.addEventListener('click', () => {
      abrirModalEnderecoHeader();
    });
  }

  atualizarPillEnderecoHeader();
  if (!lerLocalizacaoSalva()) {
    await obterUsuarioLogado();
    atualizarPillEnderecoHeader();
  }
}

// Expõe globalmente para controle e testes
window.obterCsrfToken = obterCsrfToken;
window.garantirHeadersCsrf = garantirHeadersCsrf;
window.PERTOJA_MIN_PASSWORD_LENGTH = PERTOJA_MIN_PASSWORD_LENGTH;
window.validarPoliticaSenhaLocal = validarPoliticaSenhaLocal;
window.atualizarNavegacao = atualizarNavegacao;
window.inicializarDrawerNavegacao = inicializarDrawerNavegacao;
window.inicializarHeaderLocalizacao = inicializarHeaderLocalizacao;
window.abrirModalEnderecoHeader = abrirModalEnderecoHeader;
window.atualizarPillEnderecoHeader = atualizarPillEnderecoHeader;

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.atualizarNavegacaoPromise = atualizarNavegacao();
    inicializarDrawerNavegacao();
    inicializarHeaderLocalizacao();
  });
} else {
  window.atualizarNavegacaoPromise = atualizarNavegacao();
  inicializarDrawerNavegacao();
  inicializarHeaderLocalizacao();
}
