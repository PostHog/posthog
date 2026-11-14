import uuid
from typing import TypedDict

from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

UNREAD_COUNT_TTL_SECONDS = 60
UNREAD_SUMMARY_KEY_PREFIX = "notifications_unread_summary"


class UnreadSummary(TypedDict):
    count: int
    direct_count: int
    has_critical: bool


def _unread_count_cache_key(user_id: int, organization_id: uuid.UUID) -> str:
    return f"{UNREAD_SUMMARY_KEY_PREFIX}:{user_id}:{organization_id}"


def get_unread_summary(user_id: int, organization_id: uuid.UUID) -> UnreadSummary | None:
    try:
        return cache.get(_unread_count_cache_key(user_id, organization_id))
    except Exception:
        logger.exception("notifications.cache_get_failed")
        return None


def set_unread_summary(user_id: int, organization_id: uuid.UUID, summary: UnreadSummary) -> None:
    try:
        cache.set(_unread_count_cache_key(user_id, organization_id), summary, UNREAD_COUNT_TTL_SECONDS)
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
