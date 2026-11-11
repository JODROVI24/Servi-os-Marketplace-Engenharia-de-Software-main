import os
import sys
import traceback
import importlib.util
from urllib.parse import parse_qs, urlencode

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

# Diretório base do backend do marketplace
marketplace_dir = os.path.join(root_dir, 'Servi-os-Marketplace-Engenharia-de-Software-main', 'site_marketplace')
if not os.path.isdir(marketplace_dir):
    marketplace_dir = os.path.join(root_dir, 'site_marketplace')

if marketplace_dir not in sys.path:
    sys.path.insert(0, marketplace_dir)

# Sinaliza ambiente Vercel para fallback automático do SQLite em /tmp
if os.environ.get('VERCEL') == '1' or 'AWS_LAMBDA_FUNCTION_NAME' in os.environ:
    os.environ['VERCEL'] = '1'

try:
    # Carregamento direto e explícito do módulo para evitar qualquer colisão de import circular
    app_file = os.path.join(marketplace_dir, 'app.py')
    spec = importlib.util.spec_from_file_location("pertoja_marketplace_backend", app_file)
    backend_module = importlib.util.module_from_spec(spec)
    sys.modules["pertoja_marketplace_backend"] = backend_module
    spec.loader.exec_module(backend_module)
    app = backend_module.app
except Exception as exc:
    print(f"❌ [CRITICAL] Falha ao importar aplicação Flask no Serverless Vercel: {exc}", file=sys.stderr)
    traceback.print_exc()
    from flask import Flask, jsonify
    app = Flask(__name__)
    
    @app.route('/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    @app.route('/', methods=['GET', 'POST'])
    def vercel_import_error(subpath=''):
        return jsonify({
            'error': 'Falha na inicialização da função Serverless no Vercel',
            'detail': str(exc),
            'traceback': traceback.format_exc()
        }), 500


class VercelPathNormalizerWSGI:
    """
    Middleware WSGI que normaliza PATH_INFO quando a Vercel reescreve
    rotas /api/(.*) para /api/index.py ou remove o prefixo /api.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '') or '/'
        qs = environ.get('QUERY_STRING', '') or ''

        # 1. Caso __path tenha sido enviado na query string pelo rewrite da Vercel
        if '__path=' in qs:
            params = parse_qs(qs, keep_blank_values=True)
            if '__path' in params:
                subpath = params.pop('__path')[0].lstrip('/')
                environ['PATH_INFO'] = f'/api/{subpath}' if subpath else '/api'
                environ['QUERY_STRING'] = urlencode(params, doseq=True)
                return self.wsgi_app(environ, start_response)

        # 2. Caso PATH_INFO tenha sido reescrito diretamente para o arquivo
        if path in ('/api/index.py', '/api/index', '/index.py', '/index'):
            orig_url = (
                environ.get('HTTP_X_MATCHED_PATH')
                or environ.get('HTTP_X_VERCEL_ORIGINAL_PATH')
                or environ.get('REQUEST_URI')
                or environ.get('RAW_URI')
                or ''
            )
            if orig_url and orig_url.startswith('/api') and orig_url not in ('/api/index.py', '/api/index'):
                orig_path = orig_url.split('?', 1)[0]
                environ['PATH_INFO'] = orig_path

        # 3. Caso a Vercel tenha removido o prefixo /api ao despachar para a função
        elif not path.startswith('/api') and path.lstrip('/').split('/')[0] in (
            'auth', 'services', 'my-services', 'orders', 'reviews', 'profile', 'cep', 'geocode', 'health'
        ):
            environ['PATH_INFO'] = '/api/' + path.lstrip('/')

        return self.wsgi_app(environ, start_response)


# Envolve o wsgi_app do Flask
if not isinstance(app.wsgi_app, VercelPathNormalizerWSGI):
    app.wsgi_app = VercelPathNormalizerWSGI(app.wsgi_app)
