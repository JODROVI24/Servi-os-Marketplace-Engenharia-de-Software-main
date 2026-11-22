"""Pacote principal do backend PertoJá Marketplace e Application Factory."""

import importlib
import importlib.util

from flask import Flask

from pertoja.config import PUBLIC_DIR, configure_app
from pertoja.extensions import add_response_headers_and_compression, csrf_origin_check
from pertoja.logging_config import configure_logging, init_sentry


def create_app(config_overrides: dict | None = None, *, init_database: bool = True) -> Flask:
    """Cria e configura a instância Flask seguindo o padrão Application Factory."""
    app = Flask("pertoja", static_folder=PUBLIC_DIR)
    logger = configure_logging(app)
    init_sentry(logger)
    configure_app(app, config_overrides=config_overrides)

    app.before_request(csrf_origin_check)
    app.after_request(add_response_headers_and_compression)

    if init_database:
        import database

        database.init_db()

    # Blueprints serão conectados na Etapa 5 assim que pertoja.blueprints existir
    if importlib.util.find_spec("pertoja.blueprints") is not None:
        bp_pkg = importlib.import_module("pertoja.blueprints")
        if hasattr(bp_pkg, "register_blueprints"):
            bp_pkg.register_blueprints(app)

    return app
