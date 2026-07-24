"""Shared Temporal trigger for on-demand scanner applications (observe and retry)."""

import enum
from datetime import datetime
from uuid import UUID

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from rest_framework.exceptions import Throttled
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions import QuotaLimitExceeded
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.search_attributes import (
    POSTHOG_SCANNER_ID_KEY,
    POSTHOG_SESSION_RECORDING_ID_KEY,
    POSTHOG_TEAM_ID_KEY,
)

from products.replay_vision.backend.enqueue_claims import (
    pending_enqueue_claims_for_scanner,
    pending_enqueue_claims_for_team,
    release_enqueue_claim,
    try_claim_enqueue_slot,
)
from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.quota import compute_quota_snapshot
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_EXECUTION_TIMEOUT,
    APPLY_SCANNER_WORKFLOW_NAME,
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
    PROCESS_VISION_ACTION_EXECUTION_TIMEOUT,
    PROCESS_VISION_ACTION_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
    build_process_vision_action_workflow_id,
)
from products.replay_vision.backend.temporal.types import ApplyScannerInputs

logger = structlog.get_logger(__name__)


class WorkflowStartOutcome(enum.Enum):
    STARTED = "started"
    # A workflow with our deterministic id is already running — the scan is effectively in progress.
    ALREADY_RUNNING = "already_running"
    # The atomic enqueue-slot claim was refused: the in-flight caps have no headroom.
    CAPPED = "capped"
    FAILED = "failed"


def check_team_in_flight_capacity(team_id: int) -> None:
    """Raise 429 when in-flight rows plus enqueued-but-not-yet-persisted claims hit the team cap."""
    count = ReplayObservation.in_flight_for_team(team_id).count() + pending_enqueue_claims_for_team(team_id)
    if count >= MAX_IN_FLIGHT_APPLIES_PER_TEAM:
        raise Throttled(detail=f"This team already has {count} observations running. Try again in a few minutes.")


def check_observation_quota(organization_id: UUID, observation_credits: int) -> None:
    """Raise 402 when starting an observation of this credit cost would exceed the org's monthly limit."""
    snapshot = compute_quota_snapshot(organization_id=organization_id)
    if snapshot.would_exceed(observation_credits):
        # would_exceed is only ever true when a limit is set, so credit_limit is non-None here.
        assert snapshot.credit_limit is not None
        raise QuotaLimitExceeded(
            detail=(
                f"Starting this observation would exceed your monthly Replay vision limit of "
                f"${snapshot.credit_limit / 100:,.2f}. Resets {snapshot.period_end.strftime('%b')} "
                f"{snapshot.period_end.day}."
            )
        )


def _admission_still_within_caps(scanner: ReplayScanner) -> bool:
    """Validate a fresh claim against fresh counts. The claim is already registered, so this read
    sees every competitor, and rows younger than the decay grace are still covered by their claims;
    a pre-claim row snapshot staler than the grace self-corrects here instead of over-admitting."""
    in_flight = ReplayObservation.in_flight_for_team(scanner.team_id)
    if in_flight.count() + pending_enqueue_claims_for_team(scanner.team_id) > MAX_IN_FLIGHT_APPLIES_PER_TEAM:
        return False
    scanner_rows = in_flight.filter(scanner_id=scanner.id).count()
    return scanner_rows + pending_enqueue_claims_for_scanner(scanner.id) <= MAX_IN_FLIGHT_APPLIES_PER_SCANNER


def start_apply_scanner_workflow(
    scanner: ReplayScanner,
    session_id: str,
    *,
    triggered_by_user_id: int,
    trigger: ObservationTrigger,
    team_in_flight_rows: int | None = None,
    scanner_in_flight_rows: int | None = None,
) -> tuple[str, WorkflowStartOutcome]:
    """Start the deterministic apply-scanner workflow for one (scanner, session); never raises.
    An atomic enqueue-slot claim guards the in-flight caps; pass row counts to save two queries."""
    workflow_id = build_apply_scanner_workflow_id(scanner.id, session_id)
    if team_in_flight_rows is None:
        team_in_flight_rows = ReplayObservation.in_flight_for_team(scanner.team_id).count()
    if scanner_in_flight_rows is None:
        scanner_in_flight_rows = (
            ReplayObservation.in_flight_for_team(scanner.team_id).filter(scanner_id=scanner.id).count()
        )
    if not try_claim_enqueue_slot(
        team_id=scanner.team_id,
        scanner_id=scanner.id,
        workflow_id=workflow_id,
        team_in_flight_rows=team_in_flight_rows,
        scanner_in_flight_rows=scanner_in_flight_rows,
    ):
        return workflow_id, WorkflowStartOutcome.CAPPED
    if not _admission_still_within_caps(scanner):
        release_enqueue_claim(team_id=scanner.team_id, scanner_id=scanner.id, workflow_id=workflow_id)
        return workflow_id, WorkflowStartOutcome.CAPPED
    try:
        client = sync_connect()
        async_to_sync(client.start_workflow)(  # type: ignore[misc]
            APPLY_SCANNER_WORKFLOW_NAME,  # type: ignore[arg-type]
            ApplyScannerInputs(  # type: ignore[arg-type]
                scanner_id=scanner.id,
                session_id=session_id,
                team_id=scanner.team_id,
                triggered_by=trigger,
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
            release_enqueue_claim(team_id=scanner.team_id, scanner_id=scanner.id, workflow_id=workflow_id)
            return workflow_id, WorkflowStartOutcome.FAILED
        logger.info("replay_vision.observe.workflow_already_started", workflow_id=workflow_id)
        # A persisted row already counts this run, so our claim is a resurrected duplicate — drop
        # it. Without a row the running workflow is still in the enqueue gap: keep the claim.
        if ReplayObservation.objects.filter(scanner_id=scanner.id, session_id=session_id).exists():
            release_enqueue_claim(
                team_id=scanner.team_id, scanner_id=scanner.id, workflow_id=workflow_id, immediately=True
            )
        return workflow_id, WorkflowStartOutcome.ALREADY_RUNNING
    except Exception:
        logger.exception("replay_vision.observe.workflow_start_failed", workflow_id=workflow_id)
        release_enqueue_claim(team_id=scanner.team_id, scanner_id=scanner.id, workflow_id=workflow_id)
        return workflow_id, WorkflowStartOutcome.FAILED
    return workflow_id, WorkflowStartOutcome.STARTED


def start_process_vision_action_workflow(
    vision_action_id: UUID,
    team_id: int,
    *,
    scheduled_at: datetime,
) -> tuple[str, WorkflowStartOutcome]:
    """Start the per-action processing workflow on demand ("Run now"); never raises.

    Reuses the same deterministic workflow id as the scheduled sweep, so a manual run coalesces with
    an already-running run (scheduled or manual) rather than double-charging — ALREADY_RUNNING is
    returned in that case. The workflow never advances next_run_at, so the recurring schedule is
    untouched; passing scheduled_at=now just anchors this run's observation window at the present.
    """
    # Deferred: importing this triggers the vision_actions package __init__, which pulls the whole
    # engine (workflows + activities + LLM clients). Keep that off the API module-load path — only
    # the web process, only when Run now is actually invoked, pays for it.
    from products.replay_vision.backend.temporal.vision_actions.types import ProcessVisionActionInputs  # noqa: PLC0415

    workflow_id = build_process_vision_action_workflow_id(vision_action_id)
    try:
        client = sync_connect()
        async_to_sync(client.start_workflow)(  # type: ignore[misc]
            PROCESS_VISION_ACTION_WORKFLOW_NAME,  # type: ignore[arg-type]
            ProcessVisionActionInputs(  # type: ignore[arg-type]
                vision_action_id=vision_action_id,
                team_id=team_id,
                scheduled_at=scheduled_at,
                mode="group_summary",
            ),
            id=workflow_id,
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
            execution_timeout=PROCESS_VISION_ACTION_EXECUTION_TIMEOUT,
        )
    except WorkflowAlreadyStartedError as exc:
        if exc.workflow_id != workflow_id:
            logger.exception("replay_vision.run_now.workflow_id_mismatch", workflow_id=workflow_id)
            return workflow_id, WorkflowStartOutcome.FAILED
        logger.info("replay_vision.run_now.workflow_already_started", workflow_id=workflow_id)
        return workflow_id, WorkflowStartOutcome.ALREADY_RUNNING
    except Exception:
        logger.exception("replay_vision.run_now.workflow_start_failed", workflow_id=workflow_id)
        return workflow_id, WorkflowStartOutcome.FAILED
    return workflow_id, WorkflowStartOutcome.STARTED
