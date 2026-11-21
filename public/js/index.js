// public/js/index.js - Handlers externos da página inicial (PertoJá)
(function () {
  function vincularBuscaRapida(formId, inputId) {
    const form = document.getElementById(formId);
    const input = document.getElementById(inputId);
    if (!form || !input) return;
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const termo = input.value.trim();
      window.location.href = termo
        ? `pedido.html?q=${encodeURIComponent(termo)}`
        : 'pedido.html';
    });
  }

  vincularBuscaRapida('formBuscaHeader', 'busca-rapida-header');
  vincularBuscaRapida('formBuscaHero', 'busca-hero-principal');

  function navegarCategoria(categoria) {
    if (typeof window.irParaCategoria === 'function') {
      window.irParaCategoria(categoria);
      return;
    }
    window.location.href = `pedido.html?cat=${encodeURIComponent(categoria)}`;
  }

  document.querySelectorAll('.card-home[data-categoria]').forEach((card) => {
    const categoria = card.getAttribute('data-categoria');
    if (!categoria) return;
    card.addEventListener('click', () => navegarCategoria(categoria));
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        navegarCategoria(categoria);
      }
    });
  });
})();
