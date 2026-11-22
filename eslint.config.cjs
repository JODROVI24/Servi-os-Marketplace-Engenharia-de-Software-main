const globals = require('globals');
const noUnsanitized = require('eslint-plugin-no-unsanitized');

const sharedSecurityRules = {
  'no-eval': 'error',
  'no-implied-eval': 'error',
  'no-new-func': 'error',
  'no-script-url': 'error',
  'no-unsanitized/method': 'error',
  'no-unsanitized/property': 'error',
  'no-dupe-keys': 'error',
  'no-unreachable': 'error',
  'no-redeclare': 'error',
  'no-constant-condition': 'error',
  'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
  'no-undef': 'error',
};

module.exports = [
  {
    ignores: ['node_modules/**', 'public/dist/**'],
  },
  {
    files: ['public/auth.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        ...globals.browser,
      },
    },
    plugins: {
      'no-unsanitized': noUnsanitized,
    },
    rules: sharedSecurityRules,
  },
  {
    files: ['public/script.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        ...globals.browser,
        L: 'readonly',
        MercadoPago: 'readonly',
        obterUsuarioLogado: 'readonly',
      },
    },
    plugins: {
      'no-unsanitized': noUnsanitized,
    },
    rules: sharedSecurityRules,
  },
  {
    files: ['public/js/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        ...globals.browser,
        L: 'readonly',
        MercadoPago: 'readonly',
        PERTOJA_MIN_PASSWORD_LENGTH: 'readonly',
        obterCsrfToken: 'readonly',
        garantirHeadersCsrf: 'readonly',
        escapeHtml: 'readonly',
        sanitizarUrlSegura: 'readonly',
        salvarConteudoBotao: 'readonly',
        restaurarConteudoBotao: 'readonly',
        validarPoliticaSenhaLocal: 'readonly',
        atualizarNavegacao: 'readonly',
        obterUsuarioLogado: 'readonly',
        inicializarDrawerNavegacao: 'readonly',
        inicializarHeaderLocalizacao: 'readonly',
        abrirModalEnderecoHeader: 'readonly',
        atualizarPillEnderecoHeader: 'readonly',
      },
    },
    plugins: {
      'no-unsanitized': noUnsanitized,
    },
    rules: sharedSecurityRules,
  },
  {
    files: ['scripts/check_xss_lint.js', 'tests/test_vercel_routing_adversarial.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'commonjs',
      globals: {
        ...globals.node,
      },
    },
    plugins: {
      'no-unsanitized': noUnsanitized,
    },
    rules: sharedSecurityRules,
  },
];
