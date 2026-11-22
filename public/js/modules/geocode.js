// public/js/modules/geocode.js - Geocodificação, consulta de CEP e geolocalização GPS do cliente

import { qs, store } from './state.js';
import { exibirAlertaRetry, startLoading, stopLoading, toast } from './ui.js';
import { carregarPrestadoresAPI, renderAll } from './map.js';

export async function buscarPorEnderecoCliente(withLoadingButton = null) {
  const input = document.getElementById('inputBuscaEndereco');
  if (!input || !input.value.trim()) return;
  const q = input.value.trim();
  const cleanCep = q.replace(/\D/g, '');
  const btnBusca = document.getElementById('btnBuscarEndereco') || document.getElementById('btnBuscarEnderecoHero');

  const runSearch = async () => {
    toast('Buscando localização...');
    startLoading();
    try {
      let lat = null;
      let lng = null;
      let label = q;

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

        if ((lat == null || lng == null || isNaN(lat) || isNaN(lng)) && typeof fetch !== 'undefined') {
          let street = '';
          let bairro = '';
          let city = '';
          let uf = '';
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
          } catch (_) {}

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
            } catch (_) {}
          }

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
            } catch (_) {}
          }
        }
      }

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
        } catch (_) {}

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
          } catch (_) {}
        }
      }

      if (lat != null && lng != null && !isNaN(lat) && !isNaN(lng)) {
        store.centerLat = lat;
        store.centerLng = lng;
        store.currentSearchAddress = label;

        if (store.mapInstance) {
          store.mapInstance.setView([store.centerLat, store.centerLng], 14, { animate: true });
          setTimeout(() => {
            if (store.mapInstance) store.mapInstance.invalidateSize();
          }, 200);
        }

        const locInfo = document.getElementById('locInfo');
        if (locInfo) locInfo.textContent = `Ponto de busca: ${label}`;

        const statusBox = document.getElementById('statusBuscaEndereco');
        if (statusBox) {
          statusBox.style.display = 'flex';
          const iconSpan = document.createElement('span');
          iconSpan.className = 'material-symbols-outlined text-sm text-perto-ok';
          iconSpan.setAttribute('aria-hidden', 'true');
          iconSpan.textContent = 'check_circle';
          const msgSpan = document.createElement('span');
          const boldEl = document.createElement('b');
          boldEl.textContent = String(label || '');
          msgSpan.append('Endereço localizado: ', boldEl);
          statusBox.replaceChildren(iconSpan, msgSpan);
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
  };

  if (typeof withLoadingButton === 'function') {
    await withLoadingButton(btnBusca, 'Buscando...', runSearch);
  } else {
    await runSearch();
  }
}

export async function inicializarLocalizacaoInicial() {
  let atualizado = false;
  try {
    const savedLocRaw = localStorage.getItem('pertoja_search_loc');
    if (savedLocRaw) {
      const savedLoc = JSON.parse(savedLocRaw);
      const sLat = parseFloat(savedLoc.lat);
      const sLng = parseFloat(savedLoc.lng);
      if (!isNaN(sLat) && !isNaN(sLng)) {
        store.centerLat = sLat;
        store.centerLng = sLng;
        store.currentSearchAddress = savedLoc.label || savedLoc.address || store.currentSearchAddress;
        atualizado = true;
      }
    }
  } catch (_) {}

  if (typeof window !== 'undefined' && typeof window.obterUsuarioLogado === 'function') {
    try {
      store.cachedLoggedUser = await window.obterUsuarioLogado();
    } catch (_) {
      store.cachedLoggedUser = null;
    }
  }

  if (!atualizado && store.cachedLoggedUser && store.cachedLoggedUser.tipo === 'cliente') {
    const uLat = parseFloat(store.cachedLoggedUser.lat);
    const uLng = parseFloat(store.cachedLoggedUser.lng);
    if (!isNaN(uLat) && !isNaN(uLng)) {
      store.centerLat = uLat;
      store.centerLng = uLng;
      const partes = [
        store.cachedLoggedUser.endereco,
        store.cachedLoggedUser.numero,
        store.cachedLoggedUser.bairro,
        store.cachedLoggedUser.cidade
      ].filter(Boolean);
      if (partes.length) store.currentSearchAddress = partes.join(', ');
      atualizado = true;
    }
  }

  if (atualizado) {
    const locInfo = qs('#locInfo');
    if (locInfo) locInfo.textContent = `Ponto de busca: ${store.currentSearchAddress}`;
    if (store.mapInstance) store.mapInstance.setView([store.centerLat, store.centerLng], 13);
  }
}

export function ativarGeolocalizacaoGPS(e, beginLoadingButton = null) {
  if (!navigator.geolocation) {
    toast('O navegador atual não suporta geolocalização.');
    return;
  }
  const triggerBtn = (e && e.currentTarget) ? e.currentTarget : (document.getElementById('btnGpsBusca') || document.getElementById('btnLoc'));
  const restoreBtn = typeof beginLoadingButton === 'function'
    ? beginLoadingButton(triggerBtn, 'Obtendo GPS...')
    : () => {};

  const locInfo = qs('#locInfo');
  if (locInfo) locInfo.textContent = 'Obtendo sinal do satélite GPS...';
  navigator.geolocation.getCurrentPosition(
    async (g) => {
      try {
        store.centerLat = g.coords.latitude;
        store.centerLng = g.coords.longitude;
        if (store.mapInstance) store.mapInstance.setView([store.centerLat, store.centerLng], 14);
        if (locInfo) locInfo.textContent = 'Precisão obtida: ±' + Math.round(g.coords.accuracy) + ' metros.';
        toast('Posição geográfica atualizada via GPS.');
        await carregarPrestadoresAPI();
        renderAll();
      } finally {
        restoreBtn();
      }
    },
    (erro) => {
      restoreBtn();
      const motivo = erro.code === erro.PERMISSION_DENIED ? 'Acesso não permitido pelo usuário.' : 'Falha na comunicação de rede/GPS.';
      if (locInfo) locInfo.textContent = 'Erro: ' + motivo;
      toast('Geolocalização indisponível: ' + motivo);
    },
    { enableHighAccuracy: false, timeout: 15000, maximumAge: 0 }
  );
}
