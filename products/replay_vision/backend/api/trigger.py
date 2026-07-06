"""Shared Temporal trigger for on-demand scanner applications (observe and retry)."""

import enum
from uuid import UUID

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions import QuotaLimitExceeded
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.search_attributes import (
    POSTHOG_SCANNER_ID_KEY,
    POSTHOG_SESSION_RECORDING_ID_KEY,
    POSTHOG_TEAM_ID_KEY,
)

from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.quota import compute_quota_snapshot
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_EXECUTION_TIMEOUT,
    APPLY_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
)
from products.replay_vision.backend.temporal.types import ApplyScannerInputs

logger = structlog.get_logger(__name__)


class WorkflowStartOutcome(enum.Enum):
    STARTED = "started"
    # A workflow with our deterministic id is already running — the scan is effectively in progress.
    ALREADY_RUNNING = "already_running"
    FAILED = "failed"


def check_observation_quota(organization_id: UUID) -> None:
    """Raise 402 when the org's monthly observation quota is exhausted."""
    snapshot = compute_quota_snapshot(organization_id=organization_id)
    if snapshot.exhausted:
        raise QuotaLimitExceeded(
            detail=(
                f"Monthly Replay Vision quota of {snapshot.monthly_quota:,} observations reached. "
                f"Resets {snapshot.period_end.strftime('%b')} {snapshot.period_end.day}."
            )
        )


def start_apply_scanner_workflow(
    scanner: ReplayScanner, session_id: str, *, triggered_by_user_id: int
) -> tuple[str, WorkflowStartOutcome]:
    """Start the deterministic apply-scanner workflow for one (scanner, session); never raises."""
    workflow_id = build_apply_scanner_workflow_id(scanner.id, session_id)
    try:
        client = sync_connect()
        async_to_sync(client.start_workflow)(  # type: ignore[misc]
            APPLY_SCANNER_WORKFLOW_NAME,  # type: ignore[arg-type]
            ApplyScannerInputs(  # type: ignore[arg-type]
                scanner_id=scanner.id,
                session_id=session_id,
                team_id=scanner.team_id,
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=triggered_by_user_id,
            ),
            id=workflow_id,
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
            execution_timeout=APPLY_SCANNER_EXECUTION_TIMEOUT,
            # Stamp the scanner id so on-demand applies count toward the sweep's in-flight cap.
            search_attributes=TypedSearchAttributes(
                search_attributes=[
                    SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=scanner.team_id),
                    SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=session_id),
                    SearchAttributePair(key=POSTHOG_SCANNER_ID_KEY, value=str(scanner.id)),
                ]
            ),
        )
    except WorkflowAlreadyStartedError as exc:
        # Pin to our own workflow_id so a future id_reuse_policy change can't silently accept an unrelated run.
        if exc.workflow_id != workflow_id:
            logger.exception("replay_vision.observe.workflow_id_mismatch", workflow_id=workflow_id)
            return workflow_id, WorkflowStartOutcome.FAILED
        logger.info("replay_vision.observe.workflow_already_started", workflow_id=workflow_id)
        return workflow_id, WorkflowStartOutcome.ALREADY_RUNNING
    except Exception:
        logger.exception("replay_vision.observe.workflow_start_failed", workflow_id=workflow_id)
        return workflow_id, WorkflowStartOutcome.FAILED
    return workflow_id, WorkflowStartOutcome.STARTED
