"""Redis-backed payload passing between Replay Vision workflow activities."""

import gzip
from enum import Enum
from typing import TypeVar

from django.conf import settings

import structlog
from pydantic import BaseModel, ValidationError
from redis import asyncio as aioredis
from temporalio.exceptions import ApplicationError

from posthog.redis import get_async_client

from products.replay_vision.backend.temporal.types import ScannerLlmInputs

logger = structlog.get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

# Workflow runs should complete within an hour; 24h is generous headroom for retries.
REPLAY_VISION_STATE_REDIS_TTL_SECONDS = 60 * 60 * 24

KEY_BASE = "replay-vision:state"


class StateActivitiesEnum(Enum):
    SESSION_EVENTS = "session_events"


def generate_state_key(label: StateActivitiesEnum, state_id: str) -> str:
    """Deterministic key for inter-activity Redis state, namespaced by observation."""
    return f"{KEY_BASE}:{label.value}:{state_id}"


def get_redis_state_client(label: StateActivitiesEnum, state_id: str) -> tuple[aioredis.Redis, str]:
    """Return the Vision Redis client and the generated state key."""
    redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
    return redis_client, generate_state_key(label=label, state_id=state_id)


def _compress(data: str) -> bytes:
    return gzip.compress(data.encode("utf-8"))


def decompress(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        return gzip.decompress(raw).decode("utf-8")
    return raw


async def store_data_in_redis(
    redis_client: aioredis.Redis,
    redis_key: str,
    data: str,
    ttl: int = REPLAY_VISION_STATE_REDIS_TTL_SECONDS,
) -> None:
    await redis_client.setex(redis_key, ttl, _compress(data))


async def get_data_str_from_redis(redis_client: aioredis.Redis, redis_key: str) -> str | None:
    raw = await redis_client.get(redis_key)
    if not raw:
        return None
    try:
        return decompress(raw)
    except Exception as err:
        msg = f"Failed to decompress Redis payload at {redis_key}: {err}"
        logger.exception(msg, redis_key=redis_key)
        raise ValueError(msg) from err


async def get_data_class_from_redis(
    redis_client: aioredis.Redis,
    redis_key: str,
    target_class: type[TModel],
) -> TModel | None:
    data_str = await get_data_str_from_redis(redis_client, redis_key)
    if data_str is None:
        return None
    try:
        return target_class.model_validate_json(data_str)
    except ValidationError as err:
        # Stale-schema payloads will never parse — fail-fast instead of retrying for the full Redis TTL.
        msg = f"Failed to parse Redis payload at {redis_key} into {target_class.__name__}: {err}"
        logger.exception(msg, redis_key=redis_key)
        raise ApplicationError(msg, non_retryable=True) from err


async def load_scanner_llm_inputs(observation_id: str) -> ScannerLlmInputs | None:
    """Read the ScannerLlmInputs a scan stashed under the SESSION_EVENTS key; None if absent (its TTL has lapsed)."""
    redis_client, redis_key = get_redis_state_client(label=StateActivitiesEnum.SESSION_EVENTS, state_id=observation_id)
    return await get_data_class_from_redis(redis_client, redis_key, target_class=ScannerLlmInputs)
