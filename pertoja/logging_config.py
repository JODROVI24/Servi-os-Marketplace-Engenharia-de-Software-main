"""Configuração de logging estruturado em JSON e integração opcional com Sentry."""

import json
import logging
import os
import sys
from datetime import datetime, timezone

_STANDARD_LOG_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


class JsonLogFormatter(logging.Formatter):
    """Formata registros de log em JSON de linha única com contexto estruturado."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "line": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def get_logger(name: str = "pertoja") -> logging.Logger:
    """Retorna um logger nomeado sob o namespace `pertoja`."""
    return logging.getLogger(name)


def configure_logging(app=None, level: str | None = None) -> logging.Logger:
    """Configura handler JSON estruturado em stderr de forma idempotente."""
    raw_level = (level or os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    numeric_level = getattr(logging, raw_level, logging.INFO)

    pkg_logger = logging.getLogger("pertoja")
    pkg_logger.setLevel(numeric_level)

    if not any(getattr(h, "_pertoja_json_handler", False) for h in pkg_logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonLogFormatter())
        handler._pertoja_json_handler = True  # type: ignore[attr-defined]
        pkg_logger.addHandler(handler)
    pkg_logger.propagate = False

    if app is not None:
        app.logger.setLevel(numeric_level)
        app.logger.propagate = True
        for h in list(app.logger.handlers):
            h.setFormatter(JsonLogFormatter())

    return pkg_logger


def init_sentry(logger: logging.Logger | None = None) -> bool:
    """Inicializa integração opcional com Sentry quando SENTRY_DSN estiver definida."""
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False

    log = logger or get_logger("pertoja.telemetry")
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        log.warning(
            "SENTRY_DSN definida, mas o pacote sentry-sdk não está instalado; prosseguindo sem Sentry.",
            extra={"event": "sentry_sdk_missing"},
        )
        return False

    raw_rate = (os.environ.get("SENTRY_TRACES_SAMPLE_RATE") or "0.1").strip()
    try:
        traces_rate = max(0.0, min(1.0, float(raw_rate)))
    except ValueError:
        traces_rate = 0.1

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=traces_rate,
        send_default_pii=False,
        environment=os.environ.get("VERCEL_ENV") or os.environ.get("FLASK_ENV") or "development",
    )
    log.info("Monitoramento Sentry inicializado.", extra={"event": "sentry_initialized"})
    return True
