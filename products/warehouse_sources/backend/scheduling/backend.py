"""Decide which scheduler runs a schema.

The flag records intent only. A later migrate command removes the Temporal Schedule.
The queue scheduler fires only schemas whose Temporal Schedule it removed.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from django.conf import settings

import structlog

from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_schema_flag_enabled

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)

QUEUE_SCHEDULER_FLAG = "warehouse-queue-scheduler"
DEFAULT_CACHE_TTL_SECONDS = 60.0

# schema id -> (expiry on the monotonic clock, flag value)
_cache: dict[str, tuple[float, bool]] = {}


def uses_queue_scheduler(schema: ExternalDataSchema, *, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS) -> bool:
    """Return True when the flag routes this schema to the queue scheduler.

    Any failure returns False, so the schema stays on Temporal.
    """
    key = str(schema.id)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    try:
        enabled = is_schema_flag_enabled(schema, QUEUE_SCHEDULER_FLAG)
    except Exception:
        logger.warning("queue_scheduler_flag_failed", schema_id=key, exc_info=True)
        return False

    _cache[key] = (now + ttl_seconds, enabled)
    return enabled


def clear_queue_scheduler_cache() -> None:
    _cache.clear()


def queue_scheduler_firing_enabled() -> bool:
    return bool(settings.WAREHOUSE_QUEUE_SCHEDULER_FIRING_ENABLED)
