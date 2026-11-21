// public/js/portal-prestador.js - Painel do Prestador e Gestão de Chamados PertoJá
(function () {
  let dadosPrestador = null;
  let listaMeusServicos = [];
  let listaPedidos = [];
  let filtroPedidosAtual = 'todos';
  let alertaSonoroAtivo = false;
  let idsSolicitadosConhecidos = new Set();
  let primeiraCargaPedidos = true;

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
    } else if (lower.includes('buscando') || lower.includes('obtendo') || lower.includes('recalculando') || lower.includes('carregando')) {
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

  const brl = v => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  function escapeHtml(texto) {
    return String(texto ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
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

  function tocarAlertaSonoro() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } catch (e) {}
  }

  function alternarAlertaSonoro() {
    alertaSonoroAtivo = !alertaSonoroAtivo;
    const btn = document.getElementById('btnAlertaSonoro');
    const icon = document.getElementById('iconAlertaSonoro');
    const txt = document.getElementById('txtAlertaSonoro');
    if (btn) btn.setAttribute('aria-pressed', String(alertaSonoroAtivo));
    if (icon) icon.textContent = alertaSonoroAtivo ? 'notifications_active' : 'notifications_off';
    if (txt) txt.textContent = alertaSonoroAtivo ? 'Alerta Sonoro: On' : 'Alerta Sonoro: Off';
    if (alertaSonoroAtivo) tocarAlertaSonoro();
  }

  function mudarAba(aba) {
    document.getElementById('aba-servicos-painel').style.display = aba === 'servicos' ? 'block' : 'none';
    document.getElementById('aba-pedidos-painel').style.display = aba === 'pedidos' ? 'block' : 'none';
    document.getElementById('aba-perfil-painel').style.display = aba === 'perfil' ? 'block' : 'none';
    document.getElementById('aba-financeiro-painel').style.display = aba === 'financeiro' ? 'block' : 'none';

    const btnServicos = document.getElementById('tabBtnServicos');
    const btnPedidos = document.getElementById('tabBtnPedidos');
    const btnPerfil = document.getElementById('tabBtnPerfil');
    const btnFinanceiro = document.getElementById('tabBtnFinanceiro');

    btnServicos.classList.toggle('on', aba === 'servicos');
    btnPedidos.classList.toggle('on', aba === 'pedidos');
    btnPerfil.classList.toggle('on', aba === 'perfil');
    btnFinanceiro.classList.toggle('on', aba === 'financeiro');

    btnServicos.setAttribute('aria-selected', (aba === 'servicos').toString());
    btnPedidos.setAttribute('aria-selected', (aba === 'pedidos').toString());
    btnPerfil.setAttribute('aria-selected', (aba === 'perfil').toString());
    btnFinanceiro.setAttribute('aria-selected', (aba === 'financeiro').toString());
  }

  async function carregarPainel() {
    try {
      const res = await fetch('/api/auth/me');
      const data = await res.json();

      if (!data.authenticated || data.user.tipo !== 'prestador') {
        window.location.href = 'login.html';
        return;
      }

      dadosPrestador = data.user;
      document.getElementById('prestadorNome').textContent = dadosPrestador.nome;
      document.getElementById('prestadorEmail').textContent = `${dadosPrestador.email} · ★ ${dadosPrestador.avaliacao_media.toFixed(1)}`;
      document.getElementById('chkDisponivel').checked = dadosPrestador.disponivel;
      document.getElementById('txtDisponivel').textContent = dadosPrestador.disponivel ? 'Disponível no Mapa' : 'Indisponível (Pausado)';

      // Preenche formulário de perfil com endereço real
      document.getElementById('perfilNome').value = dadosPrestador.nome;
      document.getElementById('perfilTelefone').value = dadosPrestador.telefone || '';
      document.getElementById('perfilBio').value = dadosPrestador.bio || '';
      document.getElementById('perfilCep').value = dadosPrestador.cep || '';
      document.getElementById('perfilEndereco').value = dadosPrestador.endereco || '';
      document.getElementById('perfilNumero').value = dadosPrestador.numero || '';
      document.getElementById('perfilBairro').value = dadosPrestador.bairro || '';
      document.getElementById('perfilCidade').value = dadosPrestador.cidade || 'São Paulo';
      document.getElementById('perfilEstado').value = dadosPrestador.estado || 'SP';
      document.getElementById('perfilLat').value = dadosPrestador.lat || -23.5653;
      document.getElementById('perfilLng').value = dadosPrestador.lng || -46.6517;

      atualizarStatusKycEConta();

      await carregarServicos();
      await carregarPedidos();
    } catch (e) {
      console.error(e);
    }
  }

  function atualizarStatusKycEConta() {
    if (!dadosPrestador) return;
    const tier = dadosPrestador.kyc_tier != null ? Number(dadosPrestador.kyc_tier) : 0;
    const kycStatus = dadosPrestador.kyc_status || 'pendente';
    const badgeKyc = document.getElementById('kycStatusBadge');
    if (badgeKyc) {
      const kycLabel = kycStatus === 'em_revisao' ? 'Em revisão humana (homônimo)' : kycStatus;
      badgeKyc.textContent = `Tier ${tier} · ${kycLabel}`;
    }
    const docSelect = document.getElementById('kycDocTipoPerfil');
    if (docSelect && dadosPrestador.kyc_documento_tipo) {
      docSelect.value = dadosPrestador.kyc_documento_tipo;
    }
    const regInput = document.getElementById('kycRegProfPerfil');
    if (regInput && dadosPrestador.registro_profissional) {
      regInput.value = dadosPrestador.registro_profissional;
    }

    const statusConta = dadosPrestador.status_conta || 'ativo';
    const alertaConta = document.getElementById('alertaStatusConta');
    const blocoRecurso = document.getElementById('blocoRecursoConta');
    if (statusConta !== 'ativo') {
      if (alertaConta) {
        alertaConta.innerHTML = `Status da conta: <b>${escapeHtml(statusConta)}</b>. Você pode enviar um recurso na aba "Dados de Perfil & GPS".`;
        alertaConta.style.display = 'block';
      }
      if (blocoRecurso) blocoRecurso.style.display = 'block';
    } else {
      if (alertaConta) alertaConta.style.display = 'none';
      if (blocoRecurso) blocoRecurso.style.display = 'none';
    }
  }

  async function alternarDisponibilidade() {
    const disp = document.getElementById('chkDisponivel').checked;
    try {
      await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nome: dadosPrestador.nome,
          telefone: dadosPrestador.telefone,
          bio: dadosPrestador.bio,
          lat: dadosPrestador.lat,
          lng: dadosPrestador.lng,
          disponivel: disp
        })
      });
      dadosPrestador.disponivel = disp;
      document.getElementById('txtDisponivel').textContent = disp ? 'Disponível no Mapa' : 'Indisponível (Pausado)';
      toast(disp ? 'Você está visível no mapa para novos chamados!' : 'Seu perfil foi colocado em pausa no mapa.');
    } catch (e) {
      toast('Erro ao alterar status.');
    }
  }

  function atualizarKPIsEFinanceiro() {
    const pendentes = listaPedidos.filter(p => p.status === 'solicitado').length;
    const ativos = listaMeusServicos.filter(s => s.ativo).length;
    const avaliacao = dadosPrestador && dadosPrestador.avaliacao_media != null ? Number(dadosPrestador.avaliacao_media).toFixed(1) : '5.0';

    const plano = (dadosPrestador && dadosPrestador.plano === 'pro') ? 'pro' : 'basico';
    const taxaPct = plano === 'pro' ? 0.08 : 0.12;
    const taxaLabel = plano === 'pro' ? '8%' : '12%';

    let faturamentoBruto = 0;
    let saldoEscrow = 0;
    let totalLiberado = 0;
    const agora = new Date();
    const anoAtual = agora.getFullYear();
    const mesAtual = agora.getMonth();

    listaPedidos.forEach(p => {
      const valor = Number(p.preco_total || 0);
      const dataRef = p.completed_at || p.criado_em || p.data_criacao || p.created_at;
      let mesmoMes = true;
      if (dataRef) {
        const dt = new Date(String(dataRef).replace(' ', 'T'));
        if (!isNaN(dt.getTime())) {
          mesmoMes = dt.getFullYear() === anoAtual && dt.getMonth() === mesAtual;
        }
      }
      const escrowSt = String(p.escrow_status || '').toLowerCase();
      const estornado = Number(p.valor_estornado || 0);
      const valorLiquidoBase = escrowSt === 'estornado_total'
        ? 0
        : (escrowSt === 'estornado_parcial' ? Math.max(0, valor - estornado) : valor);
      if (p.status === 'finalizado' && mesmoMes && escrowSt !== 'estornado_total') {
        faturamentoBruto += valorLiquidoBase;
      }
      if (escrowSt === 'estornado_total') {
        // Estornado total não compõe saldo em escrow nem liberado
      } else if (escrowSt === 'liberado' && Number(p.pago) === 1) {
        totalLiberado += valorLiquidoBase * (1 - taxaPct);
      } else if (p.status !== 'cancelado' && (Number(p.pago) === 1 || escrowSt === 'retido' || escrowSt === 'aguardando_liberacao')) {
        saldoEscrow += valorLiquidoBase * (1 - taxaPct);
      }
    });

    const elPend = document.getElementById('kpiPendentes');
    const elAtiv = document.getElementById('kpiServicosAtivos');
    const elContSvc = document.getElementById('contServicos');
    const elAval = document.getElementById('kpiAvaliacao');
    const elFat = document.getElementById('kpiFaturamento');
    const elBar = document.getElementById('kpiProgressoBarra');
    const elIsen = document.getElementById('kpiIsencaoTexto');

    if (elPend) elPend.textContent = pendentes;
    if (elAtiv) elAtiv.textContent = ativos;
    if (elContSvc) elContSvc.textContent = listaMeusServicos.length;
    if (elAval) elAval.textContent = `★ ${avaliacao}`;
    if (elFat) elFat.textContent = brl(faturamentoBruto);
    if (elBar) {
      const pct = plano === 'basico' ? Math.min(100, Math.round((faturamentoBruto / 1800) * 100)) : 100;
      elBar.style.width = `${pct}%`;
      elBar.classList.toggle('bg-perto-ok', plano === 'basico' && faturamentoBruto <= 1800);
      elBar.classList.toggle('bg-perto-sea', plano !== 'basico' || faturamentoBruto > 1800);
    }
    if (elIsen) {
      if (plano === 'basico') {
        elIsen.textContent = faturamentoBruto <= 1800
          ? `Isento de mensalidade no mês (faltam ${brl(1800 - faturamentoBruto)} p/ teto)`
          : 'Teto de R$ 1.800/mês atingido (mensalidade R$ 90,00)';
      } else {
        elIsen.textContent = 'Plano Pro: mensalidade fixa R$ 180,00/mês (após 1º mês)';
      }
    }

    const finBadge = document.getElementById('finPlanoBadge');
    const finEscrow = document.getElementById('finSaldoEscrow');
    const finLib = document.getElementById('finTotalLiberado');
    const finRegra = document.getElementById('finRegraMensalidade');
    const finTaxa = document.getElementById('finTaxaInfo');
    const tbody = document.getElementById('tabelaExtratoFinanceiro');

    if (finBadge) finBadge.textContent = plano === 'pro' ? 'Plano Pro (8%)' : 'Plano Básico (12%)';
    if (finEscrow) finEscrow.textContent = brl(saldoEscrow);
    if (finLib) finLib.textContent = brl(totalLiberado);
    if (finRegra) {
      finRegra.textContent = plano === 'basico'
        ? 'Isento ≤ R$ 1.800/mês (Básico)'
        : 'Mensalidade fixa R$ 180,00/mês (Pro)';
    }
    if (finTaxa) finTaxa.textContent = `Taxa atual do plano: ${taxaLabel} por serviço concluído`;

    if (tbody) {
      if (!listaPedidos.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="py-4 px-4 text-center text-perto-ink/80">Nenhum atendimento registrado ainda.</td></tr>';
      } else {
        tbody.innerHTML = listaPedidos.map(p => {
          const bruto = Number(p.preco_total || 0);
          const escrowSt = String(p.escrow_status || '').toLowerCase();
          const estornado = Number(p.valor_estornado || 0);
          let liquido = bruto * (1 - taxaPct);
          if (p.status === 'cancelado' || escrowSt === 'estornado_total') {
            liquido = 0;
          } else if (escrowSt === 'estornado_parcial') {
            liquido = Math.max(0, bruto - estornado) * (1 - taxaPct);
          }
          let situacao = '<span class="tag">Aguardando Pagamento do Cliente</span>';
          if (escrowSt === 'estornado_total' || escrowSt === 'estornado_parcial') {
            situacao = '<span class="tag off">Estornado</span>';
          } else if (p.status === 'cancelado') {
            situacao = '<span class="tag off">Cancelado</span>';
          } else if (escrowSt === 'liberado') {
            situacao = '<span class="tag">Liberado</span>';
          } else if (escrowSt === 'aguardando_liberacao') {
            situacao = '<span class="badge-novo">Em Garantia 48h</span>';
          } else if (escrowSt === 'retido' || Number(p.pago) === 1) {
            situacao = '<span class="badge-novo">Retido em Escrow</span>';
          }
          return `
            <tr>
              <td class="py-3 px-4 font-semibold text-perto-ink tabular-nums">#${escapeHtml(p.order_id)} · ${escapeHtml(p.servico_titulo)}</td>
              <td class="py-3 px-4 text-perto-ink/80">${escapeHtml(p.cliente_nome)}</td>
              <td class="py-3 px-4 font-semibold tabular-nums">${brl(bruto)}</td>
              <td class="py-3 px-4 font-bold text-perto-ok tabular-nums">${brl(liquido)}</td>
              <td class="py-3 px-4">${situacao}</td>
            </tr>
          `;
        }).join('');
      }
    }
  }

  async function carregarServicos() {
    const div = document.getElementById('listaServicos');
    try {
      const res = await fetch('/api/my-services?all=1');
      listaMeusServicos = await res.json();
      atualizarKPIsEFinanceiro();

      if (!listaMeusServicos.length) {
        div.innerHTML = '<p class="text-sm text-perto-ink/80">Você ainda não cadastrou nenhum serviço. Clique acima para adicionar o primeiro!</p>';
        return;
      }

      div.innerHTML = listaMeusServicos.map(s => {
        const endSvc = s.endereco ? `${s.endereco}${s.numero ? ', ' + s.numero : ''} · ${s.bairro || ''} · ${s.cidade || 'SP'}` : (dadosPrestador && dadosPrestador.endereco ? `${dadosPrestador.endereco}, ${dadosPrestador.numero || ''} · ${dadosPrestador.cidade || 'SP'}` : 'São Paulo - SP');
        return `
        <div class="svc border-l-4 border-perto-sea">
          <div class="top">
            <span class="font-bold text-perto-ink">${escapeHtml(s.titulo)}</span>
            <span class="price text-xl tabular-nums">${brl(s.preco)}</span>
          </div>
          <p class="text-sm text-perto-ink/80 my-1.5 font-body">${s.descricao ? escapeHtml(s.descricao) : 'Sem descrição informada.'}</p>
          <p class="text-xs text-perto-sea font-semibold my-1">📍 ${escapeHtml(endSvc)}</p>
          <div class="meta mt-2">
            <span class="tag">${escapeHtml(s.categoria)}</span>
            <span class="tag ${s.ativo ? '' : 'off'}">${s.ativo ? 'Ativo' : 'Pausado'}</span>
          </div>
          <div class="flex flex-wrap gap-2 mt-3 justify-end">
            <button type="button" class="btn-neutral px-3.5 py-1.5 rounded-full text-xs font-bold" data-action="toggle-service" data-service-id="${Number(s.id)}" data-next-ativo="${!s.ativo}">
              ${s.ativo ? 'Pausar' : 'Ativar'}
            </button>
            <button type="button" class="btn px-3.5 py-1.5 rounded-full text-xs font-bold" data-action="edit-service" data-service-id="${Number(s.id)}">✏️ Alterar Preço / Detalhes</button>
            <button type="button" class="btn-danger-soft px-3.5 py-1.5 rounded-full text-xs font-bold" data-action="delete-service" data-service-id="${Number(s.id)}">Excluir</button>
          </div>
        </div>
      `;}).join('');
    } catch (e) {
      div.innerHTML = '<p class="text-sm text-perto-ink/80">Erro ao carregar serviços.</p>';
    }
  }

  async function alternarAtivoServico(id, novoAtivo) {
    try {
      const res = await fetch(`/api/services/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ativo: novoAtivo })
      });
      if (res.ok) {
        toast(novoAtivo ? 'Serviço ativado no catálogo!' : 'Serviço pausado temporariamente.');
        await carregarServicos();
      } else {
        toast('Erro ao atualizar visibilidade do serviço.');
      }
    } catch (e) {
      toast('Erro de comunicação.');
    }
  }

  let modalServicoTriggerEl = null;

  function onModalServicoKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      fecharModalServico();
    }
  }

  function abrirModalServico(id = null) {
    modalServicoTriggerEl = document.activeElement;
    document.getElementById('formServicoModal').reset();
    document.getElementById('modalServicoId').value = '';
    document.getElementById('modalTitulo').textContent = 'Cadastrar Novo Serviço';
    const modalEl = document.getElementById('modalServico');
    modalEl.style.display = 'flex';
    document.addEventListener('keydown', onModalServicoKeyDown);
    modalEl.onclick = (e) => {
      if (e.target === modalEl) fecharModalServico();
    };

    if (id) {
      const serv = listaMeusServicos.find(s => s.id === id);
      if (serv) {
        document.getElementById('modalServicoId').value = serv.id;
        document.getElementById('modalTitulo').textContent = 'Editar Serviço e Alterar Preço';
        document.getElementById('servicoTitulo').value = serv.titulo;
        document.getElementById('servicoCategoria').value = serv.categoria;
        document.getElementById('servicoPreco').value = serv.preco;
        document.getElementById('servicoDescricao').value = serv.descricao || '';
      }
    }

    const tituloInput = document.getElementById('servicoTitulo');
    if (tituloInput) setTimeout(() => tituloInput.focus(), 0);
  }

  function fecharModalServico() {
    document.getElementById('modalServico').style.display = 'none';
    document.removeEventListener('keydown', onModalServicoKeyDown);
    if (modalServicoTriggerEl && typeof modalServicoTriggerEl.focus === 'function') {
      modalServicoTriggerEl.focus();
    }
    modalServicoTriggerEl = null;
  }

  function editarServico(id) {
    abrirModalServico(id);
  }

  async function excluirServico(id) {
    if (!confirm('Deseja realmente remover este serviço do catálogo?')) return;
    try {
      const res = await fetch(`/api/services/${id}`, { method: 'DELETE' });
      if (res.ok) {
        toast('Serviço excluído com sucesso.');
        await carregarServicos();
      } else {
        toast('Erro ao excluir serviço.');
      }
    } catch (e) {
      toast('Erro de comunicação.');
    }
  }

  async function gerarDescricaoServicoIA() {
    const tituloInput = document.getElementById('servicoTitulo');
    const catInput = document.getElementById('servicoCategoria');
    const precoInput = document.getElementById('servicoPreco');
    const descInput = document.getElementById('servicoDescricao');
    const btnIA = document.getElementById('btnGerarDescricaoIA');
    const btnTexto = document.getElementById('btnGerarDescricaoIATexto');

    const title = (tituloInput?.value || '').trim();
    const category = (catInput?.value || '').trim();
    const price = precoInput?.value || '';
    const description = (descInput?.value || '').trim();

    if (!title) {
      toast('Informe o título do serviço primeiro para gerar a descrição com IA.');
      if (tituloInput) tituloInput.focus();
      return;
    }

    if (btnIA) {
      btnIA.classList.add('is-loading');
      btnIA.disabled = true;
    }
    if (btnTexto) btnTexto.textContent = 'Gerando...';

    try {
      const res = await fetch('/api/ads/generate-description', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          category,
          price: price ? parseFloat(price) : null,
          description
        })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        const generated = data.generated_description || data.description || '';
        if (descInput && generated) {
          descInput.value = generated;
          descInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
        toast('Descrição gerada com IA!');
      } else {
        toast(data.error || 'Não foi possível gerar a descrição no momento.');
      }
    } catch (err) {
      toast((err && err.error) || 'Não foi possível gerar a descrição no momento.');
    } finally {
      if (btnIA) {
        btnIA.classList.remove('is-loading');
        btnIA.disabled = false;
      }
      if (btnTexto) btnTexto.textContent = 'Gerar com IA';
    }
  }

  document.getElementById('formServicoModal').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('modalServicoId').value;
    const precoVal = parseFloat(document.getElementById('servicoPreco').value);
    if (isNaN(precoVal) || precoVal <= 0) {
      toast('Informe um valor de preço numérico e positivo.');
      return;
    }
    const btnSalvar = document.getElementById('btnSalvarModal');
    const origSalvarText = btnSalvar ? btnSalvar.textContent : 'Salvar Serviço';
    if (btnSalvar) {
      btnSalvar.classList.add('is-loading');
      btnSalvar.disabled = true;
      btnSalvar.textContent = 'Salvando...';
    }
    const payload = {
      titulo: document.getElementById('servicoTitulo').value,
      categoria: document.getElementById('servicoCategoria').value,
      preco: precoVal,
      descricao: document.getElementById('servicoDescricao').value,
      cep: dadosPrestador.cep,
      endereco: dadosPrestador.endereco,
      numero: dadosPrestador.numero,
      bairro: dadosPrestador.bairro,
      cidade: dadosPrestador.cidade,
      estado: dadosPrestador.estado,
      lat: dadosPrestador.lat,
      lng: dadosPrestador.lng
    };

    try {
      let res;
      if (id) {
        res = await fetch(`/api/services/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        res = await fetch('/api/services', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }

      if (res.ok) {
        toast(id ? 'Preço e serviço atualizados!' : 'Novo serviço cadastrado!');
        fecharModalServico();
        await carregarServicos();
      } else {
        const err = await res.json();
        toast(err.error || 'Erro ao salvar serviço.');
      }
    } catch (e) {
      toast('Erro ao conectar ao servidor.');
    } finally {
      if (btnSalvar) {
        btnSalvar.classList.remove('is-loading');
        btnSalvar.disabled = false;
        btnSalvar.textContent = origSalvarText;
      }
    }
  });

  function filtrarPedidos(filtro, btnEl) {
    filtroPedidosAtual = filtro;
    document.querySelectorAll('#aba-pedidos-painel [data-filtro]').forEach(b => b.classList.remove('on'));
    if (btnEl) btnEl.classList.add('on');
    renderizarPedidos();
  }

  function renderizarPedidos() {
    const div = document.getElementById('listaPedidosRecebidos');
    if (!div) return;

    const filtrados = listaPedidos.filter(p => {
      if (filtroPedidosAtual === 'novos') return p.status === 'solicitado';
      if (filtroPedidosAtual === 'andamento') return ['confirmado', 'em_transito', 'em_execucao', 'em_disputa'].includes(p.status);
      if (filtroPedidosAtual === 'finalizados') return ['finalizado', 'cancelado'].includes(p.status);
      return true;
    });

    if (!filtrados.length) {
      div.innerHTML = '<p class="text-sm text-perto-ink/80">Nenhum chamado encontrado para este filtro.</p>';
      return;
    }

    div.innerHTML = filtrados.map(p => {
      const enderecoProtegido = p.status === 'solicitado' || Boolean(p.endereco_protegido);
      const enderecoRegiao = [p.bairro_cliente, p.cidade_cliente].filter(Boolean).join(' / ');
      const enderecoCompleto = [p.endereco_cliente, p.numero_cliente, p.bairro_cliente, p.cidade_cliente].filter(Boolean).join(', ');
      const localTexto = enderecoProtegido
        ? `${enderecoRegiao || 'Região do cliente'} (endereço exato liberado após confirmação)`
        : (enderecoCompleto ? `${enderecoCompleto}${p.cep_cliente ? ` (CEP ${p.cep_cliente})` : ''}` : enderecoRegiao);
      const isNovo = p.status === 'solicitado';

      let acoesHtml = '';
      const orderIdNum = Number(p.order_id);
      if (p.status === 'solicitado') {
        acoesHtml = `
          <button type="button" class="btn px-4 py-2 rounded-full text-xs font-extrabold" data-action="status" data-order-id="${orderIdNum}" data-status="confirmado">Confirmar Atendimento</button>
          <button type="button" class="btn-danger-soft px-4 py-2 rounded-full text-xs font-bold" data-action="motivo" data-order-id="${orderIdNum}">Recusar</button>
        `;
      } else if (p.status === 'confirmado') {
        acoesHtml = `
          <button type="button" class="btn px-4 py-2 rounded-full text-xs font-extrabold" data-action="status" data-order-id="${orderIdNum}" data-status="em_transito">A Caminho</button>
          <button type="button" class="btn-danger-soft px-4 py-2 rounded-full text-xs font-bold" data-action="motivo" data-order-id="${orderIdNum}">Cancelar</button>
        `;
      } else if (p.status === 'em_transito') {
        acoesHtml = `
          <button type="button" class="btn px-4 py-2 rounded-full text-xs font-extrabold" data-action="pin" data-order-id="${orderIdNum}">Iniciar Execução</button>
        `;
      } else if (p.status === 'em_execucao') {
        acoesHtml = `
          <button type="button" class="btn px-4 py-2 rounded-full text-xs font-extrabold" data-action="status" data-order-id="${orderIdNum}" data-status="finalizado">Finalizar Serviço</button>
        `;
      } else {
        acoesHtml = `<span class="text-xs font-semibold text-perto-ink/80">${p.motivo_cancelamento ? `Motivo: ${escapeHtml(p.motivo_cancelamento)}` : 'Atendimento encerrado.'}</span>`;
      }

      const acoesContextuais = [];
      if (['solicitado', 'confirmado', 'em_transito', 'em_execucao', 'em_disputa', 'finalizado', 'cancelado'].includes(p.status)) {
        acoesContextuais.push(`<button type="button" class="btn2 px-3.5 py-1.5 rounded-full text-xs font-bold" data-action="chat" data-order-id="${orderIdNum}" data-order-status="${escapeHtml(String(p.status || ''))}">Chat Protegido</button>`);
      }
      if (['confirmado', 'em_transito', 'em_execucao'].includes(p.status)) {
        acoesContextuais.push(`<button type="button" class="btn-danger-soft px-3.5 py-1.5 rounded-full text-xs font-bold" data-action="sos" data-order-id="${orderIdNum}">SOS Emergência</button>`);
      }
      if (['confirmado', 'em_transito', 'em_execucao', 'finalizado'].includes(p.status)) {
        acoesContextuais.push(`<button type="button" class="btn-neutral px-3.5 py-1.5 rounded-full text-xs font-bold" data-action="disputa" data-order-id="${orderIdNum}">Abrir Disputa</button>`);
      }
      if (p.status === 'em_disputa') {
        acoesContextuais.push(`<span class="dispute-badge">Em Disputa</span>`);
      }
      if (p.status === 'finalizado' && !p.ja_avaliado) {
        acoesContextuais.push(`<button type="button" class="btn px-3.5 py-1.5 rounded-full text-xs font-bold text-perto-ink inline-flex items-center gap-1" data-action="avaliar" data-order-id="${orderIdNum}"><span class="material-symbols-outlined" style="font-size: 1rem;" aria-hidden="true">star</span> Avaliar Cliente</button>`);
      }
      if (p.status === 'finalizado') {
        acoesContextuais.push(`<button type="button" class="btn2 px-3.5 py-1.5 rounded-full text-xs font-bold" data-action="ver-reviews" data-order-id="${orderIdNum}">Ver Avaliações</button>`);
      }
      const reviewIdNum = Number(p.cliente_review_id || p.review_id || 0);
      if (reviewIdNum > 0) {
        const jaReplicada = Boolean(p.cliente_review_replied);
        const jaContestada = Boolean(p.cliente_review_contestada);
        acoesContextuais.push(`<button type="button" class="btn-neutral px-3 py-1.5 rounded-full text-xs font-bold ${jaReplicada ? 'opacity-50 cursor-not-allowed' : ''}" data-action="review-reply" data-review-id="${reviewIdNum}" ${jaReplicada ? 'disabled' : ''}>${jaReplicada ? 'Réplica Enviada' : 'Responder Avaliação'}</button>`);
        acoesContextuais.push(`<button type="button" class="btn-neutral px-3 py-1.5 rounded-full text-xs font-bold ${jaContestada ? 'opacity-50 cursor-not-allowed' : ''}" data-action="review-contest" data-review-id="${reviewIdNum}" ${jaContestada ? 'disabled' : ''}>${jaContestada ? 'Já Contestada' : 'Contestar Avaliação'}</button>`);
      }

      const escrowSt = String(p.escrow_status || '').toLowerCase();
      let escrowBadgeHtml = '';
      if (escrowSt === 'estornado_total' || escrowSt === 'estornado_parcial') {
        escrowBadgeHtml = `<span class="tag off">Estornado</span>`;
      } else if (escrowSt === 'liberado') {
        escrowBadgeHtml = `<span class="tag">Liberado</span>`;
      } else if (escrowSt === 'aguardando_liberacao') {
        escrowBadgeHtml = `<span class="badge-novo">Em Garantia 48h — aguardando cliente ou prazo</span>`;
      } else if (escrowSt === 'retido' || Number(p.pago) === 1) {
        escrowBadgeHtml = `<span class="badge-novo">Retido em Escrow</span>`;
      } else if (p.status !== 'cancelado') {
        escrowBadgeHtml = `<span class="tag">Aguardando Pagamento do Cliente</span>`;
      }

      return `
      <div class="svc mb-3.5 ${isNovo ? 'order-card-new' : 'border-l-4 border-perto-sun'}">
        <div class="top">
          <span class="flex items-center gap-2 flex-wrap">
            <b>${escapeHtml(p.servico_titulo)}</b>
            <span class="tag">${escapeHtml(p.servico_categoria)}</span>
            ${isNovo ? '<span class="badge-novo">Novo</span>' : ''}
          </span>
          <span class="price tabular-nums">${brl(p.preco_total)}</span>
        </div>
        <div class="meta my-1.5 text-perto-ink/80">
          <span>👤 <b>${escapeHtml(p.cliente_nome)}</b></span>
          <span class="tabular-nums">📞 ${p.cliente_telefone ? escapeHtml(p.cliente_telefone) : 'Protegido / Chat'}</span>
          <span>💳 <b>${escapeHtml(formatarMetodoPagamento(p.metodo_pagamento))}</b></span>
          <b class="tag ${p.status === 'cancelado' ? 'off' : ''}">${escapeHtml(String(p.status || '').toUpperCase())}</b>
          ${escrowBadgeHtml}
        </div>
        ${localTexto ? `<div class="text-xs sm:text-sm text-perto-sea font-semibold my-1">📍 ${escapeHtml(localTexto)}</div>` : ''}
        ${p.observacoes ? `<p class="text-xs sm:text-sm text-perto-ink/80 font-body">${escapeHtml(p.observacoes)}</p>` : ''}
        <div class="flex gap-2 mt-3 flex-wrap items-center">
          ${acoesHtml}
          ${acoesContextuais.join('')}
        </div>
      </div>
    `;}).join('');
  }

  async function carregarPedidos() {
    const div = document.getElementById('listaPedidosRecebidos');
    try {
      const res = await fetch('/api/orders');
      const pedidos = await res.json();
      listaPedidos = Array.isArray(pedidos) ? pedidos : [];
      document.getElementById('contPedidos').textContent = listaPedidos.length;

      const novosIds = new Set(listaPedidos.filter(p => p.status === 'solicitado').map(p => p.order_id));
      const chegouNovo = !primeiraCargaPedidos && [...novosIds].some(id => !idsSolicitadosConhecidos.has(id));
      idsSolicitadosConhecidos = novosIds;
      primeiraCargaPedidos = false;

      if (chegouNovo) {
        toast('Novo chamado recebido!');
        if (alertaSonoroAtivo) tocarAlertaSonoro();
      }

      atualizarKPIsEFinanceiro();
      carregarFinancialSummary();
      renderizarPedidos();
    } catch (e) {
      div.innerHTML = '<p class="text-sm text-perto-ink/80">Erro ao carregar chamados.</p>';
    }
  }

  let modalMotivoTriggerEl = null;

  function onModalMotivoKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      fecharModalMotivoPedido();
    }
  }

  function abrirModalMotivoPedido(orderId) {
    modalMotivoTriggerEl = document.activeElement;
    document.getElementById('formMotivoPedido').reset();
    document.getElementById('motivoOrderId').value = orderId;
    const modalEl = document.getElementById('modalMotivoPedido');
    modalEl.style.display = 'flex';
    document.addEventListener('keydown', onModalMotivoKeyDown);
    modalEl.onclick = (e) => {
      if (e.target === modalEl) fecharModalMotivoPedido();
    };
    setTimeout(() => document.getElementById('motivoPedidoTexto')?.focus(), 0);
  }

  function fecharModalMotivoPedido() {
    document.getElementById('modalMotivoPedido').style.display = 'none';
    document.removeEventListener('keydown', onModalMotivoKeyDown);
    if (modalMotivoTriggerEl && typeof modalMotivoTriggerEl.focus === 'function') {
      modalMotivoTriggerEl.focus();
    }
    modalMotivoTriggerEl = null;
  }

  document.getElementById('formMotivoPedido').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('motivoOrderId').value;
    const motivo = (document.getElementById('motivoPedidoTexto').value || '').trim();
    if (!motivo) {
      toast('Informe o motivo para cancelar ou recusar.');
      return;
    }
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origText = btnSubmit ? btnSubmit.textContent : '';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Cancelando...';
    }
    try {
      await alterarStatusPedido(orderId, 'cancelado', motivo);
      fecharModalMotivoPedido();
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        btnSubmit.textContent = origText;
      }
    }
  });

  let ultimoStatusHttpCode = 0;
  let ultimoStatusErroMsg = '';
  async function alterarStatusPedido(orderId, status, motivo = null, codigoConfirmacao = null) {
    ultimoStatusHttpCode = 0;
    ultimoStatusErroMsg = '';
    try {
      const body = { status };
      if (motivo) body.motivo = motivo;
      if (codigoConfirmacao) body.codigo_confirmacao = codigoConfirmacao;
      const res = await fetch(`/api/orders/${orderId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      ultimoStatusHttpCode = res.status;
      if (res.ok) {
        toast(`Status atualizado para: ${status}`);
        await carregarPedidos();
        return true;
      } else {
        const err = await res.json().catch(() => ({}));
        ultimoStatusErroMsg = err.error || 'Erro ao atualizar chamado.';
        toast(ultimoStatusErroMsg);
        return false;
      }
    } catch (e) {
      ultimoStatusErroMsg = 'Erro de conexão.';
      toast(ultimoStatusErroMsg);
      return false;
    }
  }

  async function carregarFinancialSummary() {
    try {
      const res = await fetch('/api/provider/financial-summary');
      if (!res.ok) return;
      const s = await res.json();
      const plano = (s.plano === 'pro') ? 'pro' : ((dadosPrestador && dadosPrestador.plano === 'pro') ? 'pro' : 'basico');
      const fatMes = s.faturamento_mes_corrente != null ? Number(s.faturamento_mes_corrente) : (s.faturamento_bruto_mes != null ? Number(s.faturamento_bruto_mes) : null);
      if (fatMes != null) {
        const elFat = document.getElementById('kpiFaturamento');
        const elBar = document.getElementById('kpiProgressoBarra');
        const elIsen = document.getElementById('kpiIsencaoTexto');
        if (elFat) elFat.textContent = brl(fatMes);
        if (elBar && plano === 'basico') {
          elBar.style.width = `${Math.min(100, Math.round((fatMes / 1800) * 100))}%`;
          elBar.classList.toggle('bg-perto-ok', fatMes <= 1800);
          elBar.classList.toggle('bg-perto-sea', fatMes > 1800);
        }
        if (elIsen && plano === 'basico') {
          elIsen.textContent = fatMes <= 1800
            ? `Isento de mensalidade no mês (faltam ${brl(1800 - fatMes)} p/ teto)`
            : 'Teto de R$ 1.800/mês atingido (mensalidade R$ 90,00)';
        }
      }
      const escrowVal = s.saldo_escrow_retido != null
        ? s.saldo_escrow_retido
        : (s.escrow_aguardando_48h != null ? s.escrow_aguardando_48h : s.saldo_escrow);
      if (escrowVal != null && document.getElementById('finSaldoEscrow')) {
        document.getElementById('finSaldoEscrow').textContent = brl(escrowVal);
      }
      const hintEl = document.getElementById('finEscrowHint');
      if (hintEl && s.escrow_aguardando_48h != null) {
        const val48 = Number(s.escrow_aguardando_48h || 0);
        hintEl.textContent = val48 > 0
          ? `Inclui ${brl(val48)} em Garantia 48h (aguardando cliente ou prazo)`
          : 'Liberado ao finalizar ou após garantia de 48h';
      }
      const liberadoVal = s.total_liberado_liquido != null ? s.total_liberado_liquido : s.total_liberado;
      if (liberadoVal != null && document.getElementById('finTotalLiberado')) {
        document.getElementById('finTotalLiberado').textContent = brl(liberadoVal);
      }
    } catch (e) {}
  }

  // Helper acessível para modais contextuais (Esc + foco)
  const modalTriggers = {};
  function abrirModalAcessivel(modalId, focusElId) {
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

  function fecharModalAcessivel(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
      el.style.display = 'none';
      if (el._onKeyDown) document.removeEventListener('keydown', el._onKeyDown);
    }
    const trig = modalTriggers[modalId];
    if (trig && typeof trig.focus === 'function') trig.focus();
    delete modalTriggers[modalId];
  }

  // ET-02: Modal PIN de execução
  function abrirModalPinExecucao(orderId) {
    document.getElementById('formPinExecucao').reset();
    document.getElementById('pinOrderId').value = orderId;
    const fb = document.getElementById('pinExecucaoFeedback');
    if (fb) {
      fb.textContent = '';
      fb.classList.add('hidden');
    }
    const btnSubmit = document.getElementById('btnSubmitPinExecucao');
    if (btnSubmit) btnSubmit.disabled = false;
    abrirModalAcessivel('modalPinExecucao', 'pinExecucaoInput');
  }
  function fecharModalPinExecucao() { fecharModalAcessivel('modalPinExecucao'); }

  document.getElementById('formPinExecucao').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('pinOrderId').value;
    const pinInput = document.getElementById('pinExecucaoInput');
    const pin = (pinInput.value || '').trim();
    if (!/^\d{4}$/.test(pin)) {
      toast('Informe exatamente 4 dígitos numéricos.');
      return;
    }
    const btnSubmit = document.getElementById('btnSubmitPinExecucao');
    const fb = document.getElementById('pinExecucaoFeedback');
    if (fb) {
      fb.textContent = '';
      fb.classList.add('hidden');
    }
    const origText = btnSubmit ? btnSubmit.textContent : 'Validar PIN e Iniciar';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Validando...';
    }
    try {
      const ok = await alterarStatusPedido(orderId, 'em_execucao', null, pin);
      if (ok) {
        fecharModalPinExecucao();
      } else {
        pinInput.value = '';
        pinInput.focus();
        if (fb) {
          if (ultimoStatusHttpCode === 429) {
            fb.textContent = ultimoStatusErroMsg || 'Limite de tentativas de PIN atingido (HTTP 429). Aguarde antes de tentar novamente.';
          } else {
            fb.textContent = ultimoStatusErroMsg || 'PIN inválido. Tente novamente.';
          }
          fb.classList.remove('hidden');
        }
      }
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        btnSubmit.textContent = origText;
      }
    }
  });

  // ET-08 & ET-15: Chat Protegido
  let chatPrestadorReadOnly = false;
  async function abrirModalChat(orderId, orderStatus) {
    let st = String(orderStatus || '').toLowerCase();
    if (!st && Array.isArray(listaPedidos)) {
      const found = listaPedidos.find(o => Number(o.order_id) === Number(orderId));
      if (found) st = String(found.status || '').toLowerCase();
    }
    chatPrestadorReadOnly = ['finalizado', 'cancelado'].includes(st);
    document.getElementById('chatOrderId').value = orderId;
    const input = document.getElementById('chatMensagemInput');
    const btn = document.getElementById('btnEnviarChatPedido');
    const notice = document.getElementById('chatPrestadorReadOnlyNotice');
    input.value = '';
    input.disabled = chatPrestadorReadOnly;
    if (btn) btn.disabled = chatPrestadorReadOnly;
    if (notice) notice.classList.toggle('hidden', !chatPrestadorReadOnly);
    abrirModalAcessivel('modalChatPedido', chatPrestadorReadOnly ? null : 'chatMensagemInput');
    await carregarMensagensChat(orderId);
  }
  function fecharModalChat() { fecharModalAcessivel('modalChatPedido'); }

  async function carregarMensagensChat(orderId) {
    const box = document.getElementById('listaMensagensChat');
    if (!box) return;
    box.innerHTML = '<p class="text-perto-ink/80">Carregando mensagens...</p>';
    try {
      const res = await fetch(`/api/orders/${orderId}/messages`);
      if (!res.ok) {
        box.innerHTML = '<p class="text-perto-ink/80">Chat indisponível para este chamado.</p>';
        return;
      }
      const msgs = await res.json();
      if (!Array.isArray(msgs) || !msgs.length) {
        box.innerHTML = '<p class="text-perto-ink/80">Nenhuma mensagem ainda. Inicie a conversa abaixo.</p>';
        return;
      }
      box.innerHTML = msgs.map(m => `
        <div class="p-2.5 rounded-xl bg-white border border-perto-road">
          <div class="flex items-center justify-between text-[11px] text-perto-ink/80 mb-0.5">
            <b>${escapeHtml(m.sender_nome || m.sender_tipo || 'Participante')}</b>
            <span class="tabular-nums">${escapeHtml(m.criado_em || m.created_at || '')}</span>
          </div>
          <p class="m-0 text-perto-ink">${escapeHtml(m.mensagem || m.conteudo || m.texto || '')}</p>
        </div>
      `).join('');
      box.scrollTop = box.scrollHeight;
    } catch (e) {
      box.innerHTML = '<p class="text-perto-ink/80">Erro ao carregar mensagens.</p>';
    }
  }

  document.getElementById('formChatPedido').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (chatPrestadorReadOnly) {
      toast('Chat encerrado (somente leitura).');
      return;
    }
    const orderId = document.getElementById('chatOrderId').value;
    const texto = (document.getElementById('chatMensagemInput').value || '').trim();
    if (!texto) return;
    const btn = document.getElementById('btnEnviarChatPedido');
    const origText = btn ? btn.textContent : 'Enviar';
    if (btn) {
      btn.classList.add('is-loading');
      btn.disabled = true;
      btn.textContent = 'Enviando...';
    }
    try {
      const res = await fetch(`/api/orders/${orderId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mensagem: texto, conteudo: texto })
      });
      if (res.ok) {
        document.getElementById('chatMensagemInput').value = '';
        await carregarMensagensChat(orderId);
      } else {
        const err = await res.json().catch(() => ({}));
        toast(err.error || 'Erro ao enviar mensagem.');
      }
    } catch (e) {
      toast('Erro de conexão no chat.');
    } finally {
      if (btn) {
        btn.classList.remove('is-loading');
        btn.disabled = chatPrestadorReadOnly;
        btn.textContent = origText;
      }
    }
  });

  // ET-13: SOS Emergência
  function abrirModalSos(orderId) {
    document.getElementById('formSosPedido').reset();
    document.getElementById('sosOrderId').value = orderId;
    abrirModalAcessivel('modalSosPedido', 'sosMotivoInput');
  }
  function fecharModalSos() { fecharModalAcessivel('modalSosPedido'); }

  document.getElementById('formSosPedido').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('sosOrderId').value;
    const motivoEl = document.getElementById('sosMotivoInput');
    const motivo = (motivoEl.value || '').trim();
    if (motivo.length < 10) {
      toast('Descreva a ocorrência com pelo menos 10 caracteres.');
      motivoEl.focus();
      return;
    }
    const btnSos = document.getElementById('btnConfirmarSosPrestador');
    const origText = btnSos ? btnSos.textContent : 'Confirmar SOS';
    if (btnSos) {
      btnSos.classList.add('is-loading');
      btnSos.disabled = true;
      btnSos.textContent = 'Enviando SOS...';
    }
    try {
      const res = await fetch(`/api/orders/${orderId}/sos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motivo, descricao: motivo })
      });
      if (res.ok) {
        toast('Alerta SOS registrado! Equipe notificada.');
        fecharModalSos();
      } else {
        const err = await res.json().catch(() => ({}));
        toast(err.error || 'Erro ao registrar SOS.');
      }
    } catch (e) {
      toast('Erro de conexão.');
    } finally {
      if (btnSos) {
        btnSos.classList.remove('is-loading');
        btnSos.disabled = false;
        btnSos.textContent = origText;
      }
    }
  });

  // ET-14: Abrir Disputa
  function abrirModalDisputa(orderId) {
    document.getElementById('formDisputaPedido').reset();
    document.getElementById('disputaOrderId').value = orderId;
    abrirModalAcessivel('modalDisputaPedido', 'disputaMotivoInput');
  }
  function fecharModalDisputa() { fecharModalAcessivel('modalDisputaPedido'); }

  document.getElementById('formDisputaPedido').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('disputaOrderId').value;
    const motivo = (document.getElementById('disputaMotivoInput').value || '').trim();
    const descricao = (document.getElementById('disputaDescricaoInput').value || '').trim();
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origText = btnSubmit ? btnSubmit.textContent : 'Registrar Disputa';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Registrando...';
    }
    try {
      const res = await fetch(`/api/orders/${orderId}/dispute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motivo, descricao })
      });
      if (res.ok) {
        toast('Disputa registrada para mediação.');
        fecharModalDisputa();
        await carregarPedidos();
      } else {
        const err = await res.json().catch(() => ({}));
        toast(err.error || 'Erro ao abrir disputa.');
      }
    } catch (e) {
      toast('Erro de conexão.');
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        btnSubmit.textContent = origText;
      }
    }
  });

  // ET-15: Avaliar Cliente (mesma UX em estrelas/chips do cliente para prestador)
  function atualizarEstrelasAvaliarCliente(notaSelecionada) {
    const val = String(notaSelecionada || '5');
    const input = document.getElementById('avaliarNotaInput');
    if (input) input.value = val;
    document.querySelectorAll('#avaliarClienteEstrelas [data-nota]').forEach(btn => {
      const active = btn.dataset.nota === val;
      btn.classList.toggle('on', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  document.querySelectorAll('#avaliarClienteEstrelas [data-nota]').forEach(btn => {
    btn.addEventListener('click', () => atualizarEstrelasAvaliarCliente(btn.dataset.nota));
  });

  function abrirModalAvaliar(orderId) {
    document.getElementById('formAvaliarCliente').reset();
    document.getElementById('avaliarOrderId').value = orderId;
    atualizarEstrelasAvaliarCliente('5');
    const pedido = (listaPedidos || []).find(item => Number(item.order_id) === Number(orderId));
    const sub = document.getElementById('modalAvaliarClienteSubtitulo');
    if (sub) {
      const tituloSvc = (pedido && pedido.servico_titulo) ? pedido.servico_titulo : 'atendimento';
      const nomeCli = (pedido && pedido.cliente_nome) ? pedido.cliente_nome : 'o cliente';
      sub.textContent = `Como foi o atendimento do serviço "${tituloSvc}" para ${nomeCli}?`;
    }
    abrirModalAcessivel('modalAvaliarCliente');
    const firstChip = document.querySelector('#avaliarClienteEstrelas [data-nota="5"]');
    if (firstChip) setTimeout(() => firstChip.focus(), 0);
  }
  function fecharModalAvaliar() { fecharModalAcessivel('modalAvaliarCliente'); }

  document.getElementById('formAvaliarCliente').addEventListener('submit', async (e) => {
    e.preventDefault();
    const orderId = document.getElementById('avaliarOrderId').value;
    const nota = parseInt(document.getElementById('avaliarNotaInput').value, 10) || 5;
    const comentario = (document.getElementById('avaliarComentarioInput').value || '').trim();
    const btnSubmit = document.getElementById('btnEnviarAvaliacaoCliente');
    const origText = btnSubmit ? btnSubmit.textContent : 'Enviar Avaliação';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Enviando...';
    }
    try {
      const res = await fetch(`/api/orders/${orderId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nota, comentario })
      });
      if (res.ok) {
        toast('Avaliação registrada com sucesso! Obrigado pelo feedback.');
        fecharModalAvaliar();
        await carregarPedidos();
      } else {
        const err = await res.json().catch(() => ({}));
        toast(err.error || 'Não foi possível enviar a avaliação.');
      }
    } catch (e) {
      toast('Erro de comunicação ao enviar avaliação.');
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        btnSubmit.textContent = origText;
      }
    }
  });

  // ET-13: Ver Avaliações Double-Blind do Pedido
  function fecharModalVerReviewsPrestador() { fecharModalAcessivel('modalVerReviewsPrestador'); }
  async function abrirModalVerReviewsPrestador(orderId) {
    const box = document.getElementById('verReviewsPrestadorConteudo');
    if (!box) return;
    box.innerHTML = '<p class="text-perto-ink/80">Carregando avaliações...</p>';
    abrirModalAcessivel('modalVerReviewsPrestador');
    try {
      const res = await fetch(`/api/orders/${orderId}/reviews`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        box.innerHTML = `<p class="text-perto-ink/80">${escapeHtml(data.error || 'Não foi possível carregar as avaliações.')}</p>`;
        return;
      }
      const minha = data.minha_avaliacao;
      const contraparte = data.contraparte_avaliacao || data.avaliacao_contraparte || data.avaliacao_cliente || data.review_recebida || null;
      const oculta = Boolean(data.oculta_double_blind);
      const renderStatusModeracao = (stMod) => {
        const mod = String(stMod || '').trim();
        if (!mod || mod.toLowerCase() === 'publicada') return '';
        return `<div class="mt-1.5 inline-block px-2 py-0.5 rounded-full text-[11px] font-bold bg-perto-sun/25 text-perto-ink">${escapeHtml(mod)}</div>`;
      };
      const minhaHtml = minha
        ? `
          <div class="p-3 rounded-xl bg-perto-bg border border-perto-road">
            <div class="font-bold text-perto-ink mb-1 tabular-nums">Sua avaliação ao cliente (★ ${escapeHtml(String(minha.nota || 5))})</div>
            <p class="m-0 text-perto-ink/80">${escapeHtml(minha.comentario || 'Sem comentário.')}</p>
            ${minha.replica ? `<div class="mt-2 p-2 rounded-lg bg-white border border-perto-road text-xs text-perto-ink/85"><b>Réplica:</b> ${escapeHtml(minha.replica)}</div>` : ''}
            ${renderStatusModeracao(minha.status_moderacao)}
          </div>
        `
        : `<div class="p-3 rounded-xl bg-perto-bg border border-perto-road text-perto-ink/80">Você ainda não avaliou este cliente.</div>`;

      let contraHtml = '';
      if (oculta) {
        contraHtml = `
          <div class="p-3 rounded-xl bg-perto-sun/20 border border-perto-sun text-perto-ink">
            <div class="font-bold mb-1">Avaliação do cliente protegida (Double-Blind)</div>
            <p class="m-0">A avaliação do cliente será revelada simultaneamente após ambos avaliarem ou em 7 dias.</p>
          </div>
        `;
      } else if (contraparte) {
        const revId = Number(contraparte.id || 0);
        const jaReplicada = Boolean(contraparte.replied_at || contraparte.replica);
        const statusModContra = String(contraparte.status_moderacao || '').toLowerCase();
        const jaContestada = Boolean(contraparte.contestada) || ['contestada', 'em_revisao'].includes(statusModContra);
        contraHtml = `
          <div class="p-3 rounded-xl bg-perto-bg border border-perto-road space-y-2">
            <div class="font-bold text-perto-ink tabular-nums">Avaliação do cliente (★ ${escapeHtml(String(contraparte.nota || 5))})</div>
            <p class="m-0 text-perto-ink/80">${escapeHtml(contraparte.comentario || 'Sem comentário.')}</p>
            ${contraparte.replica ? `<div class="p-2 rounded-lg bg-white border border-perto-road text-xs text-perto-ink/85"><b>Sua réplica:</b> ${escapeHtml(contraparte.replica)}</div>` : ''}
            ${renderStatusModeracao(contraparte.status_moderacao)}
            ${revId > 0 ? `
              <div class="flex flex-wrap gap-2 pt-2 border-t border-perto-road">
                <button type="button" class="btn-neutral px-3 py-1.5 rounded-full text-xs font-bold ${jaReplicada ? 'opacity-50 cursor-not-allowed' : ''}" data-action="modal-review-reply" data-review-id="${revId}" ${jaReplicada ? 'disabled' : ''}>${jaReplicada ? 'Réplica Enviada' : 'Responder Avaliação'}</button>
                <button type="button" class="btn-neutral px-3 py-1.5 rounded-full text-xs font-bold ${jaContestada ? 'opacity-50 cursor-not-allowed' : ''}" data-action="modal-review-contest" data-review-id="${revId}" ${jaContestada ? 'disabled' : ''}>${jaContestada ? 'Já Contestada' : 'Contestar Avaliação'}</button>
              </div>
            ` : ''}
          </div>
        `;
      } else {
        contraHtml = `<div class="p-3 rounded-xl bg-perto-bg border border-perto-road text-perto-ink/80">O cliente ainda não registrou uma avaliação.</div>`;
      }
      box.innerHTML = minhaHtml + contraHtml;
    } catch (e) {
      box.innerHTML = '<p class="text-perto-ink/80">Erro de comunicação ao carregar avaliações.</p>';
    }
  }

  // ET-15: Réplica / Contestação de Avaliação
  function abrirModalReviewAcao(reviewId, modo) {
    document.getElementById('formReviewAcao').reset();
    document.getElementById('reviewAcaoId').value = reviewId;
    document.getElementById('reviewAcaoModo').value = modo;
    const isContest = modo === 'contest';
    document.getElementById('tituloModalReviewAcao').textContent = isContest ? 'Contestar Avaliação' : 'Responder Avaliação';
    document.getElementById('labelReviewAcaoTexto').textContent = isContest ? 'Motivo da contestação' : 'Sua réplica pública';
    abrirModalAcessivel('modalReviewAcao', 'reviewAcaoTexto');
  }
  function fecharModalReviewAcao() { fecharModalAcessivel('modalReviewAcao'); }

  document.getElementById('formReviewAcao').addEventListener('submit', async (e) => {
    e.preventDefault();
    const reviewId = document.getElementById('reviewAcaoId').value;
    const modo = document.getElementById('reviewAcaoModo').value;
    const texto = (document.getElementById('reviewAcaoTexto').value || '').trim();
    const isContest = modo === 'contest';
    const url = isContest ? `/api/reviews/${reviewId}/contest` : `/api/reviews/${reviewId}/reply`;
    const payload = isContest ? { motivo: texto } : { replica: texto };
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origText = btnSubmit ? btnSubmit.textContent : 'Enviar';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Enviando...';
    }
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        toast(data.message || (isContest ? 'Contestação enviada!' : 'Réplica publicada!'));
        fecharModalReviewAcao();
        await carregarPedidos();
      } else {
        toast(data.error || 'Erro ao enviar.');
      }
    } catch (e) {
      toast('Erro de conexão.');
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        btnSubmit.textContent = origText;
      }
    }
  });

  // ET-09: Verificação KYC
  document.getElementById('formKycVerify').addEventListener('submit', async (e) => {
    e.preventDefault();
    const selfieCheck = document.getElementById('kycSelfieCheck');
    if (!selfieCheck || !selfieCheck.checked) {
      toast('Confirme a prova de vida (selfie com documento) para enviar a verificação KYC.');
      if (selfieCheck) selfieCheck.focus();
      return;
    }
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origHtml = btnSubmit ? btnSubmit.innerHTML : '';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Verificando KYC...';
    }
    const documento_tipo = document.getElementById('kycDocTipoPerfil').value;
    const cpf = (document.getElementById('kycCpfInput')?.value || '').trim();
    const registro_profissional = (document.getElementById('kycRegProfPerfil').value || '').trim();
    const payload = {
      kyc_documento_tipo: documento_tipo,
      registro_profissional,
      selfie_verificada: Boolean(selfieCheck && selfieCheck.checked)
    };
    if (cpf) payload.cpf = cpf;
    try {
      const res = await fetch('/api/kyc/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        toast(data.message || 'Verificação KYC atualizada!');
        if (data.kyc_tier != null) dadosPrestador.kyc_tier = data.kyc_tier;
        if (data.kyc_status) dadosPrestador.kyc_status = data.kyc_status;
        atualizarStatusKycEConta();
      } else {
        toast(data.error || 'Erro ao enviar verificação KYC.');
      }
    } catch (e) {
      toast('Erro de conexão.');
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = origHtml;
      }
    }
  });

  // ET-10: Recurso / Revisão Humana
  document.getElementById('formAppealConta').addEventListener('submit', async (e) => {
    e.preventDefault();
    const justificativa = (document.getElementById('appealJustificativa').value || '').trim();
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origText = btnSubmit ? btnSubmit.textContent : 'Enviar Recurso';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Enviando...';
    }
    try {
      const res = await fetch('/api/account/appeal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ justificativa, motivo: justificativa })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        toast(data.message || 'Recurso enviado para revisão humana.');
        document.getElementById('formAppealConta').reset();
      } else {
        toast(data.error || 'Erro ao enviar recurso.');
      }
    } catch (e) {
      toast('Erro de conexão.');
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
        btnSubmit.textContent = origText;
      }
    }
  });

  // ET-10: LGPD Exportar / Excluir Conta
  async function exportarDadosLgpd() {
    try {
      const res = await fetch('/api/profile/export');
      if (!res.ok) {
        toast('Erro ao exportar seus dados.');
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
      toast('Exportação JSON concluída!');
    } catch (e) {
      toast('Erro de conexão ao exportar dados.');
    }
  }

  function abrirModalExcluirConta() {
    document.getElementById('formExcluirConta').reset();
    abrirModalAcessivel('modalExcluirConta', 'chkConfirmarExclusao');
  }
  function fecharModalExcluirConta() { fecharModalAcessivel('modalExcluirConta'); }

  document.getElementById('formExcluirConta').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
    }
    try {
      const res = await fetch('/api/profile', { method: 'DELETE' });
      if (res.ok) {
        try {
          ['pertoja_pending_order', 'pertoja_active_order_id', 'pertoja_search_loc'].forEach((k) => {
            localStorage.removeItem(k);
            sessionStorage.removeItem(k);
          });
          localStorage.clear();
          sessionStorage.clear();
        } catch (errStorage) {}
        toast('Conta anonimizada/excluída conforme LGPD.');
        fecharModalExcluirConta();
        setTimeout(() => { window.location.href = 'index.html'; }, 800);
      } else {
        const err = await res.json().catch(() => ({}));
        toast(err.error || 'Não foi possível excluir a conta.');
      }
    } catch (e) {
      toast('Erro de conexão.');
    } finally {
      if (btnSubmit) {
        btnSubmit.classList.remove('is-loading');
        btnSubmit.disabled = false;
      }
    }
  });

  async function buscarCepPrestador(cepVal) {
    if (!cepVal) return;
    const clean = cepVal.replace(/\D/g, '');
    if (clean.length !== 8) return;
    const statusEl = document.getElementById('prestadorCepStatus');
    if (statusEl) statusEl.textContent = 'Buscando CEP...';
    try {
      const res = await fetch(`/api/cep/${clean}`);
      if (res.ok) {
        const d = await res.json();
        document.getElementById('perfilEndereco').value = d.logradouro || '';
        document.getElementById('perfilBairro').value = d.bairro || '';
        document.getElementById('perfilCidade').value = d.localidade || '';
        document.getElementById('perfilEstado').value = d.uf || '';
        if (d.lat && d.lng) {
          document.getElementById('perfilLat').value = d.lat.toFixed(6);
          document.getElementById('perfilLng').value = d.lng.toFixed(6);
        }
        if (statusEl) statusEl.textContent = '✓ Endereço preenchido!';
        document.getElementById('perfilNumero').focus();
      } else {
        if (statusEl) statusEl.textContent = 'CEP não encontrado.';
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Erro ao consultar CEP.';
    }
  }

  async function geocodificarEnderecoPrestador() {
    const cep = (document.getElementById('perfilCep').value || '').replace(/\D/g, '');
    const end = document.getElementById('perfilEndereco').value;
    const num = document.getElementById('perfilNumero').value;
    const bairro = document.getElementById('perfilBairro').value;
    const cid = document.getElementById('perfilCidade').value;
    const uf = document.getElementById('perfilEstado').value;
    const q = `${end} ${num}, ${bairro}, ${cid} - ${uf}, Brasil`;
    toast('Recalculando coordenadas com base no endereço...');
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
          document.getElementById('perfilLat').value = Number(d.lat).toFixed(6);
          document.getElementById('perfilLng').value = Number(d.lng).toFixed(6);
          toast('Coordenadas geocodificadas com sucesso!');
          return;
        }
      }
      if (cep.length === 8) {
        const cepRes = await fetch(`/api/cep/${cep}`);
        if (cepRes.ok) {
          const cd = await cepRes.json();
          if (cd.lat != null && cd.lng != null) {
            document.getElementById('perfilLat').value = Number(cd.lat).toFixed(6);
            document.getElementById('perfilLng').value = Number(cd.lng).toFixed(6);
            toast('Coordenadas atualizadas pelo CEP!');
            return;
          }
        }
      }
      toast('Endereço não localizado com precisão; mantendo coordenadas atuais.');
    } catch (e) {
      toast('Não foi possível obter coordenadas.');
    }
  }

  document.getElementById('formPerfilPrestador').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btnSubmit = e.target.querySelector('button[type="submit"]');
    const origHtml = btnSubmit ? btnSubmit.innerHTML : '';
    if (btnSubmit) {
      btnSubmit.classList.add('is-loading');
      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Salvando...';
    }
    const latVal = parseFloat(document.getElementById('perfilLat').value);
    const lngVal = parseFloat(document.getElementById('perfilLng').value);
    const payload = {
      nome: document.getElementById('perfilNome').value,
      telefone: document.getElementById('perfilTelefone').value,
      bio: document.getElementById('perfilBio').value,
      cep: document.getElementById('perfilCep').value,
      endereco: document.getElementById('perfilEndereco').value,
      numero: document.getElementById('perfilNumero').value,
      bairro: document.getElementById('perfilBairro').value,
      cidade: document.getElementById('perfilCidade').value,
      estado: document.getElementById('perfilEstado').value,
      lat: isNaN(latVal) ? dadosPrestador.lat : latVal,
      lng: isNaN(lngVal) ? dadosPrestador.lng : lngVal,
      disponivel: dadosPrestador.disponivel
    };

    try {
      const res = await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        toast('Perfil e endereço atualizados com sucesso!');
        Object.assign(dadosPrestador, payload);
        document.getElementById('prestadorNome').textContent = payload.nome;
        await carregarServicos();
        if (typeof window.atualizarNavegacao === 'function') window.atualizarNavegacao();
      } else {
        toast('Erro ao salvar dados de perfil.');
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

  function capturarLocalizacaoPrestador() {
    if (!navigator.geolocation) {
      toast('Geolocalização não suportada no seu navegador.');
      return;
    }
    toast('Obtendo posição do GPS...');
    navigator.geolocation.getCurrentPosition(
      pos => {
        document.getElementById('perfilLat').value = pos.coords.latitude.toFixed(6);
        document.getElementById('perfilLng').value = pos.coords.longitude.toFixed(6);
        toast('Coordenadas GPS obtidas com sucesso!');
      },
      err => {
        toast('Não foi possível obter a posição GPS.');
      }
    );
  }

  let historicoSuporteIA = [];
  let suporteIAPrestadorGen = 0;
  let suporteIAPrestadorEmAndamento = false;
  let suporteIAPrestadorAbort = null;

  function obterSaudacaoInicialSuporteIAPrestadorHtml() {
    return `
      <div class="p-2.5 rounded-xl bg-white border border-perto-road text-perto-ink">
        <div class="text-[10px] font-bold text-perto-sea mb-1">🤖 Assistente PertoJá</div>
        <p class="m-0">Olá! Sou o assistente do PertoJá. Posso tirar dúvidas sobre repasses em Escrow, verificação KYC, planos, PIN de execução e boas práticas no catálogo. Como posso ajudar?</p>
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
    suporteIAPrestadorGen += 1;
    if (suporteIAPrestadorAbort) {
      try { suporteIAPrestadorAbort.abort(); } catch (_) {}
      suporteIAPrestadorAbort = null;
    }
    suporteIAPrestadorEmAndamento = false;
    historicoSuporteIA = [];

    const listaEl = document.getElementById('listaMensagensSuporteIA');
    if (listaEl) {
      listaEl.removeAttribute('aria-busy');
      listaEl.innerHTML = obterSaudacaoInicialSuporteIAPrestadorHtml();
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
    abrirModalAcessivel('modalSuporteIA', 'inputMensagemSuporteIA');
    atualizarStatusSuporteIA();
  }

  function fecharModalSuporteIA() {
    fecharModalAcessivel('modalSuporteIA');
  }

  function enviarPerguntaRapidaSuporteIA(btn) {
    if (!btn || suporteIAPrestadorEmAndamento) return;
    const pergunta = (btn.getAttribute('data-pergunta') || btn.textContent || '').trim();
    if (!pergunta) return;
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    if (inputEl) inputEl.value = pergunta;
    enviarMensagemSuporteIA(pergunta);
  }

  async function enviarMensagemSuporteIA(textoDireto) {
    if (suporteIAPrestadorEmAndamento) return;
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    const listaEl = document.getElementById('listaMensagensSuporteIA');
    const msg = (typeof textoDireto === 'string' ? textoDireto : (inputEl?.value || '')).trim();
    if (!msg || !listaEl) return;

    if (inputEl) inputEl.value = '';
    suporteIAPrestadorEmAndamento = true;
    const myGen = suporteIAPrestadorGen;
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    suporteIAPrestadorAbort = controller;

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
          context: 'prestador',
          history: historicoSuporteIA.slice(-10)
        })
      });
      if (myGen !== suporteIAPrestadorGen) return;

      const data = await res.json().catch(() => ({}));
      if (myGen !== suporteIAPrestadorGen) return;

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
        historicoSuporteIA.push({ role: 'user', content: msg }, { role: 'assistant', content: reply });
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
      if (myGen !== suporteIAPrestadorGen || (err && err.name === 'AbortError')) return;
      document.getElementById('indicadorDigitandoSuporteIA')?.remove();
      aplicarBadgeStatusSuporteIA({ mode: 'fallback', warning: 'Não foi possível contatar o Assistente de Suporte IA no momento.' });
      listaEl.insertAdjacentHTML('beforeend', `
        <div class="p-2.5 rounded-xl bg-perto-sun/25 border border-perto-sun text-perto-ink mr-6">
          <div class="text-[10px] font-bold text-perto-ink mb-0.5">Aviso de Conexão</div>
          <p class="m-0">Não foi possível contatar o Assistente de Suporte IA no momento.</p>
        </div>
      `);
    } finally {
      if (myGen === suporteIAPrestadorGen) {
        document.getElementById('indicadorDigitandoSuporteIA')?.remove();
        listaEl.removeAttribute('aria-busy');
        suporteIAPrestadorEmAndamento = false;
        suporteIAPrestadorAbort = null;
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

  // Bindings externos (substituição de todos os atributos HTML inline)
  document.getElementById('chkDisponivel')?.addEventListener('change', alternarDisponibilidade);
  document.getElementById('tabBtnServicos')?.addEventListener('click', () => mudarAba('servicos'));
  document.getElementById('tabBtnPedidos')?.addEventListener('click', () => mudarAba('pedidos'));
  document.getElementById('tabBtnPerfil')?.addEventListener('click', () => mudarAba('perfil'));
  document.getElementById('tabBtnFinanceiro')?.addEventListener('click', () => mudarAba('financeiro'));
  document.getElementById('btnAbrirSuporteIA')?.addEventListener('click', abrirModalSuporteIA);
  document.getElementById('btnNovoServico')?.addEventListener('click', () => abrirModalServico());
  document.getElementById('btnAlertaSonoro')?.addEventListener('click', alternarAlertaSonoro);
  document.querySelectorAll('#aba-pedidos-painel [data-filtro]').forEach((btn) => {
    btn.addEventListener('click', () => filtrarPedidos(btn.dataset.filtro, btn));
  });
  document.getElementById('perfilCep')?.addEventListener('blur', (e) => buscarCepPrestador(e.target.value));
  document.getElementById('btnCapturarLocalizacaoPrestador')?.addEventListener('click', capturarLocalizacaoPrestador);
  document.getElementById('btnGeocodificarEnderecoPrestador')?.addEventListener('click', geocodificarEnderecoPrestador);
  document.getElementById('btnExportarDadosLgpd')?.addEventListener('click', exportarDadosLgpd);
  document.getElementById('btnExcluirContaLgpd')?.addEventListener('click', abrirModalExcluirConta);
  document.getElementById('btnGerarDescricaoIA')?.addEventListener('click', gerarDescricaoServicoIA);
  document.getElementById('btnLimparSuporteIA')?.addEventListener('click', limparConversaSuporteIA);
  document.querySelectorAll('#chipsPerguntasRapidasSuporteIA .chip-suporte-rapido').forEach((chip) => {
    chip.addEventListener('click', () => enviarPerguntaRapidaSuporteIA(chip));
  });

  const closeModalMap = {
    servico: fecharModalServico,
    motivo: fecharModalMotivoPedido,
    pin: fecharModalPinExecucao,
    chat: fecharModalChat,
    sos: fecharModalSos,
    disputa: fecharModalDisputa,
    avaliar: fecharModalAvaliar,
    excluir: fecharModalExcluirConta,
    'review-acao': fecharModalReviewAcao,
    'ver-reviews': fecharModalVerReviewsPrestador,
    'suporte-ia': fecharModalSuporteIA
  };
  document.querySelectorAll('[data-close-modal]').forEach((btn) => {
    const fn = closeModalMap[btn.getAttribute('data-close-modal')];
    if (fn) btn.addEventListener('click', fn);
  });

  document.addEventListener('DOMContentLoaded', () => {
    const listaServicosEl = document.getElementById('listaServicos');
    if (listaServicosEl) {
      listaServicosEl.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-action][data-service-id]');
        if (!btn) return;
        const serviceId = Number(btn.dataset.serviceId);
        if (!Number.isFinite(serviceId) || serviceId <= 0) return;
        const action = btn.dataset.action;
        if (action === 'toggle-service') {
          alternarAtivoServico(serviceId, btn.dataset.nextAtivo === 'true');
        } else if (action === 'edit-service') {
          editarServico(serviceId);
        } else if (action === 'delete-service') {
          excluirServico(serviceId);
        }
      });
    }

    const listaPedidosEl = document.getElementById('listaPedidosRecebidos');
    if (listaPedidosEl) {
      listaPedidosEl.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const orderId = Number(btn.dataset.orderId);
        const reviewId = Number(btn.dataset.reviewId);
        if (action === 'status' && Number.isFinite(orderId) && orderId > 0) {
          alterarStatusPedido(orderId, btn.dataset.status || '');
        } else if (action === 'motivo' && Number.isFinite(orderId) && orderId > 0) {
          abrirModalMotivoPedido(orderId);
        } else if (action === 'pin' && Number.isFinite(orderId) && orderId > 0) {
          abrirModalPinExecucao(orderId);
        } else if (action === 'chat' && Number.isFinite(orderId) && orderId > 0) {
          abrirModalChat(orderId, btn.dataset.orderStatus || '');
        } else if (action === 'sos' && Number.isFinite(orderId) && orderId > 0) {
          abrirModalSos(orderId);
        } else if (action === 'disputa' && Number.isFinite(orderId) && orderId > 0) {
          abrirModalDisputa(orderId);
        } else if (action === 'avaliar' && Number.isFinite(orderId) && orderId > 0) {
          abrirModalAvaliar(orderId);
        } else if (action === 'ver-reviews' && Number.isFinite(orderId) && orderId > 0) {
          abrirModalVerReviewsPrestador(orderId);
        } else if (action === 'review-reply' && Number.isFinite(reviewId) && reviewId > 0) {
          abrirModalReviewAcao(reviewId, 'reply');
        } else if (action === 'review-contest' && Number.isFinite(reviewId) && reviewId > 0) {
          abrirModalReviewAcao(reviewId, 'contest');
        }
      });
    }

    const verReviewsEl = document.getElementById('verReviewsPrestadorConteudo');
    if (verReviewsEl) {
      verReviewsEl.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-action][data-review-id]');
        if (!btn || btn.disabled) return;
        const reviewId = Number(btn.dataset.reviewId);
        if (!Number.isFinite(reviewId) || reviewId <= 0) return;
        const action = btn.dataset.action;
        if (action === 'modal-review-reply') {
          fecharModalVerReviewsPrestador();
          abrirModalReviewAcao(reviewId, 'reply');
        } else if (action === 'modal-review-contest') {
          fecharModalVerReviewsPrestador();
          abrirModalReviewAcao(reviewId, 'contest');
        }
      });
    }

    carregarPainel();
    // Polling em segundo plano para novos chamados a cada 20 segundos
    setInterval(carregarPedidos, 20000);
  });
})();
