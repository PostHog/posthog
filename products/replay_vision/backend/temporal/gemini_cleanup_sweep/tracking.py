"""Redis tracking for Gemini files uploaded by Replay Vision scanner workflows."""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai.errors import APIError
from redis import asyncio as aioredis

if TYPE_CHECKING:
    from google.genai import Client as RawGenAIClient

from posthog.redis import get_async_client

from products.replay_vision.backend.temporal.gemini_cleanup_sweep.constants import (
    MGET_BATCH_SIZE,
    REDIS_INDEX_KEY,
    REDIS_KEY_PREFIX,
    REDIS_KEY_TTL,
)
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.types import TrackedFile

logger = structlog.get_logger(__name__)


def is_gemini_file_gone(error: Exception) -> bool:
    """Whether a Gemini delete failure means the file no longer exists. Gemini reports missing
    files as 403 PERMISSION_DENIED ("...or it may not exist"), not just 404 — callers should
    untrack on either instead of retrying a doomed delete."""
    return isinstance(error, APIError) and error.code in (403, 404)


async def delete_and_untrack(
    raw_client: "RawGenAIClient", gemini_file_name: str, *, log_source: str, **log_kwargs: Any
) -> bool:
    """Delete the Gemini file and drop its tracking key; returns False (key kept for retry) on transient failure."""
    try:
        await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=gemini_file_name)
    except Exception as e:
        if not is_gemini_file_gone(e):
            logger.exception(f"{log_source}.delete_failed", gemini_file_name=gemini_file_name, **log_kwargs)
            return False
        # File already gone (e.g. a previous untrack failed) — drop the key so we don't retry a doomed delete.
        logger.info(f"{log_source}.delete_already_gone", gemini_file_name=gemini_file_name, **log_kwargs)
    await untrack_uploaded_file(gemini_file_name)
    return True


def _redis() -> aioredis.Redis:
    return get_async_client(settings.REPLAY_VISION_REDIS_URL)


def _redis_key_for(gemini_file_name: str) -> str:
    return f"{REDIS_KEY_PREFIX}{gemini_file_name}"


def _to_str(raw: str | bytes) -> str:
    return raw.decode() if isinstance(raw, bytes) else raw


def _to_str_optional(raw: str | bytes | None) -> str | None:
    return None if raw is None else _to_str(raw)


async def track_uploaded_file(gemini_file_name: str, workflow_id: str, uploaded_at: datetime) -> None:
    """Raises on Redis failure so the caller can roll back the upload."""
    redis = _redis()
    payload = json.dumps({"workflow_id": workflow_id, "uploaded_at": uploaded_at.isoformat()})
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(_redis_key_for(gemini_file_name), payload, ex=int(REDIS_KEY_TTL.total_seconds()))
        pipe.zadd(REDIS_INDEX_KEY, {gemini_file_name: uploaded_at.timestamp()})
        await pipe.execute()


async def untrack_uploaded_file(gemini_file_name: str) -> None:
    """Best-effort: TTL or sweep stale-cleanup handle leftover state on failure."""
    redis = _redis()
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.delete(_redis_key_for(gemini_file_name))
            pipe.zrem(REDIS_INDEX_KEY, gemini_file_name)
            await pipe.execute()
    except Exception:
        logger.exception(
            "replay_vision.gemini_cleanup_sweep.untrack_failed",
            gemini_file_name=gemini_file_name,
            signals_type="cleanup-sweep",
        )


async def iter_tracked_files(limit: int) -> AsyncIterator[TrackedFile | None]:
    """Yield up to ``limit`` tracked files, oldest-uploaded first. Bounded server-side via
    ZRANGE LIMIT so the fetch cost is independent of total backlog. Yields ``None`` for
    undecodable payloads. Drops stale index entries (per-file key TTL'd out) as it goes."""
    redis = _redis()
    raw_members = await redis.zrange(REDIS_INDEX_KEY, 0, limit - 1)
    file_names: list[str] = [_to_str(m) for m in raw_members]
    if not file_names:
        return

    for batch_start in range(0, len(file_names), MGET_BATCH_SIZE):
        batch = file_names[batch_start : batch_start + MGET_BATCH_SIZE]
        keys = [_redis_key_for(fn) for fn in batch]
        raw_values = await redis.mget(*keys)
        stale: list[str] = []
        for fn, raw in zip(batch, raw_values):
            value = _to_str_optional(raw)
            if value is None:
                stale.append(fn)
                continue
            try:
                payload = json.loads(value)
                workflow_id = payload["workflow_id"]
                uploaded_at = datetime.fromisoformat(payload["uploaded_at"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                logger.exception(
                    "replay_vision.gemini_cleanup_sweep.invalid_value",
                    gemini_file_name=fn,
                    signals_type="cleanup-sweep",
                )
                yield None
                continue
            yield TrackedFile(
                gemini_file_name=fn,
                workflow_id=workflow_id,
                uploaded_at=uploaded_at,
            )
        if stale:
            await redis.zrem(REDIS_INDEX_KEY, *stale)


async def index_size() -> int:
    redis = _redis()
    return await redis.zcard(REDIS_INDEX_KEY)
