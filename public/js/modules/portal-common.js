// public/js/modules/portal-common.js - Utilitários compartilhados entre Portal do Cliente e Portal do Prestador

export const brl = (v) => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

export function toast(t) {
  const container = document.getElementById('toasts');
  if (!container) return;
  const d = document.createElement('div');
  d.className = 'toast toast-animated flex items-center gap-2 transition-all duration-300 ease-out';
  const msg = String(t || '');
  const lower = msg.toLowerCase();
  let icon = 'check_circle';
  if (lower.includes('erro') || lower.includes('falha') || lower.includes('indisponível') || lower.includes('não foi possível')) {
    icon = 'error';
  } else if (
    lower.includes('buscando')
    || lower.includes('obtendo')
    || lower.includes('calculando')
    || lower.includes('recalculando')
    || lower.includes('carregando')
  ) {
    icon = 'autorenew';
  } else if (lower.includes('atenção') || lower.includes('pausa') || lower.includes('encerrado')) {
    icon = 'warning';
  }
  const iconSpan = document.createElement('span');
  iconSpan.className = 'material-symbols-outlined text-base shrink-0';
  iconSpan.setAttribute('aria-hidden', 'true');
  iconSpan.textContent = icon;
  const textSpan = document.createElement('span');
  textSpan.textContent = msg;
  d.append(iconSpan, textSpan);
  container.appendChild(d);
  setTimeout(() => {
    d.style.opacity = '0';
    d.style.transform = 'translateY(6px)';
    setTimeout(() => d.remove(), 250);
  }, 3750);
}

export function escapeHtml(str) {
  if (typeof window !== 'undefined' && typeof window.escapeHtml === 'function' && window.escapeHtml !== escapeHtml) {
    return window.escapeHtml(str);
  }
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function sanitizarUrlSegura(url, fallback = '#') {
  if (typeof window !== 'undefined' && typeof window.sanitizarUrlSegura === 'function' && window.sanitizarUrlSegura !== sanitizarUrlSegura) {
    return window.sanitizarUrlSegura(url, fallback);
  }
  if (typeof url !== 'string') return fallback;
  const trimmed = url.trim();
  if (!trimmed || /[\u0000-\u001F\u007F\\]/.test(trimmed)) return fallback;
  if (/^(javascript|data|vbscript|file):/i.test(trimmed) || trimmed.startsWith('//')) {
    return fallback;
  }
  return trimmed;
}

export function setStatusText(el, text, className = 'text-xs text-perto-ink/80') {
  if (!el) return;
  const p = document.createElement('p');
  p.className = className;
  p.textContent = text;
  el.replaceChildren(p);
}

export function formatarMetodoPagamento(metodo) {
  const mapa = {
    escrow: 'Escrow no Local',
    escrow_local: 'Escrow no Local',
    pix: 'Pix (Escrow)',
    cartao: 'Cartão (Escrow)',
    boleto: 'Boleto Bancário (Escrow)'
  };
  return mapa[String(metodo || '').toLowerCase()] || metodo || 'Escrow no Local';
}

export function vincularModalAcessivel(modalId, closeBtnIds = [], onEscapeExtra = null) {
  const modal = document.getElementById(modalId);
  if (!modal) return { abrir: () => {}, fechar: () => {} };
  let triggerEl = null;
  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      fechar();
    }
  };
  const fechar = () => {
    modal.style.display = 'none';
    document.removeEventListener('keydown', onKeyDown);
    if (onEscapeExtra) onEscapeExtra();
    if (triggerEl && typeof triggerEl.focus === 'function') triggerEl.focus();
  };
  const abrir = (focusSelector) => {
    triggerEl = document.activeElement;
    modal.style.display = 'flex';
    document.addEventListener('keydown', onKeyDown);
    if (focusSelector) {
      const el = focusSelector.startsWith('#') || focusSelector.startsWith('.')
        ? modal.querySelector(focusSelector)
        : document.getElementById(focusSelector);
      if (el) setTimeout(() => el.focus(), 0);
    }
  };
  closeBtnIds.forEach((id) => {
    const b = document.getElementById(id);
    if (b) b.addEventListener('click', fechar);
  });
  modal.addEventListener('click', (e) => {
    if (e.target === modal) fechar();
  });
  return { abrir, fechar };
}

const modalTriggers = {};

export function abrirModalAcessivel(modalId, focusElId) {
  modalTriggers[modalId] = document.activeElement;
  const el = document.getElementById(modalId);
  if (!el) return;
  el.style.display = 'flex';
  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      fecharModalAcessivel(modalId);
    }
  };
  el._onKeyDown = onKey;
  document.addEventListener('keydown', onKey);
  el.onclick = (e) => {
    if (e.target === el) fecharModalAcessivel(modalId);
  };
  if (focusElId) setTimeout(() => document.getElementById(focusElId)?.focus(), 0);
}

export function fecharModalAcessivel(modalId) {
  const el = document.getElementById(modalId);
  if (el) {
    el.style.display = 'none';
    if (el._onKeyDown) document.removeEventListener('keydown', el._onKeyDown);
  }
  const trig = modalTriggers[modalId];
  if (trig && typeof trig.focus === 'function') trig.focus();
  delete modalTriggers[modalId];
}

export async function buscarCepPortal(cepVal, fields) {
  if (!cepVal) return;
  const clean = cepVal.replace(/\D/g, '');
  if (clean.length !== 8) return;
  const statusEl = fields.statusId ? document.getElementById(fields.statusId) : null;
  if (statusEl) statusEl.textContent = 'Buscando CEP...';
  try {
    const res = await fetch(`/api/cep/${clean}`);
    if (res.ok) {
      const d = await res.json();
      const setVal = (id, v) => {
        const node = document.getElementById(id);
        if (node) node.value = v;
      };
      setVal(fields.enderecoId, d.logradouro || '');
      setVal(fields.bairroId, d.bairro || '');
      setVal(fields.cidadeId, d.localidade || '');
      setVal(fields.estadoId, d.uf || '');
      if (d.lat && d.lng) {
        setVal(fields.latId, d.lat.toFixed(6));
        setVal(fields.lngId, d.lng.toFixed(6));
      }
      if (statusEl) statusEl.textContent = '✓ Endereço preenchido!';
      document.getElementById(fields.numeroId)?.focus();
    } else if (statusEl) {
      statusEl.textContent = 'CEP não encontrado.';
    }
  } catch (_) {
    if (statusEl) statusEl.textContent = 'Erro ao consultar CEP.';
  }
}

export function capturarLocalizacaoPortal({ latId, lngId, startMessage, successMessage, errorMessage }) {
  if (!navigator.geolocation) {
    toast('Geolocalização não suportada neste navegador.');
    return;
  }
  toast(startMessage || 'Obtendo coordenadas do dispositivo...');
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const latEl = document.getElementById(latId);
      const lngEl = document.getElementById(lngId);
      if (latEl) latEl.value = pos.coords.latitude.toFixed(6);
      if (lngEl) lngEl.value = pos.coords.longitude.toFixed(6);
      toast(successMessage || 'Coordenadas GPS obtidas com sucesso!');
    },
    () => {
      toast(errorMessage || 'Não foi possível obter a localização.');
    }
  );
}

export async function geocodificarEnderecoPortal(fields) {
  const val = (id) => (document.getElementById(id)?.value || '');
  const cep = val(fields.cepId).replace(/\D/g, '');
  const end = val(fields.enderecoId);
  const num = val(fields.numeroId);
  const bairro = val(fields.bairroId);
  const cid = val(fields.cidadeId);
  const uf = val(fields.estadoId);
  const q = `${end} ${num}, ${bairro}, ${cid} - ${uf}, Brasil`;
  toast(fields.startMessage || 'Calculando coordenadas pelo endereço...');
  const setCoords = (lat, lng) => {
    const latEl = document.getElementById(fields.latId);
    const lngEl = document.getElementById(fields.lngId);
    if (latEl) latEl.value = Number(lat).toFixed(6);
    if (lngEl) lngEl.value = Number(lng).toFixed(6);
  };
  try {
    const params = new URLSearchParams({
      q,
      street: end,
      neighborhood: bairro,
      city: cid,
      state: uf
    });
    const res = await fetch(`/api/geocode?${params.toString()}`);
    if (res.ok) {
      const d = await res.json();
      if (d.lat != null && d.lng != null) {
        setCoords(d.lat, d.lng);
        toast(fields.successMessage || 'Coordenadas calculadas!');
        return;
      }
    }
    if (cep.length === 8) {
      const cepRes = await fetch(`/api/cep/${cep}`);
      if (cepRes.ok) {
        const cd = await cepRes.json();
        if (cd.lat != null && cd.lng != null) {
          setCoords(cd.lat, cd.lng);
          toast('Coordenadas atualizadas pelo CEP!');
          return;
        }
      }
    }
    toast('Endereço não localizado com precisão; mantendo coordenadas atuais.');
  } catch (_) {
    toast('Erro ao buscar coordenadas.');
  }
}

export async function exportarDadosLgpdPortal({ errorMessage = 'Não foi possível exportar seus dados.', successMessage = 'Exportação JSON gerada com sucesso!' } = {}) {
  try {
    const res = await fetch('/api/profile/export');
    if (!res.ok) {
      toast(errorMessage);
      return;
    }
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pertoja-meus-dados.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(successMessage);
  } catch (_) {
    toast('Erro de comunicação ao exportar dados.');
  }
}

export function limparArmazenamentoSessaoPortal() {
  try {
    ['pertoja_pending_order', 'pertoja_active_order_id', 'pertoja_search_loc'].forEach((k) => {
      localStorage.removeItem(k);
      sessionStorage.removeItem(k);
    });
    localStorage.clear();
    sessionStorage.clear();
  } catch (_) {}
}

export function onDomReady(fn) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fn);
  } else {
    fn();
  }
}
