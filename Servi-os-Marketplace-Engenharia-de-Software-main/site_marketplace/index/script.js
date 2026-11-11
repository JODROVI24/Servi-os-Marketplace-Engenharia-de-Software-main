// script.js - Lógica interativa de catálogo, mapa geográfico e tracking do PertoJá

let centerLat = -23.5653;
let centerLng = -46.6517;
let currentSearchAddress = 'Avenida Paulista, 1000 · Bela Vista · São Paulo - SP';
let mapInstance = null;
let layerMarkers = null;

let P = [
  { id: 1, n: 'Carlos Mendes', s: 'Limpeza residencial completa', c: 'Limpeza', p: 80, r: 4.8, lat: -23.5653, lng: -46.6517, a: true, endereco: 'Avenida Paulista, 1000 · Bela Vista · São Paulo - SP' },
  { id: 2, n: 'Marta Souza', s: 'Faxina pesada e higienização profunda', c: 'Limpeza', p: 170, r: 4.5, lat: -23.5855, lng: -46.6385, a: true, endereco: 'Rua Domingos de Morais, 500 · Vila Mariana · São Paulo - SP' },
  { id: 3, n: 'João Volts', s: 'Reparo e manutenção de quadro elétrico', c: 'Elétrica', p: 210, r: 4.9, lat: -23.5601, lng: -46.6850, a: true, endereco: 'Rua Teodoro Sampaio, 1200 · Pinheiros · São Paulo - SP' },
  { id: 4, n: 'Rafa Instalações', s: 'Troca de chuveiro e tomadas elétricas', c: 'Elétrica', p: 90, r: 4.2, lat: -23.5570, lng: -46.6640, a: true, endereco: 'Rua Haddock Lobo, 800 · Cerqueira César · São Paulo - SP' },
  { id: 5, n: 'Beto Hidráulica', s: 'Conserto de vazamentos e desentupimento', c: 'Encanamento', p: 240, r: 4.7, lat: -23.5042, lng: -46.6262, a: true, endereco: 'Rua Voluntários da Pátria, 1500 · Santana · São Paulo - SP' },
  { id: 6, n: 'Lia Cores', s: 'Pintura residencial e texturização de paredes', c: 'Pintura', p: 380, r: 4.6, lat: -23.5320, lng: -46.6710, a: true, endereco: 'Rua Turiassu, 400 · Perdizes · São Paulo - SP' },
  { id: 7, n: 'Dona Flor', s: 'Jardinagem, poda e manutenção paisagística', c: 'Jardinagem', p: 450, r: 5.0, lat: -23.5840, lng: -46.6780, a: true, endereco: 'Rua Bandeira Paulista, 700 · Itaim Bibi · São Paulo - SP' },
  { id: 8, n: 'Téo Suporte', s: 'Suporte técnico de computadores e redes Wi-Fi', c: 'Tecnologia', p: 110, r: 4.4, lat: -23.5550, lng: -46.6600, a: false, endereco: 'Rua da Consolação, 2400 · Consolação · São Paulo - SP' },
  { id: 9, n: 'Nina Montagens', s: 'Marcenaria e montagem de móveis planejados', c: 'Marcenaria', p: 260, r: 4.3, lat: -23.5535, lng: -46.6020, a: true, endereco: 'Rua da Mooca, 1500 · Mooca · São Paulo - SP' },
  { id: 10, n: 'Juliana Clean', s: 'Limpeza e higienização residencial', c: 'Limpeza', p: 85, r: 4.9, lat: -23.4628, lng: -46.5333, a: true, endereco: 'Rua do Araújo, 150 · Jardim Beirute · Guarulhos - SP' },
  { id: 11, n: 'Marcos Reparos', s: 'Instalação e reparos elétricos', c: 'Elétrica', p: 95, r: 4.7, lat: -23.4650, lng: -46.5300, a: true, endereco: 'Rua Dom Pedro II, 300 · Centro · Guarulhos - SP' },
  { id: 12, n: 'Fabio Tintas', s: 'Pintura residencial e texturização', c: 'Pintura', p: 320, r: 4.8, lat: -23.4560, lng: -46.5450, a: true, endereco: 'Rua Treze de Maio, 450 · Vila Galvão · Guarulhos - SP' }
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
let simulationTimers = [];

function clearAllSimulationTimers() {
  clearTimeout(timer);
  simulationTimers.forEach(t => clearTimeout(t));
  simulationTimers = [];
}
const catURL = new URLSearchParams(location.search).get('cat');
if (catURL) cat = catURL;

function toast(t) {
  const container = $('#toasts');
  if (!container) return;
  const d = document.createElement('div');
  d.className = 'toast';
  d.textContent = t;
  container.append(d);
  setTimeout(() => d.remove(), 4500);
}

// Carregar prestadores da API se disponível
async function carregarPrestadoresAPI() {
  try {
    const res = await fetch(`/api/services?cat=${encodeURIComponent(cat)}&radius=${radius}&lat=${centerLat}&lng=${centerLng}`);
    if (res.ok) {
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
          lat: (item.prestador && item.prestador.lat != null) ? item.prestador.lat : item.lat,
          lng: (item.prestador && item.prestador.lng != null) ? item.prestador.lng : item.lng,
          a: item.prestador ? item.prestador.disponivel : true,
          endereco: item.endereco ? item.endereco.completo : (item.endereco_completo || 'São Paulo - SP'),
          bairro: item.endereco ? item.endereco.bairro : (item.bairro || ''),
          cidade: item.endereco ? item.endereco.cidade : (item.cidade || 'São Paulo'),
          distancia: item.distancia_km
        }));
      }
    }
  } catch (e) {
    console.log('Utilizando base de prestadores local/fallback.');
  }
}

function visible() {
  return P.filter(p => (mapInstance ? dist(p) <= radius : true) && (cat === 'Todos' || p.c.toLowerCase() === cat.toLowerCase()));
}

function renderChips() {
  const chipsEl = $('#chips');
  if (!chipsEl) return;
  const cats = ['Todos', 'Limpeza', 'Elétrica', 'Encanamento', 'Pintura', 'Jardinagem', 'Tecnologia', 'Marcenaria'];
  chipsEl.innerHTML = cats.map(c => `<button class="chip ${c.toLowerCase() === cat.toLowerCase() ? 'on' : ''}" data-c="${c}">${c}</button>`).join('');
}

function renderList() {
  const listEl = $('#list');
  if (!listEl) return;
  const v = visible().sort((a, b) => dist(a) - dist(b));
  if ($('#count')) $('#count').textContent = '(' + v.length + ')';
  listEl.innerHTML = v.length ? v.map(p => `
   <div class="svc ${order && order.best.id === p.id ? 'best' : ''}">
     <div class="top"><span>${p.s}</span><span class="price">${brl(p.p)}</span></div>
     <div style="font-size: 0.8rem; color: var(--sea); font-weight: 600; margin: 3px 0; display: flex; align-items: center; gap: 4px;">
       <span>📍</span> <span>${p.endereco || 'São Paulo - SP'}</span>
     </div>
     <div class="meta"><span>👤 ${p.n}</span><span>Avaliação: ★ ${p.r.toFixed(1)}</span><span>${dist(p).toFixed(1)} km</span>
       <span class="tag ${p.a ? '' : 'off'}">${p.a ? 'Disponível' : 'Indisponível'}</span></div>
     <div style="margin-top: 10px;"><button class="btn btn-requisitar" data-req="${p.id}" ${(!p.a || busy) ? 'disabled' : ''}>Requisitar Atendimento</button></div>
    </div>`).join('') : `
     <div style="color: #666; padding: 16px 8px; text-align: center;">
       <p style="font-weight: 700; color: #10243e; margin: 0 0 6px;">Nenhum prestador encontrado neste raio de ${radius} km.</p>
       <p style="font-size: 0.85rem; color: #666; margin: 0 0 12px;">Experimente aumentar o raio de atendimento para visualizar prestadores próximos.</p>
       <button class="btn" style="font-size: 0.8rem; padding: 6px 14px; border-radius: 9999px;" onclick="const r = document.getElementById('raio'); if(r){ r.value = 15; r.dispatchEvent(new Event('input')); }">
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
      <div style="color: var(--sea); font-weight: 700; margin-bottom: 4px;">${currentSearchAddress || 'Endereço atual'}</div>
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
    marker.bindTooltip(p.n.split(' ')[0], { permanent: true, direction: 'right', className: 'map-label' });
    const isAvail = p.a && !busy;
    marker.bindPopup(`
      <div style="font-family: inherit; font-size: 0.85rem; min-width: 170px;">
        <h4 style="margin: 0 0 4px; color: #10243e; font-size: 0.95rem;">${p.s}</h4>
        <div style="color: var(--sea); font-weight: 800; font-size: 1rem; margin-bottom: 4px;">${brl(p.p)}</div>
        <div style="color: #444; margin-bottom: 3px;">👤 <b>${p.n}</b> · ★ ${p.r.toFixed(1)}</div>
        <div style="color: #666; font-size: 0.75rem; margin-bottom: 4px;">📍 ${p.endereco || 'São Paulo - SP'}</div>
        <div style="color: var(--ok); font-weight: bold; font-size: 0.8rem; margin-bottom: 8px;">A ${dist(p).toFixed(1)} km de você</div>
        <button class="btn btn-requisitar" style="width: 100%; min-height: 38px; font-size: 0.82rem; padding: 8px 14px; ${isAvail ? '' : 'opacity: 0.55; cursor: not-allowed;'}" ${isAvail ? `onclick="window.request(${p.id})"` : 'disabled'}>
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
  try {
    let lat = null, lng = null, label = q;

    // 1. Caso o termo seja um CEP numérico com 8 dígitos
    if (cleanCep.length === 8) {
      try {
        const res = await fetch(`/api/cep/${cleanCep}`);
        if (res.ok) {
          const d = await res.json();
          lat = d.lat != null ? parseFloat(d.lat) : null;
          lng = d.lng != null ? parseFloat(d.lng) : null;
          const partes = [d.logradouro, d.bairro, d.localidade ? `${d.localidade}${d.uf ? ' - ' + d.uf : ''}` : ''].filter(Boolean);
          label = partes.length ? partes.join(', ') : (d.cep || q);
        }
      } catch (errApi) {
        console.warn('API local de CEP indisponível, recorrendo a fallbacks cliente:', errApi);
      }

      // Fallback cliente 1: BrasilAPI v2 direta se a API local falhar ou não tiver coordenadas
      if ((lat == null || lng == null || isNaN(lat) || isNaN(lng)) && typeof fetch !== 'undefined') {
        try {
          const resB = await fetch(`https://brasilapi.com.br/api/cep/v2/${cleanCep}`);
          if (resB.ok) {
            const dB = await resB.json();
            if (dB.location && dB.location.coordinates) {
              const cLat = parseFloat(dB.location.coordinates.latitude);
              const cLng = parseFloat(dB.location.coordinates.longitude);
              if (!isNaN(cLat) && !isNaN(cLng)) {
                lat = cLat;
                lng = cLng;
                const partes = [dB.street, dB.neighborhood, dB.city ? `${dB.city}${dB.state ? ' - ' + dB.state : ''}` : ''].filter(Boolean);
                label = partes.length ? partes.join(', ') : label;
              }
            }
          }
        } catch (errB) {}
      }

      // Fallback cliente 2: ViaCEP + Nominatim caso ainda sem coordenadas
      if ((lat == null || lng == null || isNaN(lat) || isNaN(lng)) && typeof fetch !== 'undefined') {
        try {
          const resV = await fetch(`https://viacep.com.br/ws/${cleanCep}/json/`);
          if (resV.ok) {
            const dV = await resV.json();
            if (!dV.erro) {
              const partes = [dV.logradouro, dV.bairro, dV.localidade ? `${dV.localidade}${dV.uf ? ' - ' + dV.uf : ''}` : ''].filter(Boolean);
              label = partes.length ? partes.join(', ') : label;
              const cands = [
                [dV.logradouro, dV.localidade, dV.uf].filter(Boolean).join(', ') + ', Brasil',
                [dV.logradouro, dV.bairro, dV.localidade, dV.uf].filter(Boolean).join(', ') + ', Brasil',
                [dV.localidade, dV.uf].filter(Boolean).join(' - ') + ', Brasil'
              ];
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
        } catch (errV) {}
      }
    }

    // 2. Se não for CEP ou se o CEP ainda não tiver coordenadas: busca por geocodificação
    if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) {
      try {
        const resG = await fetch(`/api/geocode?q=${encodeURIComponent(q + ', Brasil')}`);
        if (resG.ok) {
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
        statusBox.innerHTML = `<span class="material-symbols-outlined text-sm text-perto-ok">check_circle</span> <span>Endereço localizado: <b>${label}</b></span>`;
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

async function request(id) {
  const sel = P.find(p => p.id === id);
  if (!sel || !sel.a) {
    toast('Prestador indisponível no momento.');
    return;
  }

  // Se houver API, envia o pedido para persistir no banco
  try {
    const res = await fetch('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        servico_id: sel.service_id || sel.id,
        lat: centerLat,
        lng: centerLng,
        observacoes: 'Solicitado via monitoramento ao vivo'
      })
    });
    if (res.status === 401 || res.status === 403) {
      toast('💡 Dica: faça login como Cliente para salvar o histórico no seu portal!');
    }
  } catch (err) {}

  busy = true;
  const best = sel;
  order = { best, pos: { lat: best.lat, lng: best.lng }, gps: 0 };
  best.a = false;

  if ($('#painel-lista')) $('#painel-lista').hidden = true;
  if ($('#pedidoBox')) $('#pedidoBox').hidden = false;
  if ($('#pay')) $('#pay').hidden = true;
  if ($('#novo')) $('#novo').hidden = true;
  if ($('#gps')) $('#gps').textContent = 0;

  const cands = P.filter(p => p.c.toLowerCase() === sel.c.toLowerCase() && dist(p) <= radius)
    .map(p => ({ p, score: score(p) }))
    .sort((a, b) => b.score - a.score);

  if ($('#rank')) {
    $('#rank').innerHTML = '<tr><th>Profissional</th><th>Distância</th><th>Avaliação</th><th>Score</th></tr>' +
      cands.map((c, i) => `<tr class="${c.p.id === best.id ? 'win' : ''}"><td>${c.p.n}</td><td>${dist(c.p).toFixed(1)} km</td><td>★ ${c.p.r.toFixed(1)}</td><td>${Math.round(c.score)}</td></tr>`).join('');
  }

  renderSteps(0);
  renderAll();
  info('Processando solicitação para <b>' + sel.s + '</b> com <b>' + best.n + '</b>…');

  clearAllSimulationTimers();

  simulationTimers.push(setTimeout(() => {
    if (!order) return;
    renderSteps(1);
    info('Profissional designado: <b>' + best.n + '</b> a ' + dist(best).toFixed(1) + ' km.');
    toast('Notificando prestador e cliente.');
  }, 900));

  simulationTimers.push(setTimeout(() => {
    if (!order) return;
    renderSteps(2);
    toast(best.n + ' confirmou o atendimento.');
  }, 2200));

  simulationTimers.push(setTimeout(() => {
    if (!order) return;
    renderSteps(3);
    toast(best.n + ' iniciou o deslocamento até seu endereço.');
    drive(best);
  }, 3300));
}

function drive(best) {
  const n = 6;
  let k = 0;
  const tick = () => {
    k++;
    if (!order) return;
    order.gps++;
    if ($('#gps')) $('#gps').textContent = order.gps;
    const f = k / n;
    order.pos = {
      lat: best.lat * (1 - f) + centerLat * f,
      lng: best.lng * (1 - f) + centerLng * f
    };
    const left = mapInstance ? (mapInstance.distance([order.pos.lat, order.pos.lng], [centerLat, centerLng]) / 1000) : 0;
    info(left > 0.05 ? 'O profissional encontra-se a <b>' + left.toFixed(1) + ' km</b> · Estimativa de chegada: ' + Math.max(1, Math.round(left * 3)) + ' min.' : 'O profissional chegou ao seu endereço.');
    renderMap(order.pos);
    if (k < n) {
      const isBat = $('#bat') && $('#bat').checked;
      timer = setTimeout(tick, isBat ? 2500 : 1000);
      simulationTimers.push(timer);
    } else {
      arrive();
    }
  };
  timer = setTimeout(tick, 1000);
  simulationTimers.push(timer);
}

function arrive() {
  toast('O profissional chegou ao local do serviço.');
  renderSteps(4);
  timer = setTimeout(() => {
    if (!order) return;
    renderSteps(5);
    info('Ordem de serviço concluída com sucesso! Prossiga com o encerramento financeiro.');
    toast('Serviço finalizado.');
    if ($('#pay')) $('#pay').hidden = false;
    if ($('#novo')) $('#novo').hidden = false;
  }, 2500);
  simulationTimers.push(timer);
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
  destaquesEl.innerHTML = top3.map((p, index) => `
    <div class="card-home" style="cursor: default; animation-delay: ${index * 0.1}s;">
      <div class="card-texto" style="text-align: center;">
        <div style="font-size: 0.85rem; font-weight: 800; color: var(--sun); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 12px;">★ Destaque da Semana</div>
        <h3 style="color: var(--ink); margin-bottom: 4px;">${p.n}</h3>
        <p style="color: var(--sea); font-weight: bold; margin-bottom: 8px;">${p.c} · ${p.s}</p>
        <p style="font-size: 0.9rem; color: #4b6073;">Avaliação Média: <b style="color: var(--ink);">★ ${p.r.toFixed(1)}</b> / 5.0</p>
        <p style="font-size: 1.1rem; color: var(--sea); font-weight: bold; margin-top: 8px;">${brl(p.p)}</p>
      </div>
    </div>
  `).join('');
}

// Inicialização segura
document.addEventListener('DOMContentLoaded', async () => {
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

    // Ajusta o mapa de forma fluida ao redimensionar a tela
    window.addEventListener('resize', () => {
      if (mapInstance) mapInstance.invalidateSize();
    });
    window.addEventListener('orientationchange', () => {
      setTimeout(() => {
        if (mapInstance) mapInstance.invalidateSize();
      }, 250);
    });
  }

  await carregarPrestadoresAPI();

  renderChips();
  renderAll();
  renderDestaques();

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
      const id = e.target.dataset.req;
      if (id && !busy) request(+id);
    };
  }

  if ($('#pay')) {
    $('#pay').onclick = () => {
      $('#pay').hidden = true;
      toast('Transação processada com sucesso via PertoJá Pagamentos.');
      info('Pagamento registrado. Obrigado por utilizar a plataforma!');
    };
  }

  if ($('#novo')) {
    $('#novo').onclick = async () => {
      clearAllSimulationTimers();
      busy = false;
      order = null;
      if ($('#pedidoBox')) $('#pedidoBox').hidden = true;
      if ($('#painel-lista')) $('#painel-lista').hidden = false;
      await carregarPrestadoresAPI();
      renderAll();
    };
  }

  // Vincula evento de GPS a todos os botões de disparo de geolocalização
  const gpsBtns = document.querySelectorAll('#btnLoc, #btnGpsBusca, .btn-gps-trigger');
  gpsBtns.forEach(btn => {
    btn.onclick = ativarGeolocalizacaoGPS;
  });
});

// Expõe globalmente para navegação, handlers HTML e testes
window.request = request;
window.irParaCategoria = irParaCategoria;
window.buscarPorEnderecoCliente = buscarPorEnderecoCliente;
window.carregarPrestadoresAPI = carregarPrestadoresAPI;
window.renderAll = renderAll;
window.renderDestaques = renderDestaques;
window.clearAllSimulationTimers = clearAllSimulationTimers;
