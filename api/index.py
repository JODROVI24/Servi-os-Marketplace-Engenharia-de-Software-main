import os
import sys
import traceback

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
    from app import app
except Exception as exc:
    print(f"❌ [CRITICAL] Falha ao importar aplicação Flask no Serverless Vercel: {exc}", file=sys.stderr)
    traceback.print_exc()
    from flask import Flask, jsonify
    app = Flask(__name__)
    
    @app.route('/api/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    @app.route('/api', methods=['GET', 'POST'])
    def vercel_import_error(subpath=''):
        return jsonify({
            'error': 'Falha na inicialização da função Serverless no Vercel',
            'detail': str(exc),
            'traceback': traceback.format_exc()
        }), 500

# Exporta para o runtime Serverless Python da Vercel
app = app
