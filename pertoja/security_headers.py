"""Fonte única de verdade para cabeçalhos HTTP de segurança a partir de vercel.json."""

import json
import os
import re
from functools import lru_cache

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERCEL_CONFIG_PATH = os.path.join(REPO_ROOT, "vercel.json")


@lru_cache(maxsize=1)
def load_vercel_header_policy() -> tuple[dict[str, str], re.Pattern[str] | None]:
    """Lê vercel.json e extrai os cabeçalhos globais e o padrão de rotas sem cache."""
    if not os.path.isfile(VERCEL_CONFIG_PATH):
        return {}, None

    with open(VERCEL_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    global_headers: dict[str, str] = {}
    nocache_regex: re.Pattern[str] | None = None

    for block in data.get("headers", []):
        source = str(block.get("source") or "")
        items = block.get("headers") or []
        if source == "/(.*)":
            for item in items:
                key = str(item.get("key") or "").strip()
                value = str(item.get("value") or "")
                if key:
                    global_headers[key] = value
        elif any(str(item.get("key") or "").lower() == "cache-control" for item in items):
            try:
                nocache_regex = re.compile(f"^{source}$")
            except re.error:
                nocache_regex = None

    return global_headers, nocache_regex


def clear_security_headers_cache() -> None:
    """Limpa o cache em memória da leitura de cabeçalhos do vercel.json."""
    load_vercel_header_policy.cache_clear()


def get_global_security_headers() -> dict[str, str]:
    """Retorna os cabeçalhos de segurança globais definidos em vercel.json."""
    headers, _ = load_vercel_header_policy()
    return dict(headers)


def is_sensitive_nocache_path(path: str) -> bool:
    """Indica se o caminho exige política estrita de Cache-Control sem armazenamento."""
    if not path:
        return False
    if path.startswith("/api/"):
        return True
    _, nocache_regex = load_vercel_header_policy()
    if nocache_regex is not None and nocache_regex.match(path):
        return True
    return False


def apply_security_headers(response, path: str) -> None:
    """Anexa os cabeçalhos de segurança e Cache-Control definidos na fonte única (vercel.json)."""
    for key, value in get_global_security_headers().items():
        response.headers.setdefault(key, value)

    if any(path.endswith(ext) for ext in (".css", ".js", ".webp", ".jpg", ".png", ".svg", ".ico", ".woff2", ".woff")):
        response.headers["Cache-Control"] = "public, max-age=604800, stale-while-revalidate=86400"
    elif is_sensitive_nocache_path(path):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    else:
        response.headers["Cache-Control"] = "private, no-cache, must-revalidate"
