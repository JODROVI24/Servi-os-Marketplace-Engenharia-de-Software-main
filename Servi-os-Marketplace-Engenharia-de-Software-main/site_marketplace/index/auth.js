// auth.js - Gerenciamento global de autenticação e navegação do PertoJá

async function obterUsuarioLogado() {
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) return null;
    const data = await res.json();
    return data.authenticated ? data.user : null;
  } catch (e) {
    console.warn('Backend API offline ou indisponível:', e);
    return null;
  }
}

async function atualizarNavegacao() {
  const user = await obterUsuarioLogado();
  const nav = document.querySelector('.menu-principal');
  if (!nav) return;

  // Remove botões de autenticação anteriores se houver
  const authLinks = nav.querySelectorAll('.link-auth');
  authLinks.forEach(el => el.remove());

  if (user) {
    const portalUrl = user.tipo === 'prestador' ? 'portal-prestador.html' : 'portal-cliente.html';
    const portalNome = user.tipo === 'prestador' ? 'Painel Prestador' : 'Meu Portal';
    
    const portalLink = document.createElement('a');
    portalLink.href = portalUrl;
    portalLink.className = 'link-auth destaque-portal';
    portalLink.innerHTML = `👤 ${portalNome} (${user.nome.split(' ')[0]})`;
    nav.appendChild(portalLink);

    const logoutLink = document.createElement('a');
    logoutLink.href = '#';
    logoutLink.className = 'link-auth';
    logoutLink.textContent = 'Sair';
    logoutLink.onclick = async (e) => {
      e.preventDefault();
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
      } catch (err) {}
      window.location.href = 'index.html';
    };
    nav.appendChild(logoutLink);
  } else {
    const loginLink = document.createElement('a');
    loginLink.href = 'login.html';
    loginLink.className = 'link-auth';
    loginLink.textContent = 'Entrar';
    nav.appendChild(loginLink);

    const cadastroLink = document.createElement('a');
    cadastroLink.href = 'cadastro.html';
    cadastroLink.className = 'link-auth btn-cadastrar-topo';
    cadastroLink.textContent = 'Cadastrar';
    nav.appendChild(cadastroLink);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  atualizarNavegacao();
});
