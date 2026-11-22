"""Repositórios de acesso a dados por domínio do PertoJá."""

from pertoja.repositories.geocode import get_cached_geocode, save_cached_geocode
from pertoja.repositories.orders import (
    get_order_by_id,
    get_order_by_share_token,
    get_order_recent_summaries,
    get_order_with_details,
)
from pertoja.repositories.payments import (
    find_payment_by_ref,
    find_payment_for_order,
    list_active_payment_methods,
    list_payments_for_order,
)
from pertoja.repositories.services import get_service_by_id, list_provider_services
from pertoja.repositories.users import find_user_by_email, find_user_by_id, increment_session_version

__all__ = [
    "find_payment_by_ref",
    "find_payment_for_order",
    "find_user_by_email",
    "find_user_by_id",
    "get_cached_geocode",
    "get_order_by_id",
    "get_order_by_share_token",
    "get_order_recent_summaries",
    "get_order_with_details",
    "get_service_by_id",
    "increment_session_version",
    "list_active_payment_methods",
    "list_payments_for_order",
    "list_provider_services",
    "save_cached_geocode",
]
