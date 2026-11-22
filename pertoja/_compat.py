"""Utilitários internos de compatibilidade com fachadas e monkeypatches legados."""

import sys


def resolve_compat(module_name: str, attr_name: str, default):
    """Retorna o atributo de um módulo legado caso esteja carregado e sobrescrito/patcheado."""
    mod = sys.modules.get(module_name)
    if mod is not None and hasattr(mod, attr_name):
        return getattr(mod, attr_name)
    return default


def resolve_db_connection_factory(default_fn):
    """Resolve `get_db_connection` respeitando patches tanto em `app` quanto em `database`."""
    app_mod = sys.modules.get("app")
    if app_mod is not None and hasattr(app_mod, "get_db_connection"):
        app_fn = app_mod.get_db_connection
        if app_fn is not default_fn:
            return app_fn

    db_mod = sys.modules.get("database")
    if db_mod is not None and hasattr(db_mod, "get_db_connection"):
        db_fn = db_mod.get_db_connection
        if db_fn is not default_fn:
            return db_fn

    return default_fn
