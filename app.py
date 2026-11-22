"""Entrypoint WSGI e fachada de compatibilidade do PertoJá Marketplace."""

# ruff: noqa: E402

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import requests  # noqa: E402

try:
    import openai
except ImportError:
    openai = None

from pertoja import create_app  # noqa: E402
from pertoja.blueprints.llm import (  # noqa: E402
    call_llm_compat as _call_llm,
)
from pertoja.blueprints.llm import (
    get_llm_client_compat as _get_llm_client,
)
from pertoja.config import (  # noqa: E402
    persist_dev_secret_key as _persist_dev_secret_key,
)
from pertoja.config import (
    resolve_secret_key as _resolve_secret_key,
)
from pertoja.db.connection import get_db_connection  # noqa: E402
from pertoja.extensions import (  # noqa: E402
    HybridRateLimiter,
    rate_limiter,
)
from pertoja.extensions import (
    get_client_ip as _get_client_ip,
)
from pertoja.extensions import (
    hash_ip as _hash_ip,
)
from pertoja.llm import (  # noqa: E402
    get_llm_api_key as _get_llm_api_key,
)
from pertoja.llm import (
    get_llm_base_url as _get_llm_base_url,
)
from pertoja.llm import (
    get_llm_model as _get_llm_model,
)
from pertoja.logging_config import get_logger  # noqa: E402
from pertoja.payments import get_payment_adapter  # noqa: E402
from pertoja.services.geo import geocode_address  # noqa: E402

app = create_app()

__all__ = [
    "HybridRateLimiter",
    "_call_llm",
    "_get_client_ip",
    "_get_llm_api_key",
    "_get_llm_base_url",
    "_get_llm_client",
    "_get_llm_model",
    "_hash_ip",
    "_persist_dev_secret_key",
    "_resolve_secret_key",
    "app",
    "geocode_address",
    "get_db_connection",
    "get_payment_adapter",
    "openai",
    "rate_limiter",
    "requests",
]

if __name__ == "__main__":
    get_logger("pertoja").info("Servidor PertoJá Marketplace iniciado em http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
