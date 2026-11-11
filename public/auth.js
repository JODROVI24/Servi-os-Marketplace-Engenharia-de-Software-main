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

function inicializarDrawerNavegacao() {
  const btnHamburguer = document.getElementById('btnHamburguer') || document.querySelector('.menu-hamburguer');
  const btnFechar = document.getElementById('btnFecharDrawer') || document.querySelector('.drawer-fechar');
  const backdrop = document.getElementById('drawerBackdrop') || document.querySelector('.drawer-backdrop');
  const navDrawer = document.querySelector('.menu-principal');

  if (!navDrawer || navDrawer.dataset.drawerInit) return;
  navDrawer.dataset.drawerInit = 'true';

  // Garante que ícones decorativos dentro dos botões sejam ocultados para tecnologias assistivas
  if (btnHamburguer) {
    const icon = btnHamburguer.querySelector('.material-symbols-outlined');
    if (icon && !icon.hasAttribute('aria-hidden')) icon.setAttribute('aria-hidden', 'true');
  }
  if (btnFechar) {
    const icon = btnFechar.querySelector('.material-symbols-outlined');
    if (icon && !icon.hasAttribute('aria-hidden')) icon.setAttribute('aria-hidden', 'true');
  }

  let scrollYAntesDeAbrir = 0;

  function abrirDrawer() {
    if (navDrawer.classList.contains('aberto')) return;
    scrollYAntesDeAbrir = window.scrollY || window.pageYOffset || document.documentElement.scrollTop || 0;
    navDrawer.classList.add('aberto');
    navDrawer.setAttribute('aria-modal', 'true');
    if (backdrop) {
      backdrop.classList.add('aberto');
      backdrop.setAttribute('aria-hidden', 'false');
    }
    if (btnHamburguer) {
      btnHamburguer.setAttribute('aria-expanded', 'true');
    }
    document.body.classList.add('drawer-aberto');
    if (btnFechar) {
      btnFechar.focus({ preventScroll: true });
    } else {
      const first = navDrawer.querySelector('button:not([disabled]), a[href]:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
      if (first) first.focus({ preventScroll: true });
    }
  }

  function fecharDrawer(options = {}) {
    if (!navDrawer.classList.contains('aberto')) return;
    const shouldRestoreFocus = options.restoreFocus ?? (document.activeElement && navDrawer.contains(document.activeElement));
    navDrawer.classList.remove('aberto');
    navDrawer.removeAttribute('aria-modal');
    if (backdrop) {
      backdrop.classList.remove('aberto');
      backdrop.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('drawer-aberto');
    if (scrollYAntesDeAbrir > 0) {
      window.scrollTo(0, scrollYAntesDeAbrir);
    }
    if (btnHamburguer) {
      btnHamburguer.setAttribute('aria-expanded', 'false');
      if (shouldRestoreFocus && window.getComputedStyle(btnHamburguer).display !== 'none') {
        btnHamburguer.focus({ preventScroll: true });
      }
    }
    if (scrollYAntesDeAbrir > 0) {
      window.scrollTo(0, scrollYAntesDeAbrir);
    }
    setTimeout(() => {
      if (window.map && typeof window.map.invalidateSize === 'function') window.map.invalidateSize();
      if (window.mapInstance && typeof window.mapInstance.invalidateSize === 'function') window.mapInstance.invalidateSize();
    }, 250);
  }

  if (btnHamburguer) {
    btnHamburguer.addEventListener('click', (e) => {
      e.stopPropagation();
      if (navDrawer.classList.contains('aberto')) {
        fecharDrawer();
      } else {
        abrirDrawer();
      }
    });
  }

  if (btnFechar) {
    btnFechar.addEventListener('click', (e) => {
      e.stopPropagation();
      fecharDrawer({ restoreFocus: true });
    });
  }

  if (backdrop) {
    backdrop.addEventListener('click', () => {
      fecharDrawer({ restoreFocus: true });
    });
  }

  // Fechar ao pressionar a tecla Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && navDrawer.classList.contains('aberto')) {
      fecharDrawer({ restoreFocus: true });
    }
  });

  // Focus trap acessível e abrangente dentro do drawer quando aberto
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab' || !navDrawer.classList.contains('aberto')) return;
    const focusable = Array.from(navDrawer.querySelectorAll(
      'button:not([disabled]), a[href]:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ));
    if (!focusable.length) return;
    const firstElement = focusable[0];
    const lastElement = focusable[focusable.length - 1];

    if (!navDrawer.contains(document.activeElement)) {
      e.preventDefault();
      if (e.shiftKey) {
        lastElement.focus({ preventScroll: true });
      } else {
        firstElement.focus({ preventScroll: true });
      }
    } else if (e.shiftKey && document.activeElement === firstElement) {
      e.preventDefault();
      lastElement.focus({ preventScroll: true });
    } else if (!e.shiftKey && document.activeElement === lastElement) {
      e.preventDefault();
      firstElement.focus({ preventScroll: true });
    }
  });

  // Fechar ao clicar em qualquer link de navegação dentro do menu
  navDrawer.addEventListener('click', (e) => {
    const link = e.target.closest('a');
    if (link && navDrawer.classList.contains('aberto')) {
      fecharDrawer();
    }
  });

  // Fechar automaticamente ao redimensionar além do breakpoint mobile (768px)
  const mobileMedia = window.matchMedia('(max-width: 768px)');
  const handleMediaChange = (e) => {
    if (!e.matches && navDrawer.classList.contains('aberto')) {
      fecharDrawer({ restoreFocus: false });
    }
  };
  if (mobileMedia.addEventListener) {
    mobileMedia.addEventListener('change', handleMediaChange);
  } else if (mobileMedia.addListener) {
    mobileMedia.addListener(handleMediaChange);
  }

  window.addEventListener('resize', () => {
    if (!mobileMedia.matches && navDrawer.classList.contains('aberto')) {
      fecharDrawer({ restoreFocus: false });
    }
  });
}

// Expõe globalmente para controle e testes
window.atualizarNavegacao = atualizarNavegacao;
window.inicializarDrawerNavegacao = inicializarDrawerNavegacao;

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.atualizarNavegacaoPromise = atualizarNavegacao();
    inicializarDrawerNavegacao();
  });
} else {
  window.atualizarNavegacaoPromise = atualizarNavegacao();
  inicializarDrawerNavegacao();
}
