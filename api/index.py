import os
import sys
import importlib.util

# Configura diretórios no PATH para importações relativas
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

marketplace_dir = os.path.join(root_dir, 'Servi-os-Marketplace-Engenharia-de-Software-main', 'site_marketplace')

if marketplace_dir not in sys.path:
    sys.path.insert(0, marketplace_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Importa a instância do Flask app com banco de dados SQLite /tmp inicializado
from app import app

# Exporta para o runtime Serverless Python da Vercel
app = app
