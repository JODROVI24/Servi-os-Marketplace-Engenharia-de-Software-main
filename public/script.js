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
const score = p => 1000 * (1 - Math.min(dist(p) / 10, 1)) + p.r * 100 + (p.a ? 200 : 0);
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

    const res = await fetch(`/api/services?${params.toString()}`);
    if (res.status === 429 || res.status >= 500) {
      exibirAlertaRetry(res.status);
    } else if (res.ok) {
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
           <span class="truncate">${escapeHtml(p.endereco || 'São Paulo - SP')}</span>
         </div>
         <div class="meta mt-1.5">
           <span><span aria-hidden="true">👤</span> ${escapeHtml(p.n)}</span>
           <span>★ ${p.r.toFixed(1)}</span>
           <span>${dist(p).toFixed(1)} km</span>
           <span class="score-badge" aria-label="Score ${svcScore}">Score ${svcScore}</span>
           ${isSuper ? '<span class="super-badge">★ Super Profissional</span>' : ''}
           <span class="tag ${p.a ? '' : 'off'}">${p.a ? 'Disponível' : 'Indisponível'}</span>
         </div>
       </div>
     </div>
     <div class="mt-2.5 flex justify-end">
       <button type="button" class="btn btn-requisitar" data-req="${p.id}" aria-label="Requisitar atendimento de ${escapeHtml(p.n)} para ${escapeHtml(p.s)}" ${(!p.a || busy) ? 'disabled' : ''}>Requisitar Atendimento</button>
     </div>
    </div>`;
  }).join('') : `
     <div class="empty-state-card" role="status" aria-live="polite">
       <p class="empty-title">Nenhum serviço encontrado nesta área</p>
       <p class="empty-desc">Não encontramos profissionais disponíveis neste raio de ${radius} km. Experimente expandir o raio de busca.</p>
       <button type="button" class="btn" aria-label="Expandir raio de busca para 15 km" style="font-size: 0.82rem; padding: 8px 16px; border-radius: 9999px;" onclick="const r = document.getElementById('raio'); if(r){ r.value = 15; r.dispatchEvent(new Event('input')); }">
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
        <div style="color: #666; font-size: 0.75rem; margin-bottom: 4px;">📍 ${escapeHtml(p.endereco || 'São Paulo - SP')}</div>
        <div style="color: var(--ok); font-weight: bold; font-size: 0.8rem; margin-bottom: 8px;">A ${dist(p).toFixed(1)} km de você</div>
        <button type="button" class="btn btn-requisitar" data-req-popup="${p.id}" aria-label="Requisitar atendimento de ${escapeHtml(p.n)}" style="width: 100%; min-height: 38px; font-size: 0.82rem; padding: 8px 14px; ${isAvail ? '' : 'opacity: 0.55; cursor: not-allowed;'}" ${isAvail ? `onclick="window.request(${p.id})"` : 'disabled'}>
          ${isAvail ? 'Requisitar Agora' : (busy ? 'Atendimento em Andamento' : 'Indisponível no Momento')}
        </button>
      </div>
    `);
    marker.addTo(layerMarkers);
  });

  if (order && posAtual) {
    L.polyline([[posAtual.lat, posAtual.lng], [centerLat, centerLng]], { color: '#ffc233', dashArray: '6, 6', weight: 3 }).addTo(layerMarkers);
    L.circleMarker([posAtual.lat, posAtual.lng], { radius: 12, color: '#10243e', fillColor: '#ffc233', fillOpacity: 1, weight: 3 })
      .bindTooltip(order.best.n.split(' ')[0], { permanent: true, direction: 'right', className: 'map-label' }).addTo(layerMarkers);
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
  const rawPending = sessionStorage.getItem('pertoja_pending_order') || localStorage.getItem('pertoja_pending_order');
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

function atualizarUIStatusPedido(pedidoApi, best) {
  if (!pedidoApi || !order) return;
  currentOrderData = pedidoApi;
  if (pedidoApi.codigo_confirmacao) {
    atualizarCodigoConfirmacao(pedidoApi.codigo_confirmacao);
  }
  const status = (pedidoApi.status || 'solicitado').toLowerCase();
  const stepIdx = mapStatusToStep(status);
  renderSteps(stepIdx);

  if (status === 'solicitado') {
    info(`Aguardando confirmação de <b>${escapeHtml(best.n)}</b> para <b>${escapeHtml(best.s)}</b>…`);
  } else if (status === 'confirmado') {
    info(`<b>${escapeHtml(best.n)}</b> confirmou o atendimento e está se preparando para sair.`);
  } else if (status === 'em_transito') {
    if (!order.drivingStarted) {
      order.drivingStarted = true;
      toast(`${best.n} iniciou o deslocamento até seu endereço.`);
      driveVisualOnly(best);
    }
  } else if (status === 'em_execucao') {
    clearAllSimulationTimers();
    order.pos = { lat: centerLat, lng: centerLng };
    renderMap(order.pos);
    info(`<b>${escapeHtml(best.n)}</b> está no local executando o serviço.`);
  } else if (status === 'finalizado') {
    clearAllSimulationTimers();
    pararPollingPedido();
    order.pos = { lat: centerLat, lng: centerLng };
    renderMap(order.pos);
    info('Ordem de serviço concluída com sucesso!');
    if ($('#pay')) $('#pay').hidden = Boolean(pedidoApi.pago);
    if ($('#novo')) $('#novo').hidden = false;
    const btnAvaliar = document.getElementById('btnAvaliarAtendimento');
    if (btnAvaliar) btnAvaliar.hidden = Boolean(pedidoApi.ja_avaliado);
  } else if (status === 'cancelado') {
    clearAllSimulationTimers();
    pararPollingPedido();
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
    try { localStorage.setItem('pertoja_active_order_id', String(orderDbId)); } catch (e) {}
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
    const btnEnviar = document.getElementById('btnEnviarConfirmacao');
    btnEnviar.disabled = true;

    const metodoPagamento = document.getElementById('confMetodoPagamento').value;
    const modalidade = modInput.value;
    const agendadoPara = modalidade === 'agendado' ? document.getElementById('confAgendadoPara').value : '';
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
      agendado_para: agendadoPara || null
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
      if (metodoPagamento === 'pix' || metodoPagamento === 'cartao') {
        try {
          await fetch(`/api/orders/${orderDbId}/pay`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ escrow_hold: true, metodo_pagamento: metodoPagamento })
          });
        } catch (errPay) {}
      }

      sessionStorage.removeItem('pertoja_pending_order');
      localStorage.removeItem('pertoja_pending_order');
      fechar();
      toast('Pedido confirmado! Acompanhe o status em tempo real.');
      iniciarTrackingPedido(orderDbId, sel, data);
    } catch (err) {
      toast('Erro de conexão com o servidor ao registrar pedido.');
    } finally {
      btnEnviar.disabled = false;
    }
  };
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
      localStorage.setItem('pertoja_pending_order', JSON.stringify(pendingOrder));
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

  if ($('#list')) {
    $('#list').onclick = e => {
      const btn = e.target.closest('.btn-requisitar[data-req]');
      if (!btn) return;
      const id = btn.dataset.req;
      if (id && !busy) request(+id);
    };
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
          const res = await fetch(`/api/orders/${order.db_id}/pay`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
          });
          if (res.status === 429 || res.status >= 500) {
            exibirAlertaRetry(res.status);
          }
          if (res.status === 401) {
            toast('Sua sessão expirou. Faça login para confirmar o pagamento.');
            window.location.href = 'login.html?redirect=pedido.html';
            return;
          }
        }
      } catch (e) {
        console.warn('Erro ao registrar pagamento na API:', e);
      }
      $('#pay').hidden = true;
      toast('Transação processada com sucesso via PertoJá Pagamentos.');
      info('Pagamento registrado. Chamado concluído com sucesso!');
    };
  }

  if ($('#novo')) {
    $('#novo').onclick = async () => {
      clearAllSimulationTimers();
      pararPollingPedido();
      localStorage.removeItem('pertoja_active_order_id');
      busy = false;
      order = null;
      currentOrderData = null;
      if ($('#pedidoBox')) $('#pedidoBox').hidden = true;
      if ($('#painel-lista')) $('#painel-lista').hidden = false;
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

  // Vincula evento de GPS a todos os botões de disparo de geolocalização
  const gpsBtns = document.querySelectorAll('#btnLoc, #btnGpsBusca, .btn-gps-trigger');
  gpsBtns.forEach(btn => {
    btn.onclick = ativarGeolocalizacaoGPS;
  });

  // Carrega pedido ativo via ?order_id= ou localStorage (PA-02)
  const targetOrderId = orderIdURL || localStorage.getItem('pertoja_active_order_id');
  if (targetOrderId) {
    await carregarPedidoAtivoPorId(targetOrderId);
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
