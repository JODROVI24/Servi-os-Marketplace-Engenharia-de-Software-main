"""Repositório de cache de geocodificação com TTL de 30 dias."""

import sqlite3
from datetime import datetime, timedelta, timezone

from pertoja._compat import resolve_db_connection_factory
from pertoja.db.connection import PG_DB_ERRORS, _normalizar_query, get_db_connection
from pertoja.logging_config import get_logger

_logger = get_logger("pertoja.repositories.geocode")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_cached_geocode(query: str) -> tuple[float, float] | None:
    """Recupera coordenadas em cache respeitando TTL de 30 dias."""
    normalized = _normalizar_query(query)
    if not normalized:
        return None
    conn = None
    try:
        conn = resolve_db_connection_factory(get_db_connection)()
        row = conn.execute("SELECT lat, lng, criado_em FROM geocode_cache WHERE query = ?", (normalized,)).fetchone()
        if row:
            try:
                criado_em = row["criado_em"]
            except (KeyError, IndexError, TypeError):
                criado_em = None
            if criado_em is not None:
                if isinstance(criado_em, str):
                    try:
                        dt = datetime.fromisoformat(criado_em.replace("Z", "+00:00")).replace(tzinfo=None)
                    except ValueError:
                        dt = _utcnow_naive()
                elif isinstance(criado_em, datetime):
                    dt = criado_em.replace(tzinfo=None)
                else:
                    dt = _utcnow_naive()
                if _utcnow_naive() - dt > timedelta(days=30):
                    conn.execute("DELETE FROM geocode_cache WHERE query = ?", (normalized,))
                    conn.commit()
                    return None
            return float(row["lat"]), float(row["lng"])
    except (sqlite3.Error, ValueError, TypeError, KeyError, RuntimeError, *PG_DB_ERRORS) as exc:
        _logger.debug(
            "Falha ao ler cache de geocodificação.",
            extra={"event": "geocode_cache_read_error", "error_type": type(exc).__name__},
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except (sqlite3.Error, RuntimeError, AttributeError, *PG_DB_ERRORS):
                pass
    return None


def save_cached_geocode(query: str, lat: float, lng: float, origem: str = "nominatim") -> None:
    """Salva ou atualiza coordenadas normalizadas no cache via upsert SQL padrão."""
    normalized = _normalizar_query(query)
    if not normalized or lat is None or lng is None:
        return
    conn = None
    try:
        conn = resolve_db_connection_factory(get_db_connection)()
        conn.execute(
            """
            INSERT INTO geocode_cache (query, lat, lng, origem, criado_em)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (query) DO UPDATE SET
                lat = excluded.lat,
                lng = excluded.lng,
                origem = excluded.origem,
                criado_em = CURRENT_TIMESTAMP
        """,
            (normalized, float(lat), float(lng), origem),
        )
        conn.commit()
    except (sqlite3.Error, ValueError, TypeError, RuntimeError, *PG_DB_ERRORS) as exc:
        _logger.warning(
            "Não foi possível persistir cache de geocodificação.",
            extra={"event": "geocode_cache_write_error", "error_type": type(exc).__name__},
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except (sqlite3.Error, RuntimeError, AttributeError, *PG_DB_ERRORS):
                pass
