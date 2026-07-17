from __future__ import annotations

import asyncio

import structlog
from cachetools import TTLCache
from posthoganalytics import Posthog

from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)

GLM_MODAL_FLAG = "tasks-glm-modal-inference"

_flag_cache: TTLCache[tuple[str, str], bool] = TTLCache(maxsize=10_000, ttl=60)
# Global per-flag backoff so an evaluation outage doesn't stack one blocking roundtrip per new user.
_flag_unavailable_cache: TTLCache[str, bool] = TTLCache(maxsize=100, ttl=5)
_client: Posthog | None = None


def _get_client() -> Posthog | None:
    global _client
    settings = get_settings()
    if not settings.posthog_project_token:
        return None
    if _client is None:
        _client = Posthog(
            settings.posthog_project_token,
            host=settings.posthog_host,
            sync_mode=True,
            enable_local_evaluation=False,
            feature_flags_request_timeout_seconds=2,
        )
    return _client


async def evaluate_flag(flag_key: str, distinct_id: str) -> bool | None:
    """None when evaluation is unavailable — callers fall back to their own default."""
    cache_key = (flag_key, distinct_id)
    if cache_key in _flag_cache:
        return _flag_cache[cache_key]
    if flag_key in _flag_unavailable_cache:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        # Blocking /flags roundtrip — keep it off the event loop. send_feature_flag_events=False:
        # with sync_mode the default would also block on a $feature_flag_called capture upload
        # (15s SDK timeout) for every uncached user.
        enabled = await asyncio.to_thread(client.feature_enabled, flag_key, distinct_id, send_feature_flag_events=False)
    except Exception as exc:
        logger.warning("flag_evaluation_failed", flag=flag_key, error=str(exc))
        _flag_unavailable_cache[flag_key] = True
        return None
    if enabled is None:
        _flag_unavailable_cache[flag_key] = True
        return None
    _flag_cache[cache_key] = bool(enabled)
    return bool(enabled)
