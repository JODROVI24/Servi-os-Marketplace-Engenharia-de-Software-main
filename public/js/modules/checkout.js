// public/js/modules/checkout.js - QR Code PIX determinístico e modal de checkout multi-gateway

import { brl, csrfHeaders, qs, store } from './state.js';
import { copiarTextoSeguro, gerarIdempotencyKey, sanitizeSafeUrl, toast } from './ui.js';

let checkoutPollTimer = null;
let checkoutExpiryTimer = null;

export function criarSvgQrDeterministico(payload) {
  const text = String(payload || 'PERTOJA-PIX');
  const bytes = typeof TextEncoder !== 'undefined'
    ? Array.from(new TextEncoder().encode(text))
    : Array.from(unescape(encodeURIComponent(text))).map((ch) => ch.charCodeAt(0));

  const QR_SPEC = [
    null,
    { cap: 17, total: 19, ec: 7, b1: 1, d1: 19, b2: 0, d2: 0, align: [] },
    { cap: 32, total: 34, ec: 10, b1: 1, d1: 34, b2: 0, d2: 0, align: [6, 18] },
    { cap: 53, total: 55, ec: 15, b1: 1, d1: 55, b2: 0, d2: 0, align: [6, 22] },
    { cap: 78, total: 80, ec: 20, b1: 1, d1: 80, b2: 0, d2: 0, align: [6, 26] },
    { cap: 106, total: 108, ec: 26, b1: 1, d1: 108, b2: 0, d2: 0, align: [6, 30] },
    { cap: 134, total: 136, ec: 18, b1: 2, d1: 68, b2: 0, d2: 0, align: [6, 34] },
    { cap: 154, total: 156, ec: 20, b1: 2, d1: 78, b2: 0, d2: 0, align: [6, 22, 38] },
    { cap: 192, total: 194, ec: 24, b1: 2, d1: 97, b2: 0, d2: 0, align: [6, 24, 42] },
    { cap: 230, total: 232, ec: 30, b1: 2, d1: 116, b2: 0, d2: 0, align: [6, 26, 46] },
    { cap: 271, total: 274, ec: 18, b1: 2, d1: 68, b2: 2, d2: 69, align: [6, 28, 50] },
    { cap: 321, total: 324, ec: 20, b1: 4, d1: 81, b2: 0, d2: 0, align: [6, 30, 54] },
    { cap: 367, total: 370, ec: 24, b1: 2, d1: 92, b2: 2, d2: 93, align: [6, 32, 58] }
  ];

  let ver = 1;
  while (ver < QR_SPEC.length - 1 && bytes.length > QR_SPEC[ver].cap) ver++;
  const spec = QR_SPEC[ver];
  const dataBytes = bytes.slice(0, spec.cap);
  const size = ver * 4 + 17;

  const gfExp = new Uint8Array(512);
  const gfLog = new Uint8Array(256);
  let x = 1;
  for (let i = 0; i < 255; i++) {
    gfExp[i] = x;
    gfLog[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) gfExp[i] = gfExp[i - 255];
  const gfMul = (a, b) => ((a === 0 || b === 0) ? 0 : gfExp[gfLog[a] + gfLog[b]]);

  const rsGenPoly = (deg) => {
    let poly = [1];
    for (let i = 0; i < deg; i++) {
      const next = new Array(poly.length + 1).fill(0);
      const factor = gfExp[i];
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];
        next[j + 1] ^= gfMul(poly[j], factor);
      }
      poly = next;
    }
    return poly;
  };

  const rsCompute = (data, ecLen) => {
    const gen = rsGenPoly(ecLen);
    const res = new Uint8Array(data.length + ecLen);
    res.set(data, 0);
    for (let i = 0; i < data.length; i++) {
      const coef = res[i];
      if (coef !== 0) {
        for (let j = 0; j < gen.length; j++) {
          res[i + j] ^= gfMul(gen[j], coef);
        }
      }
    }
    return Array.from(res.slice(data.length));
  };

  const bits = [];
  const pushBits = (val, len) => {
    for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
  };
  pushBits(0b0100, 4);
  pushBits(dataBytes.length, ver >= 10 ? 16 : 8);
  dataBytes.forEach((b) => pushBits(b, 8));
  const maxDataBits = spec.total * 8;
  const termLen = Math.min(4, maxDataBits - bits.length);
  for (let i = 0; i < termLen; i++) bits.push(0);
  while (bits.length % 8 !== 0) bits.push(0);
  const padBytes = [0xec, 0x11];
  let padIdx = 0;
  while (bits.length < maxDataBits) {
    pushBits(padBytes[padIdx % 2], 8);
    padIdx++;
  }

  const dataCw = [];
  for (let i = 0; i < bits.length; i += 8) {
    let b = 0;
    for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j];
    dataCw.push(b);
  }

  const dataBlocks = [];
  const ecBlocks = [];
  let offset = 0;
  for (let i = 0; i < spec.b1; i++) {
    const blk = dataCw.slice(offset, offset + spec.d1);
    offset += spec.d1;
    dataBlocks.push(blk);
    ecBlocks.push(rsCompute(blk, spec.ec));
  }
  for (let i = 0; i < spec.b2; i++) {
    const blk = dataCw.slice(offset, offset + spec.d2);
    offset += spec.d2;
    dataBlocks.push(blk);
    ecBlocks.push(rsCompute(blk, spec.ec));
  }

  const finalCw = [];
  const maxD = Math.max(spec.d1, spec.d2);
  for (let i = 0; i < maxD; i++) {
    for (let b = 0; b < dataBlocks.length; b++) {
      if (i < dataBlocks[b].length) finalCw.push(dataBlocks[b][i]);
    }
  }
  for (let i = 0; i < spec.ec; i++) {
    for (let b = 0; b < ecBlocks.length; b++) {
      finalCw.push(ecBlocks[b][i]);
    }
  }

  const finalBits = [];
  finalCw.forEach((cw) => {
    for (let i = 7; i >= 0; i--) finalBits.push((cw >>> i) & 1);
  });

  const mat = Array.from({ length: size }, () => new Int8Array(size).fill(-1));
  const isFunc = Array.from({ length: size }, () => new Uint8Array(size));

  const setMod = (r, c, v, func = true) => {
    if (r >= 0 && r < size && c >= 0 && c < size) {
      mat[r][c] = v ? 1 : 0;
      if (func) isFunc[r][c] = 1;
    }
  };

  const drawFinder = (r0, c0) => {
    for (let dr = -1; dr <= 7; dr++) {
      for (let dc = -1; dc <= 7; dc++) {
        const r = r0 + dr;
        const c = c0 + dc;
        if (r < 0 || r >= size || c < 0 || c >= size) continue;
        const inOuter = dr >= 0 && dr <= 6 && dc >= 0 && dc <= 6;
        const onBorder = dr === 0 || dr === 6 || dc === 0 || dc === 6;
        const inInner = dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4;
        setMod(r, c, inOuter && (onBorder || inInner), true);
      }
    }
  };
  drawFinder(0, 0);
  drawFinder(0, size - 7);
  drawFinder(size - 7, 0);

  const alignCoords = spec.align;
  for (let i = 0; i < alignCoords.length; i++) {
    for (let j = 0; j < alignCoords.length; j++) {
      const ar = alignCoords[i];
      const ac = alignCoords[j];
      if ((ar <= 8 && ac <= 8) || (ar <= 8 && ac >= size - 9) || (ar >= size - 9 && ac <= 8)) continue;
      for (let dr = -2; dr <= 2; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          const dark = Math.abs(dr) === 2 || Math.abs(dc) === 2 || (dr === 0 && dc === 0);
          setMod(ar + dr, ac + dc, dark, true);
        }
      }
    }
  }

  for (let i = 8; i < size - 8; i++) {
    if (!isFunc[6][i]) setMod(6, i, i % 2 === 0, true);
    if (!isFunc[i][6]) setMod(i, 6, i % 2 === 0, true);
  }
  setMod(4 * ver + 9, 8, 1, true);

  for (let i = 0; i < 9; i++) {
    if (i !== 6) {
      isFunc[8][i] = 1;
      isFunc[i][8] = 1;
    }
  }
  for (let i = 0; i < 8; i++) {
    isFunc[8][size - 1 - i] = 1;
    isFunc[size - 1 - i][8] = 1;
  }
  if (ver >= 7) {
    for (let i = 0; i < 6; i++) {
      for (let j = 0; j < 3; j++) {
        isFunc[i][size - 11 + j] = 1;
        isFunc[size - 11 + j][i] = 1;
      }
    }
  }

  let bitIdx = 0;
  let up = true;
  for (let c = size - 1; c > 0; c -= 2) {
    if (c === 6) c--;
    for (let rowStep = 0; rowStep < size; rowStep++) {
      const r = up ? (size - 1 - rowStep) : rowStep;
      for (let dc = 0; dc < 2; dc++) {
        const col = c - dc;
        if (!isFunc[r][col]) {
          mat[r][col] = bitIdx < finalBits.length ? finalBits[bitIdx++] : 0;
        }
      }
    }
    up = !up;
  }

  const maskFn = (m, r, c) => {
    switch (m) {
      case 0: return (r + c) % 2 === 0;
      case 1: return r % 2 === 0;
      case 2: return c % 3 === 0;
      case 3: return (r + c) % 3 === 0;
      case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
      case 5: return ((r * c) % 2 + (r * c) % 3) === 0;
      case 6: return (((r * c) % 2 + (r * c) % 3) % 2) === 0;
      default: return (((r + c) % 2 + (r * c) % 3) % 2) === 0;
    }
  };

  const applyFormatAndVersion = (grid, m) => {
    const fmtData = (0b01 << 3) | m;
    let rem = fmtData << 10;
    for (let i = 14; i >= 10; i--) {
      if ((rem >>> i) & 1) rem ^= 0x537 << (i - 10);
    }
    const fmt = ((fmtData << 10) | rem) ^ 0x5412;
    for (let i = 0; i <= 5; i++) grid[8][i] = (fmt >>> (14 - i)) & 1;
    grid[8][7] = (fmt >>> 8) & 1;
    grid[8][8] = (fmt >>> 7) & 1;
    grid[7][8] = (fmt >>> 6) & 1;
    for (let i = 9; i < 15; i++) grid[14 - i][8] = (fmt >>> (14 - i)) & 1;
    for (let i = 0; i < 8; i++) grid[8][size - 1 - i] = (fmt >>> i) & 1;
    for (let i = 0; i < 7; i++) grid[size - 1 - i][8] = (fmt >>> (14 - i)) & 1;

    if (ver >= 7) {
      let vRem = ver << 12;
      for (let i = 17; i >= 12; i--) {
        if ((vRem >>> i) & 1) vRem ^= 0x1f25 << (i - 12);
      }
      const vBits = (ver << 12) | vRem;
      for (let i = 0; i < 18; i++) {
        const bit = (vBits >>> i) & 1;
        grid[Math.floor(i / 3)][size - 11 + (i % 3)] = bit;
        grid[size - 11 + (i % 3)][Math.floor(i / 3)] = bit;
      }
    }
  };

  const scorePenalty = (grid) => {
    let pen = 0;
    for (let r = 0; r < size; r++) {
      let runR = 1;
      let runC = 1;
      for (let i = 1; i < size; i++) {
        runR = grid[r][i] === grid[r][i - 1] ? runR + 1 : 1;
        if (runR === 5) pen += 3; else if (runR > 5) pen += 1;
        runC = grid[i][r] === grid[i - 1][r] ? runC + 1 : 1;
        if (runC === 5) pen += 3; else if (runC > 5) pen += 1;
      }
    }
    return pen;
  };

  let bestGrid = null;
  let bestPen = Infinity;
  for (let m = 0; m < 8; m++) {
    const cand = mat.map((row, r) => row.map((v, c) => (isFunc[r][c] ? v : (v ^ (maskFn(m, r, c) ? 1 : 0)))));
    applyFormatAndVersion(cand, m);
    const p = scorePenalty(cand);
    if (p < bestPen) {
      bestPen = p;
      bestGrid = cand;
    }
  }

  const quiet = 2;
  const vbSize = size + quiet * 2;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${vbSize} ${vbSize}`);
  svg.setAttribute('width', '200');
  svg.setAttribute('height', '200');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'QR Code PIX para pagamento');
  svg.style.display = 'block';
  svg.style.margin = '0 auto';
  svg.style.borderRadius = '12px';
  svg.style.border = '1px solid #d8e1e8';
  svg.style.background = '#ffffff';

  const bg = document.createElementNS(ns, 'rect');
  bg.setAttribute('x', '0');
  bg.setAttribute('y', '0');
  bg.setAttribute('width', String(vbSize));
  bg.setAttribute('height', String(vbSize));
  bg.setAttribute('fill', '#ffffff');
  svg.appendChild(bg);

  let d = '';
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (bestGrid[r][c] === 1) {
        d += `M${c + quiet},${r + quiet}h1v1h-1z`;
      }
    }
  }
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', '#000000');
  svg.appendChild(path);
  return svg;
}

export function pararTimersCheckout() {
  if (checkoutPollTimer) {
    clearInterval(checkoutPollTimer);
    checkoutPollTimer = null;
  }
  if (checkoutExpiryTimer) {
    clearInterval(checkoutExpiryTimer);
    checkoutExpiryTimer = null;
  }
}

export async function abrirModalCheckoutPagamento(orderDbId, metodoPagamento, orderSnapshot = {}, hooks = {}) {
  const modal = document.getElementById('modalCheckoutPagamento');
  if (!modal) return;
  const triggerEl = document.activeElement;
  pararTimersCheckout();

  const { buscarEstadoPedidoReal, atualizarUIStatusPedido } = hooks;

  let metodo = ['pix', 'cartao', 'boleto', 'escrow'].includes(String(metodoPagamento || '').toLowerCase())
    ? String(metodoPagamento).toLowerCase()
    : 'pix';
  const labelsMetodo = {
    pix: 'Pix (Reserva Escrow)',
    cartao: 'Cartão de Crédito/Débito (Checkout Seguro)',
    boleto: 'Boleto Bancário (Escrow)',
    escrow: 'Escrow no Local (Reserva Protegida)'
  };

  const pedidoLabel = document.getElementById('checkoutPedidoLabel');
  const metodoLabel = document.getElementById('checkoutMetodoLabel');
  const valorLabel = document.getElementById('checkoutValorLabel');
  const metodoSelect = document.getElementById('checkoutMetodoSelect');
  const sandboxBanner = document.getElementById('checkoutSandboxBanner');
  const gatewayRow = document.getElementById('checkoutGatewayRow');
  const gatewaySelect = document.getElementById('checkoutGatewaySelect');
  const configNotice = document.getElementById('checkoutConfigNotice');
  const bodyEl = document.getElementById('checkoutBody');
  const statusBox = document.getElementById('checkoutStatusBox');
  const statusText = document.getElementById('checkoutStatusText');
  const expiryText = document.getElementById('checkoutExpiryText');
  const btnSimular = document.getElementById('btnCheckoutSimularSandbox');

  if (pedidoLabel) pedidoLabel.textContent = `Pedido #${orderDbId}`;
  if (metodoLabel) metodoLabel.textContent = labelsMetodo[metodo] || metodo.toUpperCase();
  if (metodoSelect) metodoSelect.value = metodo;
  const precoVal = orderSnapshot && orderSnapshot.preco_total != null
    ? Number(orderSnapshot.preco_total)
    : (store.order && store.order.best && store.order.best.p != null ? Number(store.order.best.p) : 0);
  if (valorLabel) valorLabel.textContent = brl(precoVal);

  const fechar = () => {
    pararTimersCheckout();
    modal.style.display = 'none';
    document.removeEventListener('keydown', onKeyDown);
    if (triggerEl && typeof triggerEl.focus === 'function') triggerEl.focus();
  };
  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      fechar();
    }
  };

  modal.style.display = 'flex';
  document.addEventListener('keydown', onKeyDown);
  const btnFecharTopo = document.getElementById('btnFecharModalCheckout');
  const btnFecharRodape = document.getElementById('btnFecharCheckoutRodape');
  if (btnFecharTopo) btnFecharTopo.onclick = fechar;
  if (btnFecharRodape) btnFecharRodape.onclick = fechar;
  modal.onclick = (e) => { if (e.target === modal) fechar(); };
  if (btnFecharTopo) setTimeout(() => btnFecharTopo.focus(), 0);

  const sincronizarPedidoAposPagamento = async () => {
    if (typeof buscarEstadoPedidoReal === 'function' && typeof atualizarUIStatusPedido === 'function') {
      const updated = await buscarEstadoPedidoReal(orderDbId);
      if (updated && store.order && store.order.best) {
        atualizarUIStatusPedido(updated, store.order.best);
      }
    }
    if (qs('#pay')) qs('#pay').hidden = true;
  };

  let configData = null;
  const carregarConfig = async () => {
    if (configData) return configData;
    try {
      const cfgRes = await fetch('/api/payments/config');
      if (cfgRes.ok) configData = await cfgRes.json();
    } catch (_) {
      configData = null;
    }
    return configData;
  };

  const atualizarStatusCheckout = async (payData) => {
    const st = String((payData && payData.status) || 'pending').toLowerCase();
    const isTerminalSuccess = ['paid', 'escrow_held', 'released'].includes(st);
    const isTerminalFail = ['failed', 'expired', 'cancelled', 'refunded'].includes(st);

    if (statusBox) statusBox.hidden = false;
    if (statusText) {
      if (isTerminalSuccess) {
        statusText.textContent = 'Pagamento confirmado! Valor retido em Escrow.';
      } else if (st === 'failed') {
        statusText.textContent = 'Pagamento recusado ou falhou.';
      } else if (st === 'expired') {
        statusText.textContent = 'Cobrança expirada. Feche e tente novamente.';
      } else if (st === 'cancelled') {
        statusText.textContent = 'Pagamento cancelado.';
      } else {
        statusText.textContent = 'Aguardando confirmação do pagamento...';
      }
    }

    if (isTerminalSuccess) {
      pararTimersCheckout();
      if (btnSimular) btnSimular.hidden = true;
      await sincronizarPedidoAposPagamento();
      toast('Pagamento confirmado e protegido em Escrow!');
      return true;
    }
    if (isTerminalFail) {
      pararTimersCheckout();
      if (btnSimular) btnSimular.hidden = true;
      return true;
    }
    return false;
  };

  const renderizarIntent = async (data) => {
    if (!bodyEl) return;
    bodyEl.replaceChildren();
    const gw = String(data.gateway || '').toLowerCase();
    if (sandboxBanner) sandboxBanner.hidden = gw !== 'sandbox';

    if (data.expires_at && expiryText) {
      const expDate = new Date(String(data.expires_at).replace(' ', 'T'));
      const atualizarExp = () => {
        if (isNaN(expDate.getTime())) {
          expiryText.textContent = `Expira: ${String(data.expires_at)}`;
          return;
        }
        const diffSec = Math.max(0, Math.floor((expDate.getTime() - Date.now()) / 1000));
        const min = Math.floor(diffSec / 60);
        const sec = diffSec % 60;
        expiryText.textContent = diffSec > 0 ? `Expira em ${min}m ${String(sec).padStart(2, '0')}s` : 'Expirado';
      };
      atualizarExp();
      if (checkoutExpiryTimer) clearInterval(checkoutExpiryTimer);
      checkoutExpiryTimer = setInterval(atualizarExp, 1000);
    }

    if (metodo === 'pix') {
      const pixCode = String(data.pix_qr_code || '');
      const qrWrapper = document.createElement('div');
      qrWrapper.className = 'p-3 rounded-xl bg-white border border-perto-road text-center space-y-2';
      const rawB64 = typeof data.pix_qr_base64 === 'string' ? data.pix_qr_base64.trim() : '';
      if (rawB64 && /^[A-Za-z0-9+/=\s]+$/.test(rawB64)) {
        const cleanB64 = rawB64.replace(/\s+/g, '');
        const img = document.createElement('img');
        img.src = `data:image/png;base64,${cleanB64}`;
        img.alt = 'QR Code PIX';
        img.className = 'w-44 h-44 mx-auto rounded-lg';
        qrWrapper.appendChild(img);
      } else {
        qrWrapper.appendChild(criarSvgQrDeterministico(pixCode));
      }

      const lbl = document.createElement('label');
      lbl.className = 'block text-left text-[11px] font-bold text-perto-ink uppercase tracking-wider mt-2';
      lbl.setAttribute('for', 'checkoutPixCopiaCola');
      lbl.textContent = 'Pix Copia e Cola';
      qrWrapper.appendChild(lbl);

      const row = document.createElement('div');
      row.className = 'flex gap-2 items-center';
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.id = 'checkoutPixCopiaCola';
      inp.readOnly = true;
      inp.className = 'input-form text-xs font-mono flex-1';
      inp.value = pixCode;
      row.appendChild(inp);

      const btnCopy = document.createElement('button');
      btnCopy.type = 'button';
      btnCopy.className = 'btn px-3.5 py-2 rounded-full text-xs font-extrabold text-perto-ink shrink-0';
      btnCopy.textContent = 'Copiar código PIX';
      btnCopy.onclick = () => copiarTextoSeguro(pixCode, 'Código PIX copiado!');
      row.appendChild(btnCopy);

      qrWrapper.appendChild(row);
      bodyEl.appendChild(qrWrapper);
    } else if (metodo === 'cartao') {
      const cardBox = document.createElement('div');
      cardBox.className = 'p-3.5 rounded-xl bg-white border border-perto-road space-y-2.5';
      const pInfo = document.createElement('p');
      pInfo.className = 'm-0 text-xs text-perto-ink/85';
      pInfo.textContent = 'Por segurança PCI, os dados do cartão são inseridos apenas no ambiente hospedado do provedor.';
      cardBox.appendChild(pInfo);

      const safeCheckoutUrl = sanitizeSafeUrl(data.checkout_url);
      if (safeCheckoutUrl && gw !== 'sandbox') {
        const link = document.createElement('a');
        link.href = safeCheckoutUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'btn px-4 py-2.5 rounded-full text-xs font-extrabold text-perto-ink inline-flex items-center gap-1.5 no-underline';
        link.textContent = 'Abrir Checkout Seguro do Cartão';
        cardBox.appendChild(link);
      } else if (gw === 'sandbox') {
        const pSbx = document.createElement('p');
        pSbx.className = 'm-0 text-xs font-semibold text-perto-sea';
        pSbx.textContent = 'No ambiente Sandbox, utilize o botão abaixo para simular a aprovação do cartão.';
        cardBox.appendChild(pSbx);
      }
      bodyEl.appendChild(cardBox);
    } else if (metodo === 'boleto') {
      const bolBox = document.createElement('div');
      bolBox.className = 'p-3.5 rounded-xl bg-white border border-perto-road space-y-2.5';

      const digitable = String(data.boleto_digitable_line || data.boleto_barcode || '');
      const lbl = document.createElement('label');
      lbl.className = 'block text-[11px] font-bold text-perto-ink uppercase tracking-wider';
      lbl.setAttribute('for', 'checkoutBoletoLinha');
      lbl.textContent = 'Linha Digitável do Boleto';
      bolBox.appendChild(lbl);

      const row = document.createElement('div');
      row.className = 'flex gap-2 items-center';
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.id = 'checkoutBoletoLinha';
      inp.readOnly = true;
      inp.className = 'input-form text-xs font-mono flex-1';
      inp.value = digitable;
      row.appendChild(inp);

      const btnCopy = document.createElement('button');
      btnCopy.type = 'button';
      btnCopy.className = 'btn px-3.5 py-2 rounded-full text-xs font-extrabold text-perto-ink shrink-0';
      btnCopy.textContent = 'Copiar linha';
      btnCopy.onclick = () => copiarTextoSeguro(digitable, 'Linha digitável copiada!');
      row.appendChild(btnCopy);
      bolBox.appendChild(row);

      const safeBolUrl = sanitizeSafeUrl(data.boleto_url);
      if (safeBolUrl) {
        const link = document.createElement('a');
        link.href = safeBolUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'btn2 px-4 py-2 rounded-full text-xs font-bold inline-flex items-center gap-1.5 no-underline';
        link.textContent = 'Visualizar Boleto Bancário';
        bolBox.appendChild(link);
      }
      bodyEl.appendChild(bolBox);
    }

    const paymentId = data.payment_id || data.id;
    const settled = await atualizarStatusCheckout(data);

    if (btnSimular) {
      btnSimular.hidden = !(gw === 'sandbox' && !settled && paymentId);
      btnSimular.disabled = false;
      btnSimular.onclick = async () => {
        btnSimular.disabled = true;
        try {
          const confRes = await fetch(`/api/payments/${encodeURIComponent(paymentId)}/confirm`, {
            method: 'POST',
            headers: csrfHeaders({
              'Content-Type': 'application/json',
              'Idempotency-Key': gerarIdempotencyKey()
            }),
            body: JSON.stringify({ simulate_outcome: 'paid' })
          });
          const confData = await confRes.json().catch(() => ({}));
          if (!confRes.ok) {
            toast(confData.error || 'Falha ao confirmar pagamento Sandbox.');
            btnSimular.disabled = false;
            return;
          }
          await atualizarStatusCheckout(confData);
        } catch (_) {
          toast('Erro de comunicação ao confirmar pagamento Sandbox.');
          btnSimular.disabled = false;
        }
      };
    }

    if (!settled && paymentId) {
      if (checkoutPollTimer) clearInterval(checkoutPollTimer);
      checkoutPollTimer = setInterval(async () => {
        if (modal.style.display === 'none') {
          pararTimersCheckout();
          return;
        }
        try {
          const pollRes = await fetch(`/api/payments/${encodeURIComponent(paymentId)}`);
          if (!pollRes.ok) return;
          const pollData = await pollRes.json();
          await atualizarStatusCheckout(pollData);
        } catch (_) {}
      }, 4000);
    }
  };

  const buscarIntentAtivaExistente = async (gatewayId) => {
    try {
      const ordRes = await fetch(`/api/payments/order/${encodeURIComponent(orderDbId)}`);
      if (!ordRes.ok) return null;
      const ordData = await ordRes.json();
      const txs = Array.isArray(ordData.transactions) ? ordData.transactions : [];
      const agora = Date.now();
      return txs.find((tx) => {
        if (!tx) return false;
        const st = String(tx.status || '').toLowerCase();
        if (st !== 'pending' && st !== 'requires_action') return false;
        if (String(tx.method || '').toLowerCase() !== metodo) return false;
        if (String(tx.gateway || '').toLowerCase() !== String(gatewayId || '').toLowerCase()) return false;
        if (tx.expires_at) {
          const expMs = new Date(String(tx.expires_at).replace(' ', 'T')).getTime();
          if (!isNaN(expMs) && expMs <= agora) return false;
        }
        return true;
      }) || null;
    } catch (_) {
      return null;
    }
  };

  const iniciarIntent = async (gatewayId) => {
    pararTimersCheckout();
    if (btnSimular) btnSimular.hidden = true;
    if (bodyEl) {
      const pCheck = document.createElement('p');
      pCheck.className = 'text-perto-ink/70 m-0';
      pCheck.textContent = 'Verificando cobrança existente...';
      bodyEl.replaceChildren(pCheck);
    }

    const existingIntent = await buscarIntentAtivaExistente(gatewayId);
    if (existingIntent) {
      await renderizarIntent(existingIntent);
      return;
    }

    if (bodyEl) {
      const pGen = document.createElement('p');
      pGen.className = 'text-perto-ink/70 m-0';
      pGen.textContent = 'Gerando cobrança segura...';
      bodyEl.replaceChildren(pGen);
    }
    try {
      const res = await fetch('/api/payments/intents', {
        method: 'POST',
        headers: csrfHeaders({
          'Content-Type': 'application/json',
          'Idempotency-Key': gerarIdempotencyKey()
        }),
        body: JSON.stringify({
          order_id: Number(orderDbId),
          method: metodo,
          gateway: gatewayId
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (bodyEl) {
          const errP = document.createElement('p');
          errP.className = 'm-0 text-red-700 font-semibold';
          errP.textContent = data.error || `Erro ao iniciar pagamento (HTTP ${res.status}).`;
          bodyEl.replaceChildren(errP);
        }
        return;
      }
      await renderizarIntent(data);
    } catch (_) {
      if (bodyEl) {
        const commErrP = document.createElement('p');
        commErrP.className = 'm-0 text-red-700 font-semibold';
        commErrP.textContent = 'Erro de comunicação ao iniciar checkout.';
        bodyEl.replaceChildren(commErrP);
      }
    }
  };

  const iniciarFluxoMetodoAtual = async () => {
    pararTimersCheckout();
    if (metodoLabel) metodoLabel.textContent = labelsMetodo[metodo] || metodo.toUpperCase();
    if (sandboxBanner) sandboxBanner.hidden = true;
    if (gatewayRow) gatewayRow.hidden = true;
    if (configNotice) { configNotice.hidden = true; configNotice.textContent = ''; }
    if (statusBox) statusBox.hidden = true;
    if (expiryText) expiryText.textContent = '';
    if (btnSimular) btnSimular.hidden = true;

    if (metodo === 'escrow') {
      if (bodyEl) {
        bodyEl.replaceChildren();
        const box = document.createElement('div');
        box.className = 'p-3.5 rounded-xl bg-white border border-perto-road space-y-2.5';
        const pInfo = document.createElement('p');
        pInfo.className = 'm-0 text-xs text-perto-ink/85';
        pInfo.textContent = 'Confirme a reserva do valor em Escrow no Local ou altere a forma de pagamento acima para Pix, Cartão ou Boleto.';
        box.appendChild(pInfo);

        const btnEscrow = document.createElement('button');
        btnEscrow.type = 'button';
        btnEscrow.className = 'btn px-4 py-2.5 rounded-full text-xs font-extrabold text-perto-ink';
        btnEscrow.textContent = 'Confirmar Reserva em Escrow';
        btnEscrow.onclick = async () => {
          btnEscrow.disabled = true;
          try {
            const resPay = await fetch(`/api/orders/${encodeURIComponent(orderDbId)}/pay`, {
              method: 'POST',
              headers: csrfHeaders({ 'Content-Type': 'application/json' }),
              body: JSON.stringify({
                escrow_hold: Boolean(!orderSnapshot || String(orderSnapshot.status || '').toLowerCase() !== 'finalizado'),
                metodo_pagamento: 'escrow'
              })
            });
            const payData = await resPay.json().catch(() => ({}));
            if (!resPay.ok) {
              toast(payData.error || 'Não foi possível confirmar pagamento em Escrow.');
              btnEscrow.disabled = false;
              return;
            }
            await sincronizarPedidoAposPagamento();
            toast(payData.message || 'Pagamento retido em Escrow com segurança.');
            fechar();
          } catch (_) {
            toast('Erro de comunicação ao confirmar Escrow.');
            btnEscrow.disabled = false;
          }
        };
        box.appendChild(btnEscrow);
        bodyEl.appendChild(box);
      }
      return;
    }

    if (bodyEl) {
      const pLoad = document.createElement('p');
      pLoad.className = 'text-perto-ink/70 m-0';
      pLoad.textContent = 'Carregando configuração de pagamento...';
      bodyEl.replaceChildren(pLoad);
    }
    const cfg = await carregarConfig();
    if (!cfg || !Array.isArray(cfg.gateways)) {
      if (configNotice) {
        configNotice.textContent = 'Não foi possível carregar os provedores de pagamento. Tente novamente.';
        configNotice.hidden = false;
      }
      if (bodyEl) bodyEl.replaceChildren();
      return;
    }

    const configuredGateways = cfg.gateways.filter((g) => g && g.configured && (!Array.isArray(g.methods) || g.methods.includes(metodo)));
    if (!configuredGateways.length) {
      if (configNotice) {
        configNotice.textContent = 'Nenhum gateway de pagamento (nem Sandbox) está configurado para este método no momento.';
        configNotice.hidden = false;
      }
      if (bodyEl) bodyEl.replaceChildren();
      return;
    }

    let selectedGateway = cfg.default_gateway && configuredGateways.some((g) => g.id === cfg.default_gateway)
      ? cfg.default_gateway
      : configuredGateways[0].id;

    if (gatewaySelect && gatewayRow) {
      gatewaySelect.replaceChildren();
      configuredGateways.forEach((gw) => {
        const opt = document.createElement('option');
        opt.value = gw.id;
        opt.textContent = gw.name || gw.id;
        if (gw.id === selectedGateway) opt.selected = true;
        gatewaySelect.appendChild(opt);
      });
      gatewayRow.hidden = configuredGateways.length <= 1;
      gatewaySelect.onchange = () => {
        selectedGateway = gatewaySelect.value;
        iniciarIntent(selectedGateway);
      };
    }

    await iniciarIntent(selectedGateway);
  };

  if (metodoSelect) {
    metodoSelect.onchange = () => {
      metodo = metodoSelect.value;
      iniciarFluxoMetodoAtual();
    };
  }

  await iniciarFluxoMetodoAtual();
}
