from __future__ import annotations

import asyncio

import structlog
from cachetools import TTLCache
from posthoganalytics import Posthog

from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)

GLM_MODAL_FLAG = "tasks-glm-modal-inference"
GLM_BASETEN_FLAG = "tasks-glm-baseten-inference"

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


async def evaluate_flags(flag_keys: list[str], distinct_id: str) -> dict[str, bool | None]:
    unique_keys = list(dict.fromkeys(flag_keys))
    results: dict[str, bool | None] = {}
    missing_keys: list[str] = []
    for flag_key in unique_keys:
        cache_key = (flag_key, distinct_id)
        if cache_key in _flag_cache:
            results[flag_key] = _flag_cache[cache_key]
        elif flag_key in _flag_unavailable_cache:
            results[flag_key] = None
        else:
            missing_keys.append(flag_key)

    if not missing_keys:
        return results

    client = _get_client()
    if client is None:
        return {flag_key: results.get(flag_key) for flag_key in unique_keys}

    try:
        snapshot = await asyncio.to_thread(client.evaluate_flags, distinct_id, flag_keys=missing_keys)
    except Exception as exc:
        logger.warning("flag_evaluation_failed", flags=missing_keys, error=str(exc))
        for flag_key in missing_keys:
            _flag_unavailable_cache[flag_key] = True
            results[flag_key] = None
        return {flag_key: results[flag_key] for flag_key in unique_keys}

    evaluated_keys = set(snapshot.keys)

    for flag_key in missing_keys:
        if flag_key not in evaluated_keys:
            _flag_unavailable_cache[flag_key] = True
            results[flag_key] = None
            continue
        enabled = snapshot.is_enabled(flag_key)
        _flag_cache[(flag_key, distinct_id)] = enabled
        results[flag_key] = enabled

    return {flag_key: results[flag_key] for flag_key in unique_keys}


async def evaluate_flag(flag_key: str, distinct_id: str) -> bool | None:
    """None when evaluation is unavailable, so callers can apply their default."""
    return (await evaluate_flags([flag_key], distinct_id))[flag_key]
