// public/js/modules/ui.js - Primitivos de UI, sanitização e feedback visual do PertoJá

import { qs, store } from './state.js';

export function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function sanitizarUrlSegura(url, fallback = '#') {
  if (typeof url !== 'string') return fallback;
  const trimmed = url.trim();
  if (!trimmed || /[\u0000-\u001F\u007F\\]/.test(trimmed)) return fallback;
  if (/^(javascript|data|vbscript|file):/i.test(trimmed) || trimmed.startsWith('//')) {
    return fallback;
  }
  return trimmed;
}

export function sanitizeSafeUrl(url) {
  if (typeof url !== 'string') return '';
  const trimmed = url.trim();
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^\/(?!\/)/.test(trimmed)) return trimmed;
  return '';
}

export function toast(t) {
  const container = qs('#toasts');
  if (!container) return;
  const d = document.createElement('div');
  d.className = 'toast toast-animated flex items-center gap-2 transition-all duration-300 ease-out';
  const msg = String(t || '');
  const lower = msg.toLowerCase();
  let icon = 'check_circle';
  if (lower.includes('erro') || lower.includes('falha') || lower.includes('indisponível') || lower.includes('recusado') || lower.includes('não foi possível')) {
    icon = 'error';
  } else if (lower.includes('buscando') || lower.includes('obtendo') || lower.includes('verificando') || lower.includes('aguardando') || lower.includes('sincronizando')) {
    icon = 'autorenew';
  } else if (lower.includes('atenção') || lower.includes('⚠️') || lower.includes('necessário') || lower.includes('expirou')) {
    icon = 'warning';
  }
  const iconSpan = document.createElement('span');
  iconSpan.className = 'material-symbols-outlined text-base shrink-0';
  iconSpan.setAttribute('aria-hidden', 'true');
  iconSpan.textContent = icon;
  const textSpan = document.createElement('span');
  textSpan.textContent = msg;
  d.append(iconSpan, textSpan);
  container.append(d);
  setTimeout(() => {
    d.style.opacity = '0';
    d.style.transform = 'translateY(6px)';
    setTimeout(() => d.remove(), 250);
  }, 4250);
}

export function atualizarEstadoCarregamento(ativo) {
  const mapEl = document.getElementById('map');
  if (mapEl) {
    let overlay = mapEl.querySelector('.map-loading-overlay');
    if (ativo) {
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'map-loading-overlay';
        overlay.setAttribute('role', 'status');
        overlay.setAttribute('aria-live', 'polite');
        const spin = document.createElement('div');
        spin.className = 'map-spinner';
        spin.setAttribute('aria-hidden', 'true');
        const txt = document.createElement('span');
        txt.textContent = 'Buscando serviços...';
        overlay.replaceChildren(spin, txt);
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
        const spinSm = document.createElement('span');
        spinSm.className = 'map-spinner-sm';
        spinSm.setAttribute('aria-hidden', 'true');
        const txtSm = document.createElement('span');
        txtSm.textContent = 'Buscando serviços...';
        statusEl.replaceChildren(spinSm, txtSm);
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

export function startLoading() {
  store.loadingDepth++;
  atualizarEstadoCarregamento(true);
}

export function stopLoading() {
  store.loadingDepth = Math.max(0, store.loadingDepth - 1);
  if (store.loadingDepth === 0) {
    atualizarEstadoCarregamento(false);
  }
}

export function exibirAlertaRetry(status) {
  let banner = document.getElementById('alertaRetryBanner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'alertaRetryBanner';
    banner.className = 'alerta-retry';
    banner.setAttribute('role', 'alert');
    banner.setAttribute('aria-live', 'assertive');
    document.body.appendChild(banner);
  }
  const codigo = status ? ` (HTTP ${Number(status)})` : '';
  const msgSpan = document.createElement('span');
  msgSpan.textContent = `Serviço temporariamente ocupado ou indisponível${codigo}. Tente novamente em alguns segundos.`;
  const btnClose = document.createElement('button');
  btnClose.type = 'button';
  btnClose.className = 'alerta-retry-close';
  btnClose.setAttribute('aria-label', 'Fechar aviso');
  btnClose.textContent = 'Fechar';
  btnClose.addEventListener('click', () => banner.remove());
  banner.replaceChildren(msgSpan, btnClose);
}

export function renderSkeletonList() {
  const listEl = qs('#list');
  if (!listEl) return;
  const specs = [
    'height: 20px; width: 60%; margin-bottom: 8px;',
    'height: 14px; width: 85%; margin-bottom: 8px;',
    'height: 14px; width: 40%; margin-bottom: 12px;',
    'height: 36px; width: 100%; border-radius: 9999px;'
  ];
  const nodes = [1, 2, 3].map(() => {
    const card = document.createElement('div');
    card.className = 'svc skeleton-card';
    card.style.cssText = 'padding: 16px; border-radius: 12px; margin-bottom: 12px;';
    specs.forEach((cssText) => {
      const bar = document.createElement('div');
      bar.className = 'skeleton';
      bar.style.cssText = cssText;
      card.appendChild(bar);
    });
    return card;
  });
  listEl.replaceChildren(...nodes);
}

export function getCategoryIcon(catName) {
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

export function gerarIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `idem_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

function fallbackCopyText(valor) {
  const tmp = document.createElement('textarea');
  tmp.value = valor;
  tmp.setAttribute('readonly', 'readonly');
  tmp.style.position = 'fixed';
  tmp.style.opacity = '0';
  document.body.appendChild(tmp);
  tmp.select();
  try { document.execCommand('copy'); } catch (_) {}
  document.body.removeChild(tmp);
}

export function copiarTextoSeguro(texto, mensagemSucesso) {
  const valor = String(texto || '');
  if (!valor) return;
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    navigator.clipboard.writeText(valor)
      .then(() => toast(mensagemSucesso || 'Copiado para a área de transferência!'))
      .catch(() => {
        fallbackCopyText(valor);
        toast(mensagemSucesso || 'Copiado para a área de transferência!');
      });
    return;
  }
  fallbackCopyText(valor);
  toast(mensagemSucesso || 'Copiado para a área de transferência!');
}
