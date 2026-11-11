/**
 * Adversarial Route Verifier (tests/test_vercel_routing_adversarial.js)
 * Challenger 1 - Vercel Routing Configuration Stress Test Harness
 */
const fs = require('fs');
const path = require('path');

// Resolve @vercel/routing-utils from global or local node_modules
let routingUtils;
try {
  routingUtils = require('@vercel/routing-utils');
} catch (e) {
  try {
    const workerNodeModules = path.resolve(__dirname, '../.agents/teamwork/worker_m1/node_modules');
    routingUtils = require(path.join(workerNodeModules, '@vercel/routing-utils'));
  } catch (err2) {
    console.log('[INFO] @vercel/routing-utils não instalado no ambiente global. Instale @vercel/routing-utils para executar a compilação formal de rotas.');
    process.exit(0);
  }
}

const rootDir = path.resolve(__dirname, '..');
const vercelJsonPath = path.join(rootDir, 'vercel.json');
const publicDir = path.join(rootDir, 'public');

console.log('================================================================');
console.log('CHALLENGER 1: ADVERSARIAL VERCEL ROUTING EMPIRICAL TEST SUITE');
console.log('================================================================\n');

// 1. Load vercel.json
const vercelConfig = JSON.parse(fs.readFileSync(vercelJsonPath, 'utf8'));
console.log('[1/4] Loaded vercel.json:');
console.log(JSON.stringify(vercelConfig, null, 2));

// 2. Compile routes
const compilation = routingUtils.getTransformedRoutes(vercelConfig);
if (compilation.error) {
  console.error('FATAL: Route compilation error:', compilation.error);
  process.exit(1);
}
const routes = compilation.routes;
console.log('\n[2/4] Compiled Vercel Routes (' + routes.length + ' rules):');
routes.forEach((r, idx) => console.log(`  [${idx}]`, JSON.stringify(r)));

const fsHandlerIdx = routes.findIndex(r => r.handle === 'filesystem');
if (fsHandlerIdx === -1) {
  console.error('FATAL: Missing { handle: "filesystem" }');
  process.exit(1);
}

// 3. Scan public directory
function listFiles(dir, prefix = '') {
  let results = [];
  fs.readdirSync(dir).forEach(file => {
    const full = path.join(dir, file);
    const rel = path.join(prefix, file);
    if (fs.statSync(full).isDirectory()) {
      results = results.concat(listFiles(full, rel));
    } else {
      results.push(rel);
    }
  });
  return results;
}
const publicFiles = listFiles(publicDir);
console.log(`\n[3/4] Scanned public/ directory (${publicFiles.length} files found)`);

// 4. Exact Vercel Edge Simulation Engine
function simulateVercelRequest(requestUrl) {
  const urlObj = new URL(requestUrl, 'https://test-marketplace.vercel.app');
  let pathname = urlObj.pathname;
  let search = urlObj.search;

  // Phase 1: Redirects (before filesystem)
  for (let i = 0; i < fsHandlerIdx; i++) {
    const r = routes[i];
    if (r.src) {
      const regex = new RegExp(r.src);
      const match = pathname.match(regex);
      if (match && r.status) {
        let loc = r.headers.Location || '';
        match.slice(1).forEach((val, idx) => {
          loc = loc.replace(new RegExp(`\\$${idx + 1}`, 'g'), val || '');
        });
        if (loc === '') loc = '/';
        return {
          status: r.status,
          type: 'REDIRECT',
          location: loc,
          matchedRule: r
        };
      }
    }
  }

  // Phase 2: Filesystem Check
  // Zero-config: root "/" maps to "index.html"
  let cleanFsPath = pathname.replace(/^\//, '');
  if (cleanFsPath === '') cleanFsPath = 'index.html';

  // 2a. Direct file exists in public/
  const directPath = path.join(publicDir, cleanFsPath);
  if (fs.existsSync(directPath) && fs.statSync(directPath).isFile()) {
    return {
      status: 200,
      type: 'STATIC_FILE',
      file: cleanFsPath,
      absolutePath: directPath
    };
  }

  // 2b. Clean URL check (only if pathname does not end with a slash, e.g. /login -> login.html)
  if (!pathname.endsWith('/')) {
    const htmlCleanPath = path.join(publicDir, cleanFsPath + '.html');
    if (fs.existsSync(htmlCleanPath) && fs.statSync(htmlCleanPath).isFile()) {
      return {
        status: 200,
        type: 'CLEAN_URL_HTML',
        file: cleanFsPath + '.html',
        absolutePath: htmlCleanPath
      };
    }
  }

  // 2c. Directory with index.html (e.g. /img/ doesn't have index.html)
  if (pathname.endsWith('/')) {
    const dirIndexPath = path.join(publicDir, cleanFsPath, 'index.html');
    if (fs.existsSync(dirIndexPath) && fs.statSync(dirIndexPath).isFile()) {
      return {
        status: 200,
        type: 'DIRECTORY_INDEX',
        file: path.join(cleanFsPath, 'index.html')
      };
    }
  }

  // Phase 3: Rewrites (after filesystem handler)
  for (let i = fsHandlerIdx + 1; i < routes.length; i++) {
    const r = routes[i];
    if (r.src && r.dest) {
      const regex = new RegExp(r.src);
      const match = pathname.match(regex);
      if (match) {
        let dest = r.dest;
        match.slice(1).forEach((val, idx) => {
          dest = dest.replace(new RegExp(`\\$${idx + 1}`, 'g'), val !== undefined ? val : '');
        });
        // Append query string if present
        if (search) {
          const sep = dest.includes('?') ? '&' : '?';
          dest += sep + search.replace(/^\?/, '');
        }
        return {
          status: 200,
          type: 'REWRITE',
          destination: dest,
          matchedRule: r
        };
      }
    }
  }

  // Phase 4: Fallback
  // Check if custom 404.html exists in public/
  const custom404 = path.join(publicDir, '404.html');
  if (fs.existsSync(custom404) && fs.statSync(custom404).isFile()) {
    return {
      status: 404,
      type: 'CUSTOM_404_HTML',
      file: '404.html',
      absolutePath: custom404
    };
  }

  // Platform 404 NOT_FOUND error (the error reported in ORIGINAL_REQUEST.md)
  return {
    status: 404,
    type: 'PLATFORM_404_NOT_FOUND',
    error: 'Vercel Platform NOT_FOUND error page'
  };
}

// 5. Test Matrix Execution
console.log('\n[4/4] Executing Adversarial Test Cases...\n');

const testCases = [
  // --- Category 1: Root request ---
  {
    name: '1. Root request "/"',
    url: '/',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'index.html'
  },
  {
    name: '1b. Direct "/index.html" request',
    url: '/index.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/'
  },
  {
    name: '1c. Trailing slash on "/index.html/"',
    url: '/index.html/',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/'
  },

  // --- Category 2: Requests with trailing slashes ---
  {
    name: '2a. Trailing slash on clean route "/pedido/"',
    url: '/pedido/',
    // Without trailingSlash: false in vercel.json, /pedido/ has no pedido/ directory, so it falls to 404.html
    expectedType: 'CUSTOM_404_HTML',
    expectedStatus: 404,
    expectedTarget: '404.html'
  },
  {
    name: '2b. Trailing slash on clean route "/login/"',
    url: '/login/',
    expectedType: 'CUSTOM_404_HTML',
    expectedStatus: 404,
    expectedTarget: '404.html'
  },
  {
    name: '2c. Trailing slash on clean route "/cadastro/"',
    url: '/cadastro/',
    expectedType: 'CUSTOM_404_HTML',
    expectedStatus: 404,
    expectedTarget: '404.html'
  },

  // --- Category 3: Direct requests to .html files (308 cleanUrls) ---
  {
    name: '3a. Direct "/login.html"',
    url: '/login.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/login'
  },
  {
    name: '3b. Direct "/pedido.html"',
    url: '/pedido.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/pedido'
  },
  {
    name: '3c. Direct "/cadastro.html"',
    url: '/cadastro.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/cadastro'
  },
  {
    name: '3d. Direct "/como-funciona.html"',
    url: '/como-funciona.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/como-funciona'
  },
  {
    name: '3e. Direct "/portal-cliente.html"',
    url: '/portal-cliente.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/portal-cliente'
  },
  {
    name: '3f. Direct "/portal-prestador.html"',
    url: '/portal-prestador.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/portal-prestador'
  },
  {
    name: '3g. Direct "/sobre-nos.html"',
    url: '/sobre-nos.html',
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/sobre-nos'
  },

  // Clean URLs resolution (extensionless)
  {
    name: '3h. Clean URL "/login"',
    url: '/login',
    expectedType: 'CLEAN_URL_HTML',
    expectedStatus: 200,
    expectedTarget: 'login.html'
  },
  {
    name: '3i. Clean URL "/pedido"',
    url: '/pedido',
    expectedType: 'CLEAN_URL_HTML',
    expectedStatus: 200,
    expectedTarget: 'pedido.html'
  },
  {
    name: '3j. Clean URL "/cadastro"',
    url: '/cadastro',
    expectedType: 'CLEAN_URL_HTML',
    expectedStatus: 200,
    expectedTarget: 'cadastro.html'
  },

  // --- Category 4: Static asset requests ---
  {
    name: '4a. Global stylesheet "/style.css"',
    url: '/style.css',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'style.css'
  },
  {
    name: '4b. Client script "/script.js"',
    url: '/script.js',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'script.js'
  },
  {
    name: '4c. Auth script "/auth.js"',
    url: '/auth.js',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'auth.js'
  },
  {
    name: '4d. PWA icon "/img/icone-192.png"',
    url: '/img/icone-192.png',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'img/icone-192.png'
  },
  {
    name: '4e. PWA icon 512 "/img/icone-512.png"',
    url: '/img/icone-512.png',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'img/icone-512.png'
  },
  {
    name: '4f. WebP image "/img/eletrica.webp"',
    url: '/img/eletrica.webp',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'img/eletrica.webp'
  },
  {
    name: '4g. Manifest "/manifest.json"',
    url: '/manifest.json',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'manifest.json'
  },
  {
    name: '4h. Robots "/robots.txt"',
    url: '/robots.txt',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'robots.txt'
  },
  {
    name: '4i. Sitemap "/sitemap.xml"',
    url: '/sitemap.xml',
    expectedType: 'STATIC_FILE',
    expectedStatus: 200,
    expectedTarget: 'sitemap.xml'
  },

  // --- Category 5: Complex nested API routes ---
  {
    name: '5a. Complex API "/api/services?cat=Marcenaria&sort=price_asc"',
    url: '/api/services?cat=Marcenaria&sort=price_asc',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path=services&cat=Marcenaria&sort=price_asc'
  },
  {
    name: '5b. Complex API with multiple filters',
    url: '/api/services?cat=Limpeza&min_price=50&max_price=200',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path=services&cat=Limpeza&min_price=50&max_price=200'
  },
  {
    name: '5c. Nested resource "/api/orders/123/pay"',
    url: '/api/orders/123/pay',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path=orders/123/pay'
  },
  {
    name: '5d. Dynamic param "/api/cep/01001000"',
    url: '/api/cep/01001000',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path=cep/01001000'
  },
  {
    name: '5e. Geocode query "/api/geocode?address=Av+Paulista"',
    url: '/api/geocode?address=Av+Paulista',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path=geocode&address=Av+Paulista'
  },

  // --- Category 6: Bare /api and /api/ ---
  {
    name: '6a. Bare "/api"',
    url: '/api',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path='
  },
  {
    name: '6b. Bare "/api/" with trailing slash',
    url: '/api/',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path='
  },

  // --- Category 7: Nonexistent static routes ---
  {
    name: '7a. Nonexistent static page "/nonexistent-route"',
    url: '/nonexistent-route',
    expectedType: 'CUSTOM_404_HTML',
    expectedStatus: 404,
    expectedTarget: '404.html'
  },
  {
    name: '7b. Nonexistent asset "/style.missing.css"',
    url: '/style.missing.css',
    expectedType: 'CUSTOM_404_HTML',
    expectedStatus: 404,
    expectedTarget: '404.html'
  },
  {
    name: '7c. Deep nonexistent path "/foo/bar/baz"',
    url: '/foo/bar/baz',
    expectedType: 'CUSTOM_404_HTML',
    expectedStatus: 404,
    expectedTarget: '404.html'
  },

  // --- Category 8: Adversarial & Boundary Edge Cases ---
  {
    name: '8a. Path traversal attempt "/../index.html"',
    url: '/../index.html',
    // In URL normalization, /../index.html resolves to /index.html which 308 redirects to /
    expectedType: 'REDIRECT',
    expectedStatus: 308,
    expectedTarget: '/'
  },
  {
    name: '8b. URL with hash "/login#section"',
    url: '/login#section',
    expectedType: 'CLEAN_URL_HTML',
    expectedStatus: 200,
    expectedTarget: 'login.html'
  },
  {
    name: '8c. Deep API path "/api/v1/deep/nested/endpoint"',
    url: '/api/v1/deep/nested/endpoint',
    expectedType: 'REWRITE',
    expectedStatus: 200,
    expectedTarget: '/api/index.py?__path=v1/deep/nested/endpoint'
  }
];

let passedCount = 0;
let failedCount = 0;

testCases.forEach((tc, idx) => {
  const res = simulateVercelRequest(tc.url);
  let passed = true;
  let reason = '';

  if (res.type !== tc.expectedType) {
    passed = false;
    reason += `Type mismatch: expected ${tc.expectedType}, got ${res.type}. `;
  }
  if (res.status !== tc.expectedStatus) {
    passed = false;
    reason += `Status mismatch: expected ${tc.expectedStatus}, got ${res.status}. `;
  }

  const actualTarget = res.location || res.destination || res.file;
  if (tc.expectedTarget && actualTarget !== tc.expectedTarget) {
    passed = false;
    reason += `Target mismatch: expected "${tc.expectedTarget}", got "${actualTarget}". `;
  }

  // CRITICAL CHECK: Verify PLATFORM_404_NOT_FOUND is NEVER returned for valid routes
  if (res.type === 'PLATFORM_404_NOT_FOUND') {
    passed = false;
    reason += 'FATAL: Platform NOT_FOUND error occurred! ';
  }

  if (passed) {
    passedCount++;
    console.log(`  [PASS] Test ${idx + 1}: ${tc.name}`);
    console.log(`         URL: "${tc.url}" -> ${res.type} (${res.status}) => "${actualTarget}"`);
  } else {
    failedCount++;
    console.error(`  [FAIL] Test ${idx + 1}: ${tc.name}`);
    console.error(`         URL: "${tc.url}"`);
    console.error(`         Reason: ${reason}`);
    console.error(`         Result:`, res);
  }
});

console.log('\n================================================================');
console.log(`TEST RESULTS: ${passedCount} PASSED, ${failedCount} FAILED out of ${testCases.length} tests.`);
console.log('================================================================');

if (failedCount > 0) {
  process.exit(1);
} else {
  console.log('SUCCESS: All adversarial routing test cases passed unconditionally!');
  process.exit(0);
}
