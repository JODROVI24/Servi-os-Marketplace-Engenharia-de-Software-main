// public/js/cadastro.js - Fluxo multi-etapa de cadastro e autocompletar de CEP (PertoJá)
(function () {
  const urlParams = new URLSearchParams(window.location.search);
  const redirectParam = urlParams.get('redirect');
  const tipoParam = urlParams.get('tipo');
  const planoParam = urlParams.get('plano');
  const emailParam = urlParams.get('email');
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

  let etapaAtualPrestador = 1;

  if (redirectParam || hasPendingOrder) {
    const alerta = document.getElementById('alerta-redirect');
    if (alerta) alerta.style.display = 'flex';

    const linkLogin = document.getElementById('linkParaLogin');
    if (linkLogin) {
      const dest = redirectParam ? sanitizarRedirectInterno(redirectParam, 'pedido.html') : 'pedido.html';
      linkLogin.href = `login.html?redirect=${encodeURIComponent(dest)}${hasPendingOrder ? '&pending_order=true' : ''}`;
    }
  }

  function atualizarBadgePlano() {
    const planoEl = document.getElementById('plano');
    const badgeEl = document.getElementById('planoSelecionadoBadge');
    if (!planoEl || !badgeEl) return;
    const isPro = planoEl.value === 'pro';
    badgeEl.textContent = isPro ? 'Plano Pro · Taxa 8%' : 'Plano Básico · Taxa 12%';
  }

  function atualizarVisualStepper() {
    const tipo = document.querySelector('input[name="tipo"]:checked')?.value || 'cliente';
    const stepper = document.getElementById('stepperPrestador');
    const s1 = document.getElementById('step1Campos');
    const s2 = document.getElementById('step2Campos');
    const s3 = document.getElementById('campos-prestador');
    const a1 = document.getElementById('step1Actions');
    const a2 = document.getElementById('step2Actions');
    const btnSubmit = document.getElementById('btnSubmitCadastro');

    if (tipo !== 'prestador') {
      if (stepper) stepper.style.display = 'none';
      if (s1) s1.style.display = 'block';
      if (s2) s2.style.display = 'block';
      if (s3) s3.style.display = 'none';
      if (a1) a1.style.display = 'none';
      if (a2) a2.style.display = 'none';
      if (btnSubmit) btnSubmit.style.display = 'flex';
      return;
    }

    if (stepper) {
      stepper.style.display = 'flex';
      stepper.querySelectorAll('.stepper-step').forEach((el) => {
        const stepNum = parseInt(el.dataset.step, 10);
        el.classList.toggle('active', stepNum === etapaAtualPrestador);
        el.classList.toggle('done', stepNum < etapaAtualPrestador);
      });
    }

    if (s1) s1.style.display = etapaAtualPrestador === 1 ? 'block' : 'none';
    if (s2) s2.style.display = etapaAtualPrestador === 2 ? 'block' : 'none';
    if (s3) s3.style.display = etapaAtualPrestador === 3 ? 'block' : 'none';
    if (a1) a1.style.display = etapaAtualPrestador === 1 ? 'flex' : 'none';
    if (a2) a2.style.display = etapaAtualPrestador === 2 ? 'flex' : 'none';
    if (btnSubmit) btnSubmit.style.display = etapaAtualPrestador === 3 ? 'flex' : 'none';
  }

  function validarEtapaAtual(etapa) {
    const erroDiv = document.getElementById('mensagem-erro');
    if (erroDiv) erroDiv.style.display = 'none';

    if (etapa === 1) {
      const nome = document.getElementById('nome');
      const email = document.getElementById('email');
      const telefone = document.getElementById('telefone');
      const senha = document.getElementById('senha');
      for (const field of [nome, email, telefone, senha]) {
        if (field && !field.checkValidity()) {
          field.reportValidity();
          return false;
        }
      }
      const checkPwd = typeof window.validarPoliticaSenhaLocal === 'function'
        ? window.validarPoliticaSenhaLocal(senha ? senha.value : '', 'A senha')
        : { valid: Boolean(senha && senha.value.length >= 10), message: 'A senha deve conter no mínimo 10 caracteres.' };
      if (!checkPwd.valid) {
        if (erroDiv) {
          erroDiv.textContent = checkPwd.message;
          erroDiv.style.display = 'block';
        }
        return false;
      }
    } else if (etapa === 2) {
      const step2Inputs = document.querySelectorAll('#step2Campos input');
      for (const field of step2Inputs) {
        if (field.type !== 'hidden' && !field.checkValidity()) {
          field.reportValidity();
          return false;
        }
      }
    }
    return true;
  }

  function irParaEtapa(novaEtapa) {
    if (novaEtapa > etapaAtualPrestador && !validarEtapaAtual(etapaAtualPrestador)) {
      return;
    }
    etapaAtualPrestador = Math.max(1, Math.min(3, novaEtapa));
    atualizarVisualStepper();
  }

  function alternarTipo(tipo) {
    const lblCliente = document.getElementById('lblCliente');
    const lblPrestador = document.getElementById('lblPrestador');

    if (tipo === 'prestador') {
      etapaAtualPrestador = 1;
      if (lblPrestador) {
        lblPrestador.classList.add('ativo');
        lblPrestador.style.borderColor = 'var(--sea)';
        lblPrestador.style.background = '#eef6f9';
      }
      if (lblCliente) {
        lblCliente.classList.remove('ativo');
        lblCliente.style.borderColor = 'var(--road)';
        lblCliente.style.background = '#ffffff';
      }
    } else {
      if (lblCliente) {
        lblCliente.classList.add('ativo');
        lblCliente.style.borderColor = 'var(--sea)';
        lblCliente.style.background = '#eef6f9';
      }
      if (lblPrestador) {
        lblPrestador.classList.remove('ativo');
        lblPrestador.style.borderColor = 'var(--road)';
        lblPrestador.style.background = '#ffffff';
      }
    }
    atualizarVisualStepper();
  }

  async function buscarCEP(cepVal) {
    if (!cepVal) return;
    const cepClean = cepVal.replace(/\D/g, '');
    if (cepClean.length !== 8) return;

    const statusEl = document.getElementById('cepStatus');
    if (statusEl) statusEl.textContent = 'Buscando CEP...';

    try {
      const res = await fetch(`/api/cep/${cepClean}`);
      if (res.ok) {
        const d = await res.json();
        document.getElementById('endereco').value = d.logradouro || '';
        document.getElementById('bairro').value = d.bairro || '';
        document.getElementById('cidade').value = d.localidade || '';
        document.getElementById('estado').value = d.uf || '';
        if (d.lat && d.lng) {
          document.getElementById('lat').value = d.lat;
          document.getElementById('lng').value = d.lng;
        }
        if (statusEl) statusEl.textContent = '✓ Endereço preenchido!';
        document.getElementById('numero')?.focus();
      } else {
        if (statusEl) statusEl.textContent = 'CEP não encontrado.';
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = 'Falha ao buscar CEP.';
    }
  }

  // Vincular eventos sem atributos inline
  document.querySelectorAll('input[name="tipo"]').forEach((radio) => {
    radio.addEventListener('change', () => alternarTipo(radio.value));
  });
  document.getElementById('btnStep1Next')?.addEventListener('click', () => irParaEtapa(2));
  document.getElementById('btnStep2Back')?.addEventListener('click', () => irParaEtapa(1));
  document.getElementById('btnStep2Next')?.addEventListener('click', () => irParaEtapa(3));
  document.getElementById('btnStep3Back')?.addEventListener('click', () => irParaEtapa(2));
  document.getElementById('cep')?.addEventListener('blur', (e) => buscarCEP(e.target.value));
  document.getElementById('plano')?.addEventListener('change', atualizarBadgePlano);

  // Pré-preenchimento via querystring (?tipo=, ?plano=, ?email=) (PA-03)
  if (emailParam) {
    const emailEl = document.getElementById('email');
    if (emailEl) emailEl.value = emailParam;
  }
  if (planoParam === 'pro' || planoParam === 'basico') {
    const planoEl = document.getElementById('plano');
    if (planoEl) planoEl.value = planoParam;
  }
  atualizarBadgePlano();
  if (tipoParam === 'prestador' || planoParam) {
    const radioPrestador = document.querySelector('input[name="tipo"][value="prestador"]');
    if (radioPrestador) radioPrestador.checked = true;
    alternarTipo('prestador');
  }

  const formCadastro = document.getElementById('formCadastro');
  if (formCadastro) {
    formCadastro.addEventListener('submit', async (e) => {
      e.preventDefault();
      const erroDiv = document.getElementById('mensagem-erro');
      if (erroDiv) erroDiv.style.display = 'none';

      const aceiteEl = document.getElementById('aceiteTermos');
      if (!aceiteEl || !aceiteEl.checked) {
        if (erroDiv) {
          erroDiv.textContent = 'Você precisa aceitar os Termos de Uso e a Política de Privacidade para criar sua conta.';
          erroDiv.style.display = 'block';
        }
        if (aceiteEl) aceiteEl.focus();
        return;
      }

      const tipo = document.querySelector('input[name="tipo"]:checked')?.value || 'cliente';
      const payload = {
        nome: document.getElementById('nome').value,
        email: document.getElementById('email').value,
        telefone: document.getElementById('telefone').value,
        senha: document.getElementById('senha').value,
        tipo: tipo,
        cep: document.getElementById('cep').value,
        endereco: document.getElementById('endereco').value,
        numero: document.getElementById('numero').value,
        bairro: document.getElementById('bairro').value,
        cidade: document.getElementById('cidade').value,
        estado: document.getElementById('estado').value,
        lat: document.getElementById('lat').value ? parseFloat(document.getElementById('lat').value) : null,
        lng: document.getElementById('lng').value ? parseFloat(document.getElementById('lng').value) : null,
        aceite_termos: Boolean(aceiteEl.checked),
        versao_termos: '2026.1'
      };

      if (!payload.nome || !payload.email || !payload.telefone) {
        if (tipo === 'prestador') {
          etapaAtualPrestador = 1;
          atualizarVisualStepper();
        }
        if (erroDiv) {
          erroDiv.textContent = 'Preencha nome, e-mail e telefone para continuar.';
          erroDiv.style.display = 'block';
        }
        return;
      }

      const checkPwdSubmit = typeof window.validarPoliticaSenhaLocal === 'function'
        ? window.validarPoliticaSenhaLocal(payload.senha, 'A senha')
        : { valid: Boolean(payload.senha && payload.senha.length >= 10), message: 'A senha deve conter no mínimo 10 caracteres.' };
      if (!checkPwdSubmit.valid) {
        if (tipo === 'prestador') {
          etapaAtualPrestador = 1;
          atualizarVisualStepper();
        }
        if (erroDiv) {
          erroDiv.textContent = checkPwdSubmit.message;
          erroDiv.style.display = 'block';
        }
        return;
      }

      if (tipo === 'prestador') {
        payload.categoria = document.getElementById('categoria').value;
        const precoVal = parseFloat(document.getElementById('preco_inicial').value);
        payload.preco_inicial = (!isNaN(precoVal) && precoVal > 0) ? precoVal : 100.0;
        payload.bio = document.getElementById('bio').value;
        payload.plano = document.getElementById('plano')?.value || 'basico';
        payload.kyc_documento_tipo = document.getElementById('kycDocumentoTipo')?.value || 'RG';
        const regProf = (document.getElementById('registroProfissional')?.value || '').trim();
        if (regProf) payload.registro_profissional = regProf;
      }

      try {
        const res = await fetch('/api/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
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
          if (data.code === 'PASSWORD_TOO_SHORT' || data.code === 'PASSWORD_PWNED') {
            if (tipo === 'prestador') {
              etapaAtualPrestador = 1;
              atualizarVisualStepper();
            }
            const senhaEl = document.getElementById('senha');
            if (senhaEl) senhaEl.focus();
          }
          if (erroDiv) {
            erroDiv.textContent = data.error || `Erro ao realizar cadastro (HTTP ${res.status}).`;
            erroDiv.style.display = 'block';
          }
          return;
        }

        if (tipo === 'prestador') {
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
          erroDiv.textContent = 'Erro ao conectar ao servidor.';
          erroDiv.style.display = 'block';
        }
      }
    });
  }
})();
