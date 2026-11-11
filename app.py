import os
import sys
import importlib.util

# Localiza e importa o app.py do site_marketplace
current_dir = os.path.dirname(os.path.abspath(__file__))
marketplace_dir = os.path.join(current_dir, 'Servi-os-Marketplace-Engenharia-de-Software-main', 'site_marketplace')
if not os.path.isdir(marketplace_dir):
    marketplace_dir = os.path.join(current_dir, 'site_marketplace')

if marketplace_dir not in sys.path:
    sys.path.insert(0, marketplace_dir)

# Se Vercel ou serverless estiver ativo, garantir /tmp
if os.environ.get('VERCEL') == '1' or 'AWS_LAMBDA_FUNCTION_NAME' in os.environ:
    os.environ['VERCEL'] = '1'

# Carrega a aplicação diretamente sem colisão de namespace
app_file = os.path.join(marketplace_dir, 'app.py')
spec = importlib.util.spec_from_file_location("pertoja_root_runner", app_file)
backend_mod = importlib.util.module_from_spec(spec)
sys.modules["pertoja_root_runner"] = backend_mod
spec.loader.exec_module(backend_mod)
app = backend_mod.app

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Servidor PertoJá Marketplace Iniciado!")
    print("👉 Acesse a aplicação no seu navegador: http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
