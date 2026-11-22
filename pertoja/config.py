"""Configurações centrais, variáveis de ambiente e constantes do PertoJá."""

import hashlib
import hmac
import os
import re
import secrets

from pertoja.logging_config import get_logger

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(REPO_ROOT, "public")

ALLOWED_STATIC_EXTENSIONS = frozenset(
    {".html", ".css", ".js", ".webp", ".jpg", ".png", ".svg", ".ico", ".woff2", ".woff"}
)
CATEGORIAS_PERMITIDAS = (
    "Limpeza",
    "Elétrica",
    "Encanamento",
    "Marcenaria",
    "Pintura",
    "Jardinagem",
    "Tecnologia",
)
CATEGORIAS_TECNICAS = ("Elétrica", "Encanamento")
PROF_REG_REGEX = re.compile(r"^(CREA|CFT|CRT|NR-10|CAU)[A-Z0-9\-\/ ]{2,30}$", re.IGNORECASE)

MIN_PASSWORD_LENGTH = 10
HIBP_RANGE_API_URL = "https://api.pwnedpasswords.com/range/"
HIBP_TIMEOUT_SECONDS = 2.5

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_ORDER_PAY_RE = re.compile(r"^/api/orders/\d+/pay$")

_logger = get_logger("pertoja.config")


def load_dotenv(env_path: str | None = None) -> None:
    """Carrega variáveis de arquivos .env locais sem sobrescrever variáveis já definidas."""
    target = env_path or os.path.join(REPO_ROOT, ".env")
    if not os.path.isfile(target):
        return
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def is_production_runtime() -> bool:
    """Retorna True quando executando em produção (VERCEL=1/true ou FLASK_ENV=production)."""
    vercel_flag = str(os.environ.get("VERCEL", "")).strip().lower()
    flask_env = str(os.environ.get("FLASK_ENV", "")).strip().lower()
    return vercel_flag in ("1", "true") or flask_env == "production"


def persist_dev_secret_key(secret_key: str, env_path: str | None = None) -> None:
    """Grava SECRET_KEY gerada automaticamente no .env local de desenvolvimento."""
    target_path = env_path or os.path.join(REPO_ROOT, ".env")
    try:
        if os.path.isfile(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            replaced = False
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, v = stripped.split("=", 1)
                    if k.strip() == "SECRET_KEY" and not v.strip().strip('"').strip("'"):
                        new_lines.append(f"SECRET_KEY={secret_key}\n")
                        replaced = True
                        continue
                new_lines.append(line)
            if not replaced:
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines[-1] += "\n"
                new_lines.append(f"SECRET_KEY={secret_key}\n")
            with open(target_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        else:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write("# Gerado automaticamente para desenvolvimento local\n")
                f.write(f"SECRET_KEY={secret_key}\n")
    except OSError as exc:
        _logger.warning(
            "Não foi possível persistir SECRET_KEY no .env local.",
            extra={"event": "persist_secret_key_failed", "error_type": type(exc).__name__},
        )


def resolve_secret_key(env_path: str | None = None) -> str:
    """Resolve SECRET_KEY exigindo >= 32 chars em produção e gerando em dev se ausente."""
    is_prod = is_production_runtime()
    require_strong = is_prod or os.environ.get("REQUIRE_SECRET_KEY") == "1"
    env_key = (os.environ.get("SECRET_KEY") or "").strip()

    if require_strong:
        if not env_key or len(env_key) < 32:
            raise RuntimeError(
                "SECRET_KEY obrigatória com no mínimo 32 caracteres em produção "
                "(VERCEL=1, FLASK_ENV=production ou REQUIRE_SECRET_KEY=1)."
            )
        return env_key

    if env_key:
        return env_key

    generated = secrets.token_hex(32)
    os.environ["SECRET_KEY"] = generated
    persist_dev_secret_key(generated, env_path=env_path)
    return generated


def hash_ip_with_secret(ip: str, secret_key: str) -> str:
    """Calcula hash HMAC-SHA256 truncado usando a secret_key configurada."""
    if not secret_key:
        raise RuntimeError("app.secret_key não configurada para hash de IP.")
    secret = str(secret_key).encode("utf-8")
    return hmac.new(secret, str(ip or "").encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def configure_app(app, config_overrides: dict | None = None) -> None:
    """Aplica configurações Flask padrão do marketplace na instância fornecida."""
    load_dotenv()
    app.secret_key = resolve_secret_key()
    app.config.update(
        TESTING=False,
        MAX_CONTENT_LENGTH=1024 * 1024,
        PERMANENT_SESSION_LIFETIME=43200,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(os.environ.get("VERCEL") == "1" or os.environ.get("HTTPS") == "1"),
    )
    if config_overrides:
        app.config.update(config_overrides)
        if "SECRET_KEY" in config_overrides:
            app.secret_key = config_overrides["SECRET_KEY"]
