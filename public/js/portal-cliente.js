// public/js/portal-cliente.js - Painel do Consumidor PertoJá

import {
  brl,
  buscarCepPortal,
  capturarLocalizacaoPortal,
  escapeHtml,
  exportarDadosLgpdPortal,
  formatarMetodoPagamento,
  geocodificarEnderecoPortal,
  limparArmazenamentoSessaoPortal,
  onDomReady,
  sanitizarUrlSegura,
  setStatusText,
  toast,
  vincularModalAcessivel
} from './modules/portal-common.js';
import { createPortalSupportController } from './modules/portal-support.js';

let dadosCliente = null;

function mudarAba(aba) {
    document.getElementById('aba-pedidos-cliente').style.display = aba === 'pedidos' ? 'block' : 'none';
    document.getElementById('aba-perfil-cliente').style.display = aba === 'perfil' ? 'block' : 'none';

    document.getElementById('tabBtnPedidos').classList.toggle('on', aba === 'pedidos');
    document.getElementById('tabBtnPerfil').classList.toggle('on', aba === 'perfil');
  }

  async function carregarPortalCliente() {
    try {
      const res = await fetch('/api/auth/me');
      const data = await res.json();

      if (!data.authenticated || data.user.tipo !== 'cliente') {
        window.location.href = 'login.html';
        return;
      }

      dadosCliente = data.user;
      atualizarBannerVerificacaoEmailCliente();
      document.getElementById('clienteNome').textContent = `Olá, ${dadosCliente.nome}!`;
      document.getElementById('clienteEmail').textContent = `${dadosCliente.email} · ${dadosCliente.telefone || 'Telefone não informado'}`;

      document.getElementById('clienteFormNome').value = dadosCliente.nome;
      document.getElementById('clienteFormTelefone').value = dadosCliente.telefone || '';
      document.getElementById('clienteFormBio').value = dadosCliente.bio || '';
      document.getElementById('clienteFormCep').value = dadosCliente.cep || '';
      document.getElementById('clienteFormEndereco').value = dadosCliente.endereco || '';
      document.getElementById('clienteFormNumero').value = dadosCliente.numero || '';
      document.getElementById('clienteFormComplemento').value = dadosCliente.complemento || '';
      document.getElementById('clienteFormBairro').value = dadosCliente.bairro || '';
      document.getElementById('clienteFormCidade').value = dadosCliente.cidade || '';
      document.getElementById('clienteFormEstado').value = dadosCliente.estado || '';
      if (dadosCliente.lat && dadosCliente.lng) {
        document.getElementById('clienteFormLat').value = dadosCliente.lat.toFixed(6);
        document.getElementById('clienteFormLng').value = dadosCliente.lng.toFixed(6);
      }

      await carregarHistoricoPedidos();
    } catch (e) {
      console.error(e);
    }
  }

  const CLIENTE_ENDERECO_FIELDS = {
    statusId: 'clienteCepStatus',
    cepId: 'clienteFormCep',
    enderecoId: 'clienteFormEndereco',
    numeroId: 'clienteFormNumero',
    bairroId: 'clienteFormBairro',
    cidadeId: 'clienteFormCidade',
    estadoId: 'clienteFormEstado',
    latId: 'clienteFormLat',
    lngId: 'clienteFormLng'
  };

  function buscarCepCliente(cepVal) {
    return buscarCepPortal(cepVal, CLIENTE_ENDERECO_FIELDS);
  }

  function capturarLocalizacaoCliente() {
    capturarLocalizacaoPortal({
      latId: 'clienteFormLat',
      lngId: 'clienteFormLng',
      startMessage: 'Obtendo coordenadas do dispositivo...',
      successMessage: 'Coordenadas GPS obtidas com sucesso!',
      errorMessage: 'Não foi possível obter a localização.'
    });
  }

  function geocodificarEnderecoCliente() {
    return geocodificarEnderecoPortal(CLIENTE_ENDERECO_FIELDS);
  }

  let avaliacaoTriggerEl = null;

  function abrirModalAvaliacao(orderId, prestadorNome, servicoTitulo) {
    avaliacaoTriggerEl = document.activeElement;
    const modal = document.getElementById('modalAvaliarPedido');
    if (!modal) return;
    document.getElementById('avaliarOrderId').value = orderId;
    document.getElementById('avaliarComentario').value = '';
    document.getElementById('avaliarNota').value = '5';
    document.querySelectorAll('#avaliarEstrelas [data-nota]').forEach(btn => {
      const is5 = btn.dataset.nota === '5';
      btn.classList.toggle('on', is5);
      btn.setAttribute('aria-pressed', is5 ? 'true' : 'false');
    });
    document.getElementById('modalAvaliarSubtitulo').textContent = `Como foi o serviço "${servicoTitulo}" realizado por ${prestadorNome}?`;
    modal.style.display = 'flex';
    document.addEventListener('keydown', onModalAvaliarKeyDown);
    const firstBtn = modal.querySelector('#avaliarEstrelas button');
    if (firstBtn) setTimeout(() => firstBtn.focus(), 0);
  }

  function fecharModalAvaliacao() {
    const modal = document.getElementById('modalAvaliarPedido');
    if (modal) modal.style.display = 'none';
    document.removeEventListener('keydown', onModalAvaliarKeyDown);
    if (avaliacaoTriggerEl && typeof avaliacaoTriggerEl.focus === 'function') {
      avaliacaoTriggerEl.focus();
    }
  }

  function onModalAvaliarKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      fecharModalAvaliacao();
    }
  }

  document.querySelectorAll('#avaliarEstrelas [data-nota]').forEach(btn => {
    btn.addEventListener('click', () => {
      const nota = btn.dataset.nota;
      document.getElementById('avaliarNota').value = nota;
      document.querySelectorAll('#avaliarEstrelas [data-nota]').forEach(b => {
        const active = b.dataset.nota === nota;
        b.classList.toggle('on', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
    });
  });

  document.getElementById('btnFecharModalAvaliar').addEventListener('click', fecharModalAvaliacao);
  document.getElementById('btnCancelarAvaliacao').addEventListener('click', fecharModalAvaliacao);
  document.getElementById('modalAvaliarPedido').addEventListener('click', (e) => {
    if (e.target.id === 'modalAvaliarPedido') fecharModalAvaliacao();
  });

  document.getElementById('formAvaliarPedido').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('avaliarOrderId').value;
    const nota = parseInt(document.getElementById('avaliarNota').value, 10) || 5;
    const comentario = document.getElementById('avaliarComentario').value.trim();
    const btnSubmit = document.getElementById('btnEnviarAvaliacao');
    const origText = btnSubmit.textContent;
    btnSubmit.classList.add('is-loading');
    btnSubmit.disabled = true;
    btnSubmit.textContent = 'Enviando...';
    try {
      const res = await fetch(`/api/orders/${orderId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nota, comentario })
      });
      const data = await res.json();
      if (res.ok) {
        toast('Avaliação registrada com sucesso! Obrigado pelo feedback.');
        fecharModalAvaliacao();
        await carregarHistoricoPedidos();
      } else {
        toast(data.error || 'Não foi possível enviar a avaliação.');
      }
    } catch (err) {
      toast('Erro de comunicação ao enviar avaliação.');
    } finally {
      btnSubmit.classList.remove('is-loading');
      btnSubmit.disabled = false;
      btnSubmit.textContent = origText;
    }
  });

  async function carregarHistoricoPedidos() {
    const div = document.getElementById('listaPedidosCliente');
    try {
      const res = await fetch('/api/orders');
      const pedidos = await res.json();
      document.getElementById('contPedidos').textContent = pedidos.length;

      if (!pedidos.length) {
        const card = document.createElement('div');
        card.className = 'empty-state-card';
        card.setAttribute('role', 'status');
        card.setAttribute('aria-live', 'polite');

        const iconWrap = document.createElement('div');
        iconWrap.className = 'w-12 h-12 rounded-full bg-perto-bg flex items-center justify-center mx-auto mb-3 text-perto-sea';
        const iconSpan = document.createElement('span');
        iconSpan.className = 'material-symbols-outlined text-2xl';
        iconSpan.setAttribute('aria-hidden', 'true');
        iconSpan.textContent = 'receipt_long';
        iconWrap.appendChild(iconSpan);

        const titleP = document.createElement('p');
        titleP.className = 'empty-title';
        titleP.textContent = 'Nenhum pedido solicitado ainda';

        const descP = document.createElement('p');
        descP.className = 'empty-desc';
        descP.textContent = 'Você ainda não solicitou nenhum serviço na plataforma. Explore os profissionais disponíveis na sua região.';

        const link = document.createElement('a');
        link.href = 'pedido.html';
        link.className = 'btn text-perto-ink font-bold px-6 py-2.5 rounded-full text-xs inline-flex items-center gap-2 text-decoration-none';
        const linkIcon = document.createElement('span');
        linkIcon.className = 'material-symbols-outlined text-sm';
        linkIcon.setAttribute('aria-hidden', 'true');
        linkIcon.textContent = 'search';
        link.append(linkIcon, ' Explorar Prestadores Locais');

        card.append(iconWrap, titleP, descP, link);
        div.replaceChildren(card);
        return;
      }

      /* eslint-disable-next-line no-unsanitized/property -- interpolações auditadas por scripts/check_xss_lint.js */
      div.innerHTML = pedidos.map(p => {
        const orderIdNum = Number(p.order_id);
        const payHref = escapeHtml(sanitizarUrlSegura(`pedido.html?order_id=${encodeURIComponent(orderIdNum)}&pay=1`, 'pedido.html'));
        const mapHref = escapeHtml(sanitizarUrlSegura(`pedido.html?order_id=${encodeURIComponent(orderIdNum)}`, 'pedido.html'));
        const st = String(p.status || '').toLowerCase();
        const badgeClass = st === 'cancelado' ? 'tag off' : 'tag';
        const codigoHtml = p.codigo_confirmacao
          ? `<span class="tag tabular-nums" style="background: var(--sun-soft, #fff7dd); color: var(--ink);">PIN <b class="tabular-nums font-mono tracking-wider">${escapeHtml(p.codigo_confirmacao)}</b></span>`
          : '';
        const pagamentoHtml = `<span>💳 <b>${escapeHtml(formatarMetodoPagamento(p.metodo_pagamento))}</b></span>`;
        const emDisputa = Boolean(p.em_disputa || st === 'em_disputa');
        const disputaBadgeHtml = emDisputa
          ? `<span class="dispute-badge">⚖️ Em Mediação</span>`
          : '';
        const escrowStatus = String(p.escrow_status || '').toLowerCase();
        const aguardandoEscrow = st === 'finalizado' && escrowStatus === 'aguardando_liberacao' && !p.confirmado_cliente;
        const escrowLiberado = st === 'finalizado' && escrowStatus === 'liberado';
        const estornadoTotal = escrowStatus === 'estornado_total';
        const estornadoParcial = escrowStatus === 'estornado_parcial';
        const precisaPagar = !p.pago && st !== 'cancelado';
        let escrowBadgeHtml = '';
        if (estornadoTotal) {
          escrowBadgeHtml = '<span class="tag off">↩️ Estornado Total</span>';
        } else if (estornadoParcial) {
          escrowBadgeHtml = '<span class="tag" style="background: var(--sun-soft, #fff7dd); color: var(--ink);">↩️ Estornado Parcial</span>';
        } else if (aguardandoEscrow) {
          escrowBadgeHtml = '<span class="tag" style="background: var(--sun-soft, #fff7dd); color: var(--ink);">⏳ Em Garantia (48h)</span>';
        } else if (escrowLiberado) {
          escrowBadgeHtml = '<span class="tag" style="background: var(--ok-soft, #e6f5ee); color: var(--ok);">✓ Escrow Liberado</span>';
        } else if (escrowStatus === 'retido' || p.pago) {
          escrowBadgeHtml = '<span class="tag" style="background: var(--ok-soft, #e6f5ee); color: var(--ok);">🔒 Retido em Escrow</span>';
        } else if (precisaPagar) {
          escrowBadgeHtml = '<span class="tag" style="background: var(--sun-soft, #fff7dd); color: var(--ink);">⏳ Aguardando Pagamento</span>';
        }
        const estornoInfoHtml = (estornadoTotal || estornadoParcial) && p.valor_estornado != null
          ? `<div class="tabular-nums" style="font-size:0.82rem; color:#991b1b; font-weight:700; margin: 4px 0;">↩️ Valor estornado: ${escapeHtml(brl(Number(p.valor_estornado || 0)))}</div>`
          : '';
        const podeAvaliar = st === 'finalizado' && !p.ja_avaliado;
        const jaAvaliadoHtml = st === 'finalizado' && p.ja_avaliado
          ? '<span class="tag" style="background: var(--ok-soft, #e6f5ee); color: var(--ok);">★ Avaliado</span>'
          : '';
        const podeChat = ['confirmado', 'em_transito', 'em_execucao', 'em_disputa', 'finalizado', 'cancelado'].includes(st);
        const podeSos = ['confirmado', 'em_transito', 'em_execucao'].includes(st);
        const podeConcluir = st === 'em_execucao';
        const podeDisputa = ['confirmado', 'em_transito', 'em_execucao', 'finalizado'].includes(st) && !emDisputa;
        const podeVerReviews = st === 'finalizado';
        const obsHtml = p.observacoes ? `<p class="text-perto-ink/80" style="font-size:0.85rem;">${escapeHtml(p.observacoes)}</p>` : '';
        const localHtml = (p.prestador_bairro || p.prestador_cidade)
          ? `<div style="font-size:0.85rem; color:var(--sea); font-weight:600; margin: 4px 0;">📍 ${escapeHtml([p.prestador_endereco, p.prestador_numero, p.prestador_bairro, p.prestador_cidade].filter(Boolean).join(', '))}</div>`
          : '';

        return `
          <div class="svc" style="margin-bottom: 14px; border-left: 5px solid var(--sea);">
            <div class="top">
              <span class="flex items-center gap-2 flex-wrap"><b>${escapeHtml(p.servico_titulo)}</b> <span class="tag">${escapeHtml(p.servico_categoria)}</span></span>
              <span class="price tabular-nums">${brl(Number(p.preco_total || 0))}</span>
            </div>
            <div class="meta text-perto-ink/80" style="margin: 6px 0;">
              <span>🛠️ <b>${escapeHtml(p.prestador_nome)}</b></span>
              <span class="tabular-nums">📞 ${escapeHtml(p.prestador_telefone || 'Não informado')}</span>
              ${pagamentoHtml}
              <b class="${escapeHtml(badgeClass)}">${escapeHtml(String(p.status).toUpperCase())}</b>
              ${codigoHtml}
              ${escrowBadgeHtml}
              ${disputaBadgeHtml}
              ${jaAvaliadoHtml}
            </div>
            ${localHtml}
            ${obsHtml}
            ${estornoInfoHtml}
            <div style="margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end;">
              ${precisaPagar ? `
                <a href="${payHref}" class="btn" style="text-decoration: none; font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  💳 Pagar / Ver Cobrança
                </a>
              ` : ''}
              ${podeChat ? `
                <button type="button" class="btn2 btn-chat-pedido" data-order-id="${Number(orderIdNum)}" data-status="${escapeHtml(st)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">chat</span>
                  Chat do Pedido
                </button>
              ` : ''}
              ${podeConcluir ? `
                <button type="button" class="btn btn-confirmar-conclusao" data-order-id="${Number(orderIdNum)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">check_circle</span>
                  Confirmar Conclusão
                </button>
              ` : ''}
              ${aguardandoEscrow ? `
                <button type="button" class="btn btn-liberar-escrow" data-order-id="${Number(orderIdNum)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">verified</span>
                  Confirmar e Liberar Escrow
                </button>
              ` : ''}
              ${podeDisputa ? `
                <button type="button" class="btn2 btn-abrir-disputa" data-order-id="${Number(orderIdNum)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">gavel</span>
                  Abrir Mediação / Disputa
                </button>
              ` : ''}
              ${podeSos ? `
                <button type="button" class="sos-btn btn-sos-pedido" data-order-id="${Number(orderIdNum)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">emergency_share</span>
                  SOS Emergência
                </button>
              ` : ''}
              ${podeAvaliar ? `
                <button type="button" class="btn btn-avaliar-pedido" data-order-id="${Number(orderIdNum)}" data-prestador="${escapeHtml(p.prestador_nome)}" data-servico="${escapeHtml(p.servico_titulo)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">star</span>
                  Avaliar Prestador
                </button>
              ` : ''}
              ${podeVerReviews ? `
                <button type="button" class="btn2 btn-ver-reviews" data-order-id="${Number(orderIdNum)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">reviews</span>
                  Ver Avaliações
                </button>
              ` : ''}
              <a href="${mapHref}" class="btn2" style="text-decoration: none; font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">map</span>
                Ver no Mapa em Tempo Real
              </a>
            </div>
          </div>
        `;
      }).join('');

      div.querySelectorAll('.btn-avaliar-pedido').forEach(btn => {
        btn.addEventListener('click', () => {
          abrirModalAvaliacao(btn.dataset.orderId, btn.dataset.prestador, btn.dataset.servico);
        });
      });
      div.querySelectorAll('.btn-ver-reviews').forEach(btn => {
        btn.addEventListener('click', () => abrirModalVerReviewsPedido(btn.dataset.orderId));
      });
      div.querySelectorAll('.btn-chat-pedido').forEach(btn => {
        btn.addEventListener('click', () => abrirModalChatCliente(btn.dataset.orderId, btn.dataset.status));
      });
      div.querySelectorAll('.btn-confirmar-conclusao').forEach(btn => {
        btn.addEventListener('click', () => confirmarConclusaoPedido(btn.dataset.orderId, btn));
      });
      div.querySelectorAll('.btn-liberar-escrow').forEach(btn => {
        btn.addEventListener('click', () => confirmarLiberacaoEscrow(btn.dataset.orderId, btn));
      });
      div.querySelectorAll('.btn-abrir-disputa').forEach(btn => {
        btn.addEventListener('click', () => abrirModalDisputaCliente(btn.dataset.orderId));
      });
      div.querySelectorAll('.btn-sos-pedido').forEach(btn => {
        btn.addEventListener('click', () => abrirModalSosCliente(btn.dataset.orderId));
      });
    } catch (e) {
      setStatusText(div, 'Erro ao carregar histórico de pedidos.', 'text-sm text-perto-ink/80');
    }
  }

  document.getElementById('formPerfilCliente').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origNodes = typeof window.salvarConteudoBotao === 'function' ? window.salvarConteudoBotao(btnSubmit) : [];
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Salvando...';
    }
    const latVal = parseFloat(document.getElementById('clienteFormLat').value);
    const lngVal = parseFloat(document.getElementById('clienteFormLng').value);

    const payload = {
      nome: document.getElementById('clienteFormNome').value,
      telefone: document.getElementById('clienteFormTelefone').value,
      bio: document.getElementById('clienteFormBio').value,
      cep: document.getElementById('clienteFormCep').value,
      endereco: document.getElementById('clienteFormEndereco').value,
      numero: document.getElementById('clienteFormNumero').value,
      complemento: document.getElementById('clienteFormComplemento').value,
      bairro: document.getElementById('clienteFormBairro').value,
      cidade: document.getElementById('clienteFormCidade').value,
      estado: document.getElementById('clienteFormEstado').value,
      lat: isNaN(latVal) ? dadosCliente.lat : latVal,
      lng: isNaN(lngVal) ? dadosCliente.lng : lngVal
    };

    try {
      const res = await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        toast('Dados cadastrais atualizados com sucesso!');
        Object.assign(dadosCliente, payload);
        document.getElementById('clienteNome').textContent = `Olá, ${payload.nome}!`;
        document.getElementById('clienteEmail').textContent = `${dadosCliente.email} · ${dadosCliente.telefone || 'Telefone não informado'}`;
        if (typeof window.atualizarNavegacao === 'function') window.atualizarNavegacao();
      } else {
        toast('Erro ao atualizar dados.');
      }
    } catch (e) {
      toast('Erro de comunicação.');
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        if (typeof window.restaurarConteudoBotao === 'function') {
          window.restaurarConteudoBotao(btnSubmit, origNodes);
        }
      }
    }
  });

  // --- Fluxos Éticos do Portal do Cliente (ET-08, ET-10, ET-13, ET-14, ET-15) ---
  async function confirmarConclusaoPedido(orderId, btnEl) {
    if (!orderId) return;
    const origNodes = typeof window.salvarConteudoBotao === 'function' ? window.salvarConteudoBotao(btnEl) : [];
    if (btnEl) {
      btnEl.classList.add('is-loading');
      btnEl.disabled = true;
      btnEl.textContent = 'Confirmando...';
    }
    try {
      const res = await fetch(`/api/orders/${orderId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'finalizado' })
      });
      const data = await res.json();
      if (res.ok) {
        toast('Conclusão do serviço confirmada! Pagamento liberado conforme Escrow.');
        await carregarHistoricoPedidos();
      } else {
        toast(data.error || 'Não foi possível confirmar a conclusão.');
      }
    } catch (e) {
      toast('Erro de comunicação ao confirmar conclusão.');
    } finally {
      if (btnEl) {
        btnEl.classList.remove('is-loading');
        btnEl.disabled = false;
        if (typeof window.restaurarConteudoBotao === 'function') {
          window.restaurarConteudoBotao(btnEl, origNodes);
        }
      }
    }
  }

  async function confirmarLiberacaoEscrow(orderId, btnEl) {
    if (!orderId) return;
    const origNodes = typeof window.salvarConteudoBotao === 'function' ? window.salvarConteudoBotao(btnEl) : [];
    if (btnEl) {
      btnEl.classList.add('is-loading');
      btnEl.disabled = true;
      btnEl.textContent = 'Liberando...';
    }
    try {
      let res = await fetch(`/api/orders/${orderId}/confirm-completion`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (res.status === 404 || res.status === 405) {
        res = await fetch(`/api/orders/${orderId}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'finalizado' })
        });
      }
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        toast(data.message || 'Escrow liberado com sucesso!');
        await carregarHistoricoPedidos();
      } else {
        toast(data.error || 'Não foi possível liberar o Escrow.');
      }
    } catch (e) {
      toast('Erro de comunicação ao liberar Escrow.');
    } finally {
      if (btnEl) {
        btnEl.classList.remove('is-loading');
        btnEl.disabled = false;
        if (typeof window.restaurarConteudoBotao === 'function') {
          window.restaurarConteudoBotao(btnEl, origNodes);
        }
      }
    }
  }

  const ctrlChatCliente = vincularModalAcessivel('modalChatPedidoCliente', ['btnFecharModalChatCliente']);
  async function carregarMensagensChatCliente(orderId) {
    const box = document.getElementById('chatClienteMessages');
    if (!box || !orderId) return;
    try {
      const res = await fetch(`/api/orders/${orderId}/messages`);
      if (!res.ok) {
        setStatusText(box, 'Não foi possível carregar as mensagens.');
        return;
      }
      const msgs = await res.json();
      if (!Array.isArray(msgs) || !msgs.length) {
        setStatusText(box, 'Nenhuma mensagem ainda. Use este canal protegido para falar com o profissional.');
        return;
      }
      const myId = dadosCliente && dadosCliente.id;
      const msgNodes = msgs.map(m => {
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
    } catch (e) {
      setStatusText(box, 'Erro de comunicação ao carregar mensagens.');
    }
  }

  let chatClienteReadOnly = false;
  async function abrirModalChatCliente(orderId, orderStatus) {
    const st = String(orderStatus || '').toLowerCase();
    chatClienteReadOnly = ['finalizado', 'cancelado'].includes(st);
    document.getElementById('chatClienteOrderId').value = orderId;
    const input = document.getElementById('inputChatClienteMsg');
    const btn = document.getElementById('btnEnviarChatCliente');
    const notice = document.getElementById('chatClienteReadOnlyNotice');
    input.value = '';
    input.disabled = chatClienteReadOnly;
    btn.disabled = chatClienteReadOnly;
    if (notice) notice.classList.toggle('hidden', !chatClienteReadOnly);
    ctrlChatCliente.abrir(chatClienteReadOnly ? '#btnFecharModalChatCliente' : '#inputChatClienteMsg');
    await carregarMensagensChatCliente(orderId);
  }

  document.getElementById('formChatCliente').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (chatClienteReadOnly) {
      toast('Chat encerrado (somente leitura).');
      return;
    }
    const orderId = document.getElementById('chatClienteOrderId').value;
    const input = document.getElementById('inputChatClienteMsg');
    const btn = document.getElementById('btnEnviarChatCliente');
    const mensagem = input.value.trim();
    if (!orderId || !mensagem) return;
    const origText = btn.textContent;
    btn.classList.add('is-loading');
    btn.disabled = true;
    btn.textContent = 'Enviando...';
    try {
      const res = await fetch(`/api/orders/${orderId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mensagem })
      });
      const data = await res.json();
      if (res.ok) {
        input.value = '';
        await carregarMensagensChatCliente(orderId);
      } else {
        toast(data.error || 'Erro ao enviar mensagem.');
      }
    } catch (err) {
      toast('Erro de comunicação ao enviar mensagem.');
    } finally {
      btn.classList.remove('is-loading');
      btn.disabled = chatClienteReadOnly;
      btn.textContent = origText;
    }
  });

  const ctrlVerReviewsPedido = vincularModalAcessivel('modalVerReviewsPedido', ['btnFecharModalVerReviews', 'btnFecharModalVerReviewsRodape']);
  async function abrirModalVerReviewsPedido(orderId) {
    const box = document.getElementById('verReviewsConteudo');
    if (!box) return;
    setStatusText(box, 'Carregando avaliações...', 'text-perto-ink/80');
    ctrlVerReviewsPedido.abrir('#btnFecharModalVerReviews');
    try {
      const res = await fetch(`/api/orders/${orderId}/reviews`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setStatusText(box, data.error || 'Não foi possível carregar as avaliações.', 'text-perto-ink/80');
        return;
      }
      const minha = data.minha_avaliacao;
      const contraparte = data.contraparte_avaliacao || data.avaliacao_contraparte || data.avaliacao_prestador || data.review_recebida || null;
      const oculta = Boolean(data.oculta_double_blind);
      const formatarStatusModeracaoHtml = (stMod) => {
        const mod = String(stMod || '').trim();
        if (!mod || mod.toLowerCase() === 'publicada') return '';
        return `<div class="mt-1.5 inline-block px-2 py-0.5 rounded-full text-[11px] font-bold bg-perto-sun/25 text-perto-ink">${escapeHtml(mod)}</div>`;
      };
      const minhaHtml = minha
        ? `
          <div class="p-3 rounded-xl bg-perto-bg border border-perto-road">
            <div class="font-bold text-perto-ink mb-1 tabular-nums">Sua avaliação (★ ${escapeHtml(String(minha.nota || 5))})</div>
            <p class="m-0 text-perto-ink/80">${escapeHtml(minha.comentario || 'Sem comentário.')}</p>
            ${minha.replica ? `<div class="mt-2 p-2 rounded-lg bg-white border border-perto-road text-xs text-perto-ink/85"><b>Réplica:</b> ${escapeHtml(minha.replica)}</div>` : ''}
            ${formatarStatusModeracaoHtml(minha.status_moderacao)}
          </div>
        `
        : `<div class="p-3 rounded-xl bg-perto-bg border border-perto-road text-perto-ink/80">Você ainda não enviou sua avaliação para este pedido.</div>`;

      let contraHtml = '';
      if (oculta) {
        contraHtml = `
          <div class="p-3 rounded-xl bg-perto-sun/20 border border-perto-sun text-perto-ink">
            <div class="font-bold mb-1">Avaliação do profissional protegida (Double-Blind)</div>
            <p class="m-0">A avaliação do prestador será revelada simultaneamente após ambos avaliarem ou em 7 dias.</p>
          </div>
        `;
      } else if (contraparte) {
        const revId = Number(contraparte.id || 0);
        const statusModContra = String(contraparte.status_moderacao || '').toLowerCase();
        const jaContestada = Boolean(contraparte.contestada) || ['contestada', 'em_revisao'].includes(statusModContra);
        contraHtml = `
          <div class="p-3 rounded-xl bg-perto-bg border border-perto-road space-y-2">
            <div class="font-bold text-perto-ink tabular-nums">Avaliação do profissional (★ ${escapeHtml(String(contraparte.nota || 5))})</div>
            <p class="m-0 text-perto-ink/80">${escapeHtml(contraparte.comentario || 'Sem comentário.')}</p>
            ${contraparte.replica ? `<div class="p-2 rounded-lg bg-white border border-perto-road text-xs text-perto-ink/85"><b>Réplica:</b> ${escapeHtml(contraparte.replica)}</div>` : ''}
            ${formatarStatusModeracaoHtml(contraparte.status_moderacao)}
            ${revId > 0 ? (jaContestada
              ? `<div class="pt-2 border-t border-perto-road text-xs font-semibold text-perto-ink/80">Avaliação já contestada e em análise de moderação.</div>`
              : `
              <form id="formContestarReviewCliente" class="pt-2 border-t border-perto-road flex gap-2">
                <input type="text" id="inputMotivoContestReviewCliente" required minlength="3" placeholder="Motivo para contestar avaliação..." class="input-form text-xs flex-1">
                <button type="submit" id="btnSubmitContestReviewCliente" class="btn2 px-3 py-1.5 rounded-full text-xs font-bold shrink-0">Contestar</button>
              </form>
            `) : ''}
          </div>
        `;
      } else {
        contraHtml = `<div class="p-3 rounded-xl bg-perto-bg border border-perto-road text-perto-ink/80">O profissional ainda não registrou uma avaliação.</div>`;
      }

      /* eslint-disable-next-line no-unsanitized/property -- interpolações auditadas por scripts/check_xss_lint.js */
      box.innerHTML = minhaHtml + contraHtml;
      const formContest = document.getElementById('formContestarReviewCliente');
      if (formContest && contraparte && contraparte.id) {
        formContest.addEventListener('submit', async (ev) => {
          ev.preventDefault();
          const motivo = (document.getElementById('inputMotivoContestReviewCliente').value || '').trim();
          if (!motivo) return;
          const btnSubmit = document.getElementById('btnSubmitContestReviewCliente');
          if (btnSubmit) {
            btnSubmit.classList.add('is-loading');
            btnSubmit.disabled = true;
          }
          try {
            const r = await fetch(`/api/reviews/${contraparte.id}/contest`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ motivo })
            });
            const d = await r.json().catch(() => ({}));
            if (r.ok) {
              toast(d.message || 'Contestação enviada com sucesso.');
              ctrlVerReviewsPedido.fechar();
            } else {
              toast(d.error || 'Erro ao contestar avaliação.');
            }
          } catch (err) {
            toast('Erro de comunicação ao contestar avaliação.');
          } finally {
            if (btnSubmit) {
              btnSubmit.classList.remove('is-loading');
              btnSubmit.disabled = false;
            }
          }
        });
      }
    } catch (e) {
      setStatusText(box, 'Erro de comunicação ao carregar avaliações.', 'text-perto-ink/80');
    }
  }

  const ctrlDisputaCliente = vincularModalAcessivel('modalDisputaCliente', ['btnFecharModalDisputa', 'btnCancelarDisputa']);
  function abrirModalDisputaCliente(orderId) {
    document.getElementById('disputaOrderId').value = orderId;
    document.getElementById('disputaMotivo').value = '';
    document.getElementById('disputaEvidencias').value = '';
    ctrlDisputaCliente.abrir('#disputaMotivo');
  }

  document.getElementById('formDisputaCliente').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('disputaOrderId').value;
    const btn = document.getElementById('btnEnviarDisputa');
    const origText = btn.textContent;
    btn.classList.add('is-loading');
    btn.disabled = true;
    btn.textContent = 'Enviando...';
    try {
      const motivo = document.getElementById('disputaMotivo').value.trim();
      const evidencias = document.getElementById('disputaEvidencias').value.trim();
      const res = await fetch(`/api/orders/${orderId}/dispute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motivo, descricao: evidencias, evidencias })
      });
      const data = await res.json();
      if (res.ok) {
        toast(data.message || 'Mediação aberta com sucesso. Escrow retido para análise.');
        ctrlDisputaCliente.fechar();
        await carregarHistoricoPedidos();
      } else {
        toast(data.error || 'Não foi possível abrir a mediação.');
      }
    } catch (err) {
      toast('Erro de comunicação ao abrir mediação.');
    } finally {
      btn.classList.remove('is-loading');
      btn.disabled = false;
      btn.textContent = origText;
    }
  });

  const ctrlSosCliente = vincularModalAcessivel('modalSosCliente', ['btnFecharModalSosCliente', 'btnCancelarSosCliente']);
  function abrirModalSosCliente(orderId) {
    document.getElementById('sosClienteOrderId').value = orderId;
    document.getElementById('sosClienteDescricao').value = '';
    document.getElementById('sosClienteDenunciar').checked = false;
    ctrlSosCliente.abrir('#sosClienteDescricao');
  }

  document.getElementById('formSosCliente').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('sosClienteOrderId').value;
    const descEl = document.getElementById('sosClienteDescricao');
    const descricao = descEl.value.trim();
    if (descricao.length < 10) {
      toast('Descreva a ocorrência com pelo menos 10 caracteres.');
      descEl.focus();
      return;
    }
    const denunciar_contraparte = Boolean(document.getElementById('sosClienteDenunciar').checked);
    if (denunciar_contraparte) {
      const ok = window.confirm('ATENÇÃO: Denunciar a contraparte acionará suspensão cautelar imediata da conta denunciada. Deseja confirmar esta denúncia?');
      if (!ok) return;
    }
    const btn = document.getElementById('btnConfirmarSosCliente');
    const origText = btn.textContent;
    btn.classList.add('is-loading');
    btn.disabled = true;
    btn.textContent = 'Enviando SOS...';
    try {
      const res = await fetch(`/api/orders/${orderId}/sos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ descricao, denunciar_contraparte })
      });
      const data = await res.json();
      if (res.ok) {
        toast(data.message || 'Alerta SOS registrado. Equipe de segurança notificada.');
        ctrlSosCliente.fechar();
      } else {
        toast(data.error || 'Erro ao registrar alerta SOS.');
      }
    } catch (err) {
      toast('Erro de comunicação ao acionar SOS.');
    } finally {
      btn.classList.remove('is-loading');
      btn.disabled = false;
      btn.textContent = origText;
    }
  });

  // LGPD Art. 18: Exportação JSON e Anonimização Irreversível
  document.getElementById('btnExportarDadosLgpd').addEventListener('click', () => exportarDadosLgpdPortal({
    errorMessage: 'Não foi possível exportar seus dados.',
    successMessage: 'Exportação JSON gerada com sucesso!'
  }));

  const ctrlExcluirLgpd = vincularModalAcessivel('modalExcluirContaLgpd', ['btnFecharModalExcluirLgpd', 'btnCancelarExcluirLgpd']);
  document.getElementById('btnAbrirExcluirContaLgpd').addEventListener('click', () => {
    ctrlExcluirLgpd.abrir('#btnCancelarExcluirLgpd');
  });
  document.getElementById('btnConfirmarExcluirLgpd').addEventListener('click', async () => {
    const btn = document.getElementById('btnConfirmarExcluirLgpd');
    btn.classList.add('is-loading');
    btn.disabled = true;
    try {
      const res = await fetch('/api/profile', { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) {
        limparArmazenamentoSessaoPortal();
        toast(data.message || 'Conta anonimizada com sucesso.');
        setTimeout(() => { window.location.href = 'index.html'; }, 800);
      } else {
        toast(data.error || 'Não foi possível excluir/anonimizar a conta.');
      }
    } catch (err) {
      toast('Erro de comunicação ao anonimizar conta.');
    } finally {
      btn.classList.remove('is-loading');
      btn.disabled = false;
    }
  });

  // Referências preservadas de contrato DOM (modalSuporteIA, badgeStatusSuporteIA, escapeHtml)
  const suporteCtrl = createPortalSupportController({
    context: 'cliente',
    healthEndpoint: '/api/chat/health',
    supportEndpoint: '/api/chat/support',
    offlineBadgeText: '🟡 Modo Offline (FAQ Local)',
    offlineSenderLabel: 'Assistente PertoJá · Modo Offline',
    thinkingLabel: 'Pensando...',
    trimHistory: (items) => items.slice(-10),
    greetingText:
      'Olá! Sou o assistente do PertoJá. Posso tirar dúvidas sobre pagamento protegido em Escrow, PIN presencial de 4 dígitos, garantia de 48h, disputas e segurança. Como posso ajudar?'
  });
  const limparConversaSuporteIA = () => suporteCtrl.limparConversa();
  const abrirModalSuporteIA = () => suporteCtrl.abrir();
  const enviarPerguntaRapidaSuporteIA = (btn) => suporteCtrl.enviarPerguntaRapida(btn);
  const enviarMensagemSuporteIA = () => suporteCtrl.enviarMensagem();

  document.getElementById('formSuporteIA').addEventListener('submit', async (e) => {
    e.preventDefault();
    await enviarMensagemSuporteIA();
  });

  // Bindings externos (substituição de atributos HTML inline)
  function atualizarBannerVerificacaoEmailCliente() {
    const banner = document.getElementById('bannerVerificarEmailCliente');
    if (!banner || !dadosCliente) return;
    banner.hidden = dadosCliente.email_verified !== false;
  }

  async function reenviarVerificacaoEmailCliente() {
    const btn = document.getElementById('btnReenviarVerificacaoEmailCliente');
    const statusEl = document.getElementById('statusVerificacaoEmailCliente');
    const inputEl = document.getElementById('inputTokenEmailCliente');
    if (btn) btn.disabled = true;
    try {
      const res = await fetch('/api/auth/send-verification-email', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (statusEl) statusEl.textContent = data.error || 'Não foi possível enviar o e-mail de verificação.';
        toast(data.error || 'Erro ao enviar e-mail de verificação.');
        return;
      }
      if (data.already_verified) {
        dadosCliente.email_verified = true;
        atualizarBannerVerificacaoEmailCliente();
        toast('Seu e-mail já está verificado!');
        return;
      }
      if (data.verification_token) {
        if (inputEl) inputEl.value = data.verification_token;
        if (statusEl) statusEl.textContent = `Token de teste (dev): ${data.verification_token}`;
      } else if (statusEl) {
        statusEl.textContent = data.message || 'E-mail de verificação enviado. Confira sua caixa de entrada.';
      }
      toast('E-mail de verificação enviado!');
    } catch (_) {
      toast('Erro de conexão ao enviar verificação.');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function confirmarTokenEmailCliente() {
    const inputEl = document.getElementById('inputTokenEmailCliente');
    const btn = document.getElementById('btnConfirmarEmailCliente');
    const statusEl = document.getElementById('statusVerificacaoEmailCliente');
    const token = inputEl ? inputEl.value.trim() : '';
    if (!token) {
      toast('Informe o token de verificação.');
      if (inputEl) inputEl.focus();
      return;
    }
    if (btn) btn.disabled = true;
    try {
      const res = await fetch('/api/auth/verify-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (statusEl) statusEl.textContent = data.error || 'Token inválido ou expirado.';
        toast(data.error || 'Token inválido ou expirado.');
        return;
      }
      if (dadosCliente) dadosCliente.email_verified = true;
      atualizarBannerVerificacaoEmailCliente();
      toast('E-mail verificado com sucesso!');
    } catch (_) {
      toast('Erro de conexão ao verificar token.');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  document.getElementById('btnReenviarVerificacaoEmailCliente')?.addEventListener('click', reenviarVerificacaoEmailCliente);
  document.getElementById('btnConfirmarEmailCliente')?.addEventListener('click', confirmarTokenEmailCliente);
  document.getElementById('tabBtnPedidos')?.addEventListener('click', () => mudarAba('pedidos'));
  document.getElementById('tabBtnPerfil')?.addEventListener('click', () => mudarAba('perfil'));
  document.getElementById('btnAbrirSuporteIA')?.addEventListener('click', abrirModalSuporteIA);
  document.getElementById('clienteFormCep')?.addEventListener('blur', (e) => buscarCepCliente(e.target.value));
  document.getElementById('btnCapturarLocalizacaoCliente')?.addEventListener('click', capturarLocalizacaoCliente);
  document.getElementById('btnGeocodificarEnderecoCliente')?.addEventListener('click', geocodificarEnderecoCliente);
  document.getElementById('btnLimparSuporteIA')?.addEventListener('click', limparConversaSuporteIA);
  document.querySelectorAll('#chipsPerguntasRapidasSuporteIA .chip-suporte-rapido').forEach((chip) => {
    chip.addEventListener('click', () => enviarPerguntaRapidaSuporteIA(chip));
  });

  onDomReady(() => {
    carregarPortalCliente();
    // Polling em segundo plano para status das ordens a cada 20 segundos
    setInterval(carregarHistoricoPedidos, 20000);
  });
