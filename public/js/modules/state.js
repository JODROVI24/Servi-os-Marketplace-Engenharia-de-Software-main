// public/js/modules/state.js - Estado compartilhado, métricas e helpers de sessão do PertoJá

export const DEFAULT_PROVIDERS = [
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

export const CATEGORIES = ['Todos', 'Limpeza', 'Elétrica', 'Encanamento', 'Pintura', 'Jardinagem', 'Tecnologia', 'Marcenaria'];
export const STEPS = ['Requisitado', 'Localizado', 'Confirmado', 'Em Trânsito', 'Em Execução', 'Finalizado'];

const urlParamsInit = typeof location !== 'undefined' ? new URLSearchParams(location.search) : new URLSearchParams();
const catURL = urlParamsInit.get('cat');
const qURL = urlParamsInit.get('q');

export const store = {
  centerLat: -23.5653,
  centerLng: -46.6517,
  currentSearchAddress: 'Avenida Paulista, 1000 · Bela Vista · São Paulo - SP',
  mapInstance: null,
  layerMarkers: null,
  providers: DEFAULT_PROVIDERS.map((item) => ({ ...item })),
  cat: catURL || 'Todos',
  radius: 8,
  busy: false,
  order: null,
  timer: null,
  currentOrder: 'distance',
  searchQuery: qURL ? qURL.trim() : '',
  onlyAvailable: false,
  loadingDepth: 0,
  simulationTimers: [],
  orderPollTimer: null,
  currentOrderData: null,
  cachedLoggedUser: null,
  urlParamsInit,
  orderIdURL: urlParamsInit.get('order_id')
};

export const qs = (s) => document.querySelector(s);

export const brl = (v) => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

export function csrfHeaders(extra = {}) {
  const out = Object.assign({}, extra || {});
  if (!Object.keys(out).some((k) => k.toLowerCase() === 'x-csrf-token')) {
    let token = typeof window !== 'undefined' && typeof window.obterCsrfToken === 'function' ? window.obterCsrfToken() : '';
    if (!token && typeof document !== 'undefined' && document.cookie) {
      const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
      if (m) {
        try {
          token = decodeURIComponent(m[1].trim());
        } catch (_) {
          token = m[1].trim();
        }
      }
    }
    if (token) out['X-CSRF-Token'] = token;
  }
  return out;
}

export function dist(p) {
  if (!store.mapInstance || p.lat == null || p.lng == null || isNaN(p.lat) || isNaN(p.lng)) return 9999;
  return store.mapInstance.distance([store.centerLat, store.centerLng], [p.lat, p.lng]) / 1000;
}

export function notaBayesiana(p) {
  const v = Number(p.total_avaliacoes || 0);
  const r = Number(p.r != null ? p.r : 4.5);
  return (v * r + 5 * 4.5) / (v + 5);
}

export function score(p) {
  return 1000 * (1 - Math.min(dist(p) / 15, 1)) + notaBayesiana(p) * 100 + (p.a ? 200 : 0);
}

export function getServiceScore(p) {
  return p.score != null && !isNaN(p.score) ? Number(p.score) : score(p);
}

export function visible() {
  const qNorm = store.searchQuery.trim().toLowerCase();
  return store.providers.filter((p) => {
    if (store.mapInstance && dist(p) > store.radius) return false;
    if (store.cat !== 'Todos' && p.c.toLowerCase() !== store.cat.toLowerCase()) return false;
    if (store.onlyAvailable && !p.a) return false;
    if (qNorm) {
      const haystack = [p.s, p.n, p.c, p.bairro, p.cidade, p.endereco].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(qNorm)) return false;
    }
    return true;
  });
}

export function clearAllSimulationTimers() {
  clearTimeout(store.timer);
  store.simulationTimers.forEach((t) => clearTimeout(t));
  store.simulationTimers = [];
}
