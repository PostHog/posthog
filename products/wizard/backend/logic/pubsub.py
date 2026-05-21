"""
Redis pub/sub fanout for wizard session updates.

Publish happens inside `transaction.on_commit` so subscribers never see
uncommitted state. Subscribers (SSE endpoint) consume via `subscribe()`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from typing import Any

from django.db import transaction

import orjson
import structlog

from posthog.redis import get_client

from products.wizard.backend.facade.contracts import WizardSessionDTO

logger = structlog.get_logger(__name__)

CHANNEL_PREFIX = "wizard_sessions"


def channel_name(team_id: int, workflow_id: str, skill_id: str) -> str:
    return f"{CHANNEL_PREFIX}:team:{team_id}:workflow:{workflow_id}:skill:{skill_id}"


def channel_pattern(team_id: int, workflow_id: str) -> str:
    """Pattern for subscribing to all skills under a (team, workflow_id)."""
    return f"{CHANNEL_PREFIX}:team:{team_id}:workflow:{workflow_id}:skill:*"


def publish_session_update(dto: WizardSessionDTO) -> None:
    """Schedule a Redis publish for after the current transaction commits.

    Safe to call outside a transaction (publishes immediately).
    """
    payload = orjson.dumps(dto, default=_json_default)
    channel = channel_name(dto.team_id, dto.workflow_id, dto.skill_id)

    def _publish() -> None:
        receivers = get_client().publish(channel, payload)
        logger.info(
            "wizard_sessions publish",
            channel=channel,
            session_id=dto.session_id,
            run_phase=dto.run_phase.value if hasattr(dto.run_phase, "value") else str(dto.run_phase),
            payload_bytes=len(payload),
            receivers=receivers,
        )

    transaction.on_commit(_publish)


@contextmanager
def subscribe(team_id: int, workflow_id: str, skill_id: str | None = None) -> Iterator[Any]:
    """Subscribe to wizard-session events.

    If `skill_id` is provided, subscribes to the exact channel for that
    (team, workflow, skill). If omitted, pattern-subscribes to every skill
    under that (team, workflow). Pattern messages arrive as `{type: 'pmessage', ...}`;
    direct messages as `{type: 'message', ...}`. Callers should accept both.
    """
    redis = get_client()
    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    if skill_id:
        target = channel_name(team_id, workflow_id, skill_id)
        pubsub.subscribe(target)
        logger.info("wizard_sessions subscribe", channel=target)
    else:
        target = channel_pattern(team_id, workflow_id)
        pubsub.psubscribe(target)
        logger.info("wizard_sessions subscribe", pattern=target)
    try:
        yield pubsub
    finally:
        logger.info("wizard_sessions unsubscribe", target=target)
        try:
            if skill_id:
                pubsub.unsubscribe(target)
            else:
                pubsub.punsubscribe(target)
        finally:
            pubsub.close()


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
