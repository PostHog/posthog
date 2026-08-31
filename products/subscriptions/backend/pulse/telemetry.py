"""Best-effort, privacy-safe product telemetry for Pulse lifecycle events."""

from uuid import UUID

import structlog

from posthog.ph_client import ph_scoped_capture

_TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled", "skipped"})
_DELIVERY_DESTINATIONS = frozenset({"email", "slack"})
_DELIVERY_OUTCOMES = frozenset({"accepted", "failed", "delivery_unknown"})
_OUTCOME_EVENTS = frozenset(
    {
        "pulse_outcome_plan_created",
        "pulse_outcome_suppressed",
        "pulse_outcome_claimed",
        "pulse_outcome_attempted",
        "pulse_outcome_adoption",
    }
)
_OUTCOME_STATUSES = frozenset(
    {
        "measured",
        "inconclusive",
        "failed",
        "not_ready",
        "claimed",
        "reclaimed",
        "suppressed",
        "adopted",
        "dismissed",
        "abandoned",
    }
)
_OUTCOME_VERDICTS = frozenset({"improved", "flat", "regressed", "inconclusive"})
_OUTCOME_REASONS = frozenset({"evidence_unavailable", "measurement_inconclusive", "not_ready_expired"})
_OUTCOME_SOURCES = frozenset({"pull_request_merged", "experiment_launched", "manual"})
_OUTCOME_ABANDON_REASONS = frozenset({"pull_request_closed", "experiment_deleted"})

logger = structlog.get_logger(__name__)


def capture_pulse_run_started(*, team_id: int, run_id: UUID) -> None:
    _capture(team_id=team_id, run_id=run_id, event="pulse_run_started", properties={})


def capture_pulse_run_terminalized(*, team_id: int, run_id: UUID, status: str) -> None:
    if status not in _TERMINAL_STATUSES:
        raise ValueError("Pulse telemetry status is not terminal.")
    _capture(team_id=team_id, run_id=run_id, event="pulse_run_terminalized", properties={"status": status})


def capture_pulse_delivery_prepared(*, team_id: int, run_id: UUID, destination: str) -> None:
    _validate_destination(destination)
    _capture(
        team_id=team_id,
        run_id=run_id,
        event="pulse_delivery_prepared",
        properties={"destination": destination},
    )


def capture_pulse_delivery_finished(*, team_id: int, run_id: UUID, destination: str, outcome: str) -> None:
    _validate_destination(destination)
    if outcome not in _DELIVERY_OUTCOMES:
        raise ValueError("Pulse telemetry delivery outcome is invalid.")
    _capture(
        team_id=team_id,
        run_id=run_id,
        event="pulse_delivery_finished",
        properties={"destination": destination, "outcome": outcome},
    )


def capture_pulse_outcome(
    *,
    team_id: int,
    run_id: UUID,
    event: str,
    plan_id: UUID | None = None,
    status: str | None = None,
    count: int | None = None,
    verdict: str | None = None,
    reason: str | None = None,
    delay_days: int | None = None,
    source: str | None = None,
) -> None:
    """Capture outcome transitions with bounded identifiers and enums only."""
    if event not in _OUTCOME_EVENTS or status is not None and status not in _OUTCOME_STATUSES:
        raise ValueError("Pulse outcome telemetry is invalid.")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > 100):
        raise ValueError("Pulse outcome telemetry count is invalid.")
    if (verdict is not None and verdict not in _OUTCOME_VERDICTS) or (
        reason is not None and reason not in _OUTCOME_REASONS
    ):
        raise ValueError("Pulse outcome telemetry evaluation is invalid.")
    if delay_days is not None and delay_days not in {3, 7, 14, 28}:
        raise ValueError("Pulse outcome telemetry delay is invalid.")
    if source is not None and source not in _OUTCOME_SOURCES | _OUTCOME_ABANDON_REASONS:
        raise ValueError("Pulse outcome telemetry source is invalid.")
    properties: dict[str, str | int] = {}
    if plan_id is not None:
        properties["plan_id"] = str(plan_id)
    if status is not None:
        properties["status"] = status
    if count is not None:
        properties["count"] = count
    if verdict is not None:
        properties["verdict"] = verdict
    if reason is not None:
        properties["reason"] = reason
    if delay_days is not None:
        properties["delay_days"] = delay_days
    if source is not None:
        properties["source"] = source
    _capture(team_id=team_id, run_id=run_id, event=event, properties=properties)


def _capture(*, team_id: int, run_id: UUID, event: str, properties: dict[str, str | int]) -> None:
    """Capture only server-owned IDs and finite lifecycle states; never break delivery."""
    try:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=f"pulse:{team_id}",
                event=event,
                properties={"run_id": str(run_id), **properties},
            )
    except Exception:
        logger.warning("pulse_telemetry_capture_failed", pulse_event=event, exc_info=True)


def _validate_destination(destination: str) -> None:
    if destination not in _DELIVERY_DESTINATIONS:
        raise ValueError("Pulse telemetry destination is invalid.")
