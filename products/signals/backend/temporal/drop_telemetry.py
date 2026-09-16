import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.event_usage import groups
from posthog.models import Team
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.facade.api import _telemetry_props_from_extra
from products.signals.backend.temporal import metrics
from products.signals.backend.temporal.types import EmitSignalInputs

logger = structlog.get_logger(__name__)

# Gate so workflows replaying history recorded before this event existed don't
# schedule a command their history doesn't have (Temporal nondeterminism).
_PATCH_SIGNAL_DROPPED = "signal-dropped-telemetry-v1"
# Same reason: a history recorded before the batch collapse holds one capture command per signal.
_PATCH_BATCH_SIGNAL_DROPPED = "signal-dropped-batch-telemetry-v1"

# Stands in for a per-signal value that the signals of one batch attempt do not agree on.
_MIXED_BATCH_VALUE = "mixed"

_MAX_ERROR_LENGTH = 500


@dataclass(frozen=False)
class CaptureSignalDroppedInput:
    team_id: int
    source_product: str
    source_type: str
    source_id: str
    weight: float
    stage: str
    error_type: str
    error: str
    extra: dict = field(default_factory=dict)
    # Signals this event accounts for: 1 per signal, or the whole batch on a batch attempt.
    signal_count: int = 1


def summarize_drop_error(error: BaseException) -> tuple[str, str]:
    """Extract the most specific (type, message) from a (possibly wrapped) activity error.

    Temporal wraps the real failure: an ActivityError's `cause` is an ApplicationError
    whose `type` carries the original exception class name (e.g. "OperationalError").
    """
    cause = getattr(error, "cause", None) or error.__cause__ or error
    error_type = getattr(cause, "type", None) or type(cause).__name__
    # First line only: multi-line messages (pydantic validation errors, LLM response
    # dumps) carry customer-derived values on continuation lines that must not reach
    # product analytics. Infra failures (DB, timeout) are single-line and unaffected.
    message = str(cause).partition("\n")[0][:_MAX_ERROR_LENGTH]
    return error_type, message


@activity.defn
@scoped_temporal()
@close_db_connections
async def capture_signal_dropped_activity(input: CaptureSignalDroppedInput) -> None:
    """Emit a lifecycle event when the pipeline drops a signal, so drops are trackable per signal."""
    metrics.increment_dropped(stage=input.stage, reason=input.error_type, count=input.signal_count)
    try:
        team = await Team.objects.select_related("organization").aget(pk=input.team_id)
        posthoganalytics.capture(
            event="signal_dropped",
            distinct_id=str(team.uuid),
            properties={
                # Flattened scalars only (truncated, nested lists/dicts dropped) — `extra`
                # nests customer-derived content that must not leak into product analytics.
                # Core keys win on conflict, same as signal_emitted / signal_emission_started.
                **_telemetry_props_from_extra(input.extra),
                # Composite of stage + error_type so drops are distinguishable by `reason`
                # alone — a transient ConnectError burst reads differently from the chronic
                # ClickHouseAtCapacity baseline instead of collapsing to one constant.
                "reason": f"{input.stage}:{input.error_type}",
                "stage": input.stage,
                "error_type": input.error_type,
                "error": input.error,
                "source_product": input.source_product,
                "source_type": input.source_type,
                "source_id": input.source_id,
                "weight": input.weight,
                "signal_count": input.signal_count,
            },
            groups=groups(team.organization, team),
        )
    except Exception as e:
        # Swallow the exception, to avoid breaking the flow over a failed analytics event
        posthoganalytics.capture_exception(e)
        logger.exception(
            "Failed to capture signal_dropped event",
            team_id=input.team_id,
            source_id=input.source_id,
        )


async def _schedule_capture(input: CaptureSignalDroppedInput) -> None:
    """Schedule the capture activity, swallowing any failure so telemetry never breaks the flow."""
    try:
        await workflow.execute_activity(
            capture_signal_dropped_activity,
            input,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
    except Exception:
        logger.exception(
            "Failed to schedule signal_dropped capture",
            team_id=input.team_id,
            source_id=input.source_id,
            signal_count=input.signal_count,
        )


async def capture_signal_dropped(signal: EmitSignalInputs, error: BaseException, stage: str) -> None:
    """Best-effort signal_dropped telemetry from workflow code; never raises into the grouping flow."""
    if not workflow.patched(_PATCH_SIGNAL_DROPPED):
        return
    error_type, error_message = summarize_drop_error(error)
    await _schedule_capture(
        CaptureSignalDroppedInput(
            team_id=signal.team_id,
            source_product=signal.source_product,
            source_type=signal.source_type,
            source_id=signal.source_id,
            weight=signal.weight,
            stage=stage,
            error_type=error_type,
            error=error_message,
            # Flatten before scheduling: the raw `extra` can nest large customer-derived
            # payloads, and the activity input is recorded verbatim in workflow history.
            extra=_telemetry_props_from_extra(signal.extra),
        )
    )


def _shared_or_mixed(values: Iterable[str]) -> str:
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else _MIXED_BATCH_VALUE


async def capture_signal_batch_dropped(batch: list[EmitSignalInputs], error: BaseException, stage: str) -> None:
    """One drop event for a whole batch attempt, instead of one per signal in it.

    A prep failure loses every signal of the batch to the same error and the batch is retried, so a
    per-signal event multiplies one dependency outage into tens of thousands of events, and makes the
    drop metric unreadable exactly when someone reads it to diagnose that outage. `signal_count`
    carries the lost volume, and `weight` the batch total.
    """
    if not batch:
        return
    if not workflow.patched(_PATCH_BATCH_SIGNAL_DROPPED):
        await asyncio.gather(*(capture_signal_dropped(signal, error, stage=stage) for signal in batch))
        return
    error_type, error_message = summarize_drop_error(error)
    await _schedule_capture(
        CaptureSignalDroppedInput(
            team_id=batch[0].team_id,
            source_product=_shared_or_mixed(signal.source_product for signal in batch),
            source_type=_shared_or_mixed(signal.source_type for signal in batch),
            # A batch attempt has no single source, and `extra` carries per-signal
            # customer-derived content that cannot be merged across the batch.
            source_id="",
            weight=sum(signal.weight for signal in batch),
            stage=stage,
            error_type=error_type,
            error=error_message,
            signal_count=len(batch),
        )
    )
