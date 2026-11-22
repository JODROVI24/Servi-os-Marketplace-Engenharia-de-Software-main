"""Serviços de consulta de CEP e geocodificação multinível com cache."""

import os
import re
import threading
import time

import requests

from pertoja._compat import resolve_compat
from pertoja.logging_config import get_logger
from pertoja.repositories.geocode import get_cached_geocode, save_cached_geocode

_logger = get_logger("pertoja.services.geo")

NOMINATIM_USER_AGENT = (
    os.environ.get("NOMINATIM_USER_AGENT") or "PertoJaMarketplace/2.0 (+https://pertoja.com.br; suporte@pertoja.com.br)"
)
NOMINATIM_MIN_INTERVAL_SECONDS = 1.0
_nominatim_lock = threading.Lock()
_last_nominatim_request_at: float | None = None


def reset_nominatim_throttle() -> None:
    """Reseta o estado do throttle do Nominatim para testes isolados."""
    global _last_nominatim_request_at
    with _nominatim_lock:
        _last_nominatim_request_at = None


def _throttle_nominatim_request() -> None:
    """Garante no máximo 1 requisição por segundo para o Nominatim de forma thread-safe."""
    global _last_nominatim_request_at
    with _nominatim_lock:
        now = time.monotonic()
        if _last_nominatim_request_at is not None:
            elapsed = now - _last_nominatim_request_at
            if elapsed < NOMINATIM_MIN_INTERVAL_SECONDS:
                time.sleep(NOMINATIM_MIN_INTERVAL_SECONDS - elapsed)
        _last_nominatim_request_at = time.monotonic()


def geocode_address(
    address_str,
    street=None,
    neighborhood=None,
    city=None,
    state=None,
    fallback=None,
    precise_only: bool = False,
):
    """Geocodifica endereço no Nominatim com candidatos progressivos e cache em banco."""
    cache_query = (
        address_str.strip()
        if address_str and address_str.strip()
        else f"{street or ''}, {neighborhood or ''}, {city or ''} - {state or ''}".strip(" ,-")
    )
    if cache_query:
        cached = get_cached_geocode(cache_query)
        if cached:
            return cached

    candidates: list[tuple[str, bool]] = []

    def add(text, precise: bool) -> None:
        clean = (text or "").strip(" ,-")
        if clean and all(clean != c[0] for c in candidates):
            candidates.append((clean, precise))

    if address_str and address_str.strip():
        raw = address_str.strip()
        add(raw, True)
        raw_no_num = re.sub(r"\s+\d+\b", "", raw)
        if raw_no_num != raw:
            add(raw_no_num, True)

    if street and city:
        if neighborhood:
            add(f"{street}, {neighborhood}, {city} - {state or ''}, Brasil", True)
        add(f"{street}, {city} - {state or ''}, Brasil", True)

    if address_str and address_str.strip():
        parts = [p.strip() for p in re.split(r"[,–-]", address_str.strip()) if p.strip()]
        if len(parts) >= 3:
            street_clean = re.sub(r"\s+\d+\b", "", parts[0]).strip()
            add(f"{street_clean}, {parts[-1]}, Brasil", True)

    if neighborhood and city:
        add(f"{neighborhood}, {city} - {state or ''}, Brasil", False)
    if city:
        add(f"{city} - {state or ''}, Brasil", False)
    if state and not city:
        add(f"{state}, Brasil", False)
    if address_str and address_str.strip():
        parts = [p.strip() for p in re.split(r"[,–-]", address_str.strip()) if p.strip()]
        if len(parts) >= 3:
            add(f"{parts[-1]}, Brasil", False)

    req_mod = resolve_compat("app", "requests", requests)
    headers = {"User-Agent": NOMINATIM_USER_AGENT}
    for cand, precise in candidates:
        if precise_only and not precise:
            continue
        cached_cand = get_cached_geocode(cand)
        if cached_cand:
            return cached_cand
        try:
            url = f"https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(cand)}&limit=1"
            _throttle_nominatim_request()
            resp = req_mod.get(url, headers=headers, timeout=3.0)
            if resp.status_code == 200:
                res = resp.json()
                if res and len(res) > 0:
                    lat_found = float(res[0]["lat"])
                    lng_found = float(res[0]["lon"])
                    save_cached_geocode(cand, lat_found, lng_found, origem="nominatim-v2")
                    if precise and cache_query and cand != cache_query:
                        save_cached_geocode(cache_query, lat_found, lng_found, origem="nominatim-v2")
                    return lat_found, lng_found
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError, OSError) as exc:
            _logger.debug(
                "Candidato de geocodificação falhou.",
                extra={"event": "geocode_candidate_error", "error_type": type(exc).__name__},
            )
            continue

    if fallback is not None:
        return fallback
    return None, None


def lookup_cep_and_coords(clean_cep: str):
    """Consulta ViaCEP/BrasilAPI e enriquece o endereço com coordenadas geográficas."""
    req_mod = resolve_compat("app", "requests", requests)
    data = None
    backup_coords = None

    try:
        resp = req_mod.get(f"https://viacep.com.br/ws/{clean_cep}/json/", timeout=4)
        if resp.status_code == 200:
            v_data = resp.json()
            if not v_data.get("erro"):
                data = v_data
    except (requests.RequestException, ValueError, TypeError, OSError):
        pass

    if not data or not data.get("localidade"):
        try:
            r_brasil = req_mod.get(
                f"https://brasilapi.com.br/api/cep/v2/{clean_cep}",
                headers={"User-Agent": "PertoJaMarketplace/2.0 (suporte@pertoja.com.br)"},
                timeout=3.5,
            )
            if r_brasil.status_code == 200:
                b_json = r_brasil.json()
                coords = b_json.get("location", {}).get("coordinates", {})
                if coords.get("latitude") and coords.get("longitude"):
                    try:
                        backup_coords = (float(coords["latitude"]), float(coords["longitude"]))
                    except (ValueError, TypeError):
                        pass

                data = {
                    "cep": b_json.get("cep") or clean_cep,
                    "logradouro": b_json.get("street") or "",
                    "bairro": b_json.get("neighborhood") or "",
                    "localidade": b_json.get("city") or "",
                    "uf": b_json.get("state") or "",
                    "ibge": str(
                        b_json.get("ibge", {}).get("city", "")
                        if isinstance(b_json.get("ibge"), dict)
                        else (b_json.get("ibge") or "")
                    ),
                }
        except (requests.RequestException, ValueError, TypeError, AttributeError, OSError):
            pass

    if not data or data.get("erro"):
        return None

    street = data.get("logradouro") or ""
    bairro = data.get("bairro") or ""
    city = data.get("localidade") or ""
    uf = data.get("uf") or ""
    address_full = f"{street}, {bairro}, {city} - {uf}".strip(", -")

    lat, lng = (None, None)
    if street:
        lat, lng = geocode_address(
            address_str=address_full, street=street, neighborhood=bairro, city=city, state=uf, precise_only=True
        )

    if (lat is None or lng is None) and not backup_coords:
        try:
            r_b = req_mod.get(
                f"https://brasilapi.com.br/api/cep/v2/{clean_cep}",
                headers={"User-Agent": "PertoJaMarketplace/2.0 (suporte@pertoja.com.br)"},
                timeout=3.0,
            )
            if r_b.status_code == 200:
                c = r_b.json().get("location", {}).get("coordinates", {})
                if c.get("latitude") and c.get("longitude"):
                    backup_coords = (float(c["latitude"]), float(c["longitude"]))
        except (requests.RequestException, ValueError, TypeError, AttributeError, OSError):
            pass

    if (lat is None or lng is None) and backup_coords:
        lat, lng = backup_coords

    if lat is None or lng is None:
        lat, lng = geocode_address(address_str=address_full, street=street, neighborhood=bairro, city=city, state=uf)
        data["aproximado"] = lat is not None

    data["lat"] = lat
    data["lng"] = lng
    return data
