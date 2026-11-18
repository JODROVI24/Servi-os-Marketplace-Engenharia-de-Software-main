// script.js - Lógica interativa de catálogo, mapa geográfico e tracking do PertoJá

let centerLat = -23.5653;
let centerLng = -46.6517;
let currentSearchAddress = 'Avenida Paulista, 1000 · Bela Vista · São Paulo - SP';
let mapInstance = null;
let layerMarkers = null;

let P = [
  // --- CENTRO DE SÃO PAULO (5) ---
  { id: 1, n: 'Carlos Mendes', s: 'Limpeza residencial completa', c: 'Limpeza', p: 80, r: 4.8, lat: -23.5653, lng: -46.6517, a: true, endereco: 'Avenida Paulista, 1000 · Bela Vista · São Paulo - SP' },
  { id: 2, n: 'Rafa Instalações', s: 'Troca de chuveiro e tomadas elétricas', c: 'Elétrica', p: 90, r: 4.2, lat: -23.5570, lng: -46.6640, a: true, endereco: 'Rua Haddock Lobo, 800 · Cerqueira César · São Paulo - SP' },
  { id: 3, n: 'Téo Suporte', s: 'Suporte técnico de computadores e redes Wi-Fi', c: 'Tecnologia', p: 110, r: 4.4, lat: -23.5550, lng: -46.6600, a: true, endereco: 'Rua da Consolação, 2400 · Consolação · São Paulo - SP' },
  { id: 4, n: 'Marcio Encanador Sé', s: 'Desentupimento e reparo de válvulas e sifões', c: 'Encanamento', p: 130, r: 4.6, lat: -23.5505, lng: -46.6333, a: true, endereco: 'Praça da Sé, 100 · Sé · São Paulo - SP' },
  { id: 5, n: 'Helena Restaurações', s: 'Restauração de portas e móveis coloniais', c: 'Marcenaria', p: 220, r: 4.9, lat: -23.5385, lng: -46.6530, a: true, endereco: 'Rua Baronesa de Itu, 350 · Santa Cecília · São Paulo - SP' },

  // --- ZONA NORTE DE SÃO PAULO (5) ---
  { id: 6, n: 'Beto Hidráulica', s: 'Conserto de vazamentos e desentupimento', c: 'Encanamento', p: 240, r: 4.7, lat: -23.5042, lng: -46.6262, a: true, endereco: 'Rua Voluntários da Pátria, 1500 · Santana · São Paulo - SP' },
  { id: 7, n: 'Lucia Jardim & Verde', s: 'Paisagismo, adubação e poda de gramados', c: 'Jardinagem', p: 190, r: 4.8, lat: -23.4795, lng: -46.6080, a: true, endereco: 'Avenida Nova Cantareira, 1200 · Tucuruvi · São Paulo - SP' },
  { id: 8, n: 'Valter Força Elétrica', s: 'Manutenção elétrica preventiva e disjuntores', c: 'Elétrica', p: 150, r: 4.5, lat: -23.5020, lng: -46.6300, a: true, endereco: 'Rua Doutor César, 400 · Santana · São Paulo - SP' },
  { id: 9, n: 'Camila Clean ZN', s: 'Faxina residencial e higienização de sofás', c: 'Limpeza', p: 140, r: 4.9, lat: -23.5130, lng: -46.6570, a: true, endereco: 'Rua Casa Verde, 850 · Casa Verde · São Paulo - SP' },
  { id: 10, n: 'Sergio Cores do Norte', s: 'Pintura de fachadas e textura grafiato', c: 'Pintura', p: 340, r: 4.6, lat: -23.5120, lng: -46.5950, a: true, endereco: 'Rua Curuçá, 600 · Vila Maria · São Paulo - SP' },

  // --- ZONA SUL DE SÃO PAULO (5) ---
  { id: 11, n: 'Marta Souza', s: 'Faxina pesada e higienização profunda', c: 'Limpeza', p: 170, r: 4.5, lat: -23.5855, lng: -46.6385, a: true, endereco: 'Rua Domingos de Morais, 500 · Vila Mariana · São Paulo - SP' },
  { id: 12, n: 'Dona Flor', s: 'Jardinagem, poda e manutenção paisagística', c: 'Jardinagem', p: 450, r: 5.0, lat: -23.5840, lng: -46.6780, a: true, endereco: 'Rua Bandeira Paulista, 700 · Itaim Bibi · São Paulo - SP' },
  { id: 13, n: 'Eduardo Reparos Sul', s: 'Instalação de iluminação LED e tomadas inteligentes', c: 'Elétrica', p: 160, r: 4.7, lat: -23.6060, lng: -46.6620, a: true, endereco: 'Alameda dos Maracatins, 900 · Moema · São Paulo - SP' },
  { id: 14, n: 'Renato Hidráulica Moema', s: 'Instalação de duchas, torneiras e pressurizadores', c: 'Encanamento', p: 180, r: 4.6, lat: -23.6090, lng: -46.6910, a: true, endereco: 'Rua Flórida, 1400 · Brooklin · São Paulo - SP' },
  { id: 15, n: 'Claudio Móveis Planejados', s: 'Montagem e ajuste de armários embutidos', c: 'Marcenaria', p: 280, r: 4.8, lat: -23.6520, lng: -46.7080, a: true, endereco: 'Rua Doutor Antônio Bento, 650 · Santo Amaro · São Paulo - SP' },

  // --- ZONA LESTE DE SÃO PAULO (5) ---
  { id: 16, n: 'Nina Montagens', s: 'Marcenaria e montagem de móveis planejados', c: 'Marcenaria', p: 260, r: 4.3, lat: -23.5535, lng: -46.6020, a: true, endereco: 'Rua da Mooca, 1500 · Mooca · São Paulo - SP' },
  { id: 17, n: 'Rogério Eletro Leste', s: 'Troca de fiação antiga e quadro elétrico', c: 'Elétrica', p: 200, r: 4.8, lat: -23.5390, lng: -46.5740, a: true, endereco: 'Rua Serra de Bragança, 850 · Tatuapé · São Paulo - SP' },
  { id: 18, n: 'Priscila Brilho Total', s: 'Limpeza pós-obra e faxina comercial', c: 'Limpeza', p: 150, r: 4.7, lat: -23.5550, lng: -46.5680, a: true, endereco: 'Rua Emília Marengo, 400 · Anália Franco · São Paulo - SP' },
  { id: 19, n: 'Tiago Desentupidora Penha', s: 'Caça vazamento eletrônico e desentupimento de esgotos', c: 'Encanamento', p: 220, r: 4.5, lat: -23.5250, lng: -46.5490, a: true, endereco: 'Rua Betari, 300 · Penha · São Paulo - SP' },
  { id: 20, n: 'Leandro Art Cobre', s: 'Pintura acrílica acetinada e esmalte sintético', c: 'Pintura', p: 310, r: 4.9, lat: -23.5410, lng: -46.4560, a: true, endereco: 'Rua Américo Salvador Novelli, 250 · Itaquera · São Paulo - SP' },

  // --- ZONA OESTE DE SÃO PAULO (5) ---
  { id: 21, n: 'João Volts', s: 'Reparo e manutenção de quadro elétrico', c: 'Elétrica', p: 210, r: 4.9, lat: -23.5601, lng: -46.6850, a: true, endereco: 'Rua Teodoro Sampaio, 1200 · Pinheiros · São Paulo - SP' },
  { id: 22, n: 'Lia Cores', s: 'Pintura residencial e texturização de paredes', c: 'Pintura', p: 380, r: 4.6, lat: -23.5320, lng: -46.6710, a: true, endereco: 'Rua Turiassu, 400 · Perdizes · São Paulo - SP' },
  { id: 23, n: 'Vitor Green Garden', s: 'Corte de árvores autorizado e jardins verticais', c: 'Jardinagem', p: 390, r: 4.8, lat: -23.5580, lng: -46.6930, a: true, endereco: 'Rua Fradique Coutinho, 1100 · Vila Madalena · São Paulo - SP' },
  { id: 24, n: 'Bruno Redes & Tech', s: 'Cabeamento estruturado e instalação de câmeras CFTV', c: 'Tecnologia', p: 175, r: 4.7, lat: -23.5220, lng: -46.7040, a: true, endereco: 'Rua Doze de Outubro, 380 · Lapa · São Paulo - SP' },
  { id: 25, n: 'Simone Limpeza Prime', s: 'Higienização de carpetes, estofados e vidros', c: 'Limpeza', p: 160, r: 4.9, lat: -23.5710, lng: -46.7090, a: true, endereco: 'Avenida Vital Brasil, 500 · Butantã · São Paulo - SP' },

  // --- GUARULHOS (10) ---
  { id: 26, n: 'Juliana Clean', s: 'Limpeza e higienização residencial', c: 'Limpeza', p: 85, r: 4.9, lat: -23.4628, lng: -46.5333, a: true, endereco: 'Rua do Araújo, 150 · Jardim Beirute · Guarulhos - SP' },
  { id: 27, n: 'Marcos Reparos', s: 'Instalação e reparos elétricos', c: 'Elétrica', p: 95, r: 4.7, lat: -23.4650, lng: -46.5300, a: true, endereco: 'Rua Dom Pedro II, 300 · Centro · Guarulhos - SP' },
  { id: 28, n: 'Fabio Tintas', s: 'Pintura residencial e texturização', c: 'Pintura', p: 320, r: 4.8, lat: -23.4560, lng: -46.5450, a: true, endereco: 'Rua Treze de Maio, 450 · Vila Galvão · Guarulhos - SP' },
  { id: 29, n: 'André Hidráulica Guarulhos', s: 'Desentupimento rápido de pias e ralos', c: 'Encanamento', p: 190, r: 4.5, lat: -23.4540, lng: -46.5210, a: true, endereco: 'Avenida Tiradentes, 1200 · Jardim Paraventi · Guarulhos - SP' },
  { id: 30, n: 'Fernanda Paisagismo Bosque', s: 'Manutenção de grama, plantas ornamentais e podas', c: 'Jardinagem', p: 250, r: 4.9, lat: -23.4600, lng: -46.5160, a: true, endereco: 'Avenida Paulo Faccini, 1800 · Macedo · Guarulhos - SP' },
  { id: 31, n: 'Rodrigo Móveis & Montagens', s: 'Montagem de guarda-roupas, cozinhas e mesas', c: 'Marcenaria', p: 210, r: 4.6, lat: -23.4470, lng: -46.5430, a: true, endereco: 'Rua Doutor Timóteo Penteado, 2200 · Picanço · Guarulhos - SP' },
  { id: 32, n: 'Patricia Faxina & Cuidado', s: 'Diarista residencial e higienização completa', c: 'Limpeza', p: 130, r: 4.8, lat: -23.4750, lng: -46.5400, a: true, endereco: 'Rua Cônego Valadão, 800 · Gopoúva · Guarulhos - SP' },
  { id: 33, n: 'Guilherme Soluções TI', s: 'Instalação de roteadores mesh e reparo de PCs', c: 'Tecnologia', p: 120, r: 4.7, lat: -23.4510, lng: -46.4680, a: true, endereco: 'Avenida Santos Dumont, 1500 · Cumbica · Guarulhos - SP' },
  { id: 34, n: 'Lucas Eletricista Taboão', s: 'Padrão de entrada Enel e curto-circuito', c: 'Elétrica', p: 170, r: 4.4, lat: -23.4310, lng: -46.5020, a: true, endereco: 'Avenida Silvestre Pires de Freitas, 900 · Taboão · Guarulhos - SP' },
  { id: 35, n: 'Marcelo Pinturas Aeroporto', s: 'Pintura predial, residencial e verniz de madeira', c: 'Pintura', p: 350, r: 4.7, lat: -23.4280, lng: -46.4950, a: true, endereco: 'Estrada dos Morros, 450 · Jardim Santa Emília · Guarulhos - SP' }
];

const $ = s => document.querySelector(s);
const brl = v => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const dist = p => {
  if (!mapInstance || p.lat == null || p.lng == null || isNaN(p.lat) || isNaN(p.lng)) return 9999;
  return mapInstance.distance([centerLat, centerLng], [p.lat, p.lng]) / 1000;
};
const notaBayesiana = p => {
  const v = Number(p.total_avaliacoes || 0);
  const r = Number(p.r != null ? p.r : 4.5);
  return (v * r + 5 * 4.5) / (v + 5);
};
const score = p => 1000 * (1 - Math.min(dist(p) / 15, 1)) + notaBayesiana(p) * 100 + (p.a ? 200 : 0);
const STEPS = ['Requisitado', 'Localizado', 'Confirmado', 'Em Trânsito', 'Em Execução', 'Finalizado'];

let cat = 'Todos', radius = 8, busy = false, order = null, timer = null;
let currentOrder = 'distance';
let searchQuery = '';
let onlyAvailable = false;
let loadingDepth = 0;
let simulationTimers = [];
let orderPollTimer = null;
let currentOrderData = null;
let cachedLoggedUser = null;

function atualizarEstadoCarregamento(ativo) {
  const mapEl = document.getElementById('map');
  if (mapEl) {
    let overlay = mapEl.querySelector('.map-loading-overlay');
    if (ativo) {
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'map-loading-overlay';
        overlay.setAttribute('role', 'status');
        overlay.setAttribute('aria-live', 'polite');
        overlay.innerHTML = '<div class="map-spinner" aria-hidden="true"></div><span>Buscando serviços...</span>';
        mapEl.appendChild(overlay);
      }
    } else if (overlay) {
      overlay.remove();
    }
  }

  const painelLista = document.getElementById('painel-lista');
  if (painelLista) {
    let statusEl = painelLista.querySelector('.list-loading-status');
    if (ativo) {
      if (!statusEl) {
        statusEl = document.createElement('div');
        statusEl.className = 'list-loading-status';
        statusEl.setAttribute('role', 'status');
        statusEl.setAttribute('aria-live', 'polite');
        statusEl.innerHTML = '<span class="map-spinner-sm" aria-hidden="true"></span><span>Buscando serviços...</span>';
        const listEl = document.getElementById('list');
        if (listEl && listEl.parentNode === painelLista) {
          painelLista.insertBefore(statusEl, listEl);
        } else {
          painelLista.appendChild(statusEl);
        }
      }
    } else if (statusEl) {
      statusEl.remove();
    }
  }
}

function startLoading() {
  loadingDepth++;
  atualizarEstadoCarregamento(true);
}

function stopLoading() {
  loadingDepth = Math.max(0, loadingDepth - 1);
  if (loadingDepth === 0) {
    atualizarEstadoCarregamento(false);
  }
}

function exibirAlertaRetry(status) {
  let banner = document.getElementById('alertaRetryBanner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'alertaRetryBanner';
    banner.className = 'alerta-retry';
    banner.setAttribute('role', 'alert');
    banner.setAttribute('aria-live', 'assertive');
    document.body.appendChild(banner);
  }
  const codigo = status ? ` (HTTP ${status})` : '';
  banner.innerHTML = `
    <span>Serviço temporariamente ocupado ou indisponível${escapeHtml(codigo)}. Tente novamente em alguns segundos.</span>
    <button type="button" class="alerta-retry-close" aria-label="Fechar aviso">Fechar</button>
  `;
  const btnClose = banner.querySelector('.alerta-retry-close');
  if (btnClose) {
    btnClose.onclick = () => banner.remove();
  }
}

function getServiceScore(p) {
  return p.score != null && !isNaN(p.score) ? Number(p.score) : score(p);
}

function clearAllSimulationTimers() {
  clearTimeout(timer);
  simulationTimers.forEach(t => clearTimeout(t));
  simulationTimers = [];
}
const urlParamsInit = new URLSearchParams(location.search);
const catURL = urlParamsInit.get('cat');
if (catURL) cat = catURL;
const qURL = urlParamsInit.get('q');
if (qURL) searchQuery = qURL.trim();
const orderIdURL = urlParamsInit.get('order_id');

function toast(t) {
  const container = $('#toasts');
  if (!container) return;
  const d = document.createElement('div');
  d.className = 'toast';
  d.textContent = t;
  container.append(d);
  setTimeout(() => d.remove(), 4500);
}

// Sanitização para proteção contra injeções de script (XSS)
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderSkeletonList() {
  const listEl = $('#list');
  if (!listEl) return;
  listEl.innerHTML = [1, 2, 3].map(() => `
    <div class="svc skeleton-card" style="padding: 16px; border-radius: 12px; margin-bottom: 12px;">
      <div class="skeleton" style="height: 20px; width: 60%; margin-bottom: 8px;"></div>
      <div class="skeleton" style="height: 14px; width: 85%; margin-bottom: 8px;"></div>
      <div class="skeleton" style="height: 14px; width: 40%; margin-bottom: 12px;"></div>
      <div class="skeleton" style="height: 36px; width: 100%; border-radius: 9999px;"></div>
    </div>
  `).join('');
}

// Carregar prestadores da API se disponível
async function carregarPrestadoresAPI() {
  startLoading();
  renderSkeletonList();
  try {
    const params = new URLSearchParams({
      cat,
      radius: String(radius),
      lat: String(centerLat),
      lng: String(centerLng),
      order: currentOrder
    });
    if (searchQuery) params.set('query', searchQuery);
    if (onlyAvailable) params.set('only_available', '1');

    const url = `/api/services?${params.toString()}`;
    let res = await fetch(url);
    if (res.status === 429 || res.status >= 500) {
      await new Promise(resolve => setTimeout(resolve, 800));
      try {
        res = await fetch(url);
      } catch (_) {}
    }

    if (res.status === 429 || res.status >= 500) {
      if (document.getElementById('list') || document.getElementById('map')) {
        exibirAlertaRetry(res.status);
      }
    } else if (res.ok) {
      document.getElementById('alertaRetryBanner')?.remove();
      const data = await res.json();
      if (Array.isArray(data)) {
        P = data.map(item => ({
          id: item.id,
          service_id: item.id,
          n: item.prestador ? item.prestador.nome : 'Profissional',
          s: item.titulo,
          c: item.categoria,
          p: item.preco,
          r: item.prestador ? item.prestador.avaliacao : 5.0,
          total_avaliacoes: item.prestador ? (item.prestador.total_avaliacoes || 0) : 0,
          super_profissional: Boolean(item.prestador && item.prestador.super_profissional),
          kyc_tier: item.prestador && item.prestador.kyc_tier != null ? item.prestador.kyc_tier : 1,
          kyc_status: item.prestador && item.prestador.kyc_status ? item.prestador.kyc_status : 'aprovado',
          novo_no_pertoja: Boolean((item.score_detalhes && item.score_detalhes.novo_no_pertoja) || ((item.prestador ? (item.prestador.total_avaliacoes || 0) : 0) < 5)),
          localizacao_aproximada: item.localizacao_aproximada !== undefined ? Boolean(item.localizacao_aproximada) : true,
          lat: (item.prestador && item.prestador.lat != null) ? item.prestador.lat : item.lat,
          lng: (item.prestador && item.prestador.lng != null) ? item.prestador.lng : item.lng,
          a: item.prestador ? item.prestador.disponivel : true,
          endereco: item.endereco ? item.endereco.completo : (item.endereco_completo || 'São Paulo - SP'),
          bairro: item.endereco ? item.endereco.bairro : (item.bairro || ''),
          cidade: item.endereco ? item.endereco.cidade : (item.cidade || 'São Paulo'),
          distancia: item.distancia_km,
          score: item.score != null ? item.score : null
        }));
      }
    }
  } catch (e) {
    console.log('Utilizando base de prestadores local/fallback.');
  } finally {
    stopLoading();
  }
}

function visible() {
  const qNorm = searchQuery.trim().toLowerCase();
  return P.filter(p => {
    if (mapInstance && dist(p) > radius) return false;
    if (cat !== 'Todos' && p.c.toLowerCase() !== cat.toLowerCase()) return false;
    if (onlyAvailable && !p.a) return false;
    if (qNorm) {
      const haystack = [p.s, p.n, p.c, p.bairro, p.cidade, p.endereco].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(qNorm)) return false;
    }
    return true;
  });
}

function getCategoryIcon(catName) {
  const mapa = {
    limpeza: 'cleaning_services',
    'elétrica': 'bolt',
    eletrica: 'bolt',
    encanamento: 'plumbing',
    pintura: 'format_paint',
    jardinagem: 'yard',
    tecnologia: 'computer',
    marcenaria: 'carpenter'
  };
  return mapa[(catName || '').toLowerCase()] || 'handyman';
}

function renderChips() {
  const chipsEl = $('#chips');
  if (!chipsEl) return;
  const cats = ['Todos', 'Limpeza', 'Elétrica', 'Encanamento', 'Pintura', 'Jardinagem', 'Tecnologia', 'Marcenaria'];
  chipsEl.innerHTML = cats.map(c => {
    const isSelected = c.toLowerCase() === cat.toLowerCase();
    return `<button type="button" class="chip ${isSelected ? 'on' : ''}" data-c="${c}" aria-pressed="${isSelected}" aria-label="Filtrar por categoria ${c}">${c}</button>`;
  }).join('');
}

function renderList() {
  const listEl = $('#list');
  if (!listEl) return;
  const v = visible().sort((a, b) => {
    if (currentOrder === 'score') {
      return (getServiceScore(b) - getServiceScore(a)) || (dist(a) - dist(b));
    }
    return dist(a) - dist(b);
  });
  if ($('#count')) $('#count').textContent = '(' + v.length + ')';
  listEl.innerHTML = v.length ? v.map(p => {
    const svcScore = Math.round(getServiceScore(p));
    const isSuper = p.super_profissional || (p.r >= 4.8 && (p.total_avaliacoes || 0) >= 5);
    const isNovo = Boolean(p.novo_no_pertoja || ((p.total_avaliacoes || 0) < 5));
    const kycTier = p.kyc_tier || 1;
    const iconName = getCategoryIcon(p.c);
    return `
   <div class="svc ${order && order.best && order.best.id === p.id ? 'best' : ''}">
     <div class="svc-card-row">
       <div class="svc-avatar" aria-hidden="true">
         <span class="material-symbols-outlined">${iconName}</span>
       </div>
       <div class="flex-1 min-w-0">
         <div class="top">
           <span>${escapeHtml(p.s)}</span>
           <span class="price">${brl(p.p)}</span>
         </div>
         <div class="text-xs font-semibold text-perto-sea mt-0.5 flex items-center gap-1 truncate">
           <span aria-hidden="true">📍</span>
           <span class="truncate">${escapeHtml(p.endereco || 'São Paulo - SP')}${p.localizacao_aproximada ? ' · Região aproximada' : ''}</span>
         </div>
         <div class="meta mt-1.5">
           <span><span aria-hidden="true">👤</span> ${escapeHtml(p.n)}</span>
           <span>★ ${p.r.toFixed(1)}</span>
           <span>${dist(p).toFixed(1)} km</span>
           <span class="score-badge" title="Score: Proximidade (15 km) + Nota Bayesiana + Disponibilidade" aria-label="Score ${svcScore}. Score: Proximidade (15 km) + Nota Bayesiana + Disponibilidade">Score ${svcScore}</span>
           <span class="kyc-badge aprovado" title="Identidade checada por nível de risco">Tier ${escapeHtml(String(kycTier))}</span>
           ${isNovo ? '<span class="novo-badge">Novo no PertoJá</span>' : ''}
           ${isSuper ? '<span class="super-badge">★ Super Profissional</span>' : ''}
           <span class="tag ${p.a ? '' : 'off'}">${p.a ? 'Disponível' : 'Indisponível'}</span>
         </div>
       </div>
     </div>
     <div class="mt-2.5 flex justify-end">
       <button type="button" class="btn btn-requisitar" data-req="${Number(p.id)}" aria-label="Requisitar atendimento de ${escapeHtml(p.n)} para ${escapeHtml(p.s)}" ${(!p.a || busy) ? 'disabled' : ''}>Requisitar Atendimento</button>
     </div>
    </div>`;
  }).join('') : `
     <div class="empty-state-card" role="status" aria-live="polite">
       <p class="empty-title">Nenhum serviço encontrado nesta área</p>
       <p class="empty-desc">Não encontramos profissionais disponíveis neste raio de ${radius} km. Experimente expandir o raio de busca.</p>
       <button type="button" class="btn" data-action="expand-radius" aria-label="Expandir raio de busca para 15 km" style="font-size: 0.82rem; padding: 8px 16px; border-radius: 9999px;">
         Expandir raio para 15 km
       </button>
     </div>`;
}

function renderMap(posAtual) {
  if (!mapInstance || !layerMarkers) return;
  layerMarkers.clearLayers();

  // Círculo de cobertura do raio de busca selecionado
  L.circle([centerLat, centerLng], { radius: radius * 1000, color: '#1f6f8b', fillOpacity: 0.07, weight: 2 }).addTo(layerMarkers);

  // Marcador da posição pesquisada pelo cliente
  const searchMarker = L.circleMarker([centerLat, centerLng], {
    radius: 11,
    color: '#ffffff',
    fillColor: '#1f6f8b',
    fillOpacity: 1,
    weight: 3
  });
  searchMarker.bindTooltip("Sua Localização de Busca", { permanent: true, direction: 'right', className: 'map-label' });
  searchMarker.bindPopup(`
    <div style="font-family: inherit; font-size: 0.85rem; min-width: 190px;">
      <h4 style="margin: 0 0 4px; color: #10243e; font-size: 0.95rem;">📍 Local Pesquisado</h4>
      <div style="color: var(--sea); font-weight: 700; margin-bottom: 4px;">${escapeHtml(currentSearchAddress || 'Endereço atual')}</div>
      <div style="font-size: 0.75rem; color: #666;">Coordenadas: ${centerLat.toFixed(5)}, ${centerLng.toFixed(5)}</div>
    </div>
  `);
  searchMarker.addTo(layerMarkers);

  visible().forEach(p => {
    const isBest = order && order.best.id === p.id;
    if (isBest && posAtual) return;
    let color = isBest ? '#ffc233' : p.a ? '#1a8f5a' : '#9aa7b1';
    const marker = L.circleMarker([p.lat, p.lng], {
      radius: isBest ? 11 : 8,
      color: '#10243e',
      fillColor: color,
      fillOpacity: 1,
      weight: isBest ? 3 : 1.5
    });
    marker.bindTooltip(escapeHtml(p.n.split(' ')[0]), { permanent: true, direction: 'right', className: 'map-label' });
    const isAvail = p.a && !busy;
    marker.bindPopup(`
      <div style="font-family: inherit; font-size: 0.85rem; min-width: 170px;">
        <h4 style="margin: 0 0 4px; color: #10243e; font-size: 0.95rem;">${escapeHtml(p.s)}</h4>
        <div style="color: var(--sea); font-weight: 800; font-size: 1rem; margin-bottom: 4px;">${brl(p.p)}</div>
        <div style="color: #444; margin-bottom: 3px;">👤 <b>${escapeHtml(p.n)}</b> · ★ ${p.r.toFixed(1)}</div>
        <div style="color: #666; font-size: 0.75rem; margin-bottom: 4px;">📍 ${escapeHtml(p.endereco || 'São Paulo - SP')}${p.localizacao_aproximada ? ' (região aproximada)' : ''}</div>
        ${p.localizacao_aproximada ? '<div style="color: #4b6073; font-size: 0.72rem; margin-bottom: 4px;">🔒 Localização aproximada na vitrine para proteção de privacidade</div>' : ''}
        <div style="color: var(--ok); font-weight: bold; font-size: 0.8rem; margin-bottom: 8px;">A ${dist(p).toFixed(1)} km de você</div>
        <button type="button" class="btn btn-requisitar" data-request-id="${Number(p.id)}" aria-label="Requisitar atendimento de ${escapeHtml(p.n)}" style="width: 100%; min-height: 38px; font-size: 0.82rem; padding: 8px 14px; ${isAvail ? '' : 'opacity: 0.55; cursor: not-allowed;'}" ${isAvail ? '' : 'disabled'}>
          ${isAvail ? 'Requisitar Agora' : (busy ? 'Atendimento em Andamento' : 'Indisponível no Momento')}
        </button>
      </div>
    `);
    marker.addTo(layerMarkers);
  });

  if (order && posAtual) {
    L.polyline([[posAtual.lat, posAtual.lng], [centerLat, centerLng]], { color: '#ffc233', dashArray: '6, 6', weight: 3 }).addTo(layerMarkers);
    L.circleMarker([posAtual.lat, posAtual.lng], { radius: 12, color: '#10243e', fillColor: '#ffc233', fillOpacity: 1, weight: 3 })
      .bindTooltip(escapeHtml(order.best.n.split(' ')[0]), { permanent: true, direction: 'right', className: 'map-label' }).addTo(layerMarkers);
  }
}

async function buscarPorEnderecoCliente() {
  const input = document.getElementById('inputBuscaEndereco');
  if (!input || !input.value.trim()) return;
  const q = input.value.trim();
  const cleanCep = q.replace(/\D/g, '');

  toast('Buscando localização...');
  startLoading();
  try {
    let lat = null, lng = null, label = q;

    // 1. Caso o termo seja um CEP numérico com 8 dígitos
    if (cleanCep.length === 8) {
      try {
        const res = await fetch(`/api/cep/${cleanCep}`);
        if (res.status === 429 || res.status >= 500) {
          exibirAlertaRetry(res.status);
        } else if (res.ok) {
          const d = await res.json();
          lat = d.lat != null ? parseFloat(d.lat) : null;
          lng = d.lng != null ? parseFloat(d.lng) : null;
          const partes = [d.logradouro, d.bairro, d.localidade ? `${d.localidade}${d.uf ? ' - ' + d.uf : ''}` : ''].filter(Boolean);
          label = partes.length ? partes.join(', ') : (d.cep || q);
        }
      } catch (errApi) {
        console.warn('API local de CEP indisponível, recorrendo a fallbacks cliente:', errApi);
      }

      // Fallback cliente: dados do logradouro via ViaCEP/BrasilAPI + geocodificação de rua via Nominatim
      if ((lat == null || lng == null || isNaN(lat) || isNaN(lng)) && typeof fetch !== 'undefined') {
        let street = '', bairro = '', city = '', uf = '';
        try {
          const resV = await fetch(`https://viacep.com.br/ws/${cleanCep}/json/`);
          if (resV.ok) {
            const dV = await resV.json();
            if (!dV.erro) {
              street = dV.logradouro || '';
              bairro = dV.bairro || '';
              city = dV.localidade || '';
              uf = dV.uf || '';
              const partes = [street, bairro, city ? `${city}${uf ? ' - ' + uf : ''}` : ''].filter(Boolean);
              label = partes.length ? partes.join(', ') : label;
            }
          }
        } catch (errV) {}

        if (!city) {
          try {
            const resB = await fetch(`https://brasilapi.com.br/api/cep/v2/${cleanCep}`);
            if (resB.ok) {
              const dB = await resB.json();
              street = dB.street || street;
              bairro = dB.neighborhood || bairro;
              city = dB.city || city;
              uf = dB.state || uf;
              const partes = [street, bairro, city ? `${city}${uf ? ' - ' + uf : ''}` : ''].filter(Boolean);
              label = partes.length ? partes.join(', ') : label;
            }
          } catch (errB) {}
        }

        // Tenta geocodificar com prioridade para rua e bairro exatos
        const cands = [];
        if (street) {
          if (bairro && city) cands.push([street, bairro, city, uf].filter(Boolean).join(', ') + ', Brasil');
          if (city) cands.push([street, city, uf].filter(Boolean).join(', ') + ', Brasil');
        }
        if (bairro && city) cands.push([bairro, city, uf].filter(Boolean).join(', ') + ', Brasil');
        if (city) cands.push([city, uf].filter(Boolean).join(' - ') + ', Brasil');

        for (const cand of cands) {
          try {
            const rNom = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(cand)}&limit=1`);
            if (rNom.ok) {
              const resNom = await rNom.json();
              if (resNom && resNom.length > 0) {
                lat = parseFloat(resNom[0].lat);
                lng = parseFloat(resNom[0].lon);
                break;
              }
            }
          } catch (eN) {}
        }
      }
    }

    // 2. Se não for CEP ou se o CEP ainda não tiver coordenadas: busca por geocodificação
    if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) {
      try {
        const resG = await fetch(`/api/geocode?q=${encodeURIComponent(q + ', Brasil')}`);
        if (resG.status === 429 || resG.status >= 500) {
          exibirAlertaRetry(resG.status);
        } else if (resG.ok) {
          const d = await resG.json();
          if (d.lat != null && d.lng != null) {
            lat = parseFloat(d.lat);
            lng = parseFloat(d.lng);
          }
        }
      } catch (errG) {}

      // Fallback direto Nominatim cliente para busca livre
      if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) {
        try {
          const rNom = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(q + ', Brasil')}&limit=1`);
          if (rNom.ok) {
            const resNom = await rNom.json();
            if (resNom && resNom.length > 0) {
              lat = parseFloat(resNom[0].lat);
              lng = parseFloat(resNom[0].lon);
            }
          }
        } catch (eN) {}
      }
    }

    // 3. Aplica coordenadas reais no mapa e atualiza interface
    if (lat != null && lng != null && !isNaN(lat) && !isNaN(lng)) {
      centerLat = lat;
      centerLng = lng;
      currentSearchAddress = label;

      if (mapInstance) {
        mapInstance.setView([centerLat, centerLng], 14, { animate: true });
        setTimeout(() => {
          if (mapInstance) mapInstance.invalidateSize();
        }, 200);
      }

      const locInfo = document.getElementById('locInfo');
      if (locInfo) locInfo.textContent = `Ponto de busca: ${label}`;

      const statusBox = document.getElementById('statusBuscaEndereco');
      if (statusBox) {
        statusBox.style.display = 'flex';
        statusBox.innerHTML = `<span class="material-symbols-outlined text-sm text-perto-ok">check_circle</span> <span>Endereço localizado: <b>${escapeHtml(label)}</b></span>`;
      }

      toast(`Localização definida: ${label}`);
      await carregarPrestadoresAPI();
      renderAll();
    } else {
      toast('Endereço ou CEP não localizado no mapa.');
    }
  } catch (e) {
    console.error('Erro ao buscar localização:', e);
    toast('Erro ao buscar localização.');
  } finally {
    stopLoading();
  }
}

function renderSteps(i) {
  const stepsEl = $('#steps');
  if (stepsEl) {
    stepsEl.innerHTML = STEPS.map((t, k) => `<span class="step ${k < i ? 'done' : k === i ? 'now' : ''}">${t}</span>`).join('');
  }
}

function info(h) {
  const infoEl = $('#info');
  if (infoEl) infoEl.innerHTML = '<p>' + h + '</p>';
}

// Modal Acessível de Autenticação Obrigatória no Checkout
function exibirModalAuthObrigatoria(pendingOrder) {
  const triggerEl = document.activeElement;
  let modalBackdrop = document.getElementById('modalAuthCheckout');
  if (!modalBackdrop) {
    modalBackdrop = document.createElement('div');
    modalBackdrop.id = 'modalAuthCheckout';
    modalBackdrop.className = 'modal-backdrop';
    modalBackdrop.setAttribute('role', 'dialog');
    modalBackdrop.setAttribute('aria-modal', 'true');
    modalBackdrop.setAttribute('aria-labelledby', 'modalAuthTitulo');
    document.body.appendChild(modalBackdrop);
  }

  modalBackdrop.innerHTML = `
    <div class="modal-conteudo" style="max-width: 460px; text-align: center;">
      <div style="width: 54px; height: 54px; border-radius: 50%; background: rgba(0, 150, 166, 0.12); color: var(--sea); display: flex; align-items: center; justify-content: center; margin: 0 auto 16px;">
        <span class="material-symbols-outlined" aria-hidden="true" style="font-size: 28px;">lock</span>
      </div>
      <h3 id="modalAuthTitulo" style="color: var(--ink); font-size: 1.35rem; font-weight: 900; margin: 0 0 8px;">Identificação Obrigatória</h3>
      <p style="color: #4b6073; font-size: 0.9rem; margin: 0 0 16px; line-height: 1.45;">
        Para concluir a solicitação de <b>${escapeHtml(pendingOrder.titulo)}</b> por <b>${brl(pendingOrder.preco)}</b> com <b>${escapeHtml(pendingOrder.prestador_nome)}</b>, você precisa estar conectado como Cliente.
      </p>
      <div style="background: var(--bg); border: 1px solid var(--road); border-radius: 12px; padding: 12px; margin-bottom: 20px; font-size: 0.8rem; color: #2e384d; text-align: left; display: flex; align-items: center; gap: 8px;">
        <span class="material-symbols-outlined" aria-hidden="true" style="font-size: 18px; color: var(--sea);">bookmark_check</span>
        <span>Seus itens selecionados e endereço foram salvos e serão restaurados após o acesso!</span>
      </div>
      <div style="display: flex; flex-direction: column; gap: 10px;">
        <a href="login.html?redirect=pedido.html&pending_order=true" class="btn" aria-label="Entrar na minha conta" style="width: 100%; padding: 12px; font-weight: 800; border-radius: 9999px; text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--ink);">
          <span class="material-symbols-outlined" aria-hidden="true" style="font-size: 18px;">login</span> Entrar na Minha Conta
        </a>
        <a href="cadastro.html?redirect=pedido.html&pending_order=true" class="btn2" aria-label="Criar cadastro gratuito" style="width: 100%; padding: 10px; font-weight: 700; border-radius: 9999px; text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 6px;">
          <span class="material-symbols-outlined" aria-hidden="true" style="font-size: 18px;">person_add</span> Criar Cadastro Gratuito
        </a>
        <button type="button" id="btnFecharModalAuth" aria-label="Cancelar e continuar navegando" style="background: none; border: none; font-size: 0.85rem; color: #4b6073; font-weight: 600; cursor: pointer; padding: 8px; margin-top: 4px;">
          Cancelar e Continuar Navegando
        </button>
      </div>
    </div>
  `;

  const fecharModalAuth = () => {
    modalBackdrop.style.display = 'none';
    document.removeEventListener('keydown', onModalKeyDown);
    if (triggerEl && typeof triggerEl.focus === 'function') {
      triggerEl.focus();
    }
  };

  const onModalKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      fecharModalAuth();
    }
  };

  modalBackdrop.style.display = 'flex';
  document.addEventListener('keydown', onModalKeyDown);

  const btnFechar = modalBackdrop.querySelector('#btnFecharModalAuth');
  if (btnFechar) {
    btnFechar.onclick = fecharModalAuth;
  }
  const firstAction = modalBackdrop.querySelector('a.btn') || btnFechar;
  if (firstAction && typeof firstAction.focus === 'function') {
    setTimeout(() => firstAction.focus(), 0);
  }
  modalBackdrop.onclick = (e) => {
    if (e.target === modalBackdrop) {
      fecharModalAuth();
    }
  };
}

// Banner e Restauração de Pedido Pendente Pós-autenticação
async function verificarERestaurarPedidoPendente() {
  const legacyPending = localStorage.getItem('pertoja_pending_order');
  if (legacyPending) {
    if (!sessionStorage.getItem('pertoja_pending_order')) {
      try { sessionStorage.setItem('pertoja_pending_order', legacyPending); } catch (e) {}
    }
    try { localStorage.removeItem('pertoja_pending_order'); } catch (e) {}
  }
  const rawPending = sessionStorage.getItem('pertoja_pending_order');
  if (!rawPending) return;

  let pending;
  try {
    pending = JSON.parse(rawPending);
  } catch (e) {
    sessionStorage.removeItem('pertoja_pending_order');
    localStorage.removeItem('pertoja_pending_order');
    return;
  }

  // Verifica se o usuário atual está autenticado como cliente
  const user = typeof obterUsuarioLogado === 'function' ? await obterUsuarioLogado() : null;
  if (!user || user.tipo !== 'cliente') return;

  const mainContainer = document.getElementById('main-content');
  if (!mainContainer || document.getElementById('bannerRestaurarPedido')) return;

  const banner = document.createElement('div');
  banner.id = 'bannerRestaurarPedido';
  banner.className = 'panel border-2 border-perto-sea bg-perto-sea/5 p-4 rounded-2xl flex flex-col sm:flex-row items-center justify-between gap-3 shadow-sm mb-4';
  banner.innerHTML = `
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-full bg-perto-sea text-white flex items-center justify-center font-bold shrink-0">
        <span class="material-symbols-outlined text-lg">restore</span>
      </div>
      <div>
        <div class="text-xs font-extrabold text-perto-sea uppercase tracking-wider">Pedido Pendente Recuperado</div>
        <div class="text-sm font-bold text-perto-ink">${escapeHtml(pending.titulo)} · ${brl(pending.preco)} (${escapeHtml(pending.prestador_nome)})</div>
        <div class="text-xs text-perto-ink/70">Você já está conectado! Deseja concluir a solicitação agora?</div>
      </div>
    </div>
    <div class="flex items-center gap-2 shrink-0">
      <button id="btnConfirmarPedidoPendente" class="btn text-xs font-bold px-4 py-2 rounded-xl text-perto-ink shadow-sm">
        Confirmar e Solicitar
      </button>
      <button id="btnDescartarPedidoPendente" class="btn2 text-xs font-semibold px-3 py-2 rounded-xl">
        Descartar
      </button>
    </div>
  `;

  mainContainer.insertBefore(banner, mainContainer.firstChild);

  banner.querySelector('#btnConfirmarPedidoPendente').onclick = async () => {
    banner.remove();
    sessionStorage.removeItem('pertoja_pending_order');
    localStorage.removeItem('pertoja_pending_order');
    await request(pending.service_id);
  };

  banner.querySelector('#btnDescartarPedidoPendente').onclick = () => {
    banner.remove();
    sessionStorage.removeItem('pertoja_pending_order');
    localStorage.removeItem('pertoja_pending_order');
    toast('Pedido pendente descartado.');
  };
}

function pararPollingPedido() {
  if (orderPollTimer) {
    clearInterval(orderPollTimer);
    orderPollTimer = null;
  }
}

function mapStatusToStep(status) {
  const s = (status || '').toLowerCase();
  if (s === 'solicitado') return 1;
  if (s === 'confirmado') return 2;
  if (s === 'em_transito') return 3;
  if (s === 'em_execucao') return 4;
  if (s === 'finalizado') return 5;
  return 0;
}

function atualizarCodigoConfirmacao(codigo) {
  const box = document.getElementById('codigoConfirmacaoBox');
  const val = document.getElementById('codigoConfirmacaoValor');
  if (!box || !val) return;
  if (codigo) {
    val.textContent = codigo;
    box.hidden = false;
  } else {
    box.hidden = true;
  }
}

function atualizarPaineisSegurancaPedido(status, pedidoApi) {
  const segBar = document.getElementById('pedidoSegurancaBar');
  const chatSec = document.getElementById('pedidoChatSection');
  const sharedBox = document.getElementById('sharedRouteBox');
  const sharedLink = document.getElementById('sharedRouteLink');
  const st = String(status || '').toLowerCase();
  const ativo = st === 'confirmado' || st === 'em_transito' || st === 'em_execucao';
  const encerrado = st === 'finalizado' || st === 'cancelado';

  if (segBar) segBar.hidden = !ativo;
  if (chatSec) chatSec.hidden = !(ativo || st === 'em_disputa' || encerrado);

  const chatInput = document.getElementById('inputPedidoChatMsg');
  const chatBtn = document.getElementById('btnEnviarPedidoChat');
  const formChat = document.getElementById('formPedidoChat');
  let roNotice = document.getElementById('pedidoChatReadOnlyNotice');
  if (!roNotice && formChat && formChat.parentNode) {
    roNotice = document.createElement('p');
    roNotice.id = 'pedidoChatReadOnlyNotice';
    roNotice.className = 'text-xs font-bold text-perto-ink bg-perto-sun/25 border border-perto-sun rounded-lg px-3 py-2 mb-2';
    roNotice.setAttribute('role', 'status');
    roNotice.textContent = 'Chat encerrado (somente leitura)';
    roNotice.hidden = true;
    formChat.parentNode.insertBefore(roNotice, formChat);
  }
  if (chatInput) {
    chatInput.disabled = encerrado;
    chatInput.placeholder = encerrado ? 'Chat encerrado (somente leitura)' : 'Escreva uma mensagem...';
  }
  if (chatBtn) chatBtn.disabled = encerrado;
  if (roNotice) roNotice.hidden = !encerrado;

  if (ativo && pedidoApi && pedidoApi.share_token && sharedBox && sharedLink) {
    const url = `${window.location.origin}/api/shared-route/${encodeURIComponent(pedidoApi.share_token)}`;
    sharedLink.href = url;
    sharedLink.textContent = url;
    sharedBox.hidden = false;
  } else if (!ativo && sharedBox) {
    sharedBox.hidden = true;
  }
}

async function carregarMensagensPedido(orderDbId) {
  const box = document.getElementById('pedidoChatMessages');
  if (!box || !orderDbId) return;
  try {
    const res = await fetch(`/api/orders/${orderDbId}/messages`);
    if (!res.ok) return;
    const msgs = await res.json();
    if (!Array.isArray(msgs) || !msgs.length) {
      box.innerHTML = '<p class="text-perto-ink/60 text-xs m-0">Nenhuma mensagem ainda. Use este canal interno para combinar detalhes do atendimento.</p>';
      return;
    }
    const myId = cachedLoggedUser && cachedLoggedUser.id;
    box.innerHTML = msgs.map(m => {
      const isMine = myId && String(m.sender_id) === String(myId);
      const autor = escapeHtml(m.sender_nome || m.sender_tipo || (isMine ? 'Você' : 'Profissional'));
      const texto = escapeHtml(m.mensagem || m.conteudo || '');
      const rawTs = m.criado_em || m.created_at;
      const hora = rawTs ? escapeHtml(String(rawTs).slice(11, 16)) : '';
      return `
        <div class="chat-msg ${isMine ? 'mine bg-perto-sea/10 border-perto-sea/30 ml-6' : 'bg-perto-bg border-perto-road mr-6'} p-2 rounded-lg border">
          <div class="flex items-center justify-between gap-2 text-[10px] font-bold text-perto-ink/70 mb-0.5">
            <span>${autor}</span>
            ${hora ? `<span>${hora}</span>` : ''}
          </div>
          <div class="text-xs text-perto-ink break-words">${texto}</div>
        </div>
      `;
    }).join('');
    box.scrollTop = box.scrollHeight;
  } catch (e) {}
}

function atualizarUIStatusPedido(pedidoApi, best) {
  if (!pedidoApi || !order) return;
  currentOrderData = pedidoApi;
  if (pedidoApi.codigo_confirmacao) {
    atualizarCodigoConfirmacao(pedidoApi.codigo_confirmacao);
  }
  const status = (pedidoApi.status || 'solicitado').toLowerCase();
  const metodoPg = String(pedidoApi.metodo_pagamento || '').toLowerCase();
  const precisaPagar = !pedidoApi.pago && (
    status === 'finalizado' ||
    (['pix', 'cartao', 'boleto'].includes(metodoPg) && ['solicitado', 'confirmado', 'em_transito', 'em_execucao'].includes(status))
  );
  if ($('#pay')) $('#pay').hidden = !precisaPagar;
  const avisoPg = precisaPagar ? ' <span class="font-semibold text-amber-700">Pagamento pendente — conclua pelo botão Pagar.</span>' : '';

  const stepIdx = mapStatusToStep(status);
  renderSteps(stepIdx);
  atualizarPaineisSegurancaPedido(status, pedidoApi);
  if (order.db_id && ['confirmado', 'em_transito', 'em_execucao', 'em_disputa', 'finalizado', 'cancelado'].includes(status)) {
    carregarMensagensPedido(order.db_id);
  }

  if (status === 'solicitado') {
    info(`Aguardando confirmação de <b>${escapeHtml(best.n)}</b> para <b>${escapeHtml(best.s)}</b>…${avisoPg}`);
  } else if (status === 'confirmado') {
    info(`<b>${escapeHtml(best.n)}</b> confirmou o atendimento e está se preparando para sair.${avisoPg}`);
  } else if (status === 'em_transito') {
    if (precisaPagar) {
      info(`<b>${escapeHtml(best.n)}</b> está a caminho.${avisoPg}`);
    }
    if (!order.drivingStarted) {
      order.drivingStarted = true;
      toast(`${best.n} iniciou o deslocamento até seu endereço.`);
      driveVisualOnly(best);
    }
  } else if (status === 'em_execucao') {
    clearAllSimulationTimers();
    order.pos = { lat: centerLat, lng: centerLng };
    renderMap(order.pos);
    info(`<b>${escapeHtml(best.n)}</b> está no local executando o serviço.${avisoPg}`);
  } else if (status === 'finalizado') {
    clearAllSimulationTimers();
    pararPollingPedido();
    order.pos = { lat: centerLat, lng: centerLng };
    renderMap(order.pos);
    info(`Ordem de serviço concluída com sucesso!${avisoPg}`);
    if ($('#pay')) $('#pay').hidden = !precisaPagar;
    if ($('#novo')) $('#novo').hidden = false;
    const btnAvaliar = document.getElementById('btnAvaliarAtendimento');
    if (btnAvaliar) btnAvaliar.hidden = Boolean(pedidoApi.ja_avaliado);
  } else if (status === 'cancelado') {
    clearAllSimulationTimers();
    pararPollingPedido();
    sessionStorage.removeItem('pertoja_active_order_id');
    localStorage.removeItem('pertoja_active_order_id');
    info(`Pedido cancelado.${pedidoApi.motivo_cancelamento ? ' Motivo: ' + escapeHtml(pedidoApi.motivo_cancelamento) : ''}`);
    if ($('#pay')) $('#pay').hidden = true;
    if ($('#novo')) $('#novo').hidden = false;
    const btnAvaliar = document.getElementById('btnAvaliarAtendimento');
    if (btnAvaliar) btnAvaliar.hidden = true;
  }
}

async function buscarEstadoPedidoReal(orderDbId) {
  try {
    const res = await fetch('/api/orders');
    if (!res.ok) return null;
    const list = await res.json();
    if (!Array.isArray(list)) return null;
    return list.find(o => String(o.order_id) === String(orderDbId)) || null;
  } catch (e) {
    return null;
  }
}

function iniciarPollingPedido(orderDbId, best) {
  pararPollingPedido();
  orderPollTimer = setInterval(async () => {
    if (!order || String(order.db_id) !== String(orderDbId)) {
      pararPollingPedido();
      return;
    }
    const found = await buscarEstadoPedidoReal(orderDbId);
    if (found) {
      atualizarUIStatusPedido(found, best);
    }
  }, 8000);
}

function driveVisualOnly(best) {
  const n = 8;
  let k = 0;
  const tick = () => {
    k++;
    if (!order) return;
    order.gps++;
    if ($('#gps')) $('#gps').textContent = order.gps;
    const f = Math.min(k / n, 0.92);
    order.pos = {
      lat: best.lat * (1 - f) + centerLat * f,
      lng: best.lng * (1 - f) + centerLng * f
    };
    const left = mapInstance ? (mapInstance.distance([order.pos.lat, order.pos.lng], [centerLat, centerLng]) / 1000) : 0;
    info(left > 0.05
      ? `O profissional encontra-se a <b>${left.toFixed(1)} km</b> · Estimativa de chegada: ${Math.max(1, Math.round(left * 3))} min.`
      : 'O profissional está chegando ao seu endereço.');
    renderMap(order.pos);
    if (k < n && currentOrderData && (currentOrderData.status === 'em_transito' || !currentOrderData.status)) {
      const isBat = $('#bat') && $('#bat').checked;
      timer = setTimeout(tick, isBat ? 2500 : 1200);
      simulationTimers.push(timer);
    }
  };
  timer = setTimeout(tick, 1000);
  simulationTimers.push(timer);
}

function iniciarTrackingPedido(orderDbId, best, initialData = {}) {
  busy = true;
  order = {
    best,
    pos: { lat: best.lat != null ? best.lat : centerLat, lng: best.lng != null ? best.lng : centerLng },
    gps: 0,
    db_id: orderDbId,
    drivingStarted: false
  };
  best.a = false;

  if (orderDbId) {
    try {
      sessionStorage.setItem('pertoja_active_order_id', String(orderDbId));
      localStorage.removeItem('pertoja_active_order_id');
    } catch (e) {}
  }

  if ($('#painel-lista')) $('#painel-lista').hidden = true;
  if ($('#pedidoBox')) $('#pedidoBox').hidden = false;
  if ($('#pay')) $('#pay').hidden = true;
  if ($('#novo')) $('#novo').hidden = true;
  const btnAvaliar = document.getElementById('btnAvaliarAtendimento');
  if (btnAvaliar) btnAvaliar.hidden = true;
  if ($('#gps')) $('#gps').textContent = 0;

  atualizarCodigoConfirmacao(initialData.codigo_confirmacao || '');

  const cands = P.filter(p => p.c && best.c && p.c.toLowerCase() === best.c.toLowerCase() && dist(p) <= radius)
    .map(p => ({ p, score: score(p) }))
    .sort((a, b) => b.score - a.score);

  if ($('#rank')) {
    $('#rank').innerHTML = '<tr><th>Profissional</th><th>Distância</th><th>Avaliação</th><th>Score</th></tr>' +
      cands.map(c => `<tr class="${c.p.id === best.id ? 'win' : ''}"><td>${escapeHtml(c.p.n)}</td><td>${dist(c.p).toFixed(1)} km</td><td>★ ${c.p.r.toFixed(1)}</td><td>${Math.round(c.score)}</td></tr>`).join('');
  }

  renderAll();
  atualizarUIStatusPedido({ status: initialData.status || 'solicitado', ...initialData }, best);
  iniciarPollingPedido(orderDbId, best);
}

async function carregarPedidoAtivoPorId(orderDbId) {
  if (!orderDbId) return;
  const user = cachedLoggedUser || (typeof obterUsuarioLogado === 'function' ? await obterUsuarioLogado() : null);
  if (!user || user.tipo !== 'cliente') return;
  const found = await buscarEstadoPedidoReal(orderDbId);
  if (!found) return;

  const best = P.find(p => String(p.id) === String(found.servico_id) || p.n === found.prestador_nome) || {
    id: found.servico_id || found.prestador_id || 0,
    service_id: found.servico_id || 0,
    n: found.prestador_nome || 'Profissional',
    s: found.servico_titulo || 'Serviço Solicitado',
    c: found.servico_categoria || 'Geral',
    p: found.preco_total || 0,
    r: 5.0,
    lat: found.prestador_lat != null ? Number(found.prestador_lat) : centerLat,
    lng: found.prestador_lng != null ? Number(found.prestador_lng) : centerLng,
    a: false
  };
  iniciarTrackingPedido(found.order_id, best, found);
}

function abrirModalConfirmarPedido(sel, user) {
  const modal = document.getElementById('modalConfirmarPedido');
  if (!modal) return;
  const triggerEl = document.activeElement;

  document.getElementById('confTitulo').textContent = sel.s;
  document.getElementById('confPrestador').textContent = `${sel.n} · ${sel.c}`;
  document.getElementById('confPreco').textContent = brl(sel.p);

  document.getElementById('confEndereco').value = (user && user.endereco) ? user.endereco : (currentSearchAddress || '');
  document.getElementById('confNumero').value = (user && user.numero) ? user.numero : '';
  document.getElementById('confComplemento').value = (user && user.complemento) ? user.complemento : '';
  document.getElementById('confBairro').value = (user && user.bairro) ? user.bairro : '';
  document.getElementById('confObservacoes').value = '';
  document.getElementById('confMetodoPagamento').value = 'escrow';
  const chkAceiteInit = document.getElementById('chkAceitePedido');
  if (chkAceiteInit) chkAceiteInit.checked = false;

  const btnImediato = document.getElementById('btnModImediato');
  const btnAgendado = document.getElementById('btnModAgendado');
  const modInput = document.getElementById('confModalidade');
  const agContainer = document.getElementById('confAgendadoContainer');
  const setModalidade = (mod) => {
    modInput.value = mod;
    const isAg = mod === 'agendado';
    btnImediato.classList.toggle('on', !isAg);
    btnImediato.setAttribute('aria-pressed', !isAg ? 'true' : 'false');
    btnAgendado.classList.toggle('on', isAg);
    btnAgendado.setAttribute('aria-pressed', isAg ? 'true' : 'false');
    agContainer.hidden = !isAg;
  };
  setModalidade('imediato');
  btnImediato.onclick = () => setModalidade('imediato');
  btnAgendado.onclick = () => setModalidade('agendado');

  const fechar = () => {
    modal.style.display = 'none';
    document.removeEventListener('keydown', onKeyDown);
    if (triggerEl && typeof triggerEl.focus === 'function') triggerEl.focus();
  };
  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      fechar();
    }
  };

  modal.style.display = 'flex';
  document.addEventListener('keydown', onKeyDown);
  document.getElementById('btnFecharModalConfirmar').onclick = fechar;
  document.getElementById('btnCancelarConfirmacao').onclick = fechar;
  modal.onclick = (e) => { if (e.target === modal) fechar(); };
  setTimeout(() => document.getElementById('confEndereco').focus(), 0);

  document.getElementById('formConfirmarPedido').onsubmit = async (e) => {
    e.preventDefault();
    const chkAceite = document.getElementById('chkAceitePedido');
    if (chkAceite && !chkAceite.checked) {
      toast('É necessário aceitar as regras de Escrow, PIN presencial e Termos & Privacidade.');
      chkAceite.focus();
      return;
    }
    const btnEnviar = document.getElementById('btnEnviarConfirmacao');
    const metodoPagamento = document.getElementById('confMetodoPagamento').value;
    const modalidade = modInput.value;
    const agendadoInput = document.getElementById('confAgendadoPara');
    const agendadoPara = modalidade === 'agendado' ? (agendadoInput ? agendadoInput.value.trim() : '') : '';
    if (modalidade === 'agendado' && !agendadoPara) {
      toast('Informe a data e hora do agendamento.');
      if (agendadoInput) agendadoInput.focus();
      return;
    }
    btnEnviar.disabled = true;

    const payload = {
      servico_id: sel.service_id || sel.id,
      lat: centerLat,
      lng: centerLng,
      cep: (user && user.cep) ? user.cep : '',
      endereco: document.getElementById('confEndereco').value.trim(),
      numero: document.getElementById('confNumero').value.trim(),
      complemento: document.getElementById('confComplemento').value.trim(),
      bairro: document.getElementById('confBairro').value.trim(),
      cidade: (user && user.cidade) ? user.cidade : 'São Paulo',
      estado: (user && user.estado) ? user.estado : 'SP',
      observacoes: document.getElementById('confObservacoes').value.trim() || 'Solicitado via PertoJá',
      metodo_pagamento: metodoPagamento,
      modalidade,
      agendado_para: agendadoPara || null,
      aceite_termos: Boolean(chkAceite && chkAceite.checked)
    };

    try {
      const res = await fetch('/api/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.status === 429 || res.status >= 500) exibirAlertaRetry(res.status);
      const data = await res.json();
      if (res.status === 401) {
        toast('Sua sessão expirou. Redirecionando para login...');
        setTimeout(() => { window.location.href = 'login.html?redirect=pedido.html&pending_order=true'; }, 1200);
        return;
      }
      if (!res.ok) {
        toast(data.error || 'Erro ao processar pedido no servidor.');
        return;
      }

      const orderDbId = data.order_id;
      const abreCheckoutOnline = ['pix', 'cartao', 'boleto'].includes(metodoPagamento);

      sessionStorage.removeItem('pertoja_pending_order');
      localStorage.removeItem('pertoja_pending_order');
      fechar();
      iniciarTrackingPedido(orderDbId, sel, data);
      if (abreCheckoutOnline) {
        if ($('#pay')) $('#pay').hidden = false;
        abrirModalCheckoutPagamento(orderDbId, metodoPagamento, data);
      } else {
        toast('Pedido confirmado! Acompanhe o status em tempo real.');
      }
    } catch (err) {
      toast('Erro de conexão com o servidor ao registrar pedido.');
    } finally {
      btnEnviar.disabled = false;
    }
  };
}

let checkoutPollTimer = null;
let checkoutExpiryTimer = null;

function sanitizeSafeUrl(url) {
  if (typeof url !== 'string') return '';
  const trimmed = url.trim();
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^\/(?!\/)/.test(trimmed)) return trimmed;
  return '';
}

function gerarIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `idem_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

function copiarTextoSeguro(texto, mensagemSucesso) {
  const valor = String(texto || '');
  if (!valor) return;
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    navigator.clipboard.writeText(valor)
      .then(() => toast(mensagemSucesso || 'Copiado para a área de transferência!'))
      .catch(() => {
        const tmp = document.createElement('textarea');
        tmp.value = valor;
        tmp.setAttribute('readonly', 'readonly');
        tmp.style.position = 'fixed';
        tmp.style.opacity = '0';
        document.body.appendChild(tmp);
        tmp.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(tmp);
        toast(mensagemSucesso || 'Copiado para a área de transferência!');
      });
    return;
  }
  const tmp = document.createElement('textarea');
  tmp.value = valor;
  tmp.setAttribute('readonly', 'readonly');
  tmp.style.position = 'fixed';
  tmp.style.opacity = '0';
  document.body.appendChild(tmp);
  tmp.select();
  try { document.execCommand('copy'); } catch (e) {}
  document.body.removeChild(tmp);
  toast(mensagemSucesso || 'Copiado para a área de transferência!');
}

function criarSvgQrDeterministico(payload) {
  const text = String(payload || 'PERTOJA-PIX');
  const bytes = typeof TextEncoder !== 'undefined'
    ? Array.from(new TextEncoder().encode(text))
    : Array.from(unescape(encodeURIComponent(text))).map(ch => ch.charCodeAt(0));

  // ISO/IEC 18004 ECC Level L tables for Versions 1..12 (max byte capacity, total data codewords, ec per block, group1/group2)
  const QR_SPEC = [
    null,
    { cap: 17, total: 19, ec: 7, b1: 1, d1: 19, b2: 0, d2: 0, align: [] },
    { cap: 32, total: 34, ec: 10, b1: 1, d1: 34, b2: 0, d2: 0, align: [6, 18] },
    { cap: 53, total: 55, ec: 15, b1: 1, d1: 55, b2: 0, d2: 0, align: [6, 22] },
    { cap: 78, total: 80, ec: 20, b1: 1, d1: 80, b2: 0, d2: 0, align: [6, 26] },
    { cap: 106, total: 108, ec: 26, b1: 1, d1: 108, b2: 0, d2: 0, align: [6, 30] },
    { cap: 134, total: 136, ec: 18, b1: 2, d1: 68, b2: 0, d2: 0, align: [6, 34] },
    { cap: 154, total: 156, ec: 20, b1: 2, d1: 78, b2: 0, d2: 0, align: [6, 22, 38] },
    { cap: 192, total: 194, ec: 24, b1: 2, d1: 97, b2: 0, d2: 0, align: [6, 24, 42] },
    { cap: 230, total: 232, ec: 30, b1: 2, d1: 116, b2: 0, d2: 0, align: [6, 26, 46] },
    { cap: 271, total: 274, ec: 18, b1: 2, d1: 68, b2: 2, d2: 69, align: [6, 28, 50] },
    { cap: 321, total: 324, ec: 20, b1: 4, d1: 81, b2: 0, d2: 0, align: [6, 30, 54] },
    { cap: 367, total: 370, ec: 24, b1: 2, d1: 92, b2: 2, d2: 93, align: [6, 32, 58] }
  ];

  let ver = 1;
  while (ver < QR_SPEC.length - 1 && bytes.length > QR_SPEC[ver].cap) ver++;
  const spec = QR_SPEC[ver];
  const dataBytes = bytes.slice(0, spec.cap);
  const size = ver * 4 + 17;

  // GF(256) arithmetic (primitive poly 0x11d)
  const gfExp = new Uint8Array(512);
  const gfLog = new Uint8Array(256);
  let x = 1;
  for (let i = 0; i < 255; i++) {
    gfExp[i] = x;
    gfLog[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) gfExp[i] = gfExp[i - 255];
  const gfMul = (a, b) => (a === 0 || b === 0) ? 0 : gfExp[gfLog[a] + gfLog[b]];

  const rsGenPoly = (deg) => {
    let poly = [1];
    for (let i = 0; i < deg; i++) {
      const next = new Array(poly.length + 1).fill(0);
      const factor = gfExp[i];
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];
        next[j + 1] ^= gfMul(poly[j], factor);
      }
      poly = next;
    }
    return poly;
  };

  const rsCompute = (data, ecLen) => {
    const gen = rsGenPoly(ecLen);
    const res = new Uint8Array(data.length + ecLen);
    res.set(data, 0);
    for (let i = 0; i < data.length; i++) {
      const coef = res[i];
      if (coef !== 0) {
        for (let j = 0; j < gen.length; j++) {
          res[i + j] ^= gfMul(gen[j], coef);
        }
      }
    }
    return Array.from(res.slice(data.length));
  };

  // Encode Byte mode (0100)
  const bits = [];
  const pushBits = (val, len) => {
    for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
  };
  pushBits(0b0100, 4);
  pushBits(dataBytes.length, ver >= 10 ? 16 : 8);
  dataBytes.forEach(b => pushBits(b, 8));
  const maxDataBits = spec.total * 8;
  const termLen = Math.min(4, maxDataBits - bits.length);
  for (let i = 0; i < termLen; i++) bits.push(0);
  while (bits.length % 8 !== 0) bits.push(0);
  const padBytes = [0xec, 0x11];
  let padIdx = 0;
  while (bits.length < maxDataBits) {
    pushBits(padBytes[padIdx % 2], 8);
    padIdx++;
  }

  const dataCw = [];
  for (let i = 0; i < bits.length; i += 8) {
    let b = 0;
    for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j];
    dataCw.push(b);
  }

  // Split blocks & compute ECC
  const dataBlocks = [];
  const ecBlocks = [];
  let offset = 0;
  for (let i = 0; i < spec.b1; i++) {
    const blk = dataCw.slice(offset, offset + spec.d1);
    offset += spec.d1;
    dataBlocks.push(blk);
    ecBlocks.push(rsCompute(blk, spec.ec));
  }
  for (let i = 0; i < spec.b2; i++) {
    const blk = dataCw.slice(offset, offset + spec.d2);
    offset += spec.d2;
    dataBlocks.push(blk);
    ecBlocks.push(rsCompute(blk, spec.ec));
  }

  const finalCw = [];
  const maxD = Math.max(spec.d1, spec.d2);
  for (let i = 0; i < maxD; i++) {
    for (let b = 0; b < dataBlocks.length; b++) {
      if (i < dataBlocks[b].length) finalCw.push(dataBlocks[b][i]);
    }
  }
  for (let i = 0; i < spec.ec; i++) {
    for (let b = 0; b < ecBlocks.length; b++) {
      finalCw.push(ecBlocks[b][i]);
    }
  }

  const finalBits = [];
  finalCw.forEach(cw => {
    for (let i = 7; i >= 0; i--) finalBits.push((cw >>> i) & 1);
  });

  // Build matrix: -1 = empty, 0 = light, 1 = dark; isFunc tracks reserved modules
  const mat = Array.from({ length: size }, () => new Int8Array(size).fill(-1));
  const isFunc = Array.from({ length: size }, () => new Uint8Array(size));

  const setMod = (r, c, v, func = true) => {
    if (r >= 0 && r < size && c >= 0 && c < size) {
      mat[r][c] = v ? 1 : 0;
      if (func) isFunc[r][c] = 1;
    }
  };

  const drawFinder = (r0, c0) => {
    for (let dr = -1; dr <= 7; dr++) {
      for (let dc = -1; dc <= 7; dc++) {
        const r = r0 + dr;
        const c = c0 + dc;
        if (r < 0 || r >= size || c < 0 || c >= size) continue;
        const inOuter = dr >= 0 && dr <= 6 && dc >= 0 && dc <= 6;
        const onBorder = dr === 0 || dr === 6 || dc === 0 || dc === 6;
        const inInner = dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4;
        setMod(r, c, inOuter && (onBorder || inInner), true);
      }
    }
  };
  drawFinder(0, 0);
  drawFinder(0, size - 7);
  drawFinder(size - 7, 0);

  // Alignment patterns
  const alignCoords = spec.align;
  for (let i = 0; i < alignCoords.length; i++) {
    for (let j = 0; j < alignCoords.length; j++) {
      const ar = alignCoords[i];
      const ac = alignCoords[j];
      if ((ar <= 8 && ac <= 8) || (ar <= 8 && ac >= size - 9) || (ar >= size - 9 && ac <= 8)) continue;
      for (let dr = -2; dr <= 2; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          const dark = Math.abs(dr) === 2 || Math.abs(dc) === 2 || (dr === 0 && dc === 0);
          setMod(ar + dr, ac + dc, dark, true);
        }
      }
    }
  }

  // Timing patterns
  for (let i = 8; i < size - 8; i++) {
    if (!isFunc[6][i]) setMod(6, i, i % 2 === 0, true);
    if (!isFunc[i][6]) setMod(i, 6, i % 2 === 0, true);
  }
  // Dark module
  setMod(4 * ver + 9, 8, 1, true);

  // Reserve format info & version info
  for (let i = 0; i < 9; i++) {
    if (i !== 6) {
      isFunc[8][i] = 1;
      isFunc[i][8] = 1;
    }
  }
  for (let i = 0; i < 8; i++) {
    isFunc[8][size - 1 - i] = 1;
    isFunc[size - 1 - i][8] = 1;
  }
  if (ver >= 7) {
    for (let i = 0; i < 6; i++) {
      for (let j = 0; j < 3; j++) {
        isFunc[i][size - 11 + j] = 1;
        isFunc[size - 11 + j][i] = 1;
      }
    }
  }

  // Place data bits (zig-zag upward/downward)
  let bitIdx = 0;
  let up = true;
  for (let c = size - 1; c > 0; c -= 2) {
    if (c === 6) c--;
    for (let rowStep = 0; rowStep < size; rowStep++) {
      const r = up ? (size - 1 - rowStep) : rowStep;
      for (let dc = 0; dc < 2; dc++) {
        const col = c - dc;
        if (!isFunc[r][col]) {
          mat[r][col] = bitIdx < finalBits.length ? finalBits[bitIdx++] : 0;
        }
      }
    }
    up = !up;
  }

  // Masking (select best of 8 masks)
  const maskFn = (m, r, c) => {
    switch (m) {
      case 0: return (r + c) % 2 === 0;
      case 1: return r % 2 === 0;
      case 2: return c % 3 === 0;
      case 3: return (r + c) % 3 === 0;
      case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
      case 5: return ((r * c) % 2 + (r * c) % 3) === 0;
      case 6: return (((r * c) % 2 + (r * c) % 3) % 2) === 0;
      default: return (((r + c) % 2 + (r * c) % 3) % 2) === 0;
    }
  };

  const applyFormatAndVersion = (grid, m) => {
    // ECC Level L = 01
    const fmtData = (0b01 << 3) | m;
    let rem = fmtData << 10;
    for (let i = 14; i >= 10; i--) {
      if ((rem >>> i) & 1) rem ^= 0x537 << (i - 10);
    }
    const fmt = ((fmtData << 10) | rem) ^ 0x5412;
    for (let i = 0; i <= 5; i++) grid[8][i] = (fmt >>> (14 - i)) & 1;
    grid[8][7] = (fmt >>> 8) & 1;
    grid[8][8] = (fmt >>> 7) & 1;
    grid[7][8] = (fmt >>> 6) & 1;
    for (let i = 9; i < 15; i++) grid[14 - i][8] = (fmt >>> (14 - i)) & 1;
    for (let i = 0; i < 8; i++) grid[8][size - 1 - i] = (fmt >>> i) & 1;
    for (let i = 0; i < 7; i++) grid[size - 1 - i][8] = (fmt >>> (14 - i)) & 1;

    if (ver >= 7) {
      let vRem = ver << 12;
      for (let i = 17; i >= 12; i--) {
        if ((vRem >>> i) & 1) vRem ^= 0x1f25 << (i - 12);
      }
      const vBits = (ver << 12) | vRem;
      for (let i = 0; i < 18; i++) {
        const bit = (vBits >>> i) & 1;
        grid[Math.floor(i / 3)][size - 11 + (i % 3)] = bit;
        grid[size - 11 + (i % 3)][Math.floor(i / 3)] = bit;
      }
    }
  };

  const scorePenalty = (grid) => {
    let pen = 0;
    for (let r = 0; r < size; r++) {
      let runR = 1;
      let runC = 1;
      for (let i = 1; i < size; i++) {
        runR = grid[r][i] === grid[r][i - 1] ? runR + 1 : 1;
        if (runR === 5) pen += 3; else if (runR > 5) pen += 1;
        runC = grid[i][r] === grid[i - 1][r] ? runC + 1 : 1;
        if (runC === 5) pen += 3; else if (runC > 5) pen += 1;
      }
    }
    return pen;
  };

  let bestGrid = null;
  let bestPen = Infinity;
  for (let m = 0; m < 8; m++) {
    const cand = mat.map((row, r) => row.map((v, c) => (isFunc[r][c] ? v : (v ^ (maskFn(m, r, c) ? 1 : 0)))));
    applyFormatAndVersion(cand, m);
    const p = scorePenalty(cand);
    if (p < bestPen) {
      bestPen = p;
      bestGrid = cand;
    }
  }

  const quiet = 2;
  const vbSize = size + quiet * 2;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${vbSize} ${vbSize}`);
  svg.setAttribute('width', '200');
  svg.setAttribute('height', '200');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'QR Code PIX para pagamento');
  svg.style.display = 'block';
  svg.style.margin = '0 auto';
  svg.style.borderRadius = '12px';
  svg.style.border = '1px solid #d8e1e8';
  svg.style.background = '#ffffff';

  const bg = document.createElementNS(ns, 'rect');
  bg.setAttribute('x', '0');
  bg.setAttribute('y', '0');
  bg.setAttribute('width', String(vbSize));
  bg.setAttribute('height', String(vbSize));
  bg.setAttribute('fill', '#ffffff');
  svg.appendChild(bg);

  let d = '';
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (bestGrid[r][c] === 1) {
        d += `M${c + quiet},${r + quiet}h1v1h-1z`;
      }
    }
  }
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', '#000000');
  svg.appendChild(path);
  return svg;
}

function pararTimersCheckout() {
  if (checkoutPollTimer) {
    clearInterval(checkoutPollTimer);
    checkoutPollTimer = null;
  }
  if (checkoutExpiryTimer) {
    clearInterval(checkoutExpiryTimer);
    checkoutExpiryTimer = null;
  }
}

async function abrirModalCheckoutPagamento(orderDbId, metodoPagamento, orderSnapshot = {}) {
  const modal = document.getElementById('modalCheckoutPagamento');
  if (!modal) return;
  const triggerEl = document.activeElement;
  pararTimersCheckout();

  let metodo = ['pix', 'cartao', 'boleto', 'escrow'].includes(String(metodoPagamento || '').toLowerCase())
    ? String(metodoPagamento).toLowerCase()
    : 'pix';
  const labelsMetodo = {
    pix: 'Pix (Reserva Escrow)',
    cartao: 'Cartão de Crédito/Débito (Checkout Seguro)',
    boleto: 'Boleto Bancário (Escrow)',
    escrow: 'Escrow no Local (Reserva Protegida)'
  };

  const pedidoLabel = document.getElementById('checkoutPedidoLabel');
  const metodoLabel = document.getElementById('checkoutMetodoLabel');
  const valorLabel = document.getElementById('checkoutValorLabel');
  const metodoSelect = document.getElementById('checkoutMetodoSelect');
  const sandboxBanner = document.getElementById('checkoutSandboxBanner');
  const gatewayRow = document.getElementById('checkoutGatewayRow');
  const gatewaySelect = document.getElementById('checkoutGatewaySelect');
  const configNotice = document.getElementById('checkoutConfigNotice');
  const bodyEl = document.getElementById('checkoutBody');
  const statusBox = document.getElementById('checkoutStatusBox');
  const statusText = document.getElementById('checkoutStatusText');
  const expiryText = document.getElementById('checkoutExpiryText');
  const btnSimular = document.getElementById('btnCheckoutSimularSandbox');

  if (pedidoLabel) pedidoLabel.textContent = `Pedido #${orderDbId}`;
  if (metodoLabel) metodoLabel.textContent = labelsMetodo[metodo] || metodo.toUpperCase();
  if (metodoSelect) metodoSelect.value = metodo;
  const precoVal = orderSnapshot && orderSnapshot.preco_total != null
    ? Number(orderSnapshot.preco_total)
    : (order && order.best && order.best.p != null ? Number(order.best.p) : 0);
  if (valorLabel) valorLabel.textContent = brl(precoVal);

  const fechar = () => {
    pararTimersCheckout();
    modal.style.display = 'none';
    document.removeEventListener('keydown', onKeyDown);
    if (triggerEl && typeof triggerEl.focus === 'function') triggerEl.focus();
  };
  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      fechar();
    }
  };

  modal.style.display = 'flex';
  document.addEventListener('keydown', onKeyDown);
  const btnFecharTopo = document.getElementById('btnFecharModalCheckout');
  const btnFecharRodape = document.getElementById('btnFecharCheckoutRodape');
  if (btnFecharTopo) btnFecharTopo.onclick = fechar;
  if (btnFecharRodape) btnFecharRodape.onclick = fechar;
  modal.onclick = (e) => { if (e.target === modal) fechar(); };
  if (btnFecharTopo) setTimeout(() => btnFecharTopo.focus(), 0);

  const sincronizarPedidoAposPagamento = async () => {
    const updated = await buscarEstadoPedidoReal(orderDbId);
    if (updated && order && order.best) {
      atualizarUIStatusPedido(updated, order.best);
    }
    if ($('#pay')) $('#pay').hidden = true;
  };

  let configData = null;
  const carregarConfig = async () => {
    if (configData) return configData;
    try {
      const cfgRes = await fetch('/api/payments/config');
      if (cfgRes.ok) configData = await cfgRes.json();
    } catch (e) {
      configData = null;
    }
    return configData;
  };

  const atualizarStatusCheckout = async (payData) => {
    const st = String((payData && payData.status) || 'pending').toLowerCase();
    const isTerminalSuccess = ['paid', 'escrow_held', 'released'].includes(st);
    const isTerminalFail = ['failed', 'expired', 'cancelled', 'refunded'].includes(st);

    if (statusBox) statusBox.hidden = false;
    if (statusText) {
      if (isTerminalSuccess) {
        statusText.textContent = 'Pagamento confirmado! Valor retido em Escrow.';
      } else if (st === 'failed') {
        statusText.textContent = 'Pagamento recusado ou falhou.';
      } else if (st === 'expired') {
        statusText.textContent = 'Cobrança expirada. Feche e tente novamente.';
      } else if (st === 'cancelled') {
        statusText.textContent = 'Pagamento cancelado.';
      } else {
        statusText.textContent = 'Aguardando confirmação do pagamento...';
      }
    }

    if (isTerminalSuccess) {
      pararTimersCheckout();
      if (btnSimular) btnSimular.hidden = true;
      await sincronizarPedidoAposPagamento();
      toast('Pagamento confirmado e protegido em Escrow!');
      return true;
    }
    if (isTerminalFail) {
      pararTimersCheckout();
      if (btnSimular) btnSimular.hidden = true;
      return true;
    }
    return false;
  };

  const renderizarIntent = async (data) => {
    if (!bodyEl) return;
    bodyEl.innerHTML = '';
    const gw = String(data.gateway || '').toLowerCase();
    if (sandboxBanner) sandboxBanner.hidden = gw !== 'sandbox';

    if (data.expires_at && expiryText) {
      const expDate = new Date(String(data.expires_at).replace(' ', 'T'));
      const atualizarExp = () => {
        if (isNaN(expDate.getTime())) {
          expiryText.textContent = `Expira: ${String(data.expires_at)}`;
          return;
        }
        const diffSec = Math.max(0, Math.floor((expDate.getTime() - Date.now()) / 1000));
        const min = Math.floor(diffSec / 60);
        const sec = diffSec % 60;
        expiryText.textContent = diffSec > 0 ? `Expira em ${min}m ${String(sec).padStart(2, '0')}s` : 'Expirado';
      };
      atualizarExp();
      if (checkoutExpiryTimer) clearInterval(checkoutExpiryTimer);
      checkoutExpiryTimer = setInterval(atualizarExp, 1000);
    }

    if (metodo === 'pix') {
      const pixCode = String(data.pix_qr_code || '');
      const qrWrapper = document.createElement('div');
      qrWrapper.className = 'p-3 rounded-xl bg-white border border-perto-road text-center space-y-2';
      const rawB64 = typeof data.pix_qr_base64 === 'string' ? data.pix_qr_base64.trim() : '';
      if (rawB64 && /^[A-Za-z0-9+/=\s]+$/.test(rawB64)) {
        const cleanB64 = rawB64.replace(/\s+/g, '');
        const img = document.createElement('img');
        img.src = `data:image/png;base64,${cleanB64}`;
        img.alt = 'QR Code PIX';
        img.className = 'w-44 h-44 mx-auto rounded-lg';
        qrWrapper.appendChild(img);
      } else {
        qrWrapper.appendChild(criarSvgQrDeterministico(pixCode));
      }

      const lbl = document.createElement('label');
      lbl.className = 'block text-left text-[11px] font-bold text-perto-ink uppercase tracking-wider mt-2';
      lbl.setAttribute('for', 'checkoutPixCopiaCola');
      lbl.textContent = 'Pix Copia e Cola';
      qrWrapper.appendChild(lbl);

      const row = document.createElement('div');
      row.className = 'flex gap-2 items-center';
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.id = 'checkoutPixCopiaCola';
      inp.readOnly = true;
      inp.className = 'input-form text-xs font-mono flex-1';
      inp.value = pixCode;
      row.appendChild(inp);

      const btnCopy = document.createElement('button');
      btnCopy.type = 'button';
      btnCopy.className = 'btn px-3.5 py-2 rounded-full text-xs font-extrabold text-perto-ink shrink-0';
      btnCopy.textContent = 'Copiar código PIX';
      btnCopy.onclick = () => copiarTextoSeguro(pixCode, 'Código PIX copiado!');
      row.appendChild(btnCopy);

      qrWrapper.appendChild(row);
      bodyEl.appendChild(qrWrapper);
    } else if (metodo === 'cartao') {
      const cardBox = document.createElement('div');
      cardBox.className = 'p-3.5 rounded-xl bg-white border border-perto-road space-y-2.5';
      const pInfo = document.createElement('p');
      pInfo.className = 'm-0 text-xs text-perto-ink/85';
      pInfo.textContent = 'Por segurança PCI, os dados do cartão são inseridos apenas no ambiente hospedado do provedor.';
      cardBox.appendChild(pInfo);

      const safeCheckoutUrl = sanitizeSafeUrl(data.checkout_url);
      if (safeCheckoutUrl && gw !== 'sandbox') {
        const link = document.createElement('a');
        link.href = safeCheckoutUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'btn px-4 py-2.5 rounded-full text-xs font-extrabold text-perto-ink inline-flex items-center gap-1.5 no-underline';
        link.textContent = 'Abrir Checkout Seguro do Cartão';
        cardBox.appendChild(link);
      } else if (gw === 'sandbox') {
        const pSbx = document.createElement('p');
        pSbx.className = 'm-0 text-xs font-semibold text-perto-sea';
        pSbx.textContent = 'No ambiente Sandbox, utilize o botão abaixo para simular a aprovação do cartão.';
        cardBox.appendChild(pSbx);
      }
      bodyEl.appendChild(cardBox);
    } else if (metodo === 'boleto') {
      const bolBox = document.createElement('div');
      bolBox.className = 'p-3.5 rounded-xl bg-white border border-perto-road space-y-2.5';

      const digitable = String(data.boleto_digitable_line || data.boleto_barcode || '');
      const lbl = document.createElement('label');
      lbl.className = 'block text-[11px] font-bold text-perto-ink uppercase tracking-wider';
      lbl.setAttribute('for', 'checkoutBoletoLinha');
      lbl.textContent = 'Linha Digitável do Boleto';
      bolBox.appendChild(lbl);

      const row = document.createElement('div');
      row.className = 'flex gap-2 items-center';
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.id = 'checkoutBoletoLinha';
      inp.readOnly = true;
      inp.className = 'input-form text-xs font-mono flex-1';
      inp.value = digitable;
      row.appendChild(inp);

      const btnCopy = document.createElement('button');
      btnCopy.type = 'button';
      btnCopy.className = 'btn px-3.5 py-2 rounded-full text-xs font-extrabold text-perto-ink shrink-0';
      btnCopy.textContent = 'Copiar linha';
      btnCopy.onclick = () => copiarTextoSeguro(digitable, 'Linha digitável copiada!');
      row.appendChild(btnCopy);
      bolBox.appendChild(row);

      const safeBolUrl = sanitizeSafeUrl(data.boleto_url);
      if (safeBolUrl) {
        const link = document.createElement('a');
        link.href = safeBolUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'btn2 px-4 py-2 rounded-full text-xs font-bold inline-flex items-center gap-1.5 no-underline';
        link.textContent = 'Visualizar Boleto Bancário';
        bolBox.appendChild(link);
      }
      bodyEl.appendChild(bolBox);
    }

    const paymentId = data.payment_id || data.id;
    const settled = await atualizarStatusCheckout(data);

    if (btnSimular) {
      btnSimular.hidden = !(gw === 'sandbox' && !settled && paymentId);
      btnSimular.disabled = false;
      btnSimular.onclick = async () => {
        btnSimular.disabled = true;
        try {
          const confRes = await fetch(`/api/payments/${encodeURIComponent(paymentId)}/confirm`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Idempotency-Key': gerarIdempotencyKey()
            },
            body: JSON.stringify({ simulate_outcome: 'paid' })
          });
          const confData = await confRes.json().catch(() => ({}));
          if (!confRes.ok) {
            toast(confData.error || 'Falha ao confirmar pagamento Sandbox.');
            btnSimular.disabled = false;
            return;
          }
          await atualizarStatusCheckout(confData);
        } catch (err) {
          toast('Erro de comunicação ao confirmar pagamento Sandbox.');
          btnSimular.disabled = false;
        }
      };
    }

    if (!settled && paymentId) {
      if (checkoutPollTimer) clearInterval(checkoutPollTimer);
      checkoutPollTimer = setInterval(async () => {
        if (modal.style.display === 'none') {
          pararTimersCheckout();
          return;
        }
        try {
          const pollRes = await fetch(`/api/payments/${encodeURIComponent(paymentId)}`);
          if (!pollRes.ok) return;
          const pollData = await pollRes.json();
          await atualizarStatusCheckout(pollData);
        } catch (e) {}
      }, 4000);
    }
  };

  const buscarIntentAtivaExistente = async (gatewayId) => {
    try {
      const ordRes = await fetch(`/api/payments/order/${encodeURIComponent(orderDbId)}`);
      if (!ordRes.ok) return null;
      const ordData = await ordRes.json();
      const txs = Array.isArray(ordData.transactions) ? ordData.transactions : [];
      const agora = Date.now();
      return txs.find(tx => {
        if (!tx) return false;
        const st = String(tx.status || '').toLowerCase();
        if (st !== 'pending' && st !== 'requires_action') return false;
        if (String(tx.method || '').toLowerCase() !== metodo) return false;
        if (String(tx.gateway || '').toLowerCase() !== String(gatewayId || '').toLowerCase()) return false;
        if (tx.expires_at) {
          const expMs = new Date(String(tx.expires_at).replace(' ', 'T')).getTime();
          if (!isNaN(expMs) && expMs <= agora) return false;
        }
        return true;
      }) || null;
    } catch (e) {
      return null;
    }
  };

  const iniciarIntent = async (gatewayId) => {
    pararTimersCheckout();
    if (btnSimular) btnSimular.hidden = true;
    if (bodyEl) bodyEl.innerHTML = '<p class="text-perto-ink/70 m-0">Verificando cobrança existente...</p>';

    const existingIntent = await buscarIntentAtivaExistente(gatewayId);
    if (existingIntent) {
      await renderizarIntent(existingIntent);
      return;
    }

    if (bodyEl) bodyEl.innerHTML = '<p class="text-perto-ink/70 m-0">Gerando cobrança segura...</p>';
    try {
      const res = await fetch('/api/payments/intents', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': gerarIdempotencyKey()
        },
        body: JSON.stringify({
          order_id: Number(orderDbId),
          method: metodo,
          gateway: gatewayId
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (bodyEl) {
          const errP = document.createElement('p');
          errP.className = 'm-0 text-red-700 font-semibold';
          errP.textContent = data.error || `Erro ao iniciar pagamento (HTTP ${res.status}).`;
          bodyEl.innerHTML = '';
          bodyEl.appendChild(errP);
        }
        return;
      }
      await renderizarIntent(data);
    } catch (e) {
      if (bodyEl) {
        bodyEl.innerHTML = '<p class="m-0 text-red-700 font-semibold">Erro de comunicação ao iniciar checkout.</p>';
      }
    }
  };

  const iniciarFluxoMetodoAtual = async () => {
    pararTimersCheckout();
    if (metodoLabel) metodoLabel.textContent = labelsMetodo[metodo] || metodo.toUpperCase();
    if (sandboxBanner) sandboxBanner.hidden = true;
    if (gatewayRow) gatewayRow.hidden = true;
    if (configNotice) { configNotice.hidden = true; configNotice.textContent = ''; }
    if (statusBox) statusBox.hidden = true;
    if (expiryText) expiryText.textContent = '';
    if (btnSimular) btnSimular.hidden = true;

    if (metodo === 'escrow') {
      if (bodyEl) {
        bodyEl.innerHTML = '';
        const box = document.createElement('div');
        box.className = 'p-3.5 rounded-xl bg-white border border-perto-road space-y-2.5';
        const pInfo = document.createElement('p');
        pInfo.className = 'm-0 text-xs text-perto-ink/85';
        pInfo.textContent = 'Confirme a reserva do valor em Escrow no Local ou altere a forma de pagamento acima para Pix, Cartão ou Boleto.';
        box.appendChild(pInfo);

        const btnEscrow = document.createElement('button');
        btnEscrow.type = 'button';
        btnEscrow.className = 'btn px-4 py-2.5 rounded-full text-xs font-extrabold text-perto-ink';
        btnEscrow.textContent = 'Confirmar Reserva em Escrow';
        btnEscrow.onclick = async () => {
          btnEscrow.disabled = true;
          try {
            const resPay = await fetch(`/api/orders/${encodeURIComponent(orderDbId)}/pay`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                escrow_hold: Boolean(!orderSnapshot || String(orderSnapshot.status || '').toLowerCase() !== 'finalizado'),
                metodo_pagamento: 'escrow'
              })
            });
            const payData = await resPay.json().catch(() => ({}));
            if (!resPay.ok) {
              toast(payData.error || 'Não foi possível confirmar pagamento em Escrow.');
              btnEscrow.disabled = false;
              return;
            }
            await sincronizarPedidoAposPagamento();
            toast(payData.message || 'Pagamento retido em Escrow com segurança.');
            fechar();
          } catch (err) {
            toast('Erro de comunicação ao confirmar Escrow.');
            btnEscrow.disabled = false;
          }
        };
        box.appendChild(btnEscrow);
        bodyEl.appendChild(box);
      }
      return;
    }

    if (bodyEl) bodyEl.innerHTML = '<p class="text-perto-ink/70 m-0">Carregando configuração de pagamento...</p>';
    const cfg = await carregarConfig();
    if (!cfg || !Array.isArray(cfg.gateways)) {
      if (configNotice) {
        configNotice.textContent = 'Não foi possível carregar os provedores de pagamento. Tente novamente.';
        configNotice.hidden = false;
      }
      if (bodyEl) bodyEl.innerHTML = '';
      return;
    }

    const configuredGateways = cfg.gateways.filter(g => g && g.configured && (!Array.isArray(g.methods) || g.methods.includes(metodo)));
    if (!configuredGateways.length) {
      if (configNotice) {
        configNotice.textContent = 'Nenhum gateway de pagamento (nem Sandbox) está configurado para este método no momento.';
        configNotice.hidden = false;
      }
      if (bodyEl) bodyEl.innerHTML = '';
      return;
    }

    let selectedGateway = cfg.default_gateway && configuredGateways.some(g => g.id === cfg.default_gateway)
      ? cfg.default_gateway
      : configuredGateways[0].id;

    if (gatewaySelect && gatewayRow) {
      gatewaySelect.innerHTML = '';
      configuredGateways.forEach(gw => {
        const opt = document.createElement('option');
        opt.value = gw.id;
        opt.textContent = gw.name || gw.id;
        if (gw.id === selectedGateway) opt.selected = true;
        gatewaySelect.appendChild(opt);
      });
      gatewayRow.hidden = configuredGateways.length <= 1;
      gatewaySelect.onchange = () => {
        selectedGateway = gatewaySelect.value;
        iniciarIntent(selectedGateway);
      };
    }

    await iniciarIntent(selectedGateway);
  };

  if (metodoSelect) {
    metodoSelect.onchange = () => {
      metodo = metodoSelect.value;
      iniciarFluxoMetodoAtual();
    };
  }

  await iniciarFluxoMetodoAtual();
}

async function request(id) {
  const sel = P.find(p => p.id === id);
  if (!sel || !sel.a) {
    toast('Prestador indisponível no momento.');
    return;
  }

  // 1. Client-side Gate: validação de autenticação obrigatória do cliente
  const user = typeof obterUsuarioLogado === 'function' ? await obterUsuarioLogado() : null;
  if (!user) {
    const pendingOrder = {
      service_id: sel.service_id || sel.id,
      titulo: sel.s,
      categoria: sel.c,
      preco: sel.p,
      prestador_nome: sel.n,
      prestador_id: sel.id,
      lat: centerLat,
      lng: centerLng,
      endereco: currentSearchAddress || 'São Paulo - SP',
      raio: radius,
      observacoes: 'Solicitado via monitoramento ao vivo',
      salvo_em: Date.now()
    };
    try {
      sessionStorage.setItem('pertoja_pending_order', JSON.stringify(pendingOrder));
      localStorage.removeItem('pertoja_pending_order');
    } catch (e) {}

    exibirModalAuthObrigatoria(pendingOrder);
    return;
  }

  if (user.tipo !== 'cliente') {
    toast('⚠️ Apenas contas de Cliente podem contratar serviços. Você está conectado como Prestador.');
    return;
  }

  // 2. Abre modal acessível de confirmação antes de enviar POST /api/orders
  abrirModalConfirmarPedido(sel, user);
}

function renderAll() {
  renderList();
  renderMap(order && order.pos);
}

function irParaCategoria(c) {
  location.href = 'pedido.html?cat=' + encodeURIComponent(c);
}

function renderDestaques() {
  const destaquesEl = document.getElementById('destaques-home');
  if (!destaquesEl) return;
  const top3 = [...P].sort((a, b) => b.r - a.r).slice(0, 3);
  destaquesEl.innerHTML = top3.map((p, index) => {
    const destUrl = `pedido.html?cat=${encodeURIComponent(p.c)}&q=${encodeURIComponent(p.s)}`;
    return `
    <div class="card-home clicavel" role="button" tabindex="0" data-dest-url="${escapeHtml(destUrl)}" style="cursor: pointer; animation-delay: ${index * 0.1}s;" aria-label="Ver ${escapeHtml(p.s)} com ${escapeHtml(p.n)}">
      <div class="card-texto" style="text-align: center;">
        <div style="font-size: 0.85rem; font-weight: 800; color: var(--sun); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 12px;">★ Destaque da Semana</div>
        <h3 style="color: var(--ink); margin-bottom: 4px;">${escapeHtml(p.n)}</h3>
        <p style="color: var(--sea); font-weight: bold; margin-bottom: 8px;">${escapeHtml(p.c)} · ${escapeHtml(p.s)}</p>
        <p style="font-size: 0.9rem; color: #4b6073;">Avaliação Média: <b style="color: var(--ink);">★ ${p.r.toFixed(1)}</b> / 5.0</p>
        <p style="font-size: 1.1rem; color: var(--sea); font-weight: bold; margin-top: 8px;">${brl(p.p)}</p>
      </div>
    </div>
  `;
  }).join('');
  destaquesEl.querySelectorAll('[data-dest-url]').forEach((card) => {
    const go = () => {
      const url = card.getAttribute('data-dest-url');
      if (url) location.href = url;
    };
    card.addEventListener('click', go);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        go();
      }
    });
  });
}

async function inicializarLocalizacaoInicial() {
  let atualizado = false;
  try {
    const savedLocRaw = localStorage.getItem('pertoja_search_loc');
    if (savedLocRaw) {
      const savedLoc = JSON.parse(savedLocRaw);
      const sLat = parseFloat(savedLoc.lat);
      const sLng = parseFloat(savedLoc.lng);
      if (!isNaN(sLat) && !isNaN(sLng)) {
        centerLat = sLat;
        centerLng = sLng;
        currentSearchAddress = savedLoc.label || savedLoc.address || currentSearchAddress;
        atualizado = true;
      }
    }
  } catch (e) {}

  if (typeof obterUsuarioLogado === 'function') {
    try {
      cachedLoggedUser = await obterUsuarioLogado();
    } catch (e) {
      cachedLoggedUser = null;
    }
  }

  if (!atualizado && cachedLoggedUser && cachedLoggedUser.tipo === 'cliente') {
    const uLat = parseFloat(cachedLoggedUser.lat);
    const uLng = parseFloat(cachedLoggedUser.lng);
    if (!isNaN(uLat) && !isNaN(uLng)) {
      centerLat = uLat;
      centerLng = uLng;
      const partes = [cachedLoggedUser.endereco, cachedLoggedUser.numero, cachedLoggedUser.bairro, cachedLoggedUser.cidade].filter(Boolean);
      if (partes.length) currentSearchAddress = partes.join(', ');
      atualizado = true;
    }
  }

  if (atualizado) {
    const locInfo = $('#locInfo');
    if (locInfo) locInfo.textContent = `Ponto de busca: ${currentSearchAddress}`;
    if (mapInstance) mapInstance.setView([centerLat, centerLng], 13);
  }
}

// Inicialização segura
document.addEventListener('DOMContentLoaded', async () => {
  const inputFiltro = document.getElementById('inputFiltroServico');
  if (inputFiltro && searchQuery) {
    inputFiltro.value = searchQuery;
  }

  const mapEl = document.getElementById('map');
  if (mapEl && typeof L !== 'undefined') {
    mapInstance = L.map('map', {
      scrollWheelZoom: false, // Usabilidade: rolagem fluida sem interceptar scroll da página
      touchZoom: true,
      tap: true,
      dragging: true
    }).setView([centerLat, centerLng], 13);

    const tileLayerEsri = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Dados geoespaciais &copy; Esri, OpenStreetMap',
      maxZoom: 18
    });

    // Fallback gracioso para OpenStreetMap caso ArcGIS encontre erro de conexão
    tileLayerEsri.on('tileerror', () => {
      if (!window.mapTileFallbackActivated && mapInstance) {
        window.mapTileFallbackActivated = true;
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '&copy; OpenStreetMap contributors',
          maxZoom: 18
        }).addTo(mapInstance);
      }
    });

    tileLayerEsri.addTo(mapInstance);
    layerMarkers = L.layerGroup().addTo(mapInstance);
    window.mapInstance = mapInstance;
    window.map = mapInstance;

    // Ajusta o mapa de forma fluida ao redimensionar a tela ou alternar elementos de layout
    const resizeMap = () => {
      if (mapInstance) mapInstance.invalidateSize();
    };
    window.addEventListener('resize', resizeMap);
    window.addEventListener('orientationchange', () => {
      setTimeout(resizeMap, 250);
    });
  }

  await inicializarLocalizacaoInicial();
  await carregarPrestadoresAPI();

  renderChips();
  renderAll();
  renderDestaques();

  // Escuta alterações de localização disparadas pelo seletor global do header (auth.js)
  window.addEventListener('pertoja:location-changed', async (e) => {
    const det = (e && e.detail) ? e.detail : null;
    if (!det) return;
    const nLat = parseFloat(det.lat);
    const nLng = parseFloat(det.lng);
    if (!isNaN(nLat) && !isNaN(nLng)) {
      centerLat = nLat;
      centerLng = nLng;
      currentSearchAddress = det.label || det.address || currentSearchAddress;
      const locInfo = $('#locInfo');
      if (locInfo) locInfo.textContent = `Ponto de busca: ${currentSearchAddress}`;
      if (mapInstance) {
        mapInstance.setView([centerLat, centerLng], 14, { animate: true });
        setTimeout(() => { if (mapInstance) mapInstance.invalidateSize(); }, 200);
      }
      await carregarPrestadoresAPI();
      renderAll();
    }
  });

  // Alternador Mobile Lista | Mapa (PA-08)
  const btnViewLista = document.getElementById('btnViewLista');
  const btnViewMapa = document.getElementById('btnViewMapa');
  const colLista = document.getElementById('colListaPedido');
  const colMapa = document.getElementById('colMapaPedido');
  if (btnViewLista && btnViewMapa && colLista && colMapa) {
    const setMobileView = (view) => {
      const isMapa = view === 'mapa';
      btnViewLista.classList.toggle('on', !isMapa);
      btnViewLista.setAttribute('aria-pressed', !isMapa ? 'true' : 'false');
      btnViewMapa.classList.toggle('on', isMapa);
      btnViewMapa.setAttribute('aria-pressed', isMapa ? 'true' : 'false');
      colLista.classList.toggle('max-[899px]:hidden', isMapa);
      colMapa.classList.toggle('max-[899px]:hidden', !isMapa);
      if (isMapa && mapInstance) {
        setTimeout(() => mapInstance.invalidateSize(), 120);
      }
    };
    btnViewLista.onclick = () => setMobileView('lista');
    btnViewMapa.onclick = () => setMobileView('mapa');
  }

  // Busca textual em pedido.html (PA-07)
  let timerBuscaDebounce = null;
  if (inputFiltro) {
    inputFiltro.oninput = (e) => {
      searchQuery = e.target.value.trim();
      renderAll();
      clearTimeout(timerBuscaDebounce);
      timerBuscaDebounce = setTimeout(async () => {
        await carregarPrestadoresAPI();
        renderAll();
      }, 300);
    };
  }

  // Toggle "Disponível agora" (PA-07)
  const btnOnlyAvail = document.getElementById('btnOnlyAvailable');
  if (btnOnlyAvail) {
    btnOnlyAvail.onclick = async () => {
      onlyAvailable = !onlyAvailable;
      btnOnlyAvail.classList.toggle('on', onlyAvailable);
      btnOnlyAvail.setAttribute('aria-pressed', onlyAvailable ? 'true' : 'false');
      await carregarPrestadoresAPI();
      renderAll();
    };
  }

  // Função reutilizável para geolocalização por satélite/dispositivo
  async function ativarGeolocalizacaoGPS() {
    if (!navigator.geolocation) {
      toast('O navegador atual não suporta geolocalização.');
      return;
    }
    const locInfo = $('#locInfo');
    if (locInfo) locInfo.textContent = 'Obtendo sinal do satélite GPS...';
    navigator.geolocation.getCurrentPosition(
      async (g) => {
        centerLat = g.coords.latitude;
        centerLng = g.coords.longitude;
        if (mapInstance) mapInstance.setView([centerLat, centerLng], 14);
        if (locInfo) locInfo.textContent = 'Precisão obtida: ±' + Math.round(g.coords.accuracy) + ' metros.';
        toast('Posição geográfica atualizada via GPS.');
        await carregarPrestadoresAPI();
        renderAll();
      },
      (erro) => {
        let motivo = erro.code === erro.PERMISSION_DENIED ? "Acesso não permitido pelo usuário." : "Falha na comunicação de rede/GPS.";
        if (locInfo) locInfo.textContent = 'Erro: ' + motivo;
        toast('Geolocalização indisponível: ' + motivo);
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 0 }
    );
  }

  // Event Listeners protegidos
  const sortBtns = document.querySelectorAll('.sort-btn[data-order]');
  sortBtns.forEach(btn => {
    btn.onclick = async () => {
      const nextOrder = btn.dataset.order;
      if (!nextOrder || nextOrder === currentOrder) return;
      currentOrder = nextOrder;
      sortBtns.forEach(b => {
        const active = b.dataset.order === currentOrder;
        b.classList.toggle('on', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      await carregarPrestadoresAPI();
      renderAll();
    };
  });

  if ($('#chips')) {
    $('#chips').onclick = async e => {
      const c = e.target.dataset.c;
      if (!c) return;
      cat = c;
      renderChips();
      await carregarPrestadoresAPI();
      renderAll();
    };
  }

  let timerRaioDebounce = null;
  if ($('#raio')) {
    $('#raio').oninput = e => {
      radius = +e.target.value;
      if ($('#raioV')) $('#raioV').textContent = radius + ' km';
      if (mapInstance) mapInstance.setZoom(radius > 8 ? 12 : (radius < 4 ? 14 : 13));
      renderAll();
      clearTimeout(timerRaioDebounce);
      timerRaioDebounce = setTimeout(async () => {
        await carregarPrestadoresAPI();
        renderAll();
      }, 350);
    };
  }

  const listContainer = $('#list');
  if (listContainer) {
    listContainer.addEventListener('click', (e) => {
      const expandBtn = e.target.closest('[data-action="expand-radius"]');
      if (expandBtn) {
        const r = document.getElementById('raio');
        if (r) {
          r.value = 15;
          r.dispatchEvent(new Event('input'));
        }
        return;
      }
      const btn = e.target.closest('.btn-requisitar[data-req], .btn-requisitar[data-request-id]');
      if (!btn) return;
      const id = btn.dataset.req || btn.dataset.requestId;
      if (id && !busy) request(+id);
    });
  }

  const mapContainer = document.getElementById('map');
  if (mapContainer) {
    mapContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-requisitar[data-request-id]');
      if (!btn || btn.disabled) return;
      const id = btn.dataset.requestId;
      if (id && !busy) request(+id);
    });
  }

  if ($('#pay')) {
    $('#pay').onclick = async () => {
      const user = typeof obterUsuarioLogado === 'function' ? await obterUsuarioLogado() : null;
      if (!user) {
        toast('Sua sessão expirou. Faça login para concluir o pagamento.');
        window.location.href = 'login.html?redirect=pedido.html';
        return;
      }
      try {
        if (order && order.db_id) {
          const metodoPg = String((currentOrderData && currentOrderData.metodo_pagamento) || 'escrow').toLowerCase();
          if (['pix', 'cartao', 'boleto'].includes(metodoPg)) {
            abrirModalCheckoutPagamento(order.db_id, metodoPg, currentOrderData || {});
            return;
          }
          const res = await fetch(`/api/orders/${order.db_id}/pay`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              escrow_hold: Boolean(currentOrderData && currentOrderData.status !== 'finalizado'),
              metodo_pagamento: (currentOrderData && currentOrderData.metodo_pagamento) || 'escrow'
            })
          });
          if (res.status === 429 || res.status >= 500) {
            exibirAlertaRetry(res.status);
          }
          if (res.status === 401) {
            toast('Sua sessão expirou. Faça login para confirmar o pagamento.');
            window.location.href = 'login.html?redirect=pedido.html';
            return;
          }
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            toast(data.error || 'Não foi possível processar o pagamento.');
            return;
          }
          const realStatus = String(data.status || (currentOrderData && currentOrderData.status) || '').toLowerCase();
          if (realStatus) {
            if (currentOrderData) currentOrderData.status = realStatus;
            renderSteps(mapStatusToStep(realStatus));
            atualizarPaineisSegurancaPedido(realStatus, data);
          }
          const escrowSt = String(data.escrow_status || '').toLowerCase();
          $('#pay').hidden = true;
          if (escrowSt === 'retido' || escrowSt === 'aguardando_liberacao') {
            toast(data.message || 'Pagamento retido em Escrow com segurança.');
            info('Pagamento confirmado e retido em Escrow conforme regras da plataforma.');
          } else if (escrowSt === 'liberado') {
            toast(data.message || 'Pagamento confirmado e Escrow liberado.');
            info(realStatus === 'finalizado' ? 'Pagamento registrado e Escrow liberado. Chamado concluído!' : 'Escrow liberado conforme confirmação.');
          } else {
            toast(data.message || 'Transação processada com sucesso via PertoJá Pagamentos.');
            info(realStatus === 'finalizado' ? 'Pagamento registrado. Chamado concluído com sucesso!' : 'Pagamento registrado com sucesso.');
          }
          return;
        }
      } catch (e) {
        console.warn('Erro ao registrar pagamento na API:', e);
        toast('Erro de comunicação ao registrar pagamento.');
        return;
      }
      $('#pay').hidden = true;
      toast('Transação processada com sucesso via PertoJá Pagamentos.');
      info('Pagamento registrado com sucesso.');
    };
  }

  if ($('#novo')) {
    $('#novo').onclick = async () => {
      clearAllSimulationTimers();
      pararPollingPedido();
      sessionStorage.removeItem('pertoja_active_order_id');
      localStorage.removeItem('pertoja_active_order_id');
      busy = false;
      order = null;
      currentOrderData = null;
      if ($('#pedidoBox')) $('#pedidoBox').hidden = true;
      if ($('#painel-lista')) $('#painel-lista').hidden = false;
      atualizarPaineisSegurancaPedido('', null);
      await carregarPrestadoresAPI();
      renderAll();
    };
  }

  // Modal de Avaliação do Atendimento no Tracking (PA-11)
  const btnAvaliarAtend = document.getElementById('btnAvaliarAtendimento');
  const modalAvaliarAtend = document.getElementById('modalAvaliarAtendimento');
  if (btnAvaliarAtend && modalAvaliarAtend) {
    let avaliarAtendTrigger = null;
    const fecharAvaliarAtend = () => {
      modalAvaliarAtend.style.display = 'none';
      document.removeEventListener('keydown', onAvaliarKeyDown);
      if (avaliarAtendTrigger && typeof avaliarAtendTrigger.focus === 'function') avaliarAtendTrigger.focus();
    };
    const onAvaliarKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        fecharAvaliarAtend();
      }
    };
    btnAvaliarAtend.onclick = () => {
      avaliarAtendTrigger = document.activeElement;
      document.getElementById('avaliarPedidoComentario').value = '';
      document.getElementById('avaliarPedidoNota').value = '5';
      modalAvaliarAtend.querySelectorAll('#avaliarPedidoEstrelas [data-nota]').forEach(b => {
        const is5 = b.dataset.nota === '5';
        b.classList.toggle('on', is5);
        b.setAttribute('aria-pressed', is5 ? 'true' : 'false');
      });
      modalAvaliarAtend.style.display = 'flex';
      document.addEventListener('keydown', onAvaliarKeyDown);
      const firstStar = modalAvaliarAtend.querySelector('#avaliarPedidoEstrelas button');
      if (firstStar) setTimeout(() => firstStar.focus(), 0);
    };
    modalAvaliarAtend.querySelectorAll('#avaliarPedidoEstrelas [data-nota]').forEach(btn => {
      btn.onclick = () => {
        const nota = btn.dataset.nota;
        document.getElementById('avaliarPedidoNota').value = nota;
        modalAvaliarAtend.querySelectorAll('#avaliarPedidoEstrelas [data-nota]').forEach(b => {
          const active = b.dataset.nota === nota;
          b.classList.toggle('on', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
      };
    });
    document.getElementById('btnFecharModalAvaliarAtendimento').onclick = fecharAvaliarAtend;
    document.getElementById('btnCancelarAvaliarAtendimento').onclick = fecharAvaliarAtend;
    modalAvaliarAtend.onclick = (e) => { if (e.target === modalAvaliarAtend) fecharAvaliarAtend(); };
    document.getElementById('formAvaliarAtendimento').onsubmit = async (e) => {
      e.preventDefault();
      if (!order || !order.db_id) return;
      const btnSubmit = document.getElementById('btnEnviarAvaliarAtendimento');
      btnSubmit.disabled = true;
      try {
        const nota = parseInt(document.getElementById('avaliarPedidoNota').value, 10) || 5;
        const comentario = document.getElementById('avaliarPedidoComentario').value.trim();
        const res = await fetch(`/api/orders/${order.db_id}/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nota, comentario })
        });
        const data = await res.json();
        if (res.ok) {
          toast('Avaliação registrada com sucesso!');
          btnAvaliarAtend.hidden = true;
          fecharAvaliarAtend();
        } else {
          toast(data.error || 'Erro ao enviar avaliação.');
        }
      } catch (err) {
        toast('Erro de comunicação ao enviar avaliação.');
      } finally {
        btnSubmit.disabled = false;
      }
    };
  }

  // Compartilhar Rota Segura (ET-14)
  const btnCompRota = document.getElementById('btnCompartilharRota');
  if (btnCompRota) {
    btnCompRota.onclick = async () => {
      if (!order || !order.db_id) return;
      btnCompRota.disabled = true;
      try {
        const res = await fetch(`/api/orders/${order.db_id}/share-route`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (res.ok && data.share_token) {
          const url = `${window.location.origin}/api/shared-route/${encodeURIComponent(data.share_token)}`;
          const sharedBox = document.getElementById('sharedRouteBox');
          const sharedLink = document.getElementById('sharedRouteLink');
          if (sharedLink) {
            sharedLink.href = url;
            sharedLink.textContent = url;
          }
          if (sharedBox) sharedBox.hidden = false;
          toast('Link de rota segura gerado!');
        } else {
          toast(data.error || 'Não foi possível gerar o link de compartilhamento.');
        }
      } catch (e) {
        toast('Erro de comunicação ao compartilhar rota.');
      } finally {
        btnCompRota.disabled = false;
      }
    };
  }

  const btnCopiarRota = document.getElementById('btnCopiarRota');
  if (btnCopiarRota) {
    btnCopiarRota.onclick = async () => {
      const sharedLink = document.getElementById('sharedRouteLink');
      const txt = sharedLink ? sharedLink.textContent.trim() : '';
      if (!txt) return;
      try {
        await navigator.clipboard.writeText(txt);
        toast('Link copiado para a área de transferência.');
      } catch (e) {
        toast('Copie o link exibido acima.');
      }
    };
  }

  // Modal SOS Emergência (ET-14)
  const btnSosPed = document.getElementById('btnSosPedido');
  const modalSosPed = document.getElementById('modalSosPedido');
  if (btnSosPed && modalSosPed) {
    let sosTrigger = null;
    const fecharSos = () => {
      modalSosPed.style.display = 'none';
      document.removeEventListener('keydown', onSosKeyDown);
      if (sosTrigger && typeof sosTrigger.focus === 'function') sosTrigger.focus();
    };
    const onSosKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        fecharSos();
      }
    };
    btnSosPed.onclick = () => {
      sosTrigger = document.activeElement;
      const desc = document.getElementById('sosDescricao');
      const den = document.getElementById('sosDenunciarContraparte');
      if (desc) desc.value = '';
      if (den) den.checked = false;
      modalSosPed.style.display = 'flex';
      document.addEventListener('keydown', onSosKeyDown);
      if (desc) setTimeout(() => desc.focus(), 0);
    };
    document.getElementById('btnFecharModalSos').onclick = fecharSos;
    document.getElementById('btnCancelarSos').onclick = fecharSos;
    modalSosPed.onclick = (e) => { if (e.target === modalSosPed) fecharSos(); };
    document.getElementById('formSosPedido').onsubmit = async (e) => {
      e.preventDefault();
      if (!order || !order.db_id) return;
      const descEl = document.getElementById('sosDescricao');
      const descricao = (descEl ? descEl.value : '').trim();
      if (descricao.length < 10) {
        toast('Descreva a ocorrência com pelo menos 10 caracteres.');
        if (descEl) descEl.focus();
        return;
      }
      const denunciar_contraparte = Boolean(document.getElementById('sosDenunciarContraparte').checked);
      if (denunciar_contraparte) {
        const ok = window.confirm('ATENÇÃO: Denunciar a contraparte acionará suspensão cautelar imediata da conta denunciada. Deseja confirmar esta denúncia?');
        if (!ok) return;
      }
      const btnConf = document.getElementById('btnConfirmarSos');
      btnConf.disabled = true;
      try {
        const res = await fetch(`/api/orders/${order.db_id}/sos`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ descricao, denunciar_contraparte })
        });
        const data = await res.json();
        if (res.ok) {
          toast(data.message || 'Alerta SOS registrado. Equipe de segurança notificada.');
          fecharSos();
        } else {
          toast(data.error || 'Erro ao registrar alerta SOS.');
        }
      } catch (err) {
        toast('Erro de comunicação ao acionar SOS.');
      } finally {
        btnConf.disabled = false;
      }
    };
  }

  // Chat Protegido do Pedido (ET-15)
  const formChatPed = document.getElementById('formPedidoChat');
  if (formChatPed) {
    formChatPed.onsubmit = async (e) => {
      e.preventDefault();
      if (!order || !order.db_id) return;
      const stAtual = currentOrderData ? String(currentOrderData.status || '').toLowerCase() : '';
      if (stAtual === 'finalizado' || stAtual === 'cancelado') {
        toast('Chat encerrado (somente leitura).');
        return;
      }
      const input = document.getElementById('inputPedidoChatMsg');
      const btnSend = document.getElementById('btnEnviarPedidoChat');
      const mensagem = input ? input.value.trim() : '';
      if (!mensagem) return;
      if (btnSend) btnSend.disabled = true;
      try {
        const res = await fetch(`/api/orders/${order.db_id}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mensagem })
        });
        const data = await res.json();
        if (res.ok) {
          if (input) input.value = '';
          await carregarMensagensPedido(order.db_id);
        } else {
          toast(data.error || 'Não foi possível enviar a mensagem.');
        }
      } catch (err) {
        toast('Erro de comunicação no chat do pedido.');
      } finally {
        if (btnSend) btnSend.disabled = false;
      }
    };
  }

  // Vincula evento de GPS a todos os botões de disparo de geolocalização
  const gpsBtns = document.querySelectorAll('#btnLoc, #btnGpsBusca, .btn-gps-trigger');
  gpsBtns.forEach(btn => {
    btn.onclick = ativarGeolocalizacaoGPS;
  });

  // Carrega pedido ativo via ?order_id= ou sessionStorage (PA-02)
  const legacyActiveId = localStorage.getItem('pertoja_active_order_id');
  if (legacyActiveId) {
    if (!sessionStorage.getItem('pertoja_active_order_id')) {
      try { sessionStorage.setItem('pertoja_active_order_id', legacyActiveId); } catch (e) {}
    }
    try { localStorage.removeItem('pertoja_active_order_id'); } catch (e) {}
  }
  const mpReturnKeys = ['payment_id', 'collection_id', 'collection_status', 'status', 'preference_id'];
  const hasMpReturnParams = Boolean(orderIdURL) && mpReturnKeys.some((k) => urlParamsInit.has(k));
  if (hasMpReturnParams) {
    const mpStatusHint = String(urlParamsInit.get('collection_status') || urlParamsInit.get('status') || '').toLowerCase();
    if (mpStatusHint === 'approved') {
      toast('Retorno do Mercado Pago recebido. Sincronizando confirmação do pagamento...');
    } else if (['rejected', 'cancelled', 'failure'].includes(mpStatusHint)) {
      toast('Retorno do Mercado Pago recebido. Verificando status do pagamento...');
    } else {
      toast('Verificando status do pagamento no servidor...');
    }
    try {
      const ordRes = await fetch(`/api/payments/order/${encodeURIComponent(orderIdURL)}`);
      if (ordRes.ok) {
        const ordData = await ordRes.json().catch(() => ({}));
        const txs = Array.isArray(ordData.transactions) ? ordData.transactions : [];
        const pendingCardTx = txs.find((tx) => {
          if (!tx) return false;
          const st = String(tx.status || '').toLowerCase();
          const gw = String(tx.gateway || '').toLowerCase();
          const met = String(tx.method || '').toLowerCase();
          return met === 'cartao' && gw !== 'sandbox' && (st === 'pending' || st === 'requires_action');
        });
        if (pendingCardTx && !['rejected', 'cancelled', 'failure'].includes(mpStatusHint)) {
          const txPaymentId = pendingCardTx.payment_id || pendingCardTx.id;
          if (txPaymentId) {
            const confRes = await fetch(`/api/payments/${encodeURIComponent(txPaymentId)}/confirm`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Idempotency-Key': gerarIdempotencyKey()
              },
              body: JSON.stringify({})
            });
            if (confRes.ok) {
              const confData = await confRes.json().catch(() => ({}));
              const syncedStatus = String(confData.status || '').toLowerCase();
              if (['paid', 'escrow_held', 'released'].includes(syncedStatus)) {
                toast('Pagamento confirmado e protegido em Escrow!');
              } else if (['failed', 'cancelled', 'expired'].includes(syncedStatus)) {
                toast('Pagamento não aprovado no provedor. Você pode tentar novamente.');
              }
            }
          }
        }
      }
    } catch (e) {}
  }

  const targetOrderId = orderIdURL || sessionStorage.getItem('pertoja_active_order_id');
  if (targetOrderId) {
    await carregarPedidoAtivoPorId(targetOrderId);
    const payParam = urlParamsInit.get('pay');
    if (payParam === '1' && currentOrderData && !currentOrderData.pago && String(currentOrderData.status || '').toLowerCase() !== 'cancelado') {
      const metodoPg = String(currentOrderData.metodo_pagamento || 'escrow').toLowerCase();
      if ($('#pay')) $('#pay').hidden = false;
      abrirModalCheckoutPagamento(currentOrderData.order_id || targetOrderId, metodoPg, currentOrderData);
    }
  }

  // Restaura e sugere pedidos pendentes caso o cliente tenha acabado de autenticar
  await verificarERestaurarPedidoPendente();
});

// Expõe globalmente para navegação, handlers HTML e testes
window.request = request;
window.irParaCategoria = irParaCategoria;
window.buscarPorEnderecoCliente = buscarPorEnderecoCliente;
window.carregarPrestadoresAPI = carregarPrestadoresAPI;
window.renderAll = renderAll;
window.renderDestaques = renderDestaques;
window.clearAllSimulationTimers = clearAllSimulationTimers;
window.exibirModalAuthObrigatoria = exibirModalAuthObrigatoria;
window.verificarERestaurarPedidoPendente = verificarERestaurarPedidoPendente;
