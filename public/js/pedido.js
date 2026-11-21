// public/js/pedido.js - Handlers externos da página de busca e pedido (PertoJá)
(function () {
  const inputEndereco = document.getElementById('inputBuscaEndereco');
  if (inputEndereco) {
    inputEndereco.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (typeof window.buscarPorEnderecoCliente === 'function') {
          window.buscarPorEnderecoCliente();
        }
      }
    });
  }

  const btnBuscar = document.getElementById('btnBuscarMapa');
  if (btnBuscar) {
    btnBuscar.addEventListener('click', () => {
      if (typeof window.buscarPorEnderecoCliente === 'function') {
        window.buscarPorEnderecoCliente();
      }
    });
  }
})();
