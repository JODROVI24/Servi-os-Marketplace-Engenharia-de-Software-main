// scripts/check_xss_lint.js - Auditoria estática anti-XSS nos scripts do frontend
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..');
const TARGET_DIRS = [
  path.join(REPO_ROOT, 'public'),
  path.join(REPO_ROOT, 'public', 'js')
];

function collectJsFiles() {
  const files = [];
  for (const dir of TARGET_DIRS) {
    if (!fs.existsSync(dir)) continue;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isFile() && entry.name.endsWith('.js')) {
        files.push(path.join(dir, entry.name));
      }
    }
  }
  return files.sort();
}

function getLineNumber(text, idx) {
  let line = 1;
  for (let i = 0; i < idx && i < text.length; i += 1) {
    if (text[i] === '\n') line += 1;
  }
  return line;
}

function stripOuterParens(expr) {
  let s = expr.trim();
  while (s.startsWith('(') && s.endsWith(')')) {
    let depth = 0;
    let wrapsAll = true;
    for (let i = 0; i < s.length; i += 1) {
      const ch = s[i];
      if (ch === '\\') { i += 1; continue; }
      if (ch === "'" || ch === '"') {
        const q = ch;
        i += 1;
        while (i < s.length && s[i] !== q) {
          if (s[i] === '\\') i += 1;
          i += 1;
        }
        continue;
      }
      if (ch === '`') {
        const nested = extractTemplateInterpolations(s, i);
        i = nested.endIdx;
        continue;
      }
      if (ch === '(') depth += 1;
      else if (ch === ')') {
        depth -= 1;
        if (depth === 0 && i < s.length - 1) {
          wrapsAll = false;
          break;
        }
      }
    }
    if (!wrapsAll) break;
    s = s.slice(1, -1).trim();
  }
  return s;
}

function splitTopLevelTernary(expr) {
  let depth = 0;
  let qIdx = -1;
  let ternaryDepth = 0;
  for (let i = 0; i < expr.length; i += 1) {
    const ch = expr[i];
    if (ch === '\\') { i += 1; continue; }
    if (ch === "'" || ch === '"') {
      const q = ch;
      i += 1;
      while (i < expr.length && expr[i] !== q) {
        if (expr[i] === '\\') i += 1;
        i += 1;
      }
      continue;
    }
    if (ch === '`') {
      const nested = extractTemplateInterpolations(expr, i);
      i = nested.endIdx;
      continue;
    }
    if (ch === '(' || ch === '[' || ch === '{') {
      depth += 1;
      continue;
    }
    if (ch === ')' || ch === ']' || ch === '}') {
      depth = Math.max(0, depth - 1);
      continue;
    }
    if (depth === 0) {
      if (ch === '?') {
        if (expr[i + 1] === '?' || expr[i + 1] === '.') {
          i += 1;
          continue;
        }
        if (qIdx === -1) qIdx = i;
        ternaryDepth += 1;
      } else if (ch === ':' && qIdx !== -1) {
        ternaryDepth -= 1;
        if (ternaryDepth === 0) {
          return {
            cond: expr.slice(0, qIdx).trim(),
            whenTrue: expr.slice(qIdx + 1, i).trim(),
            whenFalse: expr.slice(i + 1).trim()
          };
        }
      }
    }
  }
  return null;
}

function isSimpleSafeLiteral(expr) {
  if (/^'([^'\\]|\\[\s\S])*'$/.test(expr)) return true;
  if (/^"([^"\\]|\\[\s\S])*"$/.test(expr)) return true;
  if (/^-?\d+(\.\d+)?$/.test(expr)) return true;
  if (/^(true|false|null|undefined)$/.test(expr)) return true;
  return false;
}

function isSafeExpression(expr) {
  const trimmed = stripOuterParens(expr);
  if (!trimmed) return true;
  if (isSimpleSafeLiteral(trimmed)) return true;

  // Chamadas explicitamente seguras ou numéricas
  const directSafePatterns = [
    /^(window\.)?escapeHtml\s*\(/,
    /^(window\.)?sanitizarUrlSegura\s*\(/,
    /^formatarStatusModeracaoHtml\s*\(/,
    /^encodeURIComponent\s*\(/,
    /^Number\s*\(/,
    /^brl\s*\(\s*Number\s*\(/,
    /^Math\.(round|floor|ceil|max|min)\s*\(/,
    /^Number\([^)]+\)\.toFixed\s*\(/,
    /^(Number|Math\.max|Math\.min)\([^)]+\).*\.toFixed\s*\(/
  ];
  if (directSafePatterns.some((re) => re.test(trimmed))) {
    return true;
  }

  // Expressões simples seguras (variáveis *Html / payHref / mapHref pré-sanitizadas)
  if (/^[a-zA-Z0-9_$.]+Html$/.test(trimmed)) return true;
  if (/^(payHref|mapHref)$/.test(trimmed)) return true;
  if (/^Number\([a-zA-Z0-9_$.]+\)\s*\*\s*[\d.]+$/.test(trimmed)) return true;

  // Expressões ternárias balanceadas onde AMBOS os ramos são literais seguros, templates seguros ou sub-expressões seguras
  const ternary = splitTopLevelTernary(trimmed);
  if (ternary) {
    return isSafeExpression(ternary.whenTrue) && isSafeExpression(ternary.whenFalse);
  }

  // Template string segura (todas as interpolações internas precisam ser seguras)
  if (trimmed.startsWith('`') && trimmed.endsWith('`')) {
    const parsed = extractTemplateInterpolations(trimmed, 0);
    if (parsed.endIdx === trimmed.length - 1) {
      return parsed.interpolations.every((item) => isSafeExpression(item));
    }
  }

  return false;
}

function extractTemplateInterpolations(src, startQuoteIdx) {
  const interpolations = [];
  let i = startQuoteIdx + 1;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '\\') {
      i += 2;
      continue;
    }
    if (ch === '`') {
      return { endIdx: i, interpolations };
    }
    if (ch === '$' && src[i + 1] === '{') {
      let depth = 1;
      let j = i + 2;
      const exprStart = j;
      while (j < src.length && depth > 0) {
        const c = src[j];
        if (c === '\\') { j += 2; continue; }
        if (c === "'" || c === '"') {
          const q = c;
          j += 1;
          while (j < src.length && src[j] !== q) {
            if (src[j] === '\\') j += 2;
            else j += 1;
          }
          j += 1;
          continue;
        }
        if (c === '`') {
          const nested = extractTemplateInterpolations(src, j);
          j = nested.endIdx + 1;
          continue;
        }
        if (c === '{') depth += 1;
        else if (c === '}') depth -= 1;
        j += 1;
      }
      interpolations.push(src.slice(exprStart, j - 1));
      i = j;
      continue;
    }
    i += 1;
  }
  return { endIdx: src.length - 1, interpolations };
}

function scanFile(filePath) {
  const rel = path.relative(REPO_ROOT, filePath).replace(/\\/g, '/');
  const content = fs.readFileSync(filePath, 'utf-8');
  const violations = [];

  // 1. Sinks perigosos banidos
  const bannedPatterns = [
    { re: /\beval\s*\(/g, msg: 'Uso proibido de eval()' },
    { re: /\bnew\s+Function\s*\(/g, msg: 'Uso proibido de new Function()' },
    { re: /\bdocument\.write(ln)?\s*\(/g, msg: 'Uso proibido de document.write()' },
    { re: /\.outerHTML\s*=/g, msg: 'Uso proibido de outerHTML' },
    { re: /\.insertAdjacentHTML\s*\(/g, msg: 'Uso proibido de insertAdjacentHTML()' },
    { re: /on(?:click|change|submit|blur|keydown|keyup|error|load)\s*=\s*["'][^"']*["']/gi, msg: 'Handler inline HTML detectado em string JS' },
    { re: /\bjavascript\s*:\s*[^'")\s]/gi, msg: 'Esquema javascript: potencialmente inseguro' }
  ];

  // Em auth.js/script.js/cadastro.js/login.js permitimos a regex de bloqueio /^(javascript|...)/i
  for (const rule of bannedPatterns) {
    rule.re.lastIndex = 0;
    let m;
    while ((m = rule.re.exec(content)) !== null) {
      /* eslint-disable-next-line no-script-url -- literal usada na detecção estática de URLs perigosas */
      if (rule.msg.includes('javascript:') && /\/\^\(javascript\|/.test(content.slice(Math.max(0, m.index - 20), m.index + 30))) {
        continue;
      }
      violations.push(`${rel}:${getLineNumber(content, m.index)} - ${rule.msg}: ${m[0]}`);
    }
  }

  // 2. Verificar todas as atribuições a .innerHTML e variáveis *Html, plus bindPopup/bindTooltip
  const htmlSinkRe = /(?:\.innerHTML\s*=|\b[a-zA-Z0-9_]*Html\s*\+?=|\.(?:bindPopup|bindTooltip)\s*\()/g;
  let sinkMatch;
  while ((sinkMatch = htmlSinkRe.exec(content)) !== null) {
    let cursor = sinkMatch.index + sinkMatch[0].length;
    while (cursor < content.length && /\s/.test(content[cursor])) cursor += 1;

    // Se atribuído concatenando com string e + variável não-escapada em .innerHTML =
    if (sinkMatch[0].includes('innerHTML') && (content[cursor] === "'" || content[cursor] === '"')) {
      const q = content[cursor];
      let j = cursor + 1;
      while (j < content.length && content[j] !== q) {
        if (content[j] === '\\') j += 2;
        else j += 1;
      }
      let afterStr = j + 1;
      while (afterStr < content.length && /\s/.test(content[afterStr])) afterStr += 1;
      if (content[afterStr] === '+') {
        violations.push(`${rel}:${getLineNumber(content, sinkMatch.index)} - Concatenação direta em .innerHTML =`);
      }
      continue;
    }

    // Se atribuído diretamente a variável/parâmetro sem ser array.map(...)`
    if (sinkMatch[0].includes('innerHTML') && /[a-zA-Z_$]/.test(content[cursor] || '')) {
      const restLine = content.slice(cursor, content.indexOf('\n', cursor));
      const allowedRhs = /^(escapeHtml\(|minhaHtml\s*\+\s*contraHtml|v\.length\s*\?|[\[\]a-zA-Z0-9_$.]+\.map\s*\()/;
      if (!allowedRhs.test(restLine.trim()) && !/^(['"`])/.test(restLine.trim())) {
        violations.push(`${rel}:${getLineNumber(content, sinkMatch.index)} - Atribuição dinâmica em .innerHTML = (${restLine.trim().slice(0, 60)})`);
      }
    }

    // Scan template literals dentro da instrução completa (até ; de nível raiz)
    let endStmt = cursor;
    let paren = 0;
    let brace = 0;
    while (endStmt < content.length) {
      const ch = content[endStmt];
      if (ch === "'" || ch === '"') {
        const q = ch;
        endStmt += 1;
        while (endStmt < content.length && content[endStmt] !== q) {
          if (content[endStmt] === '\\') endStmt += 2;
          else endStmt += 1;
        }
        endStmt += 1;
        continue;
      }
      if (ch === '`') {
        const resTpl = extractTemplateInterpolations(content, endStmt);
        for (const expr of resTpl.interpolations) {
          if (!isSafeExpression(expr)) {
            violations.push(
              `${rel}:${getLineNumber(content, endStmt)} - Interpolação não sanitizada em HTML template: \${${expr.trim().slice(0, 80)}}`
            );
          }
        }
        endStmt = resTpl.endIdx + 1;
        continue;
      }
      if (ch === '(') paren += 1;
      else if (ch === ')') {
        if (paren === 0 && sinkMatch[0].includes('bind')) break;
        paren = Math.max(0, paren - 1);
      } else if (ch === '{') brace += 1;
      else if (ch === '}') brace = Math.max(0, brace - 1);
      else if (ch === ';' && paren === 0 && brace === 0) break;
      endStmt += 1;
    }
  }

  return violations;
}

function main() {
  const files = collectJsFiles();
  if (!files.length) {
    console.error('Nenhum arquivo JS encontrado em public/.');
    process.exit(1);
  }
  const allViolations = [];
  for (const file of files) {
    allViolations.push(...scanFile(file));
  }
  if (allViolations.length) {
    console.error(`XSS lint falhou (${allViolations.length} violação(ões)):`);
    for (const v of allViolations) console.error(`  - ${v}`);
    process.exit(1);
  }
  console.log(`XSS lint OK (${files.length} arquivos JS verificados, 0 violações).`);
}

main();
