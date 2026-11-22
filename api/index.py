import importlib.util
import logging
import os
import sys
from urllib.parse import parse_qs, urlencode

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

# Diretório base do backend do marketplace (raiz canônica do repositório)
marketplace_dir = root_dir

if marketplace_dir not in sys.path:
    sys.path.insert(0, marketplace_dir)

# Sinaliza ambiente Vercel para guardrails de produção (PostgreSQL e SECRET_KEY obrigatórios)
if os.environ.get("VERCEL") == "1" or "AWS_LAMBDA_FUNCTION_NAME" in os.environ:
    os.environ["VERCEL"] = "1"


class VercelPathNormalizerWSGI:
    """
    Middleware WSGI que normaliza PATH_INFO quando a Vercel reescreve
    rotas /api/(.*) para /api/index.py ou remove o prefixo /api.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "") or "/"
        qs = environ.get("QUERY_STRING", "") or ""

        # 1. Caso __path tenha sido enviado na query string pelo rewrite da Vercel
        if "__path=" in qs:
            params = parse_qs(qs, keep_blank_values=True)
            if "__path" in params:
                subpath = params.pop("__path")[0].lstrip("/")
                environ["PATH_INFO"] = f"/api/{subpath}" if subpath else "/api"
                environ["QUERY_STRING"] = urlencode(params, doseq=True)
                return self.wsgi_app(environ, start_response)

        # 2. Caso PATH_INFO tenha sido reescrito diretamente para o arquivo
        clean_path = path.strip("/")
        if clean_path in ("api/index.py", "api/index", "index.py", "index"):
            orig_url = (
                environ.get("HTTP_X_MATCHED_PATH")
                or environ.get("HTTP_X_VERCEL_ORIGINAL_PATH")
                or environ.get("REQUEST_URI")
                or environ.get("RAW_URI")
                or ""
            )
            if orig_url:
                orig_path = orig_url.split("?", 1)[0]
                if orig_path not in ("/api/index.py", "/api/index", "/index.py", "/index", ""):
                    if not orig_path.startswith("/api"):
                        orig_path = "/api/" + orig_path.lstrip("/")
                    environ["PATH_INFO"] = orig_path

        # 3. Caso a Vercel tenha removido o prefixo /api ao despachar para a função
        elif not path.startswith("/api") and path.lstrip("/").split("/")[0] in (
            "auth",
            "services",
            "my-services",
            "orders",
            "reviews",
            "profile",
            "cep",
            "geocode",
            "health",
            "kyc",
            "account",
            "provider",
            "shared-route",
            "payments",
            "webhooks",
            "chat",
            "ads",
        ):
            environ["PATH_INFO"] = "/api/" + path.lstrip("/")

        return self.wsgi_app(environ, start_response)


def _init_marketplace_app():
    """
    Carrega a aplicação Flask do Marketplace e acopla o middleware WSGI.
    Retorna a instância Flask ou uma aplicação de erro estruturada caso ocorra exceção inesperada.
    Falhas explícitas de configuração em produção (RuntimeError) recusam a inicialização.
    """
    try:
        app_file = os.path.join(marketplace_dir, "app.py")
        if os.path.isfile(app_file):
            import database

            database.ensure_production_database()
        spec = importlib.util.spec_from_file_location("pertoja_marketplace_backend", app_file)
        backend_module = importlib.util.module_from_spec(spec)
        sys.modules["pertoja_marketplace_backend"] = backend_module
        spec.loader.exec_module(backend_module)
        target_app = backend_module.app
        if not isinstance(target_app.wsgi_app, VercelPathNormalizerWSGI):
            target_app.wsgi_app = VercelPathNormalizerWSGI(target_app.wsgi_app)
        return target_app
    except RuntimeError:
        raise
    except (OSError, ImportError, SyntaxError, ValueError, TypeError, AttributeError):
        try:
            from pertoja.logging_config import configure_logging, get_logger

            configure_logging()
            logger = get_logger("api.index")
        except ImportError:
            logger = logging.getLogger("api.index")
        logger.exception("Falha ao importar aplicação Flask no Serverless Vercel")
        from flask import Flask, jsonify

        err_app = Flask(__name__)

        @err_app.route("/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
        @err_app.route("/", methods=["GET", "POST"])
        def vercel_import_error(subpath=""):
            return jsonify({"error": "Erro interno ao inicializar o serviço."}), 500

        return err_app


# Atribuição estrita em nível superior (top-level module scope) para atendimento
# obrigatório ao parser AST do Vercel (@vercel/python-analysis / ruff_python_ast)
app = _init_marketplace_app()
application = app
handler = app
