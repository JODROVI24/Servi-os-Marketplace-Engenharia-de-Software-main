"""Extensões compartilhadas: rate limiter híbrido, CSRF, sessão, autenticação e helpers."""

import gzip
import hmac
import math
import os
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

import requests
from flask import current_app, g, jsonify, make_response, request, session

from pertoja._compat import resolve_compat, resolve_db_connection_factory
from pertoja.config import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRF_ORDER_PAY_RE,
    hash_ip_with_secret,
)
from pertoja.db.connection import get_db_connection
from pertoja.logging_config import get_logger
from pertoja.repositories.users import find_user_by_id
from pertoja.security_headers import apply_security_headers

_logger = get_logger("pertoja.extensions")


def row_get(row, key: str, default=None):
    """Acesso seguro a colunas em sqlite3.Row, HybridRow ou dict."""
    if row is None:
        return default
    if hasattr(row, "get"):
        val = row.get(key, default)
        return val if val is not None else default
    try:
        if key in row.keys():
            val = row[key]
            return val if val is not None else default
    except (AttributeError, KeyError, TypeError, IndexError):
        pass
    return default


def parse_dt(val):
    """Converte string ISO/SQL ou datetime para datetime naive UTC."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def log_escrow_ledger(conn, order_id, tipo_evento: str, valor, status_escrow: str, observacao: str = "") -> None:
    """Registra movimentação imutável no razão de Escrow."""
    conn.execute(
        """
        INSERT INTO escrow_ledger (order_id, tipo_evento, valor, status_escrow, observacao)
        VALUES (?, ?, ?, ?, ?)
    """,
        (order_id, tipo_evento, float(valor or 0.0), status_escrow, observacao),
    )


def is_review_revealed(rev_row) -> bool:
    """Verifica se uma avaliação já foi revelada via double-blind ou janela de 7 dias."""
    if not rev_row:
        return False
    if row_get(rev_row, "revealed_at") is not None:
        return True
    dt = parse_dt(row_get(rev_row, "criado_em"))
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    return bool(dt is not None and (now_naive - dt) >= timedelta(days=7))


def mask_phone(phone) -> str:
    """Mascara telefone exibindo apenas um sufixo ofuscado."""
    if not phone:
        return ""
    s = str(phone)
    return (s[:-4] + "****") if len(s) >= 4 else "****"


def parse_positive_price(val, max_val: float = 1000000.0):
    """Valida e normaliza valor monetário estritamente positivo."""
    if isinstance(val, bool) or val is None or val == "":
        return None
    try:
        num = float(val)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(num) or num <= 0 or num > max_val:
        return None
    return round(num, 2)


def safe_coord(val, default: float = -23.5653, min_val: float = -90.0, max_val: float = 90.0) -> float:
    """Valida coordenadas geográficas finitas dentro dos limites esperados."""
    if isinstance(val, bool) or val is None or val == "":
        return default
    try:
        f = float(val)
        if not math.isfinite(f) or f < min_val or f > max_val:
            return default
        return f
    except (ValueError, TypeError):
        return default


def calcular_distancia(lat1, lng1, lat2, lng2) -> float:
    """Calcula distância aproximada em quilômetros entre dois pares de coordenadas."""
    try:
        if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
            return 0.0
        lat1_f, lng1_f, lat2_f, lng2_f = float(lat1), float(lng1), float(lat2), float(lng2)
        d_lat = (lat2_f - lat1_f) * 111.0
        d_lng = (lng2_f - lng1_f) * (111.0 * math.cos(math.radians(lat1_f)))
        return math.sqrt(d_lat**2 + d_lng**2)
    except (ValueError, TypeError):
        return 0.0


def get_client_ip() -> str:
    """Extrai o IP do cliente priorizando cabeçalhos assinados de proxy confiável."""
    vercel_ip = (request.headers.get("x-vercel-forwarded-for") or "").strip()
    if vercel_ip:
        return vercel_ip.split(",")[-1].strip()
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[-1].strip()
    return request.remote_addr or "127.0.0.1"


def hash_ip(ip: str) -> str:
    """Calcula hash HMAC-SHA256 usando a secret_key da aplicação ativa."""
    app_mod_obj = resolve_compat("app", "app", None)
    secret_key = getattr(app_mod_obj, "secret_key", None)
    if secret_key is None:
        try:
            secret_key = current_app.secret_key
        except RuntimeError:
            secret_key = ""
    return hash_ip_with_secret(ip, secret_key)


class InMemoryRateLimiter:
    """Limitador de requisições por janela deslizante em memória (thread-safe)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, deque] = {}

    def _prune_stale_locked(self, now: float) -> None:
        stale_keys = [k for k, dq in self._buckets.items() if not dq or dq[-1] <= now - 86400]
        for k in stale_keys:
            del self._buckets[k]

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            dq = self._buckets.get(key)
            if dq is None:
                dq = deque()
                self._buckets[key] = dq
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            if len(self._buckets) > 2048:
                self._prune_stale_locked(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class UpstashRedisRateLimiter:
    """Limitador distribuído via Upstash Redis REST API (/pipeline)."""

    def __init__(self, rest_url: str, rest_token: str, timeout: float = 1.5):
        self.rest_url = (rest_url or "").rstrip("/")
        self.rest_token = rest_token or ""
        self.timeout = timeout

    def _post_pipeline(self, commands):
        req_mod = resolve_compat("app", "requests", requests)
        return req_mod.post(
            f"{self.rest_url}/pipeline",
            headers={
                "Authorization": f"Bearer {self.rest_token}",
                "Content-Type": "application/json",
            },
            json=commands,
            timeout=self.timeout,
        )

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        redis_key = f"rl:{key}"
        now_ms = int(time.time() * 1000)
        window_ms = max(1000, int(window_seconds * 1000))
        cutoff_ms = now_ms - window_ms
        member = f"{now_ms}:{secrets.token_hex(6)}"

        resp = self._post_pipeline(
            [
                ["ZREMRANGEBYSCORE", redis_key, 0, cutoff_ms],
                ["ZADD", redis_key, now_ms, member],
                ["ZCARD", redis_key],
                ["PEXPIRE", redis_key, window_ms + 5000],
            ]
        )
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code} do Upstash Redis")

        results = resp.json()
        if not isinstance(results, list) or len(results) < 4:
            raise ValueError("Resposta inesperada do pipeline Upstash Redis")
        for item in results:
            if isinstance(item, dict) and item.get("error"):
                raise ValueError(f"Erro Redis no pipeline: {item.get('error')}")

        count = int(results[2]["result"])
        if count > limit:
            try:
                self._post_pipeline([["ZREM", redis_key, member]])
            except requests.RequestException:
                pass
            return False
        return True


class HybridRateLimiter:
    """Rate limiter híbrido com Upstash Redis em produção e fallback em memória."""

    def __init__(self):
        self._memory = InMemoryRateLimiter()

    def _get_upstash_credentials(self) -> tuple[str, str]:
        url = (os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL") or "").strip()
        token = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN") or "").strip()
        return url, token

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        url, token = self._get_upstash_credentials()
        if url and token:
            try:
                return UpstashRedisRateLimiter(url, token).is_allowed(key, limit, window_seconds)
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                try:
                    current_app.logger.warning(
                        "Falha no rate limiter Upstash Redis (%s); utilizando fallback em memória.",
                        exc,
                        extra={"event": "upstash_fallback", "error_type": type(exc).__name__},
                    )
                except RuntimeError:
                    _logger.warning("Falha no rate limiter Upstash Redis (%s); usando memória.", exc)
        return self._memory.is_allowed(key, limit, window_seconds)

    def reset(self) -> None:
        self._memory.reset()


rate_limiter = HybridRateLimiter()


def get_active_rate_limiter():
    """Obtém o rate limiter ativo respeitando eventual override em app.rate_limiter."""
    return resolve_compat("app", "rate_limiter", rate_limiter)


def rate_limit(limit: int, window_seconds: int = 60, key_prefix: str | None = None):
    """Decorator de rate limit por IP (HMAC-SHA256) para rotas da API."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if current_app.config.get("TESTING"):
                return f(*args, **kwargs)
            ip_hash = hash_ip(get_client_ip())
            prefix = key_prefix or request.endpoint or f.__name__
            key = f"{prefix}:{ip_hash}"
            limiter = get_active_rate_limiter()
            if not limiter.is_allowed(key, limit, window_seconds):
                resp = make_response(
                    jsonify(
                        {
                            "error": "Muitas requisições. Por favor, aguarde alguns instantes antes de tentar novamente.",
                            "retry_after_seconds": window_seconds,
                        }
                    ),
                    429,
                )
                resp.headers["Retry-After"] = str(window_seconds)
                return resp
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def check_email_rate_limit(endpoint_name: str, email: str, limit: int = 10, window_seconds: int = 60):
    """Aplica limite secundário por e-mail normalizado em endpoints de autenticação."""
    if current_app.config.get("TESTING") or not email:
        return None
    email_hash = hash_ip(email.strip().lower())
    key = f"{endpoint_name}:email:{email_hash}"
    limiter = get_active_rate_limiter()
    if not limiter.is_allowed(key, limit, window_seconds):
        resp = make_response(
            jsonify(
                {
                    "error": "Muitas requisições para este e-mail. Por favor, aguarde alguns instantes.",
                    "retry_after_seconds": window_seconds,
                }
            ),
            429,
        )
        resp.headers["Retry-After"] = str(window_seconds)
        return resp
    return None


def is_csrf_double_submit_path(path: str) -> bool:
    """Retorna True para rotas sensíveis protegidas por cookie/header CSRF double-submit."""
    if not path:
        return False
    if path == "/api/profile" or path.startswith("/api/profile/"):
        return True
    if path.startswith("/api/payments/"):
        return True
    return bool(CSRF_ORDER_PAY_RE.match(path))


def set_csrf_cookie(response, token: str | None = None) -> str:
    """Emite cookie csrf_token legível pelo JS same-origin para validação double-submit."""
    value = (token or secrets.token_urlsafe(32)).strip()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        value,
        max_age=int(current_app.config.get("PERMANENT_SESSION_LIFETIME", 43200)),
        httponly=False,
        samesite="Lax",
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
        path="/",
    )
    g._csrf_cookie_set = True
    return value


def csrf_origin_check():
    """Valida Origin/Referer em mutações HTTP e double-submit CSRF em rotas sensíveis."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    if request.path == "/api/webhooks/payments" or request.path.startswith("/api/webhooks/payments/"):
        return None

    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    if origin is None and referer is None:
        return (
            jsonify(
                {
                    "error": "Cabeçalho Origin ou Referer obrigatório para esta requisição.",
                    "code": "CSRF_ORIGIN_REQUIRED",
                }
            ),
            403,
        )

    host = (urlparse(f"//{request.host}").hostname or "").lower() if request.host else ""
    for hdr in (origin, referer):
        if hdr is not None:
            parsed = urlparse(hdr)
            hdr_host = (parsed.hostname or "").lower()
            if not hdr_host or (host and hdr_host != host):
                return jsonify({"error": "Origem da requisição não autorizada."}), 403

    if is_csrf_double_submit_path(request.path) and session.get("user_id"):
        cookie_token = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
        header_token = (request.headers.get(CSRF_HEADER_NAME) or "").strip()
        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
            return (
                jsonify(
                    {
                        "error": "Token CSRF ausente ou inválido.",
                        "code": "CSRF_TOKEN_INVALID",
                    }
                ),
                403,
            )
    return None


def add_response_headers_and_compression(response):
    """Aplica cabeçalhos do vercel.json, cookie CSRF inicial e Gzip fora da Vercel."""
    path = request.path
    apply_security_headers(response, path)

    is_static_asset = any(
        path.endswith(ext) for ext in (".css", ".js", ".webp", ".jpg", ".png", ".svg", ".ico", ".woff2", ".woff")
    )
    is_html_route = (
        path == "/"
        or path.endswith(".html")
        or path
        in (
            "/pedido",
            "/portal-cliente",
            "/portal-prestador",
            "/login",
            "/cadastro",
            "/como-funciona",
            "/sobre-nos",
            "/termos",
            "/privacidade",
        )
    )
    if (
        not is_static_asset
        and (path.startswith("/api/") or is_html_route)
        and path != "/api/auth/logout"
        and not path.startswith("/api/webhooks/")
        and not request.cookies.get(CSRF_COOKIE_NAME)
        and not getattr(g, "_csrf_cookie_set", False)
    ):
        set_csrf_cookie(response)

    is_vercel = os.environ.get("VERCEL") == "1" or "AWS_LAMBDA_FUNCTION_NAME" in os.environ
    accept_encoding = request.headers.get("Accept-Encoding", "")
    if (
        not is_vercel
        and "gzip" in accept_encoding
        and response.status_code < 300
        and not response.headers.get("Content-Encoding")
        and response.mimetype
        in ("text/html", "text/css", "text/javascript", "application/javascript", "application/json", "image/svg+xml")
    ):
        response.direct_passthrough = False
        response_data = response.get_data()
        if len(response_data) > 500:
            compressed_data = gzip.compress(response_data, compresslevel=6)
            response.set_data(compressed_data)
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Length"] = len(compressed_data)
            response.headers["Vary"] = "Accept-Encoding"

    return response


def compat_get_db_connection():
    """Abre conexão via get_db_connection respeitando eventuais patches nos testes."""
    return resolve_db_connection_factory(get_db_connection)()


def get_current_user():
    """Obtém o usuário autenticado na sessão validando status e session_version."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = compat_get_db_connection()
    try:
        user = find_user_by_id(conn, user_id)
    finally:
        conn.close()
    if not user:
        session.clear()
        return None
    status_conta = row_get(user, "status_conta", "ativo")
    if status_conta in ("bloqueado", "anonimizado"):
        session.clear()
        return None
    db_sv = int(row_get(user, "session_version", 1) or 1)
    sess_sv = session.get("session_version")
    try:
        sess_sv_int = int(sess_sv) if sess_sv is not None else 1
    except (ValueError, TypeError):
        session.clear()
        return None
    if sess_sv_int != db_sv:
        session.clear()
        return None
    return user


def require_active_account(user):
    """Retorna resposta 403 se a conta autenticada estiver restrita ou suspensa."""
    status_conta = row_get(user, "status_conta", "ativo")
    if status_conta != "ativo":
        return (
            jsonify(
                {
                    "error": "Sua conta está temporariamente suspensa ou restrita. Envie um recurso em /api/account/appeal."
                }
            ),
            403,
        )
    return None
