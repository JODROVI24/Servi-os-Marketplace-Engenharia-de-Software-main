// public/js/modules/orders.js - Fluxo de solicitação, tracking ao vivo, segurança SOS e chat do pedido

import {
  STEPS,
  brl,
  clearAllSimulationTimers,
  csrfHeaders,
  dist,
  qs,
  score,
  store
} from './state.js';
import {
  escapeHtml,
  exibirAlertaRetry,
  gerarIdempotencyKey,
  toast
} from './ui.js';
import {
  carregarPrestadoresAPI,
  renderAll,
  renderMap
} from './map.js';
import { abrirModalCheckoutPagamento } from './checkout.js';

export function renderSteps(i) {
  const stepsEl = qs('#steps');
  if (stepsEl) {
    const nodes = STEPS.map((t, k) => {
      const sp = document.createElement('span');
      sp.className = `step ${k < i ? 'done' : k === i ? 'now' : ''}`;
      sp.textContent = t;
      return sp;
    });
    stepsEl.replaceChildren(...nodes);
  }
}

export function info(h) {
  const infoEl = qs('#info');
  if (!infoEl) return;
  const p = document.createElement('p');
  if (Array.isArray(h)) {
    h.forEach((part) => {
      if (part == null || part === false || part === '') return;
      if (typeof part === 'string') {
        p.appendChild(document.createTextNode(part));
      } else if (part && typeof part === 'object') {
        if (part.bold != null) {
          const b = document.createElement('b');
          b.textContent = String(part.bold);
          p.appendChild(b);
        } else if (part.highlight != null) {
          const sp = document.createElement('span');
          sp.className = 'font-semibold text-amber-700';
          sp.textContent = String(part.highlight);
          p.appendChild(sp);
        }
      }
    });
  } else {
    p.textContent = String(h || '');
  }
  infoEl.replaceChildren(p);
}

export function exibirModalAuthObrigatoria(pendingOrder) {
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

  /* eslint-disable-next-line no-unsanitized/property -- interpolações auditadas por scripts/check_xss_lint.js */
  modalBackdrop.innerHTML = `
    <div class="modal-conteudo" style="max-width: 460px; text-align: center;">
      <div style="width: 54px; height: 54px; border-radius: 50%; background: rgba(0, 150, 166, 0.12); color: var(--sea); display: flex; align-items: center; justify-content: center; margin: 0 auto 16px;">
        <span class="material-symbols-outlined" aria-hidden="true" style="font-size: 28px;">lock</span>
      </div>
      <h3 id="modalAuthTitulo" style="color: var(--ink); font-size: 1.35rem; font-weight: 900; margin: 0 0 8px;">Identificação Obrigatória</h3>
      <p style="color: #4b6073; font-size: 0.9rem; margin: 0 0 16px; line-height: 1.45;">
        Para concluir a solicitação de <b>${escapeHtml(pendingOrder.titulo)}</b> por <b>${brl(Number(pendingOrder.preco || 0))}</b> com <b>${escapeHtml(pendingOrder.prestador_nome)}</b>, você precisa estar conectado como Cliente.
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

export async function verificarERestaurarPedidoPendente() {
  const legacyPending = localStorage.getItem('pertoja_pending_order');
  if (legacyPending) {
    if (!sessionStorage.getItem('pertoja_pending_order')) {
      try { sessionStorage.setItem('pertoja_pending_order', legacyPending); } catch (_) {}
    }
    try { localStorage.removeItem('pertoja_pending_order'); } catch (_) {}
  }
  const rawPending = sessionStorage.getItem('pertoja_pending_order');
  if (!rawPending) return;

  let pending;
  try {
    pending = JSON.parse(rawPending);
  } catch (_) {
    sessionStorage.removeItem('pertoja_pending_order');
    localStorage.removeItem('pertoja_pending_order');
    return;
  }

  const user = typeof window !== 'undefined' && typeof window.obterUsuarioLogado === 'function' ? await window.obterUsuarioLogado() : null;
  if (!user || user.tipo !== 'cliente') return;

  const mainContainer = document.getElementById('main-content');
  if (!mainContainer || document.getElementById('bannerRestaurarPedido')) return;

  const banner = document.createElement('div');
  banner.id = 'bannerRestaurarPedido';
  banner.className = 'panel border-2 border-perto-sea bg-perto-sea/5 p-4 rounded-2xl flex flex-col sm:flex-row items-center justify-between gap-3 shadow-sm mb-4';
  /* eslint-disable-next-line no-unsanitized/property -- interpolações auditadas por scripts/check_xss_lint.js */
  banner.innerHTML = `
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-full bg-perto-sea text-white flex items-center justify-center font-bold shrink-0">
        <span class="material-symbols-outlined text-lg">restore</span>
      </div>
      <div>
        <div class="text-xs font-extrabold text-perto-sea uppercase tracking-wider">Pedido Pendente Recuperado</div>
        <div class="text-sm font-bold text-perto-ink">${escapeHtml(pending.titulo)} · ${brl(Number(pending.preco || 0))} (${escapeHtml(pending.prestador_nome)})</div>
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

export function pararPollingPedido() {
  if (store.orderPollTimer) {
    clearInterval(store.orderPollTimer);
    store.orderPollTimer = null;
  }
  if (store.orderLocationTimer) {
    clearInterval(store.orderLocationTimer);
    store.orderLocationTimer = null;
  }
}

export function mapStatusToStep(status) {
  const s = (status || '').toLowerCase();
  if (s === 'solicitado') return 1;
  if (s === 'confirmado') return 2;
  if (s === 'em_transito') return 3;
  if (s === 'em_execucao') return 4;
  if (s === 'finalizado') return 5;
  return 0;
}

export function atualizarCodigoConfirmacao(codigo) {
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

export function atualizarPaineisSegurancaPedido(status, pedidoApi) {
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

export async function carregarMensagensPedido(orderDbId) {
  const box = document.getElementById('pedidoChatMessages');
  if (!box || !orderDbId) return;
  try {
    const res = await fetch(`/api/orders/${orderDbId}/messages`);
    if (!res.ok) return;
    const msgs = await res.json();
    if (!Array.isArray(msgs) || !msgs.length) {
      const emptyP = document.createElement('p');
      emptyP.className = 'text-perto-ink/80 text-xs m-0';
      emptyP.textContent = 'Nenhuma mensagem ainda. Use este canal interno para combinar detalhes do atendimento.';
      box.replaceChildren(emptyP);
      return;
    }
    const myId = store.cachedLoggedUser && store.cachedLoggedUser.id;
    const msgNodes = msgs.map((m) => {
      const isMine = myId && String(m.sender_id) === String(myId);
      const autor = String(m.sender_nome || m.sender_tipo || (isMine ? 'Você' : 'Profissional'));
      const texto = String(m.mensagem || m.conteudo || '');
      const rawTs = m.criado_em || m.created_at;
      const hora = rawTs ? String(rawTs).slice(11, 16) : '';

      const card = document.createElement('div');
      card.className = `chat-msg ${isMine ? 'mine bg-perto-sea/10 border-perto-sea/30 ml-6' : 'bg-perto-bg border-perto-road mr-6'} p-2 rounded-lg border`;

      const header = document.createElement('div');
      header.className = 'flex items-center justify-between gap-2 text-[10px] font-bold text-perto-ink/80 mb-0.5';
      const autorEl = document.createElement('span');
      autorEl.textContent = autor;
      header.appendChild(autorEl);
      if (hora) {
        const horaEl = document.createElement('span');
        horaEl.className = 'tabular-nums';
        horaEl.textContent = hora;
        header.appendChild(horaEl);
      }

      const body = document.createElement('div');
      body.className = 'text-xs text-perto-ink break-words';
      body.textContent = texto;

      card.append(header, body);
      return card;
    });
    box.replaceChildren(...msgNodes);
    box.scrollTop = box.scrollHeight;
  } catch (_) {}
}

export function driveVisualOnly(best) {
  const n = 8;
  let k = 0;
  const tick = () => {
    k++;
    if (!store.order) return;
    store.order.gps++;
    if (qs('#gps')) qs('#gps').textContent = store.order.gps;
    const f = Math.min(k / n, 0.92);
    store.order.pos = {
      lat: best.lat * (1 - f) + store.centerLat * f,
      lng: best.lng * (1 - f) + store.centerLng * f
    };
    const left = store.mapInstance ? (store.mapInstance.distance([store.order.pos.lat, store.order.pos.lng], [store.centerLat, store.centerLng]) / 1000) : 0;
    info(left > 0.05
      ? ['O profissional encontra-se a ', { bold: `${left.toFixed(1)} km` }, ` · Estimativa de chegada: ${Math.max(1, Math.round(left * 3))} min.`]
      : 'O profissional está chegando ao seu endereço.');
    renderMap(store.order.pos);
    if (k < n && store.currentOrderData && (store.currentOrderData.status === 'em_transito' || !store.currentOrderData.status)) {
      const isBat = qs('#bat') && qs('#bat').checked;
      store.timer = setTimeout(tick, isBat ? 2500 : 1200);
      store.simulationTimers.push(store.timer);
    }
  };
  store.timer = setTimeout(tick, 1000);
  store.simulationTimers.push(store.timer);
}

export function atualizarModoRastreamento(data) {
  const badge = document.getElementById('trackingModeBadge');
  const hasRealCoords = Boolean(
    data && (
      data.tracking_mode === 'real_gps' ||
      (data.lat != null && data.lng != null) ||
      (data.prestador_lat_atual != null && data.prestador_lng_atual != null)
    )
  );
  const lat = data ? Number(data.lat ?? data.prestador_lat_atual) : NaN;
  const lng = data ? Number(data.lng ?? data.prestador_lng_atual) : NaN;
  const isRealGps = hasRealCoords && Number.isFinite(lat) && Number.isFinite(lng);

  if (badge) {
    if (isRealGps) {
      badge.textContent = 'Posição GPS em tempo real';
      badge.className = 'tag bg-perto-ok/15 text-perto-ok border border-perto-ok/40';
    } else {
      badge.textContent = 'Posição estimada';
      badge.className = 'tag bg-perto-bg text-perto-ink border border-perto-road';
    }
  }

  if (isRealGps && store.order) {
    clearAllSimulationTimers();
    store.order.realGpsActive = true;
    store.order.pos = { lat, lng };
    renderMap(store.order.pos);
  } else if (store.order && data && data.tracking_mode === 'estimated') {
    store.order.realGpsActive = false;
  }
}

export async function buscarLocalizacaoPedidoReal(orderDbId) {
  if (!orderDbId) return null;
  try {
    const res = await fetch(`/api/orders/${orderDbId}/location`);
    if (!res.ok) return null;
    const loc = await res.json();
    atualizarModoRastreamento(loc);
    return loc;
  } catch (_) {
    return null;
  }
}

export function atualizarUIStatusPedido(pedidoApi, best) {
  if (!pedidoApi || !store.order) return;
  store.currentOrderData = pedidoApi;
  if (pedidoApi.codigo_confirmacao) {
    atualizarCodigoConfirmacao(pedidoApi.codigo_confirmacao);
  }
  const status = (pedidoApi.status || 'solicitado').toLowerCase();
  const metodoPg = String(pedidoApi.metodo_pagamento || '').toLowerCase();
  const precisaPagar = !pedidoApi.pago && (
    status === 'finalizado' ||
    (['pix', 'cartao', 'boleto'].includes(metodoPg) && ['solicitado', 'confirmado', 'em_transito', 'em_execucao'].includes(status))
  );
  if (qs('#pay')) qs('#pay').hidden = !precisaPagar;
  const avisoPgSeg = precisaPagar ? { highlight: ' Pagamento pendente — conclua pelo botão Pagar.' } : null;

  const stepIdx = mapStatusToStep(status);
  renderSteps(stepIdx);
  atualizarPaineisSegurancaPedido(status, pedidoApi);
  atualizarModoRastreamento(pedidoApi);
  if (store.order.db_id && ['confirmado', 'em_transito', 'em_execucao', 'em_disputa', 'finalizado', 'cancelado'].includes(status)) {
    carregarMensagensPedido(store.order.db_id);
  }

  if (status === 'solicitado') {
    info(['Aguardando confirmação de ', { bold: best.n }, ' para ', { bold: best.s }, '…', avisoPgSeg]);
  } else if (status === 'confirmado') {
    info([{ bold: best.n }, ' confirmou o atendimento e está se preparando para sair.', avisoPgSeg]);
  } else if (status === 'em_transito') {
    if (precisaPagar) {
      info([{ bold: best.n }, ' está a caminho.', avisoPgSeg]);
    } else if (store.order.realGpsActive) {
      info([{ bold: best.n }, ' está a caminho (GPS em tempo real ativo).']);
    }
    if (!store.order.drivingStarted) {
      store.order.drivingStarted = true;
      toast(`${best.n} iniciou o deslocamento até seu endereço.`);
      if (!store.order.realGpsActive) {
        driveVisualOnly(best);
      }
    }
  } else if (status === 'em_execucao') {
    clearAllSimulationTimers();
    store.order.pos = { lat: store.centerLat, lng: store.centerLng };
    renderMap(store.order.pos);
    info([{ bold: best.n }, ' está no local executando o serviço.', avisoPgSeg]);
  } else if (status === 'finalizado') {
    clearAllSimulationTimers();
    pararPollingPedido();
    store.order.pos = { lat: store.centerLat, lng: store.centerLng };
    renderMap(store.order.pos);
    info(['Ordem de serviço concluída com sucesso!', avisoPgSeg]);
    if (qs('#pay')) qs('#pay').hidden = !precisaPagar;
    if (qs('#novo')) qs('#novo').hidden = false;
    const btnAvaliar = document.getElementById('btnAvaliarAtendimento');
    if (btnAvaliar) btnAvaliar.hidden = Boolean(pedidoApi.ja_avaliado);
  } else if (status === 'cancelado') {
    clearAllSimulationTimers();
    pararPollingPedido();
    sessionStorage.removeItem('pertoja_active_order_id');
    localStorage.removeItem('pertoja_active_order_id');
    info(`Pedido cancelado.${pedidoApi.motivo_cancelamento ? ' Motivo: ' + pedidoApi.motivo_cancelamento : ''}`);
    if (qs('#pay')) qs('#pay').hidden = true;
    if (qs('#novo')) qs('#novo').hidden = false;
    const btnAvaliar = document.getElementById('btnAvaliarAtendimento');
    if (btnAvaliar) btnAvaliar.hidden = true;
  }
}

export async function buscarEstadoPedidoReal(orderDbId) {
  try {
    const res = await fetch('/api/orders');
    if (!res.ok) return null;
    const list = await res.json();
    if (!Array.isArray(list)) return null;
    return list.find((o) => String(o.order_id) === String(orderDbId)) || null;
  } catch (_) {
    return null;
  }
}

export function iniciarPollingPedido(orderDbId, best) {
  pararPollingPedido();
  store.orderPollTimer = setInterval(async () => {
    if (!store.order || String(store.order.db_id) !== String(orderDbId)) {
      pararPollingPedido();
      return;
    }
    const found = await buscarEstadoPedidoReal(orderDbId);
    if (found) {
      atualizarUIStatusPedido(found, best);
    }
  }, 8000);
  store.orderLocationTimer = setInterval(async () => {
    if (!store.order || String(store.order.db_id) !== String(orderDbId)) {
      pararPollingPedido();
      return;
    }
    const st = String((store.currentOrderData && store.currentOrderData.status) || '').toLowerCase();
    if (['confirmado', 'em_transito', 'em_execucao'].includes(st)) {
      await buscarLocalizacaoPedidoReal(orderDbId);
    }
  }, 12000);
}

export function iniciarTrackingPedido(orderDbId, best, initialData = {}) {
  store.busy = true;
  store.order = {
    best,
    pos: { lat: best.lat != null ? best.lat : store.centerLat, lng: best.lng != null ? best.lng : store.centerLng },
    gps: 0,
    db_id: orderDbId,
    drivingStarted: false,
    realGpsActive: false
  };
  best.a = false;

  if (orderDbId) {
    try {
      sessionStorage.setItem('pertoja_active_order_id', String(orderDbId));
      localStorage.removeItem('pertoja_active_order_id');
    } catch (_) {}
  }

  if (qs('#painel-lista')) qs('#painel-lista').hidden = true;
  if (qs('#pedidoBox')) qs('#pedidoBox').hidden = false;
  if (qs('#pay')) qs('#pay').hidden = true;
  if (qs('#novo')) qs('#novo').hidden = true;
  const btnAvaliar = document.getElementById('btnAvaliarAtendimento');
  if (btnAvaliar) btnAvaliar.hidden = true;
  if (qs('#gps')) qs('#gps').textContent = 0;

  atualizarCodigoConfirmacao(initialData.codigo_confirmacao || '');

  const cands = store.providers
    .filter((p) => p.c && best.c && p.c.toLowerCase() === best.c.toLowerCase() && dist(p) <= store.radius)
    .map((p) => ({ p, score: score(p) }))
    .sort((a, b) => b.score - a.score);

  const rankEl = qs('#rank');
  if (rankEl) {
    const headerRow = document.createElement('tr');
    ['Profissional', 'Distância', 'Avaliação', 'Score'].forEach((col) => {
      const th = document.createElement('th');
      th.textContent = col;
      headerRow.appendChild(th);
    });
    const rows = cands.map((c) => {
      const tr = document.createElement('tr');
      if (c.p.id === best.id) tr.className = 'win';
      const vals = [
        String(c.p.n || ''),
        `${Number(dist(c.p)).toFixed(1)} km`,
        `★ ${Number(c.p.r || 0).toFixed(1)}`,
        String(Math.round(c.score))
      ];
      vals.forEach((v) => {
        const td = document.createElement('td');
        td.textContent = v;
        tr.appendChild(td);
      });
      return tr;
    });
    rankEl.replaceChildren(headerRow, ...rows);
  }

  renderAll();
  atualizarUIStatusPedido({ status: initialData.status || 'solicitado', ...initialData }, best);
  const initSt = String(initialData.status || 'solicitado').toLowerCase();
  if (orderDbId && ['confirmado', 'em_transito', 'em_execucao'].includes(initSt)) {
    buscarLocalizacaoPedidoReal(orderDbId);
  }
  iniciarPollingPedido(orderDbId, best);
}

export async function carregarPedidoAtivoPorId(orderDbId) {
  if (!orderDbId) return;
  const user = store.cachedLoggedUser || (typeof window !== 'undefined' && typeof window.obterUsuarioLogado === 'function' ? await window.obterUsuarioLogado() : null);
  if (!user || user.tipo !== 'cliente') return;
  const found = await buscarEstadoPedidoReal(orderDbId);
  if (!found) return;

  const best = store.providers.find((p) => String(p.id) === String(found.servico_id) || p.n === found.prestador_nome) || {
    id: found.servico_id || found.prestador_id || 0,
    service_id: found.servico_id || 0,
    n: found.prestador_nome || 'Profissional',
    s: found.servico_titulo || 'Serviço Solicitado',
    c: found.servico_categoria || 'Geral',
    p: found.preco_total || 0,
    r: 5.0,
    lat: found.prestador_lat != null ? Number(found.prestador_lat) : store.centerLat,
    lng: found.prestador_lng != null ? Number(found.prestador_lng) : store.centerLng,
    a: false
  };
  iniciarTrackingPedido(found.order_id, best, found);
}

export function abrirModalConfirmarPedido(sel, user) {
  const modal = document.getElementById('modalConfirmarPedido');
  if (!modal) return;
  const triggerEl = document.activeElement;

  document.getElementById('confTitulo').textContent = sel.s;
  document.getElementById('confPrestador').textContent = `${sel.n} · ${sel.c}`;
  document.getElementById('confPreco').textContent = brl(sel.p);

  document.getElementById('confEndereco').value = (user && user.endereco) ? user.endereco : (store.currentSearchAddress || '');
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
      lat: store.centerLat,
      lng: store.centerLng,
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
      if (res.status === 403 && data && data.code === 'EMAIL_NOT_VERIFIED') {
        toast('⚠️ Confirme seu e-mail no Meu Portal antes de solicitar serviços.');
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
        if (qs('#pay')) qs('#pay').hidden = false;
        abrirModalCheckoutPagamento(orderDbId, metodoPagamento, data, {
          buscarEstadoPedidoReal,
          atualizarUIStatusPedido
        });
      } else {
        toast('Pedido confirmado! Acompanhe o status em tempo real.');
      }
    } catch (_) {
      toast('Erro de conexão com o servidor ao registrar pedido.');
    } finally {
      btnEnviar.disabled = false;
    }
  };
}

export async function request(id) {
  const sel = store.providers.find((p) => p.id === id);
  if (!sel || !sel.a) {
    toast('Prestador indisponível no momento.');
    return;
  }

  const user = typeof window !== 'undefined' && typeof window.obterUsuarioLogado === 'function' ? await window.obterUsuarioLogado() : null;
  if (!user) {
    const pendingOrder = {
      service_id: sel.service_id || sel.id,
      titulo: sel.s,
      categoria: sel.c,
      preco: sel.p,
      prestador_nome: sel.n,
      prestador_id: sel.id,
      lat: store.centerLat,
      lng: store.centerLng,
      endereco: store.currentSearchAddress || 'São Paulo - SP',
      raio: store.radius,
      observacoes: 'Solicitado via monitoramento ao vivo',
      salvo_em: Date.now()
    };
    try {
      sessionStorage.setItem('pertoja_pending_order', JSON.stringify(pendingOrder));
      localStorage.removeItem('pertoja_pending_order');
    } catch (_) {}

    exibirModalAuthObrigatoria(pendingOrder);
    return;
  }

  if (user.tipo !== 'cliente') {
    toast('⚠️ Apenas contas de Cliente podem contratar serviços. Você está conectado como Prestador.');
    return;
  }

  abrirModalConfirmarPedido(sel, user);
}

export function bindOrderListeners() {
  if (qs('#pay')) {
    qs('#pay').onclick = async () => {
      const user = typeof window !== 'undefined' && typeof window.obterUsuarioLogado === 'function' ? await window.obterUsuarioLogado() : null;
      if (!user) {
        toast('Sua sessão expirou. Faça login para concluir o pagamento.');
        window.location.href = 'login.html?redirect=pedido.html';
        return;
      }
      try {
        if (store.order && store.order.db_id) {
          const metodoPg = String((store.currentOrderData && store.currentOrderData.metodo_pagamento) || 'escrow').toLowerCase();
          if (['pix', 'cartao', 'boleto'].includes(metodoPg)) {
            abrirModalCheckoutPagamento(store.order.db_id, metodoPg, store.currentOrderData || {}, {
              buscarEstadoPedidoReal,
              atualizarUIStatusPedido
            });
            return;
          }
          const res = await fetch(`/api/orders/${store.order.db_id}/pay`, {
            method: 'POST',
            headers: csrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
              escrow_hold: Boolean(store.currentOrderData && store.currentOrderData.status !== 'finalizado'),
              metodo_pagamento: (store.currentOrderData && store.currentOrderData.metodo_pagamento) || 'escrow'
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
          const realStatus = String(data.status || (store.currentOrderData && store.currentOrderData.status) || '').toLowerCase();
          if (realStatus) {
            if (store.currentOrderData) store.currentOrderData.status = realStatus;
            renderSteps(mapStatusToStep(realStatus));
            atualizarPaineisSegurancaPedido(realStatus, data);
          }
          const escrowSt = String(data.escrow_status || '').toLowerCase();
          qs('#pay').hidden = true;
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
      qs('#pay').hidden = true;
      toast('Transação processada com sucesso via PertoJá Pagamentos.');
      info('Pagamento registrado com sucesso.');
    };
  }

  if (qs('#novo')) {
    qs('#novo').onclick = async () => {
      clearAllSimulationTimers();
      pararPollingPedido();
      sessionStorage.removeItem('pertoja_active_order_id');
      localStorage.removeItem('pertoja_active_order_id');
      store.busy = false;
      store.order = null;
      store.currentOrderData = null;
      if (qs('#pedidoBox')) qs('#pedidoBox').hidden = true;
      if (qs('#painel-lista')) qs('#painel-lista').hidden = false;
      atualizarPaineisSegurancaPedido('', null);
      await carregarPrestadoresAPI();
      renderAll();
    };
  }

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
      modalAvaliarAtend.querySelectorAll('#avaliarPedidoEstrelas [data-nota]').forEach((b) => {
        const is5 = b.dataset.nota === '5';
        b.classList.toggle('on', is5);
        b.setAttribute('aria-pressed', is5 ? 'true' : 'false');
      });
      modalAvaliarAtend.style.display = 'flex';
      document.addEventListener('keydown', onAvaliarKeyDown);
      const firstStar = modalAvaliarAtend.querySelector('#avaliarPedidoEstrelas button');
      if (firstStar) setTimeout(() => firstStar.focus(), 0);
    };
    modalAvaliarAtend.querySelectorAll('#avaliarPedidoEstrelas [data-nota]').forEach((btn) => {
      btn.onclick = () => {
        const nota = btn.dataset.nota;
        document.getElementById('avaliarPedidoNota').value = nota;
        modalAvaliarAtend.querySelectorAll('#avaliarPedidoEstrelas [data-nota]').forEach((b) => {
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
      if (!store.order || !store.order.db_id) return;
      const btnSubmit = document.getElementById('btnEnviarAvaliarAtendimento');
      btnSubmit.disabled = true;
      try {
        const nota = parseInt(document.getElementById('avaliarPedidoNota').value, 10) || 5;
        const comentario = document.getElementById('avaliarPedidoComentario').value.trim();
        const res = await fetch(`/api/orders/${store.order.db_id}/review`, {
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
      } catch (_) {
        toast('Erro de comunicação ao enviar avaliação.');
      } finally {
        btnSubmit.disabled = false;
      }
    };
  }

  const btnCompRota = document.getElementById('btnCompartilharRota');
  if (btnCompRota) {
    btnCompRota.onclick = async () => {
      if (!store.order || !store.order.db_id) return;
      btnCompRota.disabled = true;
      try {
        const res = await fetch(`/api/orders/${store.order.db_id}/share-route`, {
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
      } catch (_) {
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
      } catch (_) {
        toast('Copie o link exibido acima.');
      }
    };
  }

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
      if (!store.order || !store.order.db_id) return;
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
        const res = await fetch(`/api/orders/${store.order.db_id}/sos`, {
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
      } catch (_) {
        toast('Erro de comunicação ao acionar SOS.');
      } finally {
        btnConf.disabled = false;
      }
    };
  }

  const formChatPed = document.getElementById('formPedidoChat');
  if (formChatPed) {
    formChatPed.onsubmit = async (e) => {
      e.preventDefault();
      if (!store.order || !store.order.db_id) return;
      const stAtual = store.currentOrderData ? String(store.currentOrderData.status || '').toLowerCase() : '';
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
        const res = await fetch(`/api/orders/${store.order.db_id}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mensagem })
        });
        const data = await res.json();
        if (res.ok) {
          if (input) input.value = '';
          await carregarMensagensPedido(store.order.db_id);
        } else {
          toast(data.error || 'Não foi possível enviar a mensagem.');
        }
      } catch (_) {
        toast('Erro de comunicação no chat do pedido.');
      } finally {
        if (btnSend) btnSend.disabled = false;
      }
    };
  }
}

export async function sincronizarRetornoPagamentoERestaurar() {
  const legacyActiveId = localStorage.getItem('pertoja_active_order_id');
  if (legacyActiveId) {
    if (!sessionStorage.getItem('pertoja_active_order_id')) {
      try { sessionStorage.setItem('pertoja_active_order_id', legacyActiveId); } catch (_) {}
    }
    try { localStorage.removeItem('pertoja_active_order_id'); } catch (_) {}
  }

  const mpReturnKeys = ['payment_id', 'collection_id', 'collection_status', 'status', 'preference_id'];
  const hasMpReturnParams = Boolean(store.orderIdURL) && mpReturnKeys.some((k) => store.urlParamsInit.has(k));
  if (hasMpReturnParams) {
    const mpStatusHint = String(store.urlParamsInit.get('collection_status') || store.urlParamsInit.get('status') || '').toLowerCase();
    if (mpStatusHint === 'approved') {
      toast('Retorno do Mercado Pago recebido. Sincronizando confirmação do pagamento...');
    } else if (['rejected', 'cancelled', 'failure'].includes(mpStatusHint)) {
      toast('Retorno do Mercado Pago recebido. Verificando status do pagamento...');
    } else {
      toast('Verificando status do pagamento no servidor...');
    }
    try {
      const ordRes = await fetch(`/api/payments/order/${encodeURIComponent(store.orderIdURL)}`);
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
              headers: csrfHeaders({
                'Content-Type': 'application/json',
                'Idempotency-Key': gerarIdempotencyKey()
              }),
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
    } catch (_) {}
  }

  const targetOrderId = store.orderIdURL || sessionStorage.getItem('pertoja_active_order_id');
  if (targetOrderId) {
    await carregarPedidoAtivoPorId(targetOrderId);
    const payParam = store.urlParamsInit.get('pay');
    if (
      payParam === '1'
      && store.currentOrderData
      && !store.currentOrderData.pago
      && String(store.currentOrderData.status || '').toLowerCase() !== 'cancelado'
    ) {
      const metodoPg = String(store.currentOrderData.metodo_pagamento || 'escrow').toLowerCase();
      if (qs('#pay')) qs('#pay').hidden = false;
      abrirModalCheckoutPagamento(store.currentOrderData.order_id || targetOrderId, metodoPg, store.currentOrderData, {
        buscarEstadoPedidoReal,
        atualizarUIStatusPedido
      });
    }
  }

  await verificarERestaurarPedidoPendente();
}
