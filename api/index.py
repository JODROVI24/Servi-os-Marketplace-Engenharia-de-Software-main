import os
import sys
import traceback
from urllib.parse import parse_qs, urlencode

# Configura diretórios no PATH para importações dinâmicas e relativas
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

candidate_dirs = [
    os.path.join(root_dir, 'Servi-os-Marketplace-Engenharia-de-Software-main', 'site_marketplace'),
    os.path.join(root_dir, 'site_marketplace'),
    root_dir,
    current_dir
]

for d in candidate_dirs:
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)

# Sinaliza ambiente Vercel para fallback automático em /tmp
if os.environ.get('VERCEL') == '1' or 'AWS_LAMBDA_FUNCTION_NAME' in os.environ:
    os.environ['VERCEL'] = '1'

try:
    from app import app as _flask_app
except Exception as exc:
    print(f"❌ [CRITICAL] Falha ao importar aplicação Flask no Serverless Vercel: {exc}", file=sys.stderr)
    traceback.print_exc()
    from flask import Flask, jsonify
    _flask_app = Flask(__name__)
    
    @_flask_app.route('/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    @_flask_app.route('/', methods=['GET', 'POST'])
    def vercel_import_error(subpath=''):
        return jsonify({
            'error': 'Falha na inicialização da função Serverless no Vercel',
            'detail': str(exc),
            'traceback': traceback.format_exc()
        }), 500


class VercelPathNormalizerWSGI:
    """
    Middleware WSGI que normaliza PATH_INFO quando a Vercel reescreve
    rotas /api/(.*) para /api/index.py ou /api/index.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        qs = environ.get('QUERY_STRING', '')

        # Se o rewrite da Vercel substituiu PATH_INFO por /api/index.py ou /api/index
        if path in ('/api/index.py', '/api/index', '/index.py', '/index'):
            # 1. Tenta recuperar da query string __path (passada pelo rewrite)
            params = parse_qs(qs, keep_blank_values=True)
            if '__path' in params:
                subpath = params.pop('__path')[0].lstrip('/')
                environ['PATH_INFO'] = f'/api/{subpath}' if subpath else '/api'
                environ['QUERY_STRING'] = urlencode(params, doseq=True)
            else:
                # 2. Tenta recuperar de headers ou variáveis do ambiente Vercel/WSGI
                orig_url = (
                    environ.get('HTTP_X_MATCHED_PATH')
                    or environ.get('HTTP_X_VERCEL_ORIGINAL_PATH')
                    or environ.get('REQUEST_URI')
                    or environ.get('RAW_URI')
                    or ''
                )
                if orig_url and orig_url.startswith('/api') and orig_url not in ('/api/index.py', '/api/index'):
                    if '?' in orig_url:
                        orig_path, _ = orig_url.split('?', 1)
                    else:
                        orig_path = orig_url
                    environ['PATH_INFO'] = orig_path

        return self.wsgi_app(environ, start_response)


# Envolve o wsgi_app do Flask mantendo todos os atributos da instância Flask intactos
_flask_app.wsgi_app = VercelPathNormalizerWSGI(_flask_app.wsgi_app)

# Exporta para o runtime Serverless Python da Vercel
app = _flask_app
