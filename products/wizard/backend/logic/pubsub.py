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

from posthog.redis import get_client

from products.wizard.backend.facade.contracts import WizardSessionDTO

CHANNEL_PREFIX = "wizard_sessions"


def channel_name(team_id: int, workflow_id: str, skill_id: str) -> str:
    return f"{CHANNEL_PREFIX}:team:{team_id}:workflow:{workflow_id}:skill:{skill_id}"


def publish_session_update(dto: WizardSessionDTO) -> None:
    """Schedule a Redis publish for after the current transaction commits.

    Safe to call outside a transaction (publishes immediately).
    """
    payload = orjson.dumps(dto, default=_json_default)
    channel = channel_name(dto.team_id, dto.workflow_id, dto.skill_id)

    def _publish() -> None:
        get_client().publish(channel, payload)

    transaction.on_commit(_publish)


@contextmanager
def subscribe(team_id: int, workflow_id: str, skill_id: str) -> Iterator[Any]:
    """Subscribe to a wizard-session channel. Yields a pubsub object whose
    `listen()` produces dicts with `{type, data, ...}`.

    The caller is responsible for iterating; this context manager only owns
    the connection lifecycle.
    """
    redis = get_client()
    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    channel = channel_name(team_id, workflow_id, skill_id)
    pubsub.subscribe(channel)
    try:
        yield pubsub
    finally:
        try:
            pubsub.unsubscribe(channel)
        finally:
            pubsub.close()


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
