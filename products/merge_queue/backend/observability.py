"""Observability — the single QueueEvent emit point.

Invariant #2: every state mutation in the engine emits exactly one `QueueEvent`. Routing
all writes through `emit()` is how we hold that — the rest of the engine never constructs a
`QueueEvent` directly.

The append-only `QueueEvent` stream is also the source for `engineering_analytics`
emission. That ingestion path does not exist yet (open external dependency, sign-off #1),
so `_to_engineering_analytics()` is a stub.
"""

import logging
import dataclasses
from typing import Any

from posthog.sync import database_sync_to_async

from products.merge_queue.backend.facade.types import Actor
from products.merge_queue.backend.models import Enrollment, Partition, QueueEvent, QueueEventType, Slot, Trial

logger = logging.getLogger(__name__)


def emit(
    event_type: QueueEventType | str,
    *,
    actor: Actor | None = None,
    enrollment: Enrollment | None = None,
    slot: Slot | None = None,
    trial: Trial | None = None,
    partition: Partition | None = None,
    payload: dict[str, Any] | None = None,
) -> QueueEvent:
    """Write one `QueueEvent` row and forward it to engineering_analytics (stubbed)."""
    event = QueueEvent.objects.create(
        type=event_type,
        enrollment=enrollment,
        slot=slot,
        trial=trial,
        partition=partition,
        actor_id=actor.id if actor else None,
        actor_kind=str(actor.kind) if actor else None,
        payload=payload or {},
    )
    _to_engineering_analytics(event)
    return event


def _to_engineering_analytics(event: QueueEvent) -> None:
    """Forward a queue event to engineering_analytics.

    TODO(sign-off #1): the engineering_analytics event-ingestion path is net-new work and
    does not exist yet. Lean is `pull_request`-group-typed events through the
    PostHog event pipeline. Until it lands, this is a no-op; the QueueEvent row is the
    durable record.
    """
    return None


async def record_shadow(hook: str, args: tuple, kwargs: dict, taken: Any) -> None:
    """Record a Cowboy would-be decision as a SHADOW_DECISION event.

    Wired into `GatedProvider`; currently dormant because `cowboy=None`. `would_be` (the actual
    Cowboy call) is filled in when Cowboy lands; for now we capture the hook and the
    deterministic decision that was taken.
    """
    await database_sync_to_async(emit)(
        QueueEventType.SHADOW_DECISION,
        payload={"hook": hook, "would_be": None, "taken": _serialize(taken)},
    )


def _serialize(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, list | tuple):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value if isinstance(value, str | int | float | bool | None.__class__) else str(value)
