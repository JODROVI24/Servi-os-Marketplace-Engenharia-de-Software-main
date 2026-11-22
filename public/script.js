// script.js - Entrypoint modular do catálogo, mapa geográfico e tracking do PertoJá

import {
  brl,
  clearAllSimulationTimers,
  qs,
  store
} from './js/modules/state.js';
import {
  escapeHtml,
  sanitizarUrlSegura
} from './js/modules/ui.js';
import {
  carregarPrestadoresAPI,
  initLeafletMap,
  renderAll,
  renderChips
} from './js/modules/map.js';
import {
  ativarGeolocalizacaoGPS,
  buscarPorEnderecoCliente,
  inicializarLocalizacaoInicial
} from './js/modules/geocode.js';
import {
  bindOrderListeners,
  exibirModalAuthObrigatoria,
  request,
  sincronizarRetornoPagamentoERestaurar,
  verificarERestaurarPedidoPendente
} from './js/modules/orders.js';

function beginLoadingButton(btn, loadingLabel) {
  if (!btn) return () => {};
  const originalNodes = typeof window.salvarConteudoBotao === 'function' ? window.salvarConteudoBotao(btn) : [];
  btn.classList.add('is-loading');
  btn.disabled = true;
  btn.textContent = loadingLabel;
  return () => {
    btn.classList.remove('is-loading');
    btn.disabled = false;
    if (typeof window.restaurarConteudoBotao === 'function') {
      window.restaurarConteudoBotao(btn, originalNodes);
    }
  };
}

async function withLoadingButton(btn, loadingLabel, fn) {
  const restore = beginLoadingButton(btn, loadingLabel);
  try {
    return await fn();
  } finally {
    restore();
  }
}

export function irParaCategoria(c) {
  location.href = 'pedido.html?cat=' + encodeURIComponent(c);
}

export function renderDestaques() {
  const destaquesEl = document.getElementById('destaques-home');
  if (!destaquesEl) return;
  const top3 = [...store.providers].sort((a, b) => b.r - a.r).slice(0, 3);
  /* eslint-disable-next-line no-unsanitized/property -- interpolações auditadas por scripts/check_xss_lint.js */
  destaquesEl.innerHTML = top3.map((p, index) => {
    const destUrl = sanitizarUrlSegura(`pedido.html?cat=${encodeURIComponent(p.c)}&q=${encodeURIComponent(p.s)}`, 'pedido.html');
    const bairroClean = p.bairro || (p.endereco ? String(p.endereco).split('·')[1] || String(p.endereco).split(',')[0] : 'São Paulo');
    return `
    <div class="card-home clicavel" role="button" tabindex="0" data-dest-url="${escapeHtml(destUrl)}" style="cursor: pointer; animation-delay: ${Number(index) * 0.1}s;" aria-label="Ver ${escapeHtml(p.s)} com ${escapeHtml(p.n)}">
      <div class="card-texto" style="text-align: center;">
        <div class="flex items-center justify-center gap-2 mb-2">
          <span class="tag">${escapeHtml(p.c)}</span>
          <span class="tabular-nums font-extrabold text-perto-ink text-sm">★ ${Number(p.r || 0).toFixed(1)}</span>
        </div>
        <h3 style="color: var(--ink); margin-bottom: 4px;">${escapeHtml(p.n)}</h3>
        <p style="color: var(--sea); font-weight: 700; margin-bottom: 6px;">${escapeHtml(p.s)}</p>
        <p class="text-xs font-semibold text-perto-ink/80 mb-2 flex items-center justify-center gap-1">
          <span class="material-symbols-outlined text-sm text-perto-sea" aria-hidden="true">location_on</span>
          <span>${escapeHtml(String(bairroClean).trim())}</span>
        </p>
        <p class="tabular-nums" style="font-size: 1.15rem; color: var(--sea); font-weight: 800; margin-top: 8px;">${brl(Number(p.p || 0))}</p>
      </div>
    </div>
  `;
  }).join('');
  destaquesEl.querySelectorAll('[data-dest-url]').forEach((card) => {
    const go = () => {
      const url = sanitizarUrlSegura(card.getAttribute('data-dest-url') || '', 'pedido.html');
      if (url && url !== '#') location.href = url;
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

function bindFilterAndMapListeners() {
  window.addEventListener('pertoja:location-changed', async (e) => {
    const det = (e && e.detail) ? e.detail : null;
    if (!det) return;
    const nLat = parseFloat(det.lat);
    const nLng = parseFloat(det.lng);
    if (!isNaN(nLat) && !isNaN(nLng)) {
      store.centerLat = nLat;
      store.centerLng = nLng;
      store.currentSearchAddress = det.label || det.address || store.currentSearchAddress;
      const locInfo = qs('#locInfo');
      if (locInfo) locInfo.textContent = `Ponto de busca: ${store.currentSearchAddress}`;
      if (store.mapInstance) {
        store.mapInstance.setView([store.centerLat, store.centerLng], 14, { animate: true });
        setTimeout(() => { if (store.mapInstance) store.mapInstance.invalidateSize(); }, 200);
      }
      await carregarPrestadoresAPI();
      renderAll();
    }
  });

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
      if (isMapa && store.mapInstance) {
        setTimeout(() => store.mapInstance.invalidateSize(), 120);
      }
    };
    btnViewLista.onclick = () => setMobileView('lista');
    btnViewMapa.onclick = () => setMobileView('mapa');
  }

  const inputFiltro = document.getElementById('inputFiltroServico');
  let timerBuscaDebounce = null;
  if (inputFiltro) {
    if (store.searchQuery) inputFiltro.value = store.searchQuery;
    inputFiltro.oninput = (e) => {
      store.searchQuery = e.target.value.trim();
      renderAll();
      clearTimeout(timerBuscaDebounce);
      timerBuscaDebounce = setTimeout(async () => {
        await carregarPrestadoresAPI();
        renderAll();
      }, 300);
    };
  }

  const btnOnlyAvail = document.getElementById('btnOnlyAvailable');
  if (btnOnlyAvail) {
    btnOnlyAvail.onclick = async () => {
      store.onlyAvailable = !store.onlyAvailable;
      btnOnlyAvail.classList.toggle('on', store.onlyAvailable);
      btnOnlyAvail.setAttribute('aria-pressed', store.onlyAvailable ? 'true' : 'false');
      await carregarPrestadoresAPI();
      renderAll();
    };
  }

  const sortBtns = document.querySelectorAll('.sort-btn[data-order]');
  sortBtns.forEach((btn) => {
    btn.onclick = async () => {
      const nextOrder = btn.dataset.order;
      if (!nextOrder || nextOrder === store.currentOrder) return;
      store.currentOrder = nextOrder;
      sortBtns.forEach((b) => {
        const active = b.dataset.order === store.currentOrder;
        b.classList.toggle('on', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      await carregarPrestadoresAPI();
      renderAll();
    };
  });

  if (qs('#chips')) {
    qs('#chips').onclick = async (e) => {
      const c = e.target.dataset.c;
      if (!c) return;
      store.cat = c;
      renderChips();
      await carregarPrestadoresAPI();
      renderAll();
    };
  }

  let timerRaioDebounce = null;
  if (qs('#raio')) {
    qs('#raio').oninput = (e) => {
      store.radius = +e.target.value;
      if (qs('#raioV')) qs('#raioV').textContent = store.radius + ' km';
      if (store.mapInstance) store.mapInstance.setZoom(store.radius > 8 ? 12 : (store.radius < 4 ? 14 : 13));
      renderAll();
      clearTimeout(timerRaioDebounce);
      timerRaioDebounce = setTimeout(async () => {
        await carregarPrestadoresAPI();
        renderAll();
      }, 350);
    };
  }

  const listContainer = qs('#list');
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
      if (id && !store.busy) request(+id);
    });
  }

  const mapContainer = document.getElementById('map');
  if (mapContainer) {
    mapContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-requisitar[data-request-id]');
      if (!btn || btn.disabled) return;
      const id = btn.dataset.requestId;
      if (id && !store.busy) request(+id);
    });
  }

  document.querySelectorAll('#btnLoc, #btnGpsBusca, .btn-gps-trigger').forEach((btn) => {
    btn.onclick = (e) => ativarGeolocalizacaoGPS(e, beginLoadingButton);
  });
}

async function initApp() {
  initLeafletMap();
  await inicializarLocalizacaoInicial();
  await carregarPrestadoresAPI();
  renderChips();
  renderAll();
  renderDestaques();
  bindFilterAndMapListeners();
  bindOrderListeners();
  await sincronizarRetornoPagamentoERestaurar();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}

const buscarEnderecoBinding = () => buscarPorEnderecoCliente(withLoadingButton);

// Expõe globalmente para navegação, handlers HTML e testes
window.request = request;
window.irParaCategoria = irParaCategoria;
window.buscarPorEnderecoCliente = buscarEnderecoBinding;
window.carregarPrestadoresAPI = carregarPrestadoresAPI;
window.renderAll = renderAll;
window.renderDestaques = renderDestaques;
window.clearAllSimulationTimers = clearAllSimulationTimers;
window.exibirModalAuthObrigatoria = exibirModalAuthObrigatoria;
window.verificarERestaurarPedidoPendente = verificarERestaurarPedidoPendente;
