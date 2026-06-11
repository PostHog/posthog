import uuid
import random
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.grouping import (
    WEIGHT_THRESHOLD,
    AssignAndEmitSignalInput,
    assign_and_emit_signal_activity,
)
from products.signals.backend.temporal.types import (
    ExistingReportMatch,
    MatchedMetadata,
    NewReportMatch,
    NoMatchMetadata,
)

GROUPING_MODULE_PATH = "products.signals.backend.temporal.grouping"


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsAssignOrg-{random.randint(1, 99999)}",
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsAssignTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


@pytest.fixture(autouse=True)
def patch_side_effects():
    """Mock only the external side effects (Kafka, analytics, ClickHouse). The Postgres state
    machine is the SUT and is exercised against a real DB."""
    with (
        patch(f"{GROUPING_MODULE_PATH}.emit_embedding_request") as emit_mock,
        patch(f"{GROUPING_MODULE_PATH}.posthoganalytics.capture") as capture_mock,
        patch(f"{GROUPING_MODULE_PATH}.soft_delete_report_signals") as soft_delete_mock,
    ):
        yield {"emit": emit_mock, "capture": capture_mock, "soft_delete": soft_delete_mock}


def _existing_match(report_id: str) -> ExistingReportMatch:
    return ExistingReportMatch(
        report_id=report_id,
        match_metadata=MatchedMetadata(
            parent_signal_id=str(uuid.uuid4()),
            match_query="test query",
            reason="similar content",
        ),
    )


def _new_match(title: str = "Test title", summary: str = "Test summary") -> NewReportMatch:
    return NewReportMatch(
        title=title,
        summary=summary,
        match_metadata=NoMatchMetadata(reason="no matching candidates"),
    )


def _build_input(
    team_id: int,
    match_result: ExistingReportMatch | NewReportMatch,
    weight: float = 0.5,
) -> AssignAndEmitSignalInput:
    return AssignAndEmitSignalInput(
        team_id=team_id,
        signal_id=str(uuid.uuid4()),
        description="A test signal description",
        weight=weight,
        source_product="conversations",
        source_type="ticket",
        source_id=f"src-{uuid.uuid4()}",
        extra={},
        embedding=[0.0] * 1536,
        match_result=match_result,
    )


# ---------------------------------------------------------------------------
# Happy path: new POTENTIAL report from NewReportMatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_new_match_creates_potential_report_below_threshold(ateam):
    """A first signal below weight threshold creates a POTENTIAL report, not promoted yet."""
    input_ = _build_input(ateam.id, _new_match(), weight=WEIGHT_THRESHOLD * 0.5)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is False
    report = await database_sync_to_async(SignalReport.objects.get)(id=result.report_id)
    assert report.status == SignalReport.Status.POTENTIAL
    assert report.total_weight == pytest.approx(WEIGHT_THRESHOLD * 0.5)
    assert report.signal_count == 1
    assert report.promoted_at is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_new_match_creates_and_immediately_promotes_when_above_threshold(ateam):
    """A first signal at/above threshold creates a POTENTIAL report and promotes it in one shot."""
    input_ = _build_input(ateam.id, _new_match(), weight=WEIGHT_THRESHOLD)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is True
    report = await database_sync_to_async(SignalReport.objects.get)(id=result.report_id)
    assert report.status == SignalReport.Status.CANDIDATE
    assert report.promoted_at is not None


# ---------------------------------------------------------------------------
# Happy path: existing POTENTIAL crossing thresholds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_potential_promotes_when_weight_crosses_threshold(ateam):
    """An existing POTENTIAL report below threshold gets pushed over by the new signal's weight."""
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.POTENTIAL,
        total_weight=WEIGHT_THRESHOLD * 0.6,
        signal_count=1,
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=WEIGHT_THRESHOLD * 0.6)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is True
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.CANDIDATE
    assert refreshed.total_weight == pytest.approx(WEIGHT_THRESHOLD * 1.2)
    assert refreshed.signal_count == 2
    assert refreshed.promoted_at is not None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_potential_does_not_promote_below_weight_threshold(ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.POTENTIAL,
        total_weight=WEIGHT_THRESHOLD * 0.2,
        signal_count=1,
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=WEIGHT_THRESHOLD * 0.2)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is False
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.POTENTIAL
    assert refreshed.promoted_at is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_potential_does_not_promote_when_signals_at_run_gate_holds(ateam):
    """Snooze gate: even at weight threshold, a POTENTIAL with signals_at_run > signal_count stays put."""
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.POTENTIAL,
        total_weight=WEIGHT_THRESHOLD,
        signal_count=2,
        signals_at_run=10,  # need 10 signals before re-promoting
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.5)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is False
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.POTENTIAL
    assert refreshed.signal_count == 3


# ---------------------------------------------------------------------------
# THE NEW BEHAVIOR — CANDIDATE re-promotion as self-healing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_candidate_returns_promoted_true_without_changing_status(ateam):
    """A new signal arriving at an already-CANDIDATE report must:
    - return promoted=True so the caller spawns a recovery workflow
    - leave status at CANDIDATE
    - increment weight + signal_count atomically
    """
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.CANDIDATE,
        total_weight=2.0,
        signal_count=3,
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.5)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is True
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.CANDIDATE
    assert refreshed.total_weight == pytest.approx(2.5)
    assert refreshed.signal_count == 4


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_candidate_repromotion_preserves_original_promoted_at(ateam):
    """promoted_at must not be reset on re-promotion of an already-CANDIDATE report — the
    original timestamp is more useful (it reflects when the report first became actionable)."""
    original_promoted_at = timezone.now() - timedelta(hours=2)
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.CANDIDATE,
        total_weight=1.5,
        signal_count=2,
        promoted_at=original_promoted_at,
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.5)

    await assign_and_emit_signal_activity(input_)

    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.promoted_at == original_promoted_at


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_repeated_signals_to_candidate_never_raise_invalid_transition(ateam):
    """The havoc test: ten signals in a row at the same CANDIDATE report must not raise
    InvalidStatusTransition (which transition_to would, since CANDIDATE -> CANDIDATE has no
    case in the match). All counter increments must persist."""
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.CANDIDATE,
        total_weight=1.0,
        signal_count=1,
    )

    for _ in range(10):
        input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.1)
        result = await assign_and_emit_signal_activity(input_)
        assert result.promoted is True

    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.CANDIDATE
    assert refreshed.total_weight == pytest.approx(2.0)
    assert refreshed.signal_count == 11


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_candidate_repromotion_does_not_advance_run_count(ateam):
    """run_count is incremented by mark_report_in_progress_activity (CANDIDATE -> IN_PROGRESS),
    NOT by the assign-and-emit gate. Re-promoting an already-CANDIDATE report must not touch it."""
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.CANDIDATE,
        total_weight=1.5,
        signal_count=2,
        run_count=3,
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.5)

    result = await assign_and_emit_signal_activity(input_)

    assert result.run_count == 3
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.run_count == 3


# ---------------------------------------------------------------------------
# Existing re-promotion behaviors — preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "starting_status",
    [SignalReport.Status.READY, SignalReport.Status.RESOLVED],
)
async def test_ready_and_resolved_repromote_to_candidate_on_any_signal(ateam, starting_status):
    """READY and RESOLVED re-promote on every signal regardless of weight thresholds."""
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=starting_status,
        total_weight=1.5,
        signal_count=2,
        title="original title",
        summary="original summary",
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.1)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is True
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.CANDIDATE
    assert refreshed.promoted_at is not None
    # title/summary must be preserved through the transition
    assert refreshed.title == "original title"
    assert refreshed.summary == "original summary"


# ---------------------------------------------------------------------------
# States that should NOT promote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "starting_status",
    [
        SignalReport.Status.IN_PROGRESS,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.FAILED,
        SignalReport.Status.SUPPRESSED,
    ],
)
async def test_non_promoting_states_increment_counters_but_do_not_promote(ateam, starting_status):
    """For IN_PROGRESS / PENDING_INPUT / FAILED / SUPPRESSED:
    - weight + signal_count still update
    - status is unchanged
    - promoted=False so no workflow spawn attempt
    """
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=starting_status,
        total_weight=1.0,
        signal_count=2,
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.5)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is False
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == starting_status
    assert refreshed.total_weight == pytest.approx(1.5)
    assert refreshed.signal_count == 3


# ---------------------------------------------------------------------------
# DELETED report short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_deleted_report_skips_counter_updates_and_marks_signal_deleted(ateam, patch_side_effects):
    """When a signal matches a DELETED report:
    - counters are NOT incremented
    - status remains DELETED
    - the signal is still emitted to ClickHouse but marked deleted=True in metadata
    - soft_delete_report_signals is invoked to clean up stale rows
    """
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.DELETED,
        total_weight=2.0,
        signal_count=3,
    )
    input_ = _build_input(ateam.id, _existing_match(str(report.id)), weight=0.5)

    result = await assign_and_emit_signal_activity(input_)

    assert result.promoted is False
    refreshed = await database_sync_to_async(SignalReport.objects.get)(id=report.id)
    assert refreshed.status == SignalReport.Status.DELETED
    assert refreshed.total_weight == 2.0
    assert refreshed.signal_count == 3

    patch_side_effects["soft_delete"].assert_called_once()
    emit_kwargs = patch_side_effects["emit"].call_args.kwargs
    assert emit_kwargs["metadata"]["deleted"] is True
