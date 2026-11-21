// public/js/login.js - Autenticação e recuperação de senha (PertoJá)
(function () {
  const urlParams = new URLSearchParams(window.location.search);
  const redirectParam = urlParams.get('redirect');
  const tipoParam = urlParams.get('tipo');
  const hasPendingOrder = urlParams.get('pending_order') === 'true' || !!sessionStorage.getItem('pertoja_pending_order');

  function sanitizarRedirectInterno(raw, fallback = 'portal-cliente.html') {
    if (typeof raw !== 'string' || !raw) return fallback;
    if (/^[\s\u0000-\u001F\u007F]/.test(raw) || /[\u0000-\u001F\u007F\\]/.test(raw)) {
      return fallback;
    }
    if (/^(javascript|data|vbscript):/i.test(raw) || raw.startsWith('//')) {
      return fallback;
    }
    try {
      const url = new URL(raw, window.location.origin);
      if (url.origin !== window.location.origin) return fallback;
      if (url.protocol !== 'http:' && url.protocol !== 'https:') return fallback;
      const paginasPermitidas = new Set([
        '/index.html', '/index',
        '/pedido.html', '/pedido',
        '/portal-cliente.html', '/portal-cliente',
        '/portal-prestador.html', '/portal-prestador',
        '/como-funciona.html', '/como-funciona',
        '/cadastro.html', '/cadastro',
        '/sobre-nos.html', '/sobre-nos',
        '/termos.html', '/termos',
        '/privacidade.html', '/privacidade'
      ]);
      if (!paginasPermitidas.has(url.pathname)) return fallback;
      return url.pathname + url.search + url.hash;
    } catch (e) {
      return fallback;
    }
  }

  if (tipoParam === 'prestador') {
    const badge = document.getElementById('badgePrestadorLogin');
    if (badge) badge.style.display = 'inline-flex';
  }

  // Mostrar / ocultar senha
  const btnToggleSenha = document.getElementById('btnToggleSenha');
  const inputSenha = document.getElementById('senha');
  const iconToggleSenha = document.getElementById('iconToggleSenha');
  if (btnToggleSenha && inputSenha) {
    btnToggleSenha.addEventListener('click', () => {
      const isPassword = inputSenha.type === 'password';
      inputSenha.type = isPassword ? 'text' : 'password';
      btnToggleSenha.setAttribute('aria-pressed', String(isPassword));
      btnToggleSenha.setAttribute('aria-label', isPassword ? 'Ocultar senha' : 'Mostrar senha');
      if (iconToggleSenha) iconToggleSenha.textContent = isPassword ? 'visibility_off' : 'visibility';
    });
  }

  // Modal Esqueci minha senha (acessível com Esc e restauração de foco)
  const modalRecuperar = document.getElementById('modalRecuperarSenha');
  const btnEsqueciSenha = document.getElementById('btnEsqueciSenha');
  const btnFecharModalRecuperar = document.getElementById('btnFecharModalRecuperar');
  const btnCancelarForgot = document.getElementById('btnCancelarForgot');
  const btnVoltarForgot = document.getElementById('btnVoltarForgot');
  const formForgotStep1 = document.getElementById('formForgotStep1');
  const formResetStep2 = document.getElementById('formResetStep2');
  const recuperarFeedback = document.getElementById('recuperarFeedback');
  let modalRecuperarTriggerEl = null;

  function mostrarFeedbackRecuperar(texto, sucesso) {
    if (!recuperarFeedback) return;
    recuperarFeedback.textContent = texto;
    recuperarFeedback.className = sucesso
      ? 'mt-3 p-3 rounded-xl text-xs font-semibold bg-perto-ok/10 text-perto-ok border border-perto-ok/30'
      : 'mt-3 p-3 rounded-xl text-xs font-semibold bg-[#fff4d6] text-perto-ink border border-perto-sun';
    recuperarFeedback.style.display = 'block';
  }

  function onModalRecuperarKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      fecharModalRecuperar();
    }
  }

  function abrirModalRecuperar() {
    modalRecuperarTriggerEl = document.activeElement;
    if (recuperarFeedback) recuperarFeedback.style.display = 'none';
    if (formForgotStep1) formForgotStep1.style.display = 'block';
    if (formResetStep2) formResetStep2.style.display = 'none';
    const emailLogin = document.getElementById('email')?.value || '';
    const forgotEmail = document.getElementById('forgotEmail');
    if (forgotEmail && emailLogin) forgotEmail.value = emailLogin;
    if (modalRecuperar) {
      modalRecuperar.style.display = 'flex';
      document.addEventListener('keydown', onModalRecuperarKeyDown);
      modalRecuperar.onclick = (e) => {
        if (e.target === modalRecuperar) fecharModalRecuperar();
      };
    }
    if (forgotEmail) setTimeout(() => forgotEmail.focus(), 0);
  }

  function fecharModalRecuperar() {
    if (modalRecuperar) modalRecuperar.style.display = 'none';
    document.removeEventListener('keydown', onModalRecuperarKeyDown);
    if (modalRecuperarTriggerEl && typeof modalRecuperarTriggerEl.focus === 'function') {
      modalRecuperarTriggerEl.focus();
    }
    modalRecuperarTriggerEl = null;
  }

  if (btnEsqueciSenha) btnEsqueciSenha.addEventListener('click', abrirModalRecuperar);
  if (btnFecharModalRecuperar) btnFecharModalRecuperar.addEventListener('click', fecharModalRecuperar);
  if (btnCancelarForgot) btnCancelarForgot.addEventListener('click', fecharModalRecuperar);
  if (btnVoltarForgot) {
    btnVoltarForgot.addEventListener('click', () => {
      if (formResetStep2) formResetStep2.style.display = 'none';
      if (formForgotStep1) formForgotStep1.style.display = 'block';
    });
  }

  if (formForgotStep1) {
    formForgotStep1.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = (document.getElementById('forgotEmail')?.value || '').trim();
      try {
        const res = await fetch('/api/auth/forgot-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          mostrarFeedbackRecuperar(data.error || 'Não foi possível solicitar a recuperação.', false);
          return;
        }
        const tokenHint = data.token || data.reset_token;
        if (tokenHint && document.getElementById('resetToken')) {
          document.getElementById('resetToken').value = tokenHint;
        }
        mostrarFeedbackRecuperar(
          tokenHint
            ? `Código gerado: ${tokenHint}. Informe abaixo com sua nova senha.`
            : (data.message || 'Se o e-mail existir, enviamos o código de redefinição.'),
          true
        );
        formForgotStep1.style.display = 'none';
        formResetStep2.style.display = 'block';
        setTimeout(() => document.getElementById('resetToken')?.focus(), 0);
      } catch (err) {
        mostrarFeedbackRecuperar('Erro ao conectar ao servidor.', false);
      }
    });
  }

  if (formResetStep2) {
    formResetStep2.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = (document.getElementById('forgotEmail')?.value || '').trim();
      const token = (document.getElementById('resetToken')?.value || '').trim();
      const novaSenha = document.getElementById('resetNovaSenha')?.value || '';
      const checkReset = typeof window.validarPoliticaSenhaLocal === 'function'
        ? window.validarPoliticaSenhaLocal(novaSenha, 'A nova senha')
        : { valid: novaSenha.length >= 10, message: 'A nova senha deve conter no mínimo 10 caracteres.' };
      if (!checkReset.valid) {
        mostrarFeedbackRecuperar(checkReset.message, false);
        return;
      }
      try {
        const res = await fetch('/api/auth/reset-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, token, nova_senha: novaSenha, senha: novaSenha })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          mostrarFeedbackRecuperar(data.error || 'Token inválido ou expirado.', false);
          return;
        }
        mostrarFeedbackRecuperar(data.message || 'Senha redefinida com sucesso! Você já pode entrar.', true);
        setTimeout(() => fecharModalRecuperar(), 1200);
      } catch (err) {
        mostrarFeedbackRecuperar('Erro ao conectar ao servidor.', false);
      }
    });
  }

  if (redirectParam || hasPendingOrder) {
    const alerta = document.getElementById('alerta-redirect');
    if (alerta) alerta.style.display = 'flex';

    const linkCadastro = document.getElementById('linkParaCadastro');
    if (linkCadastro) {
      const dest = redirectParam ? sanitizarRedirectInterno(redirectParam, 'pedido.html') : 'pedido.html';
      linkCadastro.href = `cadastro.html?redirect=${encodeURIComponent(dest)}${hasPendingOrder ? '&pending_order=true' : ''}`;
    }
  }

  const formLogin = document.getElementById('formLogin');
  if (formLogin) {
    formLogin.addEventListener('submit', async (e) => {
      e.preventDefault();
      const erroDiv = document.getElementById('mensagem-erro');
      if (erroDiv) erroDiv.style.display = 'none';

      const email = document.getElementById('email').value;
      const senha = document.getElementById('senha').value;

      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, senha })
        });
        const rawText = await res.text();
        let data = {};
        try {
          data = rawText ? JSON.parse(rawText) : {};
        } catch (parseErr) {
          if (erroDiv) {
            erroDiv.textContent = `Erro na resposta da API (HTTP ${res.status}).`;
            erroDiv.style.display = 'block';
          }
          return;
        }

        if (!res.ok) {
          if (erroDiv) {
            erroDiv.textContent = data.error || `Erro ao efetuar login (HTTP ${res.status}).`;
            erroDiv.style.display = 'block';
          }
          return;
        }

        if (data.user && data.user.tipo === 'prestador') {
          window.location.href = 'portal-prestador.html';
        } else {
          if (redirectParam) {
            window.location.href = sanitizarRedirectInterno(redirectParam, 'portal-cliente.html');
          } else if (hasPendingOrder) {
            window.location.href = 'pedido.html?restore_order=true';
          } else {
            window.location.href = 'portal-cliente.html';
          }
        }
      } catch (err) {
        if (erroDiv) {
          erroDiv.textContent = 'Não foi possível conectar ao servidor backend.';
          erroDiv.style.display = 'block';
        }
      }
    });
  }
})();
