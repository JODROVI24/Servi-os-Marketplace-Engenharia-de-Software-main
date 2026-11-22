"""Registro central dos 8 Blueprints de domínio e handlers de erro do Flask."""

from pertoja.blueprints.auth import auth_bp
from pertoja.blueprints.llm import llm_bp
from pertoja.blueprints.orders import orders_bp
from pertoja.blueprints.pages import handle_404, handle_500, pages_bp
from pertoja.blueprints.payments import payments_bp
from pertoja.blueprints.providers import providers_bp
from pertoja.blueprints.services import services_bp
from pertoja.blueprints.webhooks import webhooks_bp

ALL_BLUEPRINTS = (
    pages_bp,
    auth_bp,
    providers_bp,
    services_bp,
    orders_bp,
    payments_bp,
    webhooks_bp,
    llm_bp,
)


def register_blueprints(app) -> None:
    """Registra todos os Blueprints, handlers de erro HTTP e aliases curtos de endpoints."""
    for bp in ALL_BLUEPRINTS:
        if bp.name not in app.blueprints:
            app.register_blueprint(bp)

    app.register_error_handler(404, handle_404)
    app.register_error_handler(500, handle_500)

    # Preserva resolução direta em app.view_functions['<func>'] usada pelos testes de auditoria
    for full_ep, view_fn in list(app.view_functions.items()):
        if "." in full_ep:
            short_ep = full_ep.split(".", 1)[1]
            app.view_functions.setdefault(short_ep, view_fn)
