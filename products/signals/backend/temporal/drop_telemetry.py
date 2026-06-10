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

from products.signals.backend.temporal.types import EmitSignalInputs

logger = structlog.get_logger(__name__)

# Gate so workflows replaying history recorded before this event existed don't
# schedule a command their history doesn't have (Temporal nondeterminism).
_PATCH_SIGNAL_DROPPED = "signal-dropped-telemetry-v1"

_MAX_ERROR_LENGTH = 500


@dataclass
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


def _summarize_drop_error(error: BaseException) -> tuple[str, str]:
    """Extract the most specific (type, message) from a (possibly wrapped) activity error.

    Temporal wraps the real failure: an ActivityError's `cause` is an ApplicationError
    whose `type` carries the original exception class name (e.g. "OperationalError").
    """
    cause = getattr(error, "cause", None) or error.__cause__ or error
    error_type = getattr(cause, "type", None) or type(cause).__name__
    return error_type, str(cause)[:_MAX_ERROR_LENGTH]


@activity.defn
@scoped_temporal()
@close_db_connections
async def capture_signal_dropped_activity(input: CaptureSignalDroppedInput) -> None:
    """Emit a lifecycle event when the pipeline drops a signal, so drops are trackable per signal."""
    try:
        team = await Team.objects.select_related("organization").aget(pk=input.team_id)
        posthoganalytics.capture(
            event="signal_dropped",
            distinct_id=str(team.uuid),
            properties={
                "reason": "grouping_processing_error",
                "stage": input.stage,
                "error_type": input.error_type,
                "error": input.error,
                "source_product": input.source_product,
                "source_type": input.source_type,
                "source_id": input.source_id,
                "weight": input.weight,
                "extra": input.extra,
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


async def capture_signal_dropped(signal: EmitSignalInputs, error: BaseException, stage: str) -> None:
    """Best-effort signal_dropped telemetry from workflow code; never raises into the grouping flow."""
    if not workflow.patched(_PATCH_SIGNAL_DROPPED):
        return
    error_type, error_message = _summarize_drop_error(error)
    try:
        await workflow.execute_activity(
            capture_signal_dropped_activity,
            CaptureSignalDroppedInput(
                team_id=signal.team_id,
                source_product=signal.source_product,
                source_type=signal.source_type,
                source_id=signal.source_id,
                weight=signal.weight,
                stage=stage,
                error_type=error_type,
                error=error_message,
                extra=signal.extra,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
    except Exception:
        logger.exception(
            "Failed to schedule signal_dropped capture",
            team_id=signal.team_id,
            source_id=signal.source_id,
        )
