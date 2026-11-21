// public/js/como-funciona.js - Interatividade da página Como Funciona (PertoJá)
(function () {
  const formHero = document.getElementById('formHeroParceiro');
  if (formHero) {
    formHero.addEventListener('submit', (e) => {
      e.preventDefault();
      const email = (document.getElementById('heroEmailParceiro')?.value || '').trim();
      const params = new URLSearchParams({ tipo: 'prestador' });
      if (email) params.set('email', email);
      window.location.href = `cadastro.html?${params.toString()}`;
    });
  }

  const fmtBrl = (v) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  function atualizarCalculadora() {
    const precoEl = document.getElementById('calcPreco');
    if (!precoEl) return;
    const preco = Math.max(0, parseFloat(precoEl.value) || 0);
    const qtd = Math.max(0, parseInt(document.getElementById('calcAtendimentos')?.value, 10) || 0);
    const custoUnit = Math.max(0, parseFloat(document.getElementById('calcCusto')?.value) || 0);
    const plano = document.getElementById('calcPlano')?.value || 'basico';

    const bruto = preco * qtd;
    const taxaPct = plano === 'pro' ? 0.08 : 0.12;
    const taxaValor = bruto * taxaPct;
    const custosTotais = custoUnit * qtd;
    const isento = (plano === 'basico' && bruto <= 1800);
    const mensalidadeBase = plano === 'pro' ? 180 : 90;
    const mensalidadeAplicada = isento ? 0 : mensalidadeBase;
    const liquido = bruto - taxaValor - custosTotais - mensalidadeAplicada;

    document.getElementById('resBruto').textContent = fmtBrl(bruto);
    document.getElementById('resTaxaPct').textContent = `${Math.round(taxaPct * 100)}%`;
    document.getElementById('resTaxaValor').textContent = `- ${fmtBrl(taxaValor)}`;
    document.getElementById('resCustos').textContent = `- ${fmtBrl(custosTotais)}`;
    document.getElementById('resMensalidade').textContent = isento ? 'Isento (R$ 0,00)' : fmtBrl(mensalidadeAplicada);

    const badge = document.getElementById('resIsencaoBadge');
    if (badge) {
      badge.innerHTML = isento
        ? '<span class="material-symbols-outlined text-base" aria-hidden="true">verified</span><span>Isenção de mensalidade aplicada (Plano Básico com faturamento &le; R$ 1.800/mês) + 1º mês grátis!</span>'
        : (plano === 'pro'
          ? '<span class="material-symbols-outlined text-base" aria-hidden="true">info</span><span>Plano Pro: 1º mês grátis; após o 1º mês, mensalidade fixa de ' + fmtBrl(mensalidadeBase) + '/mês (isenção válida apenas no Plano Básico).</span>'
          : '<span class="material-symbols-outlined text-base" aria-hidden="true">info</span><span>Acima de R$ 1.800/mês no Plano Básico: 1º mês grátis e depois ' + fmtBrl(mensalidadeBase) + '/mês.</span>');
    }

    const resLiq = document.getElementById('resLiquido');
    resLiq.textContent = fmtBrl(liquido);
    resLiq.classList.toggle('text-perto-ok', liquido > 0);
    resLiq.classList.toggle('text-perto-ink', liquido <= 0);
  }

  ['calcPreco', 'calcAtendimentos', 'calcCusto', 'calcPlano'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', atualizarCalculadora);
    if (el) el.addEventListener('change', atualizarCalculadora);
  });
  atualizarCalculadora();

  document.querySelectorAll('.faq-trigger').forEach((btn) => {
    btn.addEventListener('click', () => {
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      const targetId = btn.getAttribute('aria-controls');
      const panel = targetId ? document.getElementById(targetId) : null;
      btn.setAttribute('aria-expanded', String(!expanded));
      if (panel) panel.style.display = expanded ? 'none' : 'block';
    });
  });
})();
