import uuid
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.facade.contracts import ErrorTrackingIssueImpact, LifecycleFilterOutcome
from products.signals.backend.facade.api import validate_signal_input
from products.signals.backend.temporal.backfill_error_tracking import (
    BACKFILL_ISSUE_LIMIT,
    CANDIDATE_LIMIT,
    BackfillErrorTrackingInput,
    BackfillErrorTrackingWorkflow,
    EmitBackfillSignalInput,
    ErrorTrackingIssueData,
    emit_backfill_signal_activity,
    rank_backfill_candidates,
)

NOW = datetime(2026, 6, 30, tzinfo=UTC)


def _issue(
    name: str,
    *,
    users: int = 10,
    occurrences: int = 50,
    first_seen_days_ago: int = 5,
    last_seen_days_ago: int = 0,
    severity: str | None = None,
    is_assigned: bool = False,
    source: str | None = None,
) -> ErrorTrackingIssueImpact:
    return ErrorTrackingIssueImpact(
        id=uuid.uuid4(),
        name=name,
        description=None,
        severity=severity,
        is_assigned=is_assigned,
        source=source,
        first_seen=NOW - timedelta(days=first_seen_days_ago),
        last_seen=NOW - timedelta(days=last_seen_days_ago),
        occurrences=occurrences,
        users=users,
        sessions=users,
        daily_occurrences=(),
    )


def test_rank_orders_by_impact_and_drops_ineligible_issues():
    issues = [
        _issue("newest_but_tiny", users=2, occurrences=3, first_seen_days_ago=0),
        _issue("broad_and_ongoing", users=500, occurrences=2000, first_seen_days_ago=20),
        _issue("broad_but_stale", users=500, occurrences=2000, first_seen_days_ago=20, last_seen_days_ago=15),
        _issue("broad_but_assigned", users=500, occurrences=2000, is_assigned=True),
        _issue("single_user_crash_loop", users=1, occurrences=5000),
        _issue("single_user_critical", users=1, occurrences=4, severity="critical"),
        _issue("older_than_window", users=900, occurrences=9000, first_seen_days_ago=60),
    ]

    ranked = [issue.name for issue in rank_backfill_candidates(issues, NOW)]

    assert ranked == [
        "broad_and_ongoing",
        "broad_but_assigned",
        "broad_but_stale",
        "single_user_critical",
        "newest_but_tiny",
    ]


def test_rank_caps_issues_sharing_a_source_file():
    issues = [_issue(f"same_file_{i}", users=100 - i, source="app/checkout.ts") for i in range(4)]
    issues.append(_issue("other_file", users=5, source="app/search.ts"))

    ranked = [issue.name for issue in rank_backfill_candidates(issues, NOW)]

    assert ranked == ["same_file_0", "same_file_1", "other_file"]


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatched_result", [True, None])
async def test_workflow_replaces_steered_out_candidates_and_stops_at_limit(dispatched_result: bool | None):
    steered_out = {"issue_0", "issue_1"}
    emitted: list[str] = []

    @activity.defn(name="fetch_error_tracking_issues_activity")
    async def fake_fetch(input: BackfillErrorTrackingInput) -> list[ErrorTrackingIssueData]:
        return [
            ErrorTrackingIssueData(issue_id=f"issue_{i}", name="Error", description="", fingerprint="")
            for i in range(input.candidate_limit)
        ]

    @activity.defn(name="emit_backfill_signal_activity")
    async def fake_emit(input: EmitBackfillSignalInput) -> bool | None:
        emitted.append(input.issue.issue_id)
        return False if input.issue.issue_id in steered_out else dispatched_result

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="backfill-error-tracking-test",
            workflows=[BackfillErrorTrackingWorkflow],
            activities=[fake_fetch, fake_emit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                BackfillErrorTrackingWorkflow.run,
                BackfillErrorTrackingInput(team_id=1),
                id=f"backfill-error-tracking-{uuid.uuid4()}",
                task_queue="backfill-error-tracking-test",
            )

    assert CANDIDATE_LIMIT > BACKFILL_ISSUE_LIMIT + len(steered_out)
    assert emitted == [f"issue_{i}" for i in range(BACKFILL_ISSUE_LIMIT + len(steered_out))]


@pytest.mark.asyncio
async def test_emitted_signal_matches_the_error_tracking_contract():
    issue = ErrorTrackingIssueData(
        issue_id=str(uuid.uuid4()),
        name="TypeError",
        description="x is undefined",
        fingerprint="fp",
        users=3,
        occurrences=9,
    )
    emit = AsyncMock(return_value=True)

    with (
        patch("posthog.models.Team.objects.aget", AsyncMock(return_value=MagicMock())),
        patch("products.signals.backend.facade.source_configs.enabled_issue_filters", return_value=None),
        patch("products.signals.backend.facade.api.emit_signal", emit),
    ):
        await ActivityEnvironment().run(emit_backfill_signal_activity, EmitBackfillSignalInput(team_id=1, issue=issue))

    kwargs = {key: value for key, value in emit.call_args.kwargs.items() if key != "team"}
    validate_signal_input(**kwargs, remediation=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome, dispatched",
    [
        (LifecycleFilterOutcome.MATCH, True),
        (LifecycleFilterOutcome.EXCLUDED_BY_FILTER, False),
        # A filter on an exception property cannot be decided for a backfilled issue.
        (LifecycleFilterOutcome.DATA_UNAVAILABLE, False),
    ],
)
async def test_issue_filter_gates_the_backfill(outcome: LifecycleFilterOutcome, dispatched: bool) -> None:
    issue = ErrorTrackingIssueData(issue_id=str(uuid.uuid4()), name="TypeError", description="", fingerprint="fp")
    emit = AsyncMock(return_value=True)
    stored_filters = {"properties": [{"key": "$environment", "value": ["production"], "type": "event"}]}

    with (
        patch("posthog.models.Team.objects.aget", AsyncMock(return_value=MagicMock(id=1))),
        patch("products.signals.backend.facade.source_configs.enabled_issue_filters", return_value=stored_filters),
        patch(
            "products.error_tracking.backend.facade.alerts.stored_issue_created_filter_outcome", return_value=outcome
        ) as filter_outcome,
        patch("products.signals.backend.facade.source_configs.record_source_filter_drop") as record_drop,
        patch("products.signals.backend.facade.api.emit_signal", emit),
    ):
        result = await ActivityEnvironment().run(
            emit_backfill_signal_activity, EmitBackfillSignalInput(team_id=1, issue=issue)
        )

    assert filter_outcome.call_args.args == (1, issue.issue_id, "fp", stored_filters)
    assert result is dispatched
    assert emit.await_count == int(dispatched)
    assert record_drop.call_count == int(not dispatched)
