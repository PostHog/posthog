"""
Redis pub/sub fanout for wizard session updates.

Publish happens inside `transaction.on_commit` so subscribers never see
uncommitted state. Subscribers (SSE endpoint) use the async client so each
idle connection is a coroutine on the event loop, not a thread pinning the
asgiref pool.
"""

from __future__ import annotations

import re
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from typing import Any

from django.db import transaction

import orjson
import structlog

from posthog.redis import get_async_client, get_client

from products.wizard.backend.facade.contracts import WizardSessionDTO
from products.wizard.backend.metrics import WIZARD_PUBSUB_PUBLISH_TOTAL

logger = structlog.get_logger(__name__)

CHANNEL_PREFIX = "wizard_sessions"

# workflow_id / skill_id appear unescaped in Redis channel names / patterns;
# reject anything that could be a glob metacharacter (`*?[]\`) or the `:` delimiter.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,255}$")


def _validate_id(value: str, name: str) -> None:
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"{name} must match {_SAFE_ID_RE.pattern}; got {value!r}")


def channel_name(team_id: int, workflow_id: str, skill_id: str) -> str:
    _validate_id(workflow_id, "workflow_id")
    _validate_id(skill_id, "skill_id")
    return f"{CHANNEL_PREFIX}:team:{team_id}:workflow:{workflow_id}:skill:{skill_id}"


def channel_pattern(team_id: int, workflow_id: str) -> str:
    """Pattern for subscribing to all skills under a (team, workflow_id)."""
    _validate_id(workflow_id, "workflow_id")
    return f"{CHANNEL_PREFIX}:team:{team_id}:workflow:{workflow_id}:skill:*"


def serialize_dto(dto: WizardSessionDTO) -> bytes:
    return orjson.dumps(dto, default=_json_default)


def publish_session_update(dto: WizardSessionDTO) -> None:
    """Schedule a Redis publish after the current transaction commits.

    Publish failures are logged and swallowed — fanout is best-effort and
    must not fail the already-committed upsert.
    """
    payload = serialize_dto(dto)
    channel = channel_name(dto.team_id, dto.workflow_id, dto.skill_id)

    def _publish() -> None:
        try:
            receivers = get_client().publish(channel, payload)
        except Exception:
            WIZARD_PUBSUB_PUBLISH_TOTAL.labels(outcome="failed").inc()
            logger.exception(
                "wizard_sessions publish failed",
                channel=channel,
                session_id=dto.session_id,
                payload_bytes=len(payload),
            )
            return
        WIZARD_PUBSUB_PUBLISH_TOTAL.labels(outcome="published").inc()
        logger.debug(
            "wizard_sessions publish",
            channel=channel,
            session_id=dto.session_id,
            run_phase=dto.run_phase.value,
            payload_bytes=len(payload),
            receivers=receivers,
        )

    transaction.on_commit(_publish)


@asynccontextmanager
async def subscribe(team_id: int, workflow_id: str, skill_id: str | None = None) -> AsyncIterator[Any]:
    """Subscribe to wizard-session events.

    With `skill_id`, subscribes to the exact `(team, workflow, skill)` channel.
    Without it, pattern-subscribes to every skill under `(team, workflow)`;
    messages arrive as `{type: 'pmessage', ...}` instead of `{type: 'message'}`.
    """
    if skill_id is not None:
        target = channel_name(team_id, workflow_id, skill_id)
        is_pattern = False
    else:
        target = channel_pattern(team_id, workflow_id)
        is_pattern = True

    redis = get_async_client()
    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    try:
        if is_pattern:
            await pubsub.psubscribe(target)
        else:
            await pubsub.subscribe(target)
    except Exception:
        try:
            await pubsub.close()
        except Exception:
            pass
        raise

    try:
        yield pubsub
    finally:
        try:
            if is_pattern:
                await pubsub.punsubscribe(target)
            else:
                await pubsub.unsubscribe(target)
        except Exception:
            logger.warning("wizard_sessions unsubscribe failed", target=target)
        finally:
            try:
                await pubsub.close()
            except Exception:
                logger.warning("wizard_sessions pubsub close failed", target=target)


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
