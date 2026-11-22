// public/js/modules/portal-support.js - Controlador unificado do Assistente de Suporte IA para os Portais

import { vincularModalAcessivel } from './portal-common.js';

export function createPortalSupportController(config) {
  const {
    context = 'cliente',
    greetingText = 'Olá! Sou o assistente do PertoJá. Como posso ajudar?',
    healthEndpoint = '/api/chat/health',
    supportEndpoint = '/api/chat/support',
    offlineBadgeText = '🟡 Modo Offline (FAQ Local)',
    offlineSenderLabel = 'Assistente PertoJá · Modo Offline',
    thinkingLabel = 'Pensando...',
    trimHistory = (items) => items.slice(-10),
    closeBtnIds = ['btnFecharModalSuporteIA']
  } = config || {};

  let historico = [];
  let gen = 0;
  let emAndamento = false;
  let abortCtrl = null;
  const modalCtrl = vincularModalAcessivel('modalSuporteIA', closeBtnIds);

  function criarBolhaSuporteIA(wrapperClass, labelClass, senderLabel, bodyText, extraBodyClass = '') {
    const wrap = document.createElement('div');
    wrap.className = wrapperClass;
    const lbl = document.createElement('div');
    lbl.className = labelClass;
    lbl.textContent = senderLabel;
    const p = document.createElement('p');
    p.className = extraBodyClass ? `m-0 ${extraBodyClass}` : 'm-0';
    p.textContent = bodyText;
    wrap.append(lbl, p);
    return wrap;
  }

  function criarIndicadorDigitandoSuporteIA() {
    const wrap = document.createElement('div');
    wrap.id = 'indicadorDigitandoSuporteIA';
    wrap.className = 'p-2.5 rounded-xl bg-white border border-perto-road text-perto-ink/80 mr-6 flex items-center gap-2';
    wrap.setAttribute('role', 'status');

    const dots = document.createElement('span');
    dots.className = 'inline-flex gap-1';
    dots.setAttribute('aria-hidden', 'true');
    ['0ms', '150ms', '300ms'].forEach((delay) => {
      const dot = document.createElement('span');
      dot.className = 'w-1.5 h-1.5 rounded-full bg-perto-sea motion-safe:animate-bounce';
      dot.style.animationDelay = delay;
      dots.appendChild(dot);
    });

    const label = document.createElement('span');
    label.className = 'text-xs font-semibold';
    label.textContent = thinkingLabel;

    wrap.append(dots, label);
    return wrap;
  }

  function criarBolhaSaudacaoInicial() {
    return criarBolhaSuporteIA(
      'p-2.5 rounded-xl bg-white border border-perto-road text-perto-ink',
      'text-[10px] font-bold text-perto-sea mb-1',
      '🤖 Assistente PertoJá',
      greetingText
    );
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
      badgeEl.textContent = `🟢 IA Online (${provider})`;
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
      badgeEl.textContent = offlineBadgeText;
      badgeEl.title = fallbackDetail || 'Assistente operando com FAQ local offline.';
    }
  }

  async function atualizarStatus() {
    const badgeEl = document.getElementById('badgeStatusSuporteIA');
    if (!badgeEl) return;
    try {
      const res = await fetch(healthEndpoint, { headers: { Accept: 'application/json' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        aplicarBadgeStatusSuporteIA({
          mode: 'fallback',
          warning: data.error || 'Não foi possível verificar o status da IA.'
        });
        return;
      }
      aplicarBadgeStatusSuporteIA(data);
    } catch (_) {
      aplicarBadgeStatusSuporteIA({
        mode: 'fallback',
        warning: 'Falha de conexão ao verificar o status da IA.'
      });
    }
  }

  function alternarEstadoEnvio(carregando) {
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
    document.querySelectorAll('#chipsPerguntasRapidasSuporteIA .chip-suporte-rapido').forEach((chip) => {
      chip.disabled = Boolean(carregando);
    });
  }

  function limparConversa() {
    gen += 1;
    if (abortCtrl) {
      try { abortCtrl.abort(); } catch (_) {}
      abortCtrl = null;
    }
    emAndamento = false;
    historico = [];

    const listaEl = document.getElementById('listaMensagensSuporteIA');
    if (listaEl) {
      listaEl.removeAttribute('aria-busy');
      listaEl.replaceChildren(criarBolhaSaudacaoInicial());
      listaEl.scrollTop = 0;
    }
    alternarEstadoEnvio(false);
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    if (inputEl) {
      inputEl.value = '';
      inputEl.focus();
    }
  }

  function abrir() {
    modalCtrl.abrir('#inputMensagemSuporteIA');
    atualizarStatus();
  }

  function fechar() {
    modalCtrl.fechar();
  }

  function enviarPerguntaRapida(btn) {
    if (!btn || emAndamento) return;
    const pergunta = (btn.getAttribute('data-pergunta') || btn.textContent || '').trim();
    if (!pergunta) return;
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    if (inputEl) inputEl.value = pergunta;
    enviarMensagem(pergunta);
  }

  async function enviarMensagem(textoDireto) {
    if (emAndamento) return;
    const inputEl = document.getElementById('inputMensagemSuporteIA');
    const listaEl = document.getElementById('listaMensagensSuporteIA');
    const msg = (typeof textoDireto === 'string' ? textoDireto : (inputEl?.value || '')).trim();
    if (!msg || !listaEl) return;

    if (inputEl) inputEl.value = '';
    emAndamento = true;
    const myGen = gen;
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    abortCtrl = controller;

    alternarEstadoEnvio(true);
    listaEl.setAttribute('aria-busy', 'true');

    listaEl.appendChild(criarBolhaSuporteIA(
      'p-2.5 rounded-xl bg-perto-sea/10 border border-perto-sea/30 text-perto-ink ml-6',
      'text-[10px] font-bold text-perto-ink/80 mb-0.5',
      'Você',
      msg,
      'break-words'
    ));

    document.getElementById('indicadorDigitandoSuporteIA')?.remove();
    listaEl.appendChild(criarIndicadorDigitandoSuporteIA());
    listaEl.scrollTop = listaEl.scrollHeight;

    try {
      const res = await fetch(supportEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller ? controller.signal : undefined,
        body: JSON.stringify({
          message: msg,
          mensagem: msg,
          context,
          history: trimHistory(historico)
        })
      });
      if (myGen !== gen) return;

      const data = await res.json().catch(() => ({}));
      if (myGen !== gen) return;

      document.getElementById('indicadorDigitandoSuporteIA')?.remove();

      if (res.ok) {
        const reply = data.reply || data.response || data.message || 'Como posso ajudar com mais detalhes?';
        const isFallback = data.fallback === true || data.provider === 'fallback';
        let senderLabel = '🤖 Assistente PertoJá';
        if (isFallback) {
          senderLabel = offlineSenderLabel;
        } else if (data.fallback === false) {
          senderLabel = `🤖 Assistente PertoJá · IA (${data.model || data.provider || 'LLM'})`;
        }
        const bubbleClass = isFallback
          ? 'p-2.5 rounded-xl bg-white border border-perto-sun/70 text-perto-ink mr-6'
          : 'p-2.5 rounded-xl bg-white border border-perto-road text-perto-ink mr-6';
        const labelClass = isFallback
          ? 'text-[10px] font-bold text-amber-900 mb-0.5'
          : 'text-[10px] font-bold text-perto-sea mb-0.5';

        aplicarBadgeStatusSuporteIA(data);
        historico.push({ role: 'user', content: msg }, { role: 'assistant', content: reply });
        listaEl.appendChild(criarBolhaSuporteIA(bubbleClass, labelClass, senderLabel, reply, 'break-words whitespace-pre-line'));
      } else {
        const errText = data.error || 'Assistente temporariamente indisponível. Tente novamente em instantes.';
        aplicarBadgeStatusSuporteIA({ mode: 'fallback', warning: errText });
        listaEl.appendChild(criarBolhaSuporteIA(
          'p-2.5 rounded-xl bg-perto-sun/25 border border-perto-sun text-perto-ink mr-6',
          'text-[10px] font-bold text-perto-ink mb-0.5',
          'Aviso do Sistema',
          errText,
          'break-words'
        ));
      }
    } catch (err) {
      if (myGen !== gen || (err && err.name === 'AbortError')) return;
      document.getElementById('indicadorDigitandoSuporteIA')?.remove();
      aplicarBadgeStatusSuporteIA({ mode: 'fallback', warning: 'Não foi possível contatar o Assistente de Suporte IA no momento.' });
      listaEl.appendChild(criarBolhaSuporteIA(
        'p-2.5 rounded-xl bg-perto-sun/25 border border-perto-sun text-perto-ink mr-6',
        'text-[10px] font-bold text-perto-ink mb-0.5',
        'Aviso de Conexão',
        'Não foi possível contatar o Assistente de Suporte IA no momento.'
      ));
    } finally {
      if (myGen === gen) {
        document.getElementById('indicadorDigitandoSuporteIA')?.remove();
        listaEl.removeAttribute('aria-busy');
        emAndamento = false;
        abortCtrl = null;
        alternarEstadoEnvio(false);
        listaEl.scrollTop = listaEl.scrollHeight;
        if (inputEl) inputEl.focus();
      }
    }
  }

  return {
    abrir,
    fechar,
    limparConversa,
    enviarPerguntaRapida,
    enviarMensagem,
    atualizarStatus
  };
}
