import uuid

from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

UNREAD_COUNT_TTL_SECONDS = 60
UNREAD_COUNT_KEY_PREFIX = "notifications_unread_count"


def _unread_count_cache_key(user_id: int, organization_id: uuid.UUID) -> str:
    return f"{UNREAD_COUNT_KEY_PREFIX}:{user_id}:{organization_id}"


def get_unread_count(user_id: int, organization_id: uuid.UUID) -> int | None:
    try:
        return cache.get(_unread_count_cache_key(user_id, organization_id))
    except Exception:
        logger.exception("notifications.cache_get_failed")
        return None


def set_unread_count(user_id: int, organization_id: uuid.UUID, count: int) -> None:
    try:
        cache.set(_unread_count_cache_key(user_id, organization_id), count, UNREAD_COUNT_TTL_SECONDS)
    except Exception:
        logger.exception("notifications.cache_set_failed")


def invalidate_unread_count(user_id: int, organization_id: uuid.UUID) -> None:
    try:
        cache.delete(_unread_count_cache_key(user_id, organization_id))
    except Exception:
        logger.exception("notifications.cache_invalidate_failed")


def invalidate_unread_count_for_users(user_ids: list[int], organization_id: uuid.UUID) -> None:
    try:
        keys = [_unread_count_cache_key(uid, organization_id) for uid in user_ids]
        cache.delete_many(keys)
    except Exception:
        logger.exception("notifications.cache_bulk_invalidate_failed")
