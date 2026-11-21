// public/js/portal-cliente.js - Painel do Consumidor PertoJá
(function () {
  let dadosCliente = null;

  function toast(t) {
    const container = document.getElementById('toasts');
    if (!container) return;
    const d = document.createElement('div');
    d.className = 'toast toast-animated flex items-center gap-2 transition-all duration-300 ease-out';
    const msg = String(t || '');
    const lower = msg.toLowerCase();
    let icon = 'check_circle';
    if (lower.includes('erro') || lower.includes('falha') || lower.includes('indisponível') || lower.includes('não foi possível')) {
      icon = 'error';
    } else if (lower.includes('buscando') || lower.includes('obtendo') || lower.includes('calculando') || lower.includes('carregando')) {
      icon = 'autorenew';
    } else if (lower.includes('atenção') || lower.includes('encerrado')) {
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

  const brl = v => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

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

  async function buscarCepCliente(cepVal) {
    if (!cepVal) return;
    const clean = cepVal.replace(/\D/g, '');
    if (clean.length !== 8) return;
    const statusEl = document.getElementById('clienteCepStatus');
    if (statusEl) statusEl.textContent = 'Buscando CEP...';
    try {
      const res = await fetch(`/api/cep/${clean}`);
      if (res.ok) {
        const d = await res.json();
        document.getElementById('clienteFormEndereco').value = d.logradouro || '';
        document.getElementById('clienteFormBairro').value = d.bairro || '';
        document.getElementById('clienteFormCidade').value = d.localidade || '';
        document.getElementById('clienteFormEstado').value = d.uf || '';
        if (d.lat && d.lng) {
          document.getElementById('clienteFormLat').value = d.lat.toFixed(6);
          document.getElementById('clienteFormLng').value = d.lng.toFixed(6);
        }
        if (statusEl) statusEl.textContent = '✓ Endereço preenchido!';
        document.getElementById('clienteFormNumero').focus();
      } else {
        if (statusEl) statusEl.textContent = 'CEP não encontrado.';
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Erro ao consultar CEP.';
    }
  }

  function capturarLocalizacaoCliente() {
    if (!navigator.geolocation) {
      toast('Geolocalização não suportada neste navegador.');
      return;
    }
    toast('Obtendo coordenadas do dispositivo...');
    navigator.geolocation.getCurrentPosition(
      pos => {
        document.getElementById('clienteFormLat').value = pos.coords.latitude.toFixed(6);
        document.getElementById('clienteFormLng').value = pos.coords.longitude.toFixed(6);
        toast('Coordenadas GPS obtidas com sucesso!');
      },
      err => {
        toast('Não foi possível obter a localização.');
      }
    );
  }

  async function geocodificarEnderecoCliente() {
    const cep = (document.getElementById('clienteFormCep').value || '').replace(/\D/g, '');
    const end = document.getElementById('clienteFormEndereco').value;
    const num = document.getElementById('clienteFormNumero').value;
    const bairro = document.getElementById('clienteFormBairro').value;
    const cid = document.getElementById('clienteFormCidade').value;
    const uf = document.getElementById('clienteFormEstado').value;
    const q = `${end} ${num}, ${bairro}, ${cid} - ${uf}, Brasil`;
    toast('Calculando coordenadas pelo endereço...');
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
          document.getElementById('clienteFormLat').value = Number(d.lat).toFixed(6);
          document.getElementById('clienteFormLng').value = Number(d.lng).toFixed(6);
          toast('Coordenadas calculadas!');
          return;
        }
      }
      if (cep.length === 8) {
        const cepRes = await fetch(`/api/cep/${cep}`);
        if (cepRes.ok) {
          const cd = await cepRes.json();
          if (cd.lat != null && cd.lng != null) {
            document.getElementById('clienteFormLat').value = Number(cd.lat).toFixed(6);
            document.getElementById('clienteFormLng').value = Number(cd.lng).toFixed(6);
            toast('Coordenadas atualizadas pelo CEP!');
            return;
          }
        }
      }
      toast('Endereço não localizado com precisão; mantendo coordenadas atuais.');
    } catch (e) {
      toast('Erro ao buscar coordenadas.');
    }
  }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatarMetodoPagamento(metodo) {
    const mapa = {
      escrow: 'Escrow no Local',
      escrow_local: 'Escrow no Local',
      pix: 'Pix (Escrow)',
      cartao: 'Cartão (Escrow)',
      boleto: 'Boleto Bancário (Escrow)'
    };
    return mapa[String(metodo || '').toLowerCase()] || metodo || 'Escrow no Local';
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
        div.innerHTML = `
          <div class="empty-state-card" role="status" aria-live="polite">
            <div class="w-12 h-12 rounded-full bg-perto-bg flex items-center justify-center mx-auto mb-3 text-perto-sea">
              <span class="material-symbols-outlined text-2xl" aria-hidden="true">receipt_long</span>
            </div>
            <p class="empty-title">Nenhum pedido solicitado ainda</p>
            <p class="empty-desc">Você ainda não solicitou nenhum serviço na plataforma. Explore os profissionais disponíveis na sua região.</p>
            <a href="pedido.html" class="btn text-perto-ink font-bold px-6 py-2.5 rounded-full text-xs inline-flex items-center gap-2 text-decoration-none">
              <span class="material-symbols-outlined text-sm" aria-hidden="true">search</span>
              Explorar Prestadores Locais
            </a>
          </div>
        `;
        return;
      }

      div.innerHTML = pedidos.map(p => {
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
          escrowBadgeHtml = `<span class="tag off">↩️ Estornado Total</span>`;
        } else if (estornadoParcial) {
          escrowBadgeHtml = `<span class="tag" style="background: var(--sun-soft, #fff7dd); color: var(--ink);">↩️ Estornado Parcial</span>`;
        } else if (aguardandoEscrow) {
          escrowBadgeHtml = `<span class="tag" style="background: var(--sun-soft, #fff7dd); color: var(--ink);">⏳ Em Garantia (48h)</span>`;
        } else if (escrowLiberado) {
          escrowBadgeHtml = `<span class="tag" style="background: var(--ok-soft, #e6f5ee); color: var(--ok);">✓ Escrow Liberado</span>`;
        } else if (escrowStatus === 'retido' || p.pago) {
          escrowBadgeHtml = `<span class="tag" style="background: var(--ok-soft, #e6f5ee); color: var(--ok);">🔒 Retido em Escrow</span>`;
        } else if (precisaPagar) {
          escrowBadgeHtml = `<span class="tag" style="background: var(--sun-soft, #fff7dd); color: var(--ink);">⏳ Aguardando Pagamento</span>`;
        }
        const estornoInfoHtml = (estornadoTotal || estornadoParcial) && p.valor_estornado != null
          ? `<div class="tabular-nums" style="font-size:0.82rem; color:#991b1b; font-weight:700; margin: 4px 0;">↩️ Valor estornado: ${escapeHtml(brl(p.valor_estornado))}</div>`
          : '';
        const podeAvaliar = st === 'finalizado' && !p.ja_avaliado;
        const jaAvaliadoHtml = st === 'finalizado' && p.ja_avaliado
          ? `<span class="tag" style="background: var(--ok-soft, #e6f5ee); color: var(--ok);">★ Avaliado</span>`
          : '';
        const podeChat = ['confirmado', 'em_transito', 'em_execucao', 'em_disputa', 'finalizado', 'cancelado'].includes(st);
        const podeSos = ['confirmado', 'em_transito', 'em_execucao'].includes(st);
        const podeConcluir = st === 'em_execucao';
        const podeDisputa = ['confirmado', 'em_transito', 'em_execucao', 'finalizado'].includes(st) && !emDisputa;
        const podeVerReviews = st === 'finalizado';

        return `
          <div class="svc" style="margin-bottom: 14px; border-left: 5px solid var(--sea);">
            <div class="top">
              <span class="flex items-center gap-2 flex-wrap"><b>${escapeHtml(p.servico_titulo)}</b> <span class="tag">${escapeHtml(p.servico_categoria)}</span></span>
              <span class="price tabular-nums">${brl(p.preco_total)}</span>
            </div>
            <div class="meta text-perto-ink/80" style="margin: 6px 0;">
              <span>🛠️ <b>${escapeHtml(p.prestador_nome)}</b></span>
              <span class="tabular-nums">📞 ${escapeHtml(p.prestador_telefone || 'Não informado')}</span>
              ${pagamentoHtml}
              <b class="${badgeClass}">${escapeHtml(String(p.status).toUpperCase())}</b>
              ${codigoHtml}
              ${escrowBadgeHtml}
              ${disputaBadgeHtml}
              ${jaAvaliadoHtml}
            </div>
            ${(p.prestador_bairro || p.prestador_cidade) ? `<div style="font-size:0.85rem; color:var(--sea); font-weight:600; margin: 4px 0;">📍 ${escapeHtml([p.prestador_endereco, p.prestador_numero, p.prestador_bairro, p.prestador_cidade].filter(Boolean).join(', '))}</div>` : ''}
            ${p.observacoes ? `<p class="text-perto-ink/80" style="font-size:0.85rem;">${escapeHtml(p.observacoes)}</p>` : ''}
            ${estornoInfoHtml}
            <div style="margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end;">
              ${precisaPagar ? `
                <a href="pedido.html?order_id=${encodeURIComponent(p.order_id)}&pay=1" class="btn" style="text-decoration: none; font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  💳 Pagar / Ver Cobrança
                </a>
              ` : ''}
              ${podeChat ? `
                <button type="button" class="btn2 btn-chat-pedido" data-order-id="${p.order_id}" data-status="${escapeHtml(st)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">chat</span>
                  Chat do Pedido
                </button>
              ` : ''}
              ${podeConcluir ? `
                <button type="button" class="btn btn-confirmar-conclusao" data-order-id="${p.order_id}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">check_circle</span>
                  Confirmar Conclusão
                </button>
              ` : ''}
              ${aguardandoEscrow ? `
                <button type="button" class="btn btn-liberar-escrow" data-order-id="${p.order_id}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">verified</span>
                  Confirmar e Liberar Escrow
                </button>
              ` : ''}
              ${podeDisputa ? `
                <button type="button" class="btn2 btn-abrir-disputa" data-order-id="${p.order_id}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">gavel</span>
                  Abrir Mediação / Disputa
                </button>
              ` : ''}
              ${podeSos ? `
                <button type="button" class="sos-btn btn-sos-pedido" data-order-id="${p.order_id}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">emergency_share</span>
                  SOS Emergência
                </button>
              ` : ''}
              ${podeAvaliar ? `
                <button type="button" class="btn btn-avaliar-pedido" data-order-id="${p.order_id}" data-prestador="${escapeHtml(p.prestador_nome)}" data-servico="${escapeHtml(p.servico_titulo)}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">star</span>
                  Avaliar Prestador
                </button>
              ` : ''}
              ${podeVerReviews ? `
                <button type="button" class="btn2 btn-ver-reviews" data-order-id="${p.order_id}" style="font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
                  <span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">reviews</span>
                  Ver Avaliações
                </button>
              ` : ''}
              <a href="pedido.html?order_id=${encodeURIComponent(p.order_id)}" class="btn2" style="text-decoration: none; font-size: 0.85rem; padding: 6px 14px; display: inline-flex; align-items: center; gap: 4px;">
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
      div.innerHTML = '<p class="text-sm text-perto-ink/80">Erro ao carregar histórico de pedidos.</p>';
    }
  }

  document.getElementById('formPerfilCliente').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origHtml = btnSubmit ? btnSubmit.innerHTML : '';
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
        btnSubmit.innerHTML = origHtml;
      }
    }
  });

  // --- Fluxos Éticos do Portal do Cliente (ET-08, ET-10, ET-13, ET-14, ET-15) ---
  async function confirmarConclusaoPedido(orderId, btnEl) {
    if (!orderId) return;
    const origHtml = btnEl ? btnEl.innerHTML : '';
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
        btnEl.innerHTML = origHtml;
      }
    }
  }

  async function confirmarLiberacaoEscrow(orderId, btnEl) {
    if (!orderId) return;
    const origHtml = btnEl ? btnEl.innerHTML : '';
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
        btnEl.innerHTML = origHtml;
      }
    }
  }

  function vincularModalAcessivel(modalId, closeBtnIds, onEscapeExtra) {
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
        const el = modal.querySelector(focusSelector);
        if (el) setTimeout(() => el.focus(), 0);
      }
    };
    closeBtnIds.forEach(id => {
      const b = document.getElementById(id);
      if (b) b.addEventListener('click', fechar);
    });
    modal.addEventListener('click', (e) => { if (e.target === modal) fechar(); });
    return { abrir, fechar };
  }

  const ctrlChatCliente = vincularModalAcessivel('modalChatPedidoCliente', ['btnFecharModalChatCliente']);
  async function carregarMensagensChatCliente(orderId) {
    const box = document.getElementById('chatClienteMessages');
    if (!box || !orderId) return;
    try {
      const res = await fetch(`/api/orders/${orderId}/messages`);
      if (!res.ok) {
        box.innerHTML = '<p class="text-xs text-perto-ink/80">Não foi possível carregar as mensagens.</p>';
        return;
      }
      const msgs = await res.json();
      if (!Array.isArray(msgs) || !msgs.length) {
        box.innerHTML = '<p class="text-xs text-perto-ink/80">Nenhuma mensagem ainda. Use este canal protegido para falar com o profissional.</p>';
        return;
      }
      const myId = dadosCliente && dadosCliente.id;
      box.innerHTML = msgs.map(m => {
        const isMine = myId && String(m.sender_id) === String(myId);
        const autor = escapeHtml(m.sender_nome || m.sender_tipo || (isMine ? 'Você' : 'Profissional'));
        const texto = escapeHtml(m.mensagem || m.conteudo || '');
        const rawTs = m.criado_em || m.created_at;
        const hora = rawTs ? escapeHtml(String(rawTs).slice(11, 16)) : '';
        return `
          <div class="chat-msg ${isMine ? 'mine bg-perto-sea/10 border-perto-sea/30 ml-6' : 'bg-perto-bg border-perto-road mr-6'} p-2 rounded-lg border">
            <div class="flex items-center justify-between gap-2 text-[10px] font-bold text-perto-ink/80 mb-0.5">
              <span>${autor}</span>
              ${hora ? `<span class="tabular-nums">${hora}</span>` : ''}
            </div>
            <div class="text-xs text-perto-ink break-words">${texto}</div>
          </div>
        `;
      }).join('');
      box.scrollTop = box.scrollHeight;
    } catch (e) {
      box.innerHTML = '<p class="text-xs text-perto-ink/80">Erro de comunicação ao carregar mensagens.</p>';
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
    box.innerHTML = '<p class="text-perto-ink/80">Carregando avaliações...</p>';
    ctrlVerReviewsPedido.abrir('#btnFecharModalVerReviews');
    try {
      const res = await fetch(`/api/orders/${orderId}/reviews`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        box.innerHTML = `<p class="text-perto-ink/80">${escapeHtml(data.error || 'Não foi possível carregar as avaliações.')}</p>`;
        return;
      }
      const minha = data.minha_avaliacao;
      const contraparte = data.contraparte_avaliacao || data.avaliacao_contraparte || data.avaliacao_prestador || data.review_recebida || null;
      const oculta = Boolean(data.oculta_double_blind);
      const renderStatusModeracao = (stMod) => {
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
            ${renderStatusModeracao(minha.status_moderacao)}
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
            ${renderStatusModeracao(contraparte.status_moderacao)}
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
      box.innerHTML = '<p class="text-perto-ink/80">Erro de comunicação ao carregar avaliações.</p>';
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
  document.getElementById('btnExportarDadosLgpd').addEventListener('click', async () => {
    try {
      const res = await fetch('/api/profile/export');
      if (!res.ok) {
        toast('Não foi possível exportar seus dados.');
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
      toast('Exportação JSON gerada com sucesso!');
    } catch (err) {
      toast('Erro de comunicação ao exportar dados.');
    }
  });

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
        try {
          ['pertoja_pending_order', 'pertoja_active_order_id', 'pertoja_search_loc'].forEach((k) => {
            localStorage.removeItem(k);
            sessionStorage.removeItem(k);
          });
          localStorage.clear();
          sessionStorage.clear();
        } catch (e) {}
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

  let historicoSuporteIACliente = [];
  let suporteIAClienteGen = 0;
  let suporteIAClienteEmAndamento = false;
  let suporteIAClienteAbort = null;
  const ctrlSuporteIACliente = vincularModalAcessivel('modalSuporteIA', ['btnFecharModalSuporteIA']);

  function obterSaudacaoInicialSuporteIAClienteHtml() {
    return `
      <div class="p-2.5 rounded-xl bg-white border border-perto-road text-perto-ink">
        <div class="text-[10px] font-bold text-perto-sea mb-1">🤖 Assistente PertoJá</div>
        <p class="m-0">Olá! Sou o assistente do PertoJá. Posso tirar dúvidas sobre pagamento protegido em Escrow, PIN presencial de 4 dígitos, garantia de 48h, disputas e segurança. Como posso ajudar?</p>
      </div>
    `;
  }

  function aplicarBadgeStatusSuporteIA(data) {
    const badgeEl = document.getElementById('badgeStatusSuporteIA');
    if (!badgeEl || !data) return;
    const isLive = data.mode === 'live' || (data.mode == null && data.fallback === false && data.provider !== 'fallback');
    if (isLive) {
      const provider = String(data.active_provider || (data.provider && data.provider !== 'fallback' ? data.provider : '') || data.model || 'LLM');
      const modelInfo = data.model ? `Modelo: ${data.model}` : '';
      const hintInfo = data.hint || '';
      badgeEl.className = 'inline-flex items-center gap-1 self-start px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 border border-emerald-300 text-emerald-900';
      badgeEl.innerHTML = `🟢 IA Online (${escapeHtml(provider)})`;
      badgeEl.title = [modelInfo, hintInfo].filter(Boolean).join(' · ') || 'IA conectada em tempo real';
    } else {
      const reasonMap = {
        unconfigured: 'Nenhuma chave de IA configurada no servidor.',
        localhost_in_serverless: 'Endpoint localhost inacessível em ambiente serverless.',
        auth_error: 'Falha de autenticação no provedor de IA.',
        model_not_found: 'Modelo de IA não encontrado no provedor.',
        rate_limited: 'Limite temporário de requisições da IA atingido.',
        timeout: 'Tempo limite esgotado ao contatar a IA.',
        connection_error: 'Não foi possível conectar ao provedor de IA.',
        provider_error: 'Provedor de IA temporariamente indisponível.'
      };
      const fallbackDetail = data.warning || data.hint || (data.fallback_reason ? (reasonMap[data.fallback_reason] || `Motivo: ${data.fallback_reason}`) : '');
      badgeEl.className = 'inline-flex items-center gap-1 self-start px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-perto-sun/25 border border-perto-sun text-perto-ink';
      badgeEl.innerHTML = '🟡 Modo Offline (FAQ Local)';
      badgeEl.title = fallbackDetail || 'Assistente operando com FAQ local offline.';
    }
  }

  async function atualizarStatusSuporteIA() {
    const badgeEl = document.getElementById('badgeStatusSuporteIA');
    if (!badgeEl) return;
    try {
      const res = await fetch('/api/chat/health', { headers: { 'Accept': 'application/json' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        aplicarBadgeStatusSuporteIA({
          mode: 'fallback',
          warning: data.error || 'Não foi possível verificar o status da IA.'
        });
        return;
      }
      aplicarBadgeStatusSuporteIA(data);
    } catch (err) {
      aplicarBadgeStatusSuporteIA({
        mode: 'fallback',
        warning: 'Falha de conexão ao verificar o status da IA.'
      });
    }
  }

  function alternarEstadoEnvioSuporteIA(carregando) {
    const btnEl = document.getElementById('btnEnviarSuporteIA');
    if (btnEl) {
      if (carregando) {
        if (!btnEl.dataset.origText) btnEl.dataset.origText = btnEl.textContent || 'Enviar';
        btnEl.classList.add('is-loading');
        btnEl.disabled = true;
        btnEl.textContent = 'Consultando...';
      } else {
        btnEl.classList.remove('is-loading');
        btnEl.disabled = false;
        btnEl.textContent = btnEl.dataset.origText || 'Enviar';
      }
    }
    document.querySelectorAll('#chipsPerguntasRapidasSuporteIA .chip-suporte-rapido').forEach(chip => {
      chip.disabled = Boolean(carregando);
    });
  }

  function limparConversaSuporteIA() {
    suporteIAClienteGen += 1;
    if (suporteIAClienteAbort) {
      try { suporteIAClienteAbort.abort(); } catch (_) {}
      suporteIAClienteAbort = null;
    }
    suporteIAClienteEmAndamento = false;
    historicoSuporteIACliente = [];

    const listaEl = document.getElementById('listaMensagensSuporteIA');
    if (listaEl) {
      listaEl.removeAttribute('aria-busy');
      listaEl.innerHTML = obterSaudacaoInicialSuporteIAClienteHtml();
      listaEl.scrollTop = 0;
    }
    alternarEstadoEnvioSuporteIA(false);
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    if (inputEl) {
      inputEl.value = '';
      inputEl.focus();
    }
  }

  function abrirModalSuporteIA() {
    ctrlSuporteIACliente.abrir('#inputMensagemSuporteIA');
    atualizarStatusSuporteIA();
  }

  function enviarPerguntaRapidaSuporteIA(btn) {
    if (!btn || suporteIAClienteEmAndamento) return;
    const pergunta = (btn.getAttribute('data-pergunta') || btn.textContent || '').trim();
    if (!pergunta) return;
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    if (inputEl) inputEl.value = pergunta;
    enviarMensagemSuporteIA(pergunta);
  }

  async function enviarMensagemSuporteIA(textoDireto) {
    if (suporteIAClienteEmAndamento) return;
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    const listaEl = document.getElementById('listaMensagensSuporteIA');
    const msg = (typeof textoDireto === 'string' ? textoDireto : (inputEl?.value || '')).trim();
    if (!msg || !listaEl) return;

    if (inputEl) inputEl.value = '';
    suporteIAClienteEmAndamento = true;
    const myGen = suporteIAClienteGen;
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    suporteIAClienteAbort = controller;

    alternarEstadoEnvioSuporteIA(true);
    listaEl.setAttribute('aria-busy', 'true');

    listaEl.insertAdjacentHTML('beforeend', `
      <div class="p-2.5 rounded-xl bg-perto-sea/10 border border-perto-sea/30 text-perto-ink ml-6">
        <div class="text-[10px] font-bold text-perto-ink/80 mb-0.5">Você</div>
        <p class="m-0 break-words">${escapeHtml(msg)}</p>
      </div>
    `);

    document.getElementById('indicadorDigitandoSuporteIA')?.remove();
    listaEl.insertAdjacentHTML('beforeend', `
      <div id="indicadorDigitandoSuporteIA" class="p-2.5 rounded-xl bg-white border border-perto-road text-perto-ink/80 mr-6 flex items-center gap-2" role="status">
        <span class="inline-flex gap-1" aria-hidden="true">
          <span class="w-1.5 h-1.5 rounded-full bg-perto-sea motion-safe:animate-bounce" style="animation-delay: 0ms;"></span>
          <span class="w-1.5 h-1.5 rounded-full bg-perto-sea motion-safe:animate-bounce" style="animation-delay: 150ms;"></span>
          <span class="w-1.5 h-1.5 rounded-full bg-perto-sea motion-safe:animate-bounce" style="animation-delay: 300ms;"></span>
        </span>
        <span class="text-xs font-semibold">Pensando...</span>
      </div>
    `);
    listaEl.scrollTop = listaEl.scrollHeight;

    try {
      const res = await fetch('/api/chat/support', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller ? controller.signal : undefined,
        body: JSON.stringify({
          message: msg,
          mensagem: msg,
          context: 'cliente',
          history: historicoSuporteIACliente.slice(-10)
        })
      });
      if (myGen !== suporteIAClienteGen) return;

      const data = await res.json().catch(() => ({}));
      if (myGen !== suporteIAClienteGen) return;

      document.getElementById('indicadorDigitandoSuporteIA')?.remove();

      if (res.ok) {
        const reply = data.reply || data.response || data.message || 'Como posso ajudar com mais detalhes?';
        const isFallback = data.fallback === true || data.provider === 'fallback';
        let senderLabel = '🤖 Assistente PertoJá';
        if (isFallback) {
          senderLabel = 'Assistente PertoJá · Modo Offline';
        } else if (data.fallback === false) {
          senderLabel = `🤖 Assistente PertoJá · IA (${escapeHtml(data.model || data.provider || 'LLM')})`;
        }
        const bubbleClass = isFallback
          ? 'p-2.5 rounded-xl bg-white border border-perto-sun/70 text-perto-ink mr-6'
          : 'p-2.5 rounded-xl bg-white border border-perto-road text-perto-ink mr-6';
        const labelClass = isFallback
          ? 'text-[10px] font-bold text-amber-900 mb-0.5'
          : 'text-[10px] font-bold text-perto-sea mb-0.5';

        aplicarBadgeStatusSuporteIA(data);
        historicoSuporteIACliente.push({ role: 'user', content: msg }, { role: 'assistant', content: reply });
        listaEl.insertAdjacentHTML('beforeend', `
          <div class="${bubbleClass}">
            <div class="${labelClass}">${senderLabel}</div>
            <p class="m-0 break-words whitespace-pre-line">${escapeHtml(reply)}</p>
          </div>
        `);
      } else {
        const errText = data.error || 'Assistente temporariamente indisponível. Tente novamente em instantes.';
        aplicarBadgeStatusSuporteIA({ mode: 'fallback', warning: errText });
        listaEl.insertAdjacentHTML('beforeend', `
          <div class="p-2.5 rounded-xl bg-perto-sun/25 border border-perto-sun text-perto-ink mr-6">
            <div class="text-[10px] font-bold text-perto-ink mb-0.5">Aviso do Sistema</div>
            <p class="m-0 break-words">${escapeHtml(errText)}</p>
          </div>
        `);
      }
    } catch (err) {
      if (myGen !== suporteIAClienteGen || (err && err.name === 'AbortError')) return;
      document.getElementById('indicadorDigitandoSuporteIA')?.remove();
      aplicarBadgeStatusSuporteIA({ mode: 'fallback', warning: 'Não foi possível contatar o Assistente de Suporte IA no momento.' });
      listaEl.insertAdjacentHTML('beforeend', `
        <div class="p-2.5 rounded-xl bg-perto-sun/25 border border-perto-sun text-perto-ink mr-6">
          <div class="text-[10px] font-bold text-perto-ink mb-0.5">Aviso de Conexão</div>
          <p class="m-0">Não foi possível contatar o Assistente de Suporte IA no momento.</p>
        </div>
      `);
    } finally {
      if (myGen === suporteIAClienteGen) {
        document.getElementById('indicadorDigitandoSuporteIA')?.remove();
        listaEl.removeAttribute('aria-busy');
        suporteIAClienteEmAndamento = false;
        suporteIAClienteAbort = null;
        alternarEstadoEnvioSuporteIA(false);
        listaEl.scrollTop = listaEl.scrollHeight;
        if (inputEl) inputEl.focus();
      }
    }
  }

  document.getElementById('formSuporteIA').addEventListener('submit', async (e) => {
    e.preventDefault();
    await enviarMensagemSuporteIA();
  });

  // Bindings externos (substituição de atributos HTML inline)
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

  document.addEventListener('DOMContentLoaded', () => {
    carregarPortalCliente();
    // Polling em segundo plano para status das ordens a cada 20 segundos
    setInterval(carregarHistoricoPedidos, 20000);
  });
})();
