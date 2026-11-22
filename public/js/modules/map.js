// public/js/modules/map.js - Listagem, chips de categoria e renderização do mapa Leaflet

import {
  CATEGORIES,
  brl,
  dist,
  getServiceScore,
  qs,
  store,
  visible
} from './state.js';
import {
  escapeHtml,
  exibirAlertaRetry,
  getCategoryIcon,
  renderSkeletonList,
  startLoading,
  stopLoading
} from './ui.js';

export async function carregarPrestadoresAPI() {
  startLoading();
  renderSkeletonList();
  try {
    const params = new URLSearchParams({
      cat: store.cat,
      radius: String(store.radius),
      lat: String(store.centerLat),
      lng: String(store.centerLng),
      order: store.currentOrder
    });
    if (store.searchQuery) params.set('query', store.searchQuery);
    if (store.onlyAvailable) params.set('only_available', '1');

    const url = `/api/services?${params.toString()}`;
    let res = await fetch(url);
    if (res.status === 429 || res.status >= 500) {
      await new Promise((resolve) => setTimeout(resolve, 800));
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
        store.providers = data.map((item) => ({
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
  } catch (_) {
    console.log('Utilizando base de prestadores local/fallback.');
  } finally {
    stopLoading();
  }
}

export function renderChips() {
  const chipsEl = qs('#chips');
  if (!chipsEl) return;
  const buttons = CATEGORIES.map((c) => {
    const isSelected = c.toLowerCase() === store.cat.toLowerCase();
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `chip ${isSelected ? 'on' : ''}`;
    btn.dataset.c = c;
    btn.setAttribute('aria-pressed', String(isSelected));
    btn.setAttribute('aria-label', `Filtrar por categoria ${c}`);
    btn.textContent = c;
    return btn;
  });
  chipsEl.replaceChildren(...buttons);
}

export function renderList() {
  const listEl = qs('#list');
  if (!listEl) return;
  const v = visible().sort((a, b) => {
    if (store.currentOrder === 'score') {
      return (getServiceScore(b) - getServiceScore(a)) || (dist(a) - dist(b));
    }
    return dist(a) - dist(b);
  });
  if (qs('#count')) {
    qs('#count').textContent = '(' + v.length + ')';
    qs('#count').classList.add('tabular-nums');
  }
  if (!v.length) {
    /* eslint-disable-next-line no-unsanitized/property -- interpolações auditadas por scripts/check_xss_lint.js */
    listEl.innerHTML = `
      <div class="empty-state-card" role="status" aria-live="polite">
        <p class="empty-title">Nenhum serviço encontrado nesta área</p>
        <p class="empty-desc">Não encontramos profissionais disponíveis neste raio de <span class="tabular-nums">${Number(store.radius) || 8} km</span>. Experimente expandir o raio de busca.</p>
        <button type="button" class="btn" data-action="expand-radius" aria-label="Expandir raio de busca para 15 km" style="font-size: 0.82rem; padding: 8px 16px; border-radius: 9999px;">
          Expandir raio para 15 km
        </button>
      </div>`;
    return;
  }
  /* eslint-disable-next-line no-unsanitized/property -- interpolações auditadas por scripts/check_xss_lint.js */
  listEl.innerHTML = v.map((p) => {
    const isSuper = p.super_profissional || (p.r >= 4.8 && (p.total_avaliacoes || 0) >= 5);
    const kycTierNum = Number(p.kyc_tier || 1);
    const isBestCard = Boolean(store.order && store.order.best && store.order.best.id === p.id);
    const kycBadgeHtml = kycTierNum >= 2
      ? `<span class="kyc-badge aprovado tabular-nums" title="Identidade e registro profissional verificados">Verificado Nível ${Number(kycTierNum)}</span>`
      : '';
    const superBadgeHtml = isSuper ? '<span class="super-badge">★ Super Profissional</span>' : '';
    const approxHtml = p.localizacao_aproximada ? ' · Região aproximada' : '';
    return `
   <div class="svc ${isBestCard ? 'best' : ''}">
     <div class="svc-card-row">
       <div class="svc-avatar" aria-hidden="true">
         <span class="material-symbols-outlined">${escapeHtml(getCategoryIcon(p.c))}</span>
       </div>
       <div class="flex-1 min-w-0 space-y-1.5">
         <div class="top">
           <span class="font-bold text-perto-ink">${escapeHtml(p.s)}</span>
           <span class="price tabular-nums">${brl(Number(p.p || 0))}</span>
         </div>
         <div class="text-xs font-semibold text-perto-sea flex items-center gap-1.5 truncate">
           <span class="material-symbols-outlined text-sm shrink-0" aria-hidden="true">location_on</span>
           <span class="truncate">${escapeHtml(p.endereco || 'São Paulo - SP')}${approxHtml}</span>
         </div>
         <div class="meta flex flex-wrap items-center gap-x-3 gap-y-1.5 text-perto-ink/80">
           <span class="inline-flex items-center gap-1 font-semibold text-perto-ink"><span class="material-symbols-outlined text-sm text-perto-sea" aria-hidden="true">person</span> ${escapeHtml(p.n)}</span>
           <span class="tabular-nums font-bold text-perto-ink">★ ${Number(p.r || 0).toFixed(1)}</span>
           <span class="tabular-nums font-semibold text-perto-ink/80">${Number(dist(p)).toFixed(1)} km</span>
           <span class="tag">${escapeHtml(p.c)}</span>
           ${kycBadgeHtml}
           ${superBadgeHtml}
           <span class="tag ${p.a ? '' : 'off'}">${p.a ? 'Disponível' : 'Indisponível'}</span>
         </div>
       </div>
     </div>
     <div class="mt-3 flex justify-end">
       <button type="button" class="btn btn-requisitar font-extrabold shadow-sm" data-req="${Number(p.id)}" aria-label="Solicitar atendimento de ${escapeHtml(p.n)} para ${escapeHtml(p.s)}" ${(!p.a || store.busy) ? 'disabled' : ''}>Solicitar Atendimento</button>
     </div>
    </div>`;
  }).join('');
}

export function renderMap(posAtual) {
  if (!store.mapInstance || !store.layerMarkers) return;
  store.layerMarkers.clearLayers();

  L.circle([store.centerLat, store.centerLng], { radius: store.radius * 1000, color: '#1f6f8b', fillOpacity: 0.07, weight: 2 }).addTo(store.layerMarkers);

  const searchMarker = L.circleMarker([store.centerLat, store.centerLng], {
    radius: 11,
    color: '#ffffff',
    fillColor: '#1f6f8b',
    fillOpacity: 1,
    weight: 3
  });
  searchMarker.bindTooltip('Sua Localização de Busca', { permanent: true, direction: 'right', className: 'map-label' });
  searchMarker.bindPopup(`
    <div style="font-family: inherit; font-size: 0.85rem; min-width: 190px;">
      <h4 style="margin: 0 0 4px; color: #10243e; font-size: 0.95rem;">📍 Local Pesquisado</h4>
      <div style="color: var(--sea); font-weight: 700; margin-bottom: 4px;">${escapeHtml(store.currentSearchAddress || 'Endereço atual')}</div>
      <div style="font-size: 0.75rem; color: #666;">Coordenadas: ${Number(store.centerLat).toFixed(5)}, ${Number(store.centerLng).toFixed(5)}</div>
    </div>
  `);
  searchMarker.addTo(store.layerMarkers);

  visible().forEach((p) => {
    const isBest = store.order && store.order.best.id === p.id;
    if (isBest && posAtual) return;
    const color = isBest ? '#ffc233' : p.a ? '#1a8f5a' : '#9aa7b1';
    const marker = L.circleMarker([p.lat, p.lng], {
      radius: isBest ? 11 : 8,
      color: '#10243e',
      fillColor: color,
      fillOpacity: 1,
      weight: isBest ? 3 : 1.5
    });
    marker.bindTooltip(escapeHtml(p.n.split(' ')[0]), { permanent: true, direction: 'right', className: 'map-label' });
    const isAvail = p.a && !store.busy;
    marker.bindPopup(`
      <div style="font-family: inherit; font-size: 0.85rem; min-width: 170px;">
        <h4 style="margin: 0 0 4px; color: #10243e; font-size: 0.95rem;">${escapeHtml(p.s)}</h4>
        <div style="color: var(--sea); font-weight: 800; font-size: 1rem; margin-bottom: 4px;">${brl(Number(p.p || 0))}</div>
        <div style="color: #444; margin-bottom: 3px;">👤 <b>${escapeHtml(p.n)}</b> · ★ ${Number(p.r || 0).toFixed(1)}</div>
        <div style="color: #666; font-size: 0.75rem; margin-bottom: 4px;">📍 ${escapeHtml(p.endereco || 'São Paulo - SP')}${p.localizacao_aproximada ? ' (região aproximada)' : ''}</div>
        ${p.localizacao_aproximada ? '<div style="color: #4b6073; font-size: 0.72rem; margin-bottom: 4px;">🔒 Localização aproximada na vitrine para proteção de privacidade</div>' : ''}
        <div style="color: var(--ok); font-weight: bold; font-size: 0.8rem; margin-bottom: 8px;">A ${Number(dist(p)).toFixed(1)} km de você</div>
        <button type="button" class="btn btn-requisitar" data-request-id="${Number(p.id)}" aria-label="Requisitar atendimento de ${escapeHtml(p.n)}" style="width: 100%; min-height: 38px; font-size: 0.82rem; padding: 8px 14px; ${isAvail ? '' : 'opacity: 0.55; cursor: not-allowed;'}" ${isAvail ? '' : 'disabled'}>
          ${isAvail ? 'Requisitar Agora' : (store.busy ? 'Atendimento em Andamento' : 'Indisponível no Momento')}
        </button>
      </div>
    `);
    marker.addTo(store.layerMarkers);
  });

  if (store.order && posAtual) {
    L.polyline([[posAtual.lat, posAtual.lng], [store.centerLat, store.centerLng]], { color: '#ffc233', dashArray: '6, 6', weight: 3 }).addTo(store.layerMarkers);
    L.circleMarker([posAtual.lat, posAtual.lng], { radius: 12, color: '#10243e', fillColor: '#ffc233', fillOpacity: 1, weight: 3 })
      .bindTooltip(escapeHtml(store.order.best.n.split(' ')[0]), { permanent: true, direction: 'right', className: 'map-label' }).addTo(store.layerMarkers);
  }
}

export function renderAll() {
  renderList();
  renderMap(store.order && store.order.pos);
}

export function initLeafletMap() {
  const mapEl = document.getElementById('map');
  if (!mapEl || typeof L === 'undefined') return null;

  store.mapInstance = L.map('map', {
    scrollWheelZoom: false,
    touchZoom: true,
    tap: true,
    dragging: true
  }).setView([store.centerLat, store.centerLng], 13);

  const tileLayerEsri = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Dados geoespaciais &copy; Esri, OpenStreetMap',
    maxZoom: 18
  });

  tileLayerEsri.on('tileerror', () => {
    if (!window.mapTileFallbackActivated && store.mapInstance) {
      window.mapTileFallbackActivated = true;
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 18
      }).addTo(store.mapInstance);
    }
  });

  tileLayerEsri.addTo(store.mapInstance);
  store.layerMarkers = L.layerGroup().addTo(store.mapInstance);
  window.mapInstance = store.mapInstance;
  window.map = store.mapInstance;

  const resizeMap = () => {
    if (store.mapInstance) store.mapInstance.invalidateSize();
  };
  window.addEventListener('resize', resizeMap);
  window.addEventListener('orientationchange', () => {
    setTimeout(resizeMap, 250);
  });

  return store.mapInstance;
}
