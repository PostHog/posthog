import json
import random
import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock, Mock, patch

from django.db import OperationalError, transaction
from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async
from parameterized import parameterized
from pydantic import ValidationError
from temporalio.exceptions import ApplicationError

from posthog.models import Integration, Organization, Team, User
from posthog.models.integration import GitHubIntegrationError
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.user_integration import UserIntegration
from posthog.sync import database_sync_to_async
from posthog.temporal.oauth import grants_scratchpad_write

from products.signals.backend.artefact_schemas import (
    DISMISSAL_REASON_WRONG_REPO,
    Dismissal,
    ImplementationAssessment,
    ImplementationTarget,
    NoteArtefact,
    RelatedTo,
    ReportLink,
)
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import (
    ArtefactAttribution,
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalScoutConfig,
    SignalScoutNote,
)
from products.signals.backend.pull_requests import link_pull_request, reconcile_reports_for_pull_request
from products.signals.backend.repo_corrections import SCOUT_REPOSITORY_REASON
from products.signals.backend.report_assignments import PullRequestDetails
from products.signals.backend.report_charts import ReportChart
from products.signals.backend.report_check_agent import FALLBACK_CHECK_SKILL_NAME
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    ActionabilityUpdate,
    FixVerificationOutput,
    Priority,
    PriorityAssessment,
    PriorityUpdate,
    ReportPresentationOutput,
    ReportResearchOutput,
    ResearchReviewerDecision,
    SignalFinding,
    _resolve_actionability_response,
    _resolve_priority_response,
    run_multi_turn_research,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.report_metrics import REPORT_METRIC_GOAL_FIELDS, ReportMetric
from products.signals.backend.startup_failure import RESEARCH_STARTUP_FAILURE, research_startup_failure
from products.signals.backend.supersession import ImplementationResearchContext
from products.signals.backend.temporal.agentic.report import (
    RESEARCH_MCP_SCOPES,
    RESEARCH_SANDBOX_UNAVAILABLE_ERROR_TYPE,
    RunAgenticReportInput,
    _load_linked_report_context,
    _load_previous_research,
    _load_recurrence_report_context,
    _parse_artefact_content,
    _parse_stored_charts,
    _parse_stored_metrics,
    _resolve_report_metrics_payload,
    run_agentic_report_activity,
)
from products.signals.backend.temporal.agentic.select_repository import (
    SelectRepositoryInput,
    select_repository_activity,
)
from products.signals.backend.temporal.summary import (
    MarkReportPendingInput,
    MarkReportReadyInput,
    mark_report_pending_input_activity,
    mark_report_ready_activity,
)
from products.signals.backend.temporal.types import SignalData
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.facade.agents import (
    AgentStartupFailed,
    CustomPromptSandboxContext,
    MultiTurnSession,
    RepositoryContextUnavailable,
    SandboxRunFailed,
)
from products.tasks.backend.facade.contracts import AgentStartupFailure
from products.tasks.backend.facade.repo_selection_types import ReportResearchContext
from products.tasks.backend.models import Task  # tach-ignore


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsTestOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )

    yield organization

    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsTestTeam-{random.randint(1, 99999)}",
    )

    yield team

    await sync_to_async(team.delete)()


def _build_research_output() -> ReportResearchOutput:
    # A first run: every finding and assessment is new.
    return ReportResearchOutput(
        title="Onboarding funnel completion tracking may be regressing",
        summary="Signals point to a likely regression around onboarding completion event tracking.",
        verification_note=NoteArtefact(
            note=(
                "## Verification plan\n\n"
                "### Confirm the current state\n\n"
                "Run query-trends for onboarding_completed over the same 14-day window.\n\n"
                "### Confirm the outcome\n\n"
                "Confirm completion volume returns to its pre-regression baseline."
            )
        ),
        new_artefacts=[
            SignalFinding(
                signal_id="sig-1",
                relevant_code_paths=["frontend/src/scenes/onboarding/OnboardingFlow.tsx"],
                data_queried="Checked onboarding_completed volume in recent events; it dropped 38% week over week.",
                verified=True,
            ),
            SignalFinding(
                signal_id="sig-2",
                relevant_code_paths=["posthog/api/event.py"],
                data_queried="Compared pageview and user_signed_up volumes; those remained stable.",
                verified=True,
            ),
            ActionabilityAssessment(
                explanation="The issue has a clear code path and supporting event-volume evidence.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            PriorityAssessment(
                explanation="The regression affects a core onboarding flow and should be addressed quickly.",
                priority=Priority.P1,
                dollar_value=5000.0,
            ),
        ],
    )


def _chart() -> ReportChart:
    return ReportChart(
        chart_id="signups-drop",
        title="Daily signups",
        query={
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "user_signed_up"}]},
        },
    )


def _build_research_output_with_chart() -> ReportResearchOutput:
    output = _build_research_output()
    return output.model_copy(update={"charts": [_chart()]})


def _build_research_output_with_duplicate_chart_ids() -> ReportResearchOutput:
    dupe = _chart()
    return _build_research_output().model_copy(
        update={"charts": [dupe, dupe.model_copy(update={"title": "Same id, different chart"})]}
    )


def _metric(metric_id: str = "affected-users") -> ReportMetric:
    return ReportMetric(
        metric_id=metric_id,
        title="Affected users",
        kind="affected_users",
        role="primary",
        value=42,
        value_at=datetime.now(UTC),
        value_format="count",
        unit="users",
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-30d"},
                "series": [{"kind": "EventsNode", "event": "$exception", "math": "dau"}],
            },
        },
    )


def _build_research_output_with_metric() -> ReportResearchOutput:
    return _build_research_output().model_copy(update={"metrics": [_metric()]})


def _build_research_output_with_duplicate_metric_ids() -> ReportResearchOutput:
    duplicate = _metric()
    return _build_research_output().model_copy(
        update={"metrics": [duplicate, duplicate.model_copy(update={"role": "supporting"})]}
    )


_EXISTING_CHART = {
    "chart_id": "existing",
    "title": "Existing chart",
    "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
}

_EXISTING_METRIC = _metric("existing-affected-users").model_dump(mode="json")


def test_report_observations_do_not_store_goal_fields():
    metric = _metric().model_copy(
        update={"goal_value": 2, "goal_direction": "at_most", "decision_window_days": 7, "minimum_data_points": 30}
    )

    observations = _resolve_report_metrics_payload([metric], True, report_id="report-1", team_id=2)
    assert observations is not None
    assert all(field_name not in observations[0] for field_name in REPORT_METRIC_GOAL_FIELDS)


async def _run_activity_with_output(
    monkeypatch,
    ateam,
    report,
    output,
    *,
    metrics_enabled=True,
    repo_selection_as_of=None,
    research_kwargs=None,
):
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_user_id_for_team",
        lambda team_id: 1,
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.team_report_metrics_enabled",
        lambda team_id: metrics_enabled,
    )

    async def fake_run_multi_turn_research(*args, **kwargs):
        if research_kwargs is not None:
            research_kwargs.update(kwargs)
        return output

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.run_multi_turn_research",
        fake_run_multi_turn_research,
    )
    with patch("products.signals.backend.temporal.agentic.report.Heartbeater"):
        return await run_agentic_report_activity(
            RunAgenticReportInput(
                team_id=ateam.id,
                report_id=str(report.id),
                signals=_build_signals(),
                repo_selection=RepoSelectionResult(repository="posthog/posthog", reason="test"),
                repo_selection_as_of=repo_selection_as_of,
            )
        )


def _build_signals() -> list[SignalData]:
    now = datetime.now(UTC)
    return [
        SignalData(
            signal_id="sig-1",
            content="Bug report: onboarding_completed volume appears to have dropped sharply.",
            source_product="zendesk",
            source_type="bug",
            source_id="44891",
            weight=0.8,
            timestamp=now,
        ),
        SignalData(
            signal_id="sig-2",
            content="Related issue mentions completion tracking may not fire in some onboarding paths.",
            source_product="github",
            source_type="issue",
            source_id="42606",
            weight=0.5,
            timestamp=now,
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("parent_status", "prior_status", "dismissal_reason", "expected"),
    [
        (SignalReport.Status.RESOLVED, None, None, True),
        (SignalReport.Status.CLOSED, None, None, True),
        (SignalReport.Status.SUPPRESSED, SignalReport.Status.CLOSED, None, True),
        (SignalReport.Status.SUPPRESSED, None, "already_fixed", True),
        (SignalReport.Status.SUPPRESSED, None, "wrong_repo", False),
        # Archived because nobody wants to see it, not because it was fixed: there is no prior fix
        # to reason about, so the research agent is told nothing.
        (SignalReport.Status.SUPPRESSED, None, "wontfix_intentional", False),
    ],
)
@pytest.mark.parametrize("typed_link", [False, True])
@pytest.mark.parametrize("safety_verdicts", [[], [False], [True], [False, True], [True, False], ["invalid"]])
async def test_recurrence_context_preserves_the_predecessor_outcome(
    ateam: Team,
    parent_status: str,
    prior_status: str | None,
    dismissal_reason: str | None,
    expected: bool,
    typed_link: bool,
    safety_verdicts: list[bool | str],
) -> None:
    parent = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=parent_status,
        status_before_suppression=prior_status,
        title="stale chunk TypeError",
        summary="Imports fail after a deploy.",
    )
    if dismissal_reason is not None:
        await database_sync_to_async(SignalReportArtefact.append_dismissal)(
            team_id=ateam.id,
            report_id=str(parent.id),
            content=Dismissal(reason=dismissal_reason),
            attribution=ArtefactAttribution.system(),
        )
    fork = await database_sync_to_async(SignalReport.objects.create)(team=ateam, title="fork", summary="fork")
    for verdict in safety_verdicts:
        await database_sync_to_async(SignalReportArtefact.objects.create)(
            team=ateam,
            report=parent,
            type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
            content="invalid" if verdict == "invalid" else json.dumps({"choice": verdict}),
        )
    await database_sync_to_async(SignalReportArtefact.add_log)(
        team_id=ateam.id,
        report_id=str(fork.id),
        content=(
            ReportLink(kind=ReportLinkKind.RECURRENCE_OF, report_id=str(parent.id))
            if typed_link
            else RelatedTo(report_id=str(parent.id))
        ),
        attribution=ArtefactAttribution.system(),
    )

    context = await _load_recurrence_report_context(ateam.id, str(fork.id))

    safe = not safety_verdicts or safety_verdicts[-1] is True
    valid_link = typed_link or parent_status in {SignalReport.Status.RESOLVED, SignalReport.Status.CLOSED}
    if expected and safe and valid_link:
        assert context is not None
        assert context.title == "stale chunk TypeError"
        assert context.summary == "Imports fail after a deploy."
        assert context.status == (
            "closed"
            if parent_status == SignalReport.Status.CLOSED or prior_status == SignalReport.Status.CLOSED
            else "resolved"
        )
    else:
        assert context is None
    assert await _load_previous_research(ateam.id, str(fork.id)) is None


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (ReportLinkKind.FOLLOW_UP_OF, True),
        (ReportLinkKind.DEPENDS_ON, True),
        (ReportLinkKind.PART_OF, True),
        # A duplicate never reaches research, and a recurrence has its own richer read.
        (ReportLinkKind.DUPLICATE_OF, False),
        (ReportLinkKind.RECURRENCE_OF, False),
    ],
)
async def test_linked_report_context_carries_the_linked_reports_findings(ateam, kind, expected):
    linked = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, title="step index column", summary="The column is missing."
    )
    await database_sync_to_async(SignalReportArtefact.objects.create)(
        team=ateam, report=linked, type="safety_judgment", content=json.dumps({"choice": True})
    )
    await database_sync_to_async(SignalReportArtefact.append_finding)(
        team_id=ateam.id,
        report_id=str(linked.id),
        content=SignalFinding(
            signal_id="sig-1",
            relevant_code_paths=["obsolete.py"],
            relevant_commit_hashes={},
            data_queried="",
            verified=True,
        ),
        attribution=ArtefactAttribution.system(),
    )
    await database_sync_to_async(SignalReportArtefact.append_finding)(
        team_id=ateam.id,
        report_id=str(linked.id),
        content=SignalFinding(
            signal_id="sig-1",
            relevant_code_paths=["products/funnels/logic.py", "products/funnels/queries.py"],
            relevant_commit_hashes={"abc1234": "Added the column."},
            data_queried="execute-sql over events",
            verified=True,
        ),
        attribution=ArtefactAttribution.system(),
    )
    report = await database_sync_to_async(SignalReport.objects.create)(team=ateam, title="r", summary="s")
    await database_sync_to_async(SignalReportArtefact.add_log)(
        team_id=ateam.id,
        report_id=str(report.id),
        content=ReportLink(kind=kind, report_id=str(linked.id), reason="only web was covered"),
        attribution=ArtefactAttribution.system(),
    )

    await database_sync_to_async(SignalReportArtefact.add_log)(
        team_id=ateam.id,
        report_id=str(report.id),
        content=ReportLink(kind=kind, report_id=str(linked.id), reason="repeated link"),
        attribution=ArtefactAttribution.system(),
    )

    context = await _load_linked_report_context(ateam.id, str(report.id))

    if not expected:
        assert context == []
        return
    assert [(entry.kind, entry.report_id, entry.title) for entry in context] == [
        (kind, str(linked.id), "step index column")
    ]
    assert context[0].reason == "only web was covered"
    assert context[0].code_paths == ["products/funnels/logic.py", "products/funnels/queries.py"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_linked_report_context_cap_counts_only_usable_reports(ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(team=ateam, title="r", summary="s")

    async def _link(target: SignalReport) -> None:
        await database_sync_to_async(SignalReportArtefact.add_log)(
            team_id=ateam.id,
            report_id=str(report.id),
            content=ReportLink(kind=ReportLinkKind.DEPENDS_ON, report_id=str(target.id)),
            attribution=ArtefactAttribution.system(),
        )

    for index in range(10):
        unjudged = await database_sync_to_async(SignalReport.objects.create)(
            team=ateam, title=f"unjudged-{index}", summary="No verdict."
        )
        await _link(unjudged)
    usable = await database_sync_to_async(SignalReport.objects.create)(team=ateam, title="usable", summary="s")
    await database_sync_to_async(SignalReportArtefact.objects.create)(
        team=ateam, report=usable, type="safety_judgment", content=json.dumps({"choice": True})
    )
    await _link(usable)

    context = await _load_linked_report_context(ateam.id, str(report.id))

    assert [entry.report_id for entry in context] == [str(usable.id)]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("verdicts", [[], [False], [True, False], [False, True], ["invalid"], [{}], ["true"]])
async def test_linked_report_context_requires_an_explicit_safe_verdict(ateam, verdicts):
    linked = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, title="unsafe", summary="Do not repeat this."
    )
    for index, verdict in enumerate(verdicts):
        await database_sync_to_async(SignalReportArtefact.objects.create)(
            team=ateam,
            report=linked,
            type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
            content="invalid" if verdict == "invalid" else json.dumps({"choice": verdict}),
            created_at=timezone.now() + timedelta(seconds=index),
        )
    report = await database_sync_to_async(SignalReport.objects.create)(team=ateam, title="r", summary="s")
    await database_sync_to_async(SignalReportArtefact.add_log)(
        team_id=ateam.id,
        report_id=str(report.id),
        content=ReportLink(kind=ReportLinkKind.FOLLOW_UP_OF, report_id=str(linked.id)),
        attribution=ArtefactAttribution.system(),
    )

    context = await _load_linked_report_context(ateam.id, str(report.id))
    assert bool(context) == bool(verdicts and verdicts[-1] is True)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("edit_type", "edited_after_verdict", "expected"),
    [
        (SignalReportArtefact.ArtefactType.TITLE_CHANGE, True, False),
        (SignalReportArtefact.ArtefactType.SUMMARY_CHANGE, True, False),
        (SignalReportArtefact.ArtefactType.SUMMARY_CHANGE, False, True),
    ],
)
async def test_a_linked_report_edited_after_its_verdict_is_not_read_into_a_prompt(
    ateam, edit_type, edited_after_verdict, expected
):
    # The report PATCH path replaces a title or summary without re-running the safety judge, so a
    # `choice: true` verdict can vouch for prose nobody reviewed. Without this the edited text goes
    # straight into the research sandbox prompt under the old approval.
    linked = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, title="edited", summary="Prose the judge never saw."
    )
    judged_at = timezone.now()

    def _stamp(artefact_type: str, content: dict, created_at) -> None:
        # `created_at` is auto_now_add, so it ignores whatever `create()` is handed; the update is
        # what actually orders these two rows, and this test is entirely about their order.
        artefact = SignalReportArtefact.objects.create(
            team=ateam, report=linked, type=artefact_type, content=json.dumps(content)
        )
        SignalReportArtefact.objects.filter(id=artefact.id).update(created_at=created_at)

    await database_sync_to_async(_stamp)(SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT, {"choice": True}, judged_at)
    await database_sync_to_async(_stamp)(
        edit_type,
        {"new_title": "edited"} if "title" in edit_type else {"new_summary": "edited"},
        judged_at + timedelta(seconds=30 if edited_after_verdict else -30),
    )
    report = await database_sync_to_async(SignalReport.objects.create)(team=ateam, title="r", summary="s")
    await database_sync_to_async(SignalReportArtefact.add_log)(
        team_id=ateam.id,
        report_id=str(report.id),
        content=ReportLink(kind=ReportLinkKind.FOLLOW_UP_OF, report_id=str(linked.id)),
        attribution=ArtefactAttribution.system(),
    )

    context = await _load_linked_report_context(ateam.id, str(report.id))

    assert bool(context) is expected


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_load_previous_research_ignores_report_from_another_team(ateam, aorganization):
    other_team = await database_sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsOtherTeam-{random.randint(1, 99999)}",
    )
    other_report = await database_sync_to_async(SignalReport.objects.create)(
        team=other_team,
        title="Another team's report",
        summary="Private research from another team.",
    )

    assert await _load_previous_research(ateam.id, str(other_report.id)) is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_load_previous_research_ignores_artefacts_from_another_team(ateam, aorganization):
    other_team = await database_sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsOtherTeam-{random.randint(1, 99999)}",
    )
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        title="Current team's report",
        summary="Current team's summary.",
    )
    finding = SignalFinding(
        signal_id="foreign-signal",
        relevant_code_paths=[],
        data_queried="Private research from another team.",
        verified=True,
    )
    actionability = ActionabilityAssessment(
        explanation="Another team's assessment.",
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
        already_addressed=False,
    )
    await database_sync_to_async(SignalReportArtefact.objects.bulk_create)(
        [
            SignalReportArtefact(
                team=other_team,
                report=report,
                type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
                content=finding.model_dump_json(),
            ),
            SignalReportArtefact(
                team=other_team,
                report=report,
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content=actionability.model_dump_json(),
            ),
        ]
    )

    assert await _load_previous_research(ateam.id, str(report.id)) is None


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "connection,expected",
    [
        ("missing", "no_integration"),
        ("empty", "no_repositories"),
        ("broken", "github_unavailable"),
        ("transport_failure", "github_unavailable"),
    ],
)
async def test_pilot_repository_failure_keeps_research_available(monkeypatch, ateam, connection, expected):
    if connection != "missing":
        await Integration.objects.acreate(
            team=ateam,
            kind="github",
            integration_id="123",
            config={"installation_id": 123},
            errors="TOKEN_REFRESH_FAILED" if connection == "broken" else "",
            repository_cache=[] if connection == "empty" else [{"full_name": "example/app"}],
            repository_cache_updated_at=timezone.now(),
        )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository._resolve_sandbox_user_id", lambda team_id: 1
    )
    with (
        patch("products.signals.backend.temporal.agentic.select_repository.Heartbeater"),
        patch(
            "products.signals.backend.temporal.agentic.select_repository.select_repository_for_report",
            side_effect=GitHubIntegrationError("Unavailable", status_code=503),
        ),
    ):
        result = await select_repository_activity(
            SelectRepositoryInput(
                team_id=ateam.id, report_id=str(uuid4()), signals=_build_signals(), github_optional=True
            )
        )
    assert result.repository is None
    assert result.research_context is not None
    assert result.research_context.mode == "data_only"
    assert result.research_context.repository_status == expected


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_select_repository_activity_returns_repo(monkeypatch, ateam):
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.persisted_repo_selection",
        lambda report_id: None,
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository._resolve_sandbox_user_id",
        lambda team_id: 1,
    )

    async def fake_select_repo(*args, **kwargs):
        return RepoSelectionResult(repository="posthog/posthog", reason="Single repository connected: posthog/posthog")

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.select_repository_for_report",
        fake_select_repo,
    )

    with patch("products.signals.backend.temporal.agentic.select_repository.Heartbeater"):
        result = await select_repository_activity(
            SelectRepositoryInput(team_id=ateam.id, report_id=str(uuid4()), signals=_build_signals())
        )

    assert result.repository == "posthog/posthog"
    assert "Single repository" in result.reason


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "github_optional,connected,reused",
    [
        (False, True, True),
        (False, False, False),
        (True, True, True),
        (True, False, True),
    ],
)
async def test_select_repository_activity_reuses_previous_selection(
    monkeypatch, ateam, github_optional, connected, reused
):
    previous = RepoSelectionResult(repository="posthog/posthog", reason="Previously selected")
    if connected:
        await Integration.objects.acreate(
            team=ateam, kind="github", integration_id="123", config={"installation_id": 123}
        )

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.persisted_repo_selection",
        lambda report_id: previous,
    )

    select_repo_called = False

    async def fake_select_repo(*args, **kwargs):
        nonlocal select_repo_called
        select_repo_called = True
        raise AssertionError("should not be called")

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.select_repository_for_report",
        fake_select_repo,
    )

    with patch("products.signals.backend.temporal.agentic.select_repository.Heartbeater"):
        result = await select_repository_activity(
            SelectRepositoryInput(
                team_id=ateam.id, report_id=str(uuid4()), signals=_build_signals(), github_optional=github_optional
            )
        )

    if reused:
        assert result is previous
    else:
        assert result.repository is None
        assert "No GitHub integration" in result.reason
    assert not select_repo_called


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_select_repository_activity_retries_transient_db_drop(monkeypatch, ateam):
    # A pooled pgbouncer connection dropped mid-request raises OperationalError on the
    # activity's early read. The retry-once guard must evict the dead connection and
    # succeed on the second attempt rather than letting it escape as error-tracking noise.
    previous = RepoSelectionResult(repository="posthog/posthog", reason="Previously selected")
    await Integration.objects.acreate(team=ateam, kind="github", integration_id="123", config={"installation_id": 123})
    attempts = {"n": 0}

    def flaky_load(report_id):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OperationalError("server closed the connection unexpectedly")
        return previous

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.persisted_repo_selection",
        flaky_load,
    )

    with patch("products.signals.backend.temporal.agentic.select_repository.Heartbeater"):
        result = await select_repository_activity(
            SelectRepositoryInput(team_id=ateam.id, report_id=str(uuid4()), signals=_build_signals())
        )

    assert result is previous
    assert attempts["n"] == 2


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_select_repository_activity_no_repo(monkeypatch, ateam):
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.persisted_repo_selection",
        lambda report_id: None,
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository._resolve_sandbox_user_id",
        lambda team_id: 1,
    )

    async def fake_select_repo(*args, **kwargs):
        return RepoSelectionResult(repository=None, reason="No GitHub repositories connected to this team.")

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.select_repository_for_report",
        fake_select_repo,
    )

    with patch("products.signals.backend.temporal.agentic.select_repository.Heartbeater"):
        result = await select_repository_activity(
            SelectRepositoryInput(team_id=ateam.id, report_id=str(uuid4()), signals=_build_signals())
        )

    assert result.repository is None
    assert "No GitHub repositories" in result.reason


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_select_repository_activity_does_not_raise_with_only_user_integration(monkeypatch, ateam):
    # PostHog Desktop installs land in `UserIntegration`, never on `Integration`. Before the cascade
    # was wired up, this combination raised `RuntimeError("No GitHub integration found ...")` and
    # killed the activity. Now it must resolve a user_id and reach `select_repository_for_report`.
    user = await sync_to_async(User.objects.create)(email=f"posthog-code-{random.randint(1, 99999)}@example.com")
    await sync_to_async(OrganizationMembership.objects.create)(
        user=user, organization_id=ateam.organization_id, level=OrganizationMembership.Level.OWNER
    )
    await sync_to_async(UserIntegration.objects.create)(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id="999",
        config={"installation_id": "999"},
        sensitive_config={},
    )

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.persisted_repo_selection",
        lambda report_id: None,
    )

    captured_user_id: list[int | None] = []

    async def fake_select_repo(*args, **kwargs):
        captured_user_id.append(kwargs.get("user_id"))
        return RepoSelectionResult(repository="posthog/posthog", reason="Single repository connected: posthog/posthog")

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository.select_repository_for_report",
        fake_select_repo,
    )

    with patch("products.signals.backend.temporal.agentic.select_repository.Heartbeater"):
        result = await select_repository_activity(
            SelectRepositoryInput(team_id=ateam.id, report_id=str(uuid4()), signals=_build_signals())
        )

    assert result.repository == "posthog/posthog"
    assert captured_user_id == [user.id], "user_id should come from the UserIntegration owner"


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("repository", ["posthog/posthog", None])
@pytest.mark.parametrize(
    "sandbox_error_type,expected_transient",
    [
        ("RepositoryCloneError", True),
        ("RepositoryAccessError", False),
        ("startup_requires_action", False),
        ("startup_unknown", False),
        ("startup_transient", True),
        ("startup_unknown_transient_sandbox", True),
    ],
)
async def test_run_agentic_report_activity_flags_transient_sandbox_failures(
    monkeypatch, ateam, repository, sandbox_error_type, expected_transient
):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )
    monkeypatch.setattr("products.signals.backend.temporal.agentic.report.resolve_user_id_for_team", lambda team_id: 1)
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_acting_user_id_for_team", lambda team_id: 1
    )

    async def fake_run_multi_turn_research(*args, **kwargs):
        if sandbox_error_type.startswith("startup_"):
            requires_action = sandbox_error_type == "startup_requires_action"
            raise AgentStartupFailed(
                failure=AgentStartupFailure(
                    provider="claude",
                    phase="sdk_initialization",
                    reason="proxy_invalid" if requires_action else None,
                    retryability="requires_action"
                    if requires_action
                    else "transient"
                    if sandbox_error_type == "startup_transient"
                    else "unknown",
                ),
                task_id=str(uuid4()),
                run_id=str(uuid4()),
                error_type="SandboxExecutionError"
                if sandbox_error_type == "startup_unknown_transient_sandbox"
                else None,
            )
        raise SandboxRunFailed("TaskRun reached terminal status=failed", error_type=sandbox_error_type)

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.run_multi_turn_research", fake_run_multi_turn_research
    )

    with patch("products.signals.backend.temporal.agentic.report.Heartbeater"):
        with pytest.raises((ApplicationError, SandboxRunFailed)) as error:
            await run_agentic_report_activity(
                RunAgenticReportInput(
                    team_id=ateam.id,
                    report_id=str(report.id),
                    signals=_build_signals(),
                    repo_selection=RepoSelectionResult(repository=repository, reason="test research context"),
                    github_optional=repository is None,
                )
            )

    if sandbox_error_type.startswith("startup_"):
        assert isinstance(error.value, ApplicationError)
        assert error.value.type == (
            RESEARCH_SANDBOX_UNAVAILABLE_ERROR_TYPE if expected_transient else RESEARCH_STARTUP_FAILURE
        )
        assert error.value.non_retryable is (sandbox_error_type == "startup_requires_action")
        assert research_startup_failure(error.value) is not None
    elif expected_transient:
        assert isinstance(error.value, ApplicationError)
        assert error.value.type == RESEARCH_SANDBOX_UNAVAILABLE_ERROR_TYPE
    else:
        assert isinstance(error.value, SandboxRunFailed)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "repository,failure",
    [
        (None, None),
        ("example/app", RepositoryContextUnavailable("RepositoryAccessError")),
        ("example/app", RepositoryContextUnavailable("RepositoryCloneError")),
    ],
)
async def test_pilot_research_persists_a_report_without_code(monkeypatch, ateam, repository, failure):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.IN_PROGRESS
    )
    if repository:
        await SignalReportArtefact.objects.acreate(
            team=ateam,
            report=report,
            type="repo_selection",
            content=RepoSelectionResult(repository=repository, reason="Reviewer pinned").model_dump_json(),
        )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_acting_user_id_for_team", lambda team_id: 1
    )
    contexts = []

    async def research(signals, context, **kwargs):
        contexts.append(context)
        if failure is not None and len(contexts) == 1:
            raise failure
        return _build_research_output()

    with (
        patch("products.signals.backend.temporal.agentic.report.Heartbeater"),
        patch("products.signals.backend.temporal.agentic.report.run_multi_turn_research", side_effect=research),
    ):
        result = await run_agentic_report_activity(
            RunAgenticReportInput(
                team_id=ateam.id,
                report_id=str(report.id),
                signals=_build_signals(),
                github_optional=True,
                repo_selection=RepoSelectionResult(
                    repository=repository,
                    reason="Pilot",
                    research_context=ReportResearchContext(
                        mode="code" if repository else "data_only",
                        repository_status="available" if repository else "no_integration",
                    ),
                ),
            )
        )
    assert result.repository is None
    assert result.title == "Onboarding funnel completion tracking may be regressing"
    assert contexts[-1].repository is None
    assert contexts[-1].github_read_access is False
    assert contexts[0].github_read_access is (repository is not None)
    assert len(contexts) == (2 if failure else 1)
    selections = SignalReportArtefact.objects.filter(report=report, type="repo_selection")
    assert await selections.acount() == 1
    selection = await selections.afirst()
    assert selection is not None
    assert json.loads(selection.content)["repository"] == repository
    if not repository:
        assert json.loads(selection.content)["research_context"]["mode"] == "data_only"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_agentic_report_activity_persists_artefacts(monkeypatch, ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_user_id_for_team",
        lambda team_id: 1,
    )

    async def fake_run_multi_turn_research(*args, **kwargs):
        return _build_research_output()

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.run_multi_turn_research",
        fake_run_multi_turn_research,
    )

    with (
        patch("products.signals.backend.temporal.agentic.report.Heartbeater"),
        patch("products.signals.backend.report_generation.reviewer_telemetry.posthoganalytics.capture") as mock_capture,
    ):
        result = await run_agentic_report_activity(
            RunAgenticReportInput(
                team_id=ateam.id,
                report_id=str(report.id),
                signals=_build_signals(),
                repo_selection=RepoSelectionResult(
                    repository="posthog/posthog", reason="Single repository connected: posthog/posthog"
                ),
            )
        )

        assert result.title == "Onboarding funnel completion tracking may be regressing"

        # Scoped to the reviewer events on purpose: patching `capture` on one module patches the
        # shared `posthoganalytics` module, so every other event this activity fires lands in the
        # same mock. This test owns the reviewer contract only.
        reviewer_calls = [
            call.kwargs
            for call in mock_capture.call_args_list
            if call.kwargs["event"].startswith("signals_suggested_reviewers")
        ]
        # The findings cite no commits, so no reviewers artefact is written; the run must say why.
        assert [call["event"] for call in reviewer_calls] == ["signals_suggested_reviewers_unresolved"]
        unresolved_props = reviewer_calls[0]["properties"]
        assert unresolved_props["report_id"] == str(report.id)
        assert unresolved_props["outcome"] == "no_commit_hashes"
        assert unresolved_props["finding_count"] == 2
        assert result.choice == ActionabilityChoice.IMMEDIATELY_ACTIONABLE
        assert result.priority == Priority.P1
        assert result.already_addressed is False
        assert result.repository == "posthog/posthog"

        artefacts = await database_sync_to_async(
            lambda: list(SignalReportArtefact.objects.filter(report=report).order_by("type", "created_at"))
        )()
        assert [artefact.type for artefact in artefacts] == [
            SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            SignalReportArtefact.ArtefactType.NOTE,
            SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            SignalReportArtefact.ArtefactType.REPO_SELECTION,
            SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
            SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
        ]

        actionability_content = json.loads(artefacts[0].content)
        assert actionability_content == {
            "actionability": "immediately_actionable",
            "explanation": "The issue has a clear code path and supporting event-volume evidence.",
            "already_addressed": False,
        }

        note_content = json.loads(artefacts[1].content)
        assert note_content == {
            "note": (
                "## Verification plan\n\n"
                "### Confirm the current state\n\n"
                "Run query-trends for onboarding_completed over the same 14-day window.\n\n"
                "### Confirm the outcome\n\n"
                "Confirm completion volume returns to its pre-regression baseline."
            ),
            "author": None,
        }

        priority_content = json.loads(artefacts[2].content)
        assert priority_content == {
            "priority": "P1",
            "explanation": "The regression affects a core onboarding flow and should be addressed quickly.",
            "dollar_value": 5000.0,
        }

        repo_selection_content = json.loads(artefacts[3].content)
        assert repo_selection_content == {
            "repository": "posthog/posthog",
            "reason": "Single repository connected: posthog/posthog",
            "research_context": None,
            "task_id": None,
            "autostart_eligible": True,
        }

        finding_contents = [json.loads(artefact.content) for artefact in artefacts[4:]]
        assert [finding["signal_id"] for finding in finding_contents] == ["sig-1", "sig-2"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_agentic_report_activity_keeps_reviewer_selection_written_mid_run(monkeypatch, ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )
    as_of = datetime.now(UTC)
    reviewer = await sync_to_async(User.objects.create)(email=f"reviewer-{random.randint(1, 99999)}@example.com")
    # A wrong-repo dismissal cleared the selection after this run resolved its own. The reviewer's
    # row must stay the newest one — settle-time auto-start reads the report's current artefacts.
    await database_sync_to_async(SignalReportArtefact.append_status)(
        team_id=ateam.id,
        report_id=str(report.id),
        content=RepoSelectionResult(repository=None, reason="cleared by a reviewer", autostart_eligible=False),
        attribution=ArtefactAttribution.from_user(reviewer.id),
    )

    await _run_activity_with_output(monkeypatch, ateam, report, _build_research_output(), repo_selection_as_of=as_of)

    selections = await database_sync_to_async(
        lambda: list(
            SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.REPO_SELECTION
            ).order_by("created_at")
        )
    )()
    assert [json.loads(selection.content)["repository"] for selection in selections] == [None]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_agentic_report_activity_detects_task_attributed_wrong_repo_dismissal(monkeypatch, ateam):
    # An agent dismissing a report as wrong_repo through the MCP surface attributes the dismissal to
    # its task, so the `dismissal` artefact carries a null created_by. The supersede guard must still
    # detect it off the dismissal artefact; keying only off a user-attributed repo_selection row
    # would miss it, and the run would bury the correction with its stale selection.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )
    as_of = datetime.now(UTC)
    task = await database_sync_to_async(Task.objects.create)(team=ateam, title="agent", description="d")
    await database_sync_to_async(SignalReportArtefact.append_dismissal)(
        team_id=ateam.id,
        report_id=str(report.id),
        content=Dismissal(
            reason=DISMISSAL_REASON_WRONG_REPO,
            selected_repository="posthog/posthog",
            corrected_repository="acme/other",
        ),
        attribution=ArtefactAttribution.from_task(str(task.id)),
    )

    await _run_activity_with_output(monkeypatch, ateam, report, _build_research_output(), repo_selection_as_of=as_of)

    # Superseded by the agent's correction: the run must not persist its own stale selection on top.
    selections = await database_sync_to_async(
        lambda: list(
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.REPO_SELECTION)
        )
    )()
    assert selections == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_agentic_report_activity_keeps_a_scout_repository_correction(monkeypatch, ateam):
    # A scout repointing a live report through `edit_report` writes the selection under its own task,
    # so the row carries a null created_by and no dismissal is filed — neither of the guard's other
    # shapes sees it. Selections are latest-wins, so a run appending its own stale selection on top
    # would hand the repository the scout rejected back to settle-time auto-start.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )
    as_of = datetime.now(UTC)
    task = await database_sync_to_async(Task.objects.create)(team=ateam, title="scout", description="d")
    await database_sync_to_async(SignalReportArtefact.append_status)(
        team_id=ateam.id,
        report_id=str(report.id),
        content=RepoSelectionResult(repository="acme/other", reason=SCOUT_REPOSITORY_REASON),
        attribution=ArtefactAttribution.from_task(str(task.id)),
        reevaluate_autostart=False,
    )

    await _run_activity_with_output(monkeypatch, ateam, report, _build_research_output(), repo_selection_as_of=as_of)

    selections = await database_sync_to_async(
        lambda: list(
            SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.REPO_SELECTION
            ).order_by("created_at")
        )
    )()
    assert [json.loads(selection.content)["repository"] for selection in selections] == ["acme/other"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_agentic_report_activity_hands_fleet_steering_to_the_research_session(monkeypatch, ateam):
    # Resolving the team's steering and then not passing it to the session is the failure this
    # whole path exists to prevent, and nothing downstream would report it: the run still produces
    # a title, a summary, and both assessments, just without the feedback the team already gave.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )

    def _leave_note() -> None:
        with team_scope(ateam.id, canonical=True):
            SignalScoutNote.objects.create(team=ateam, skill_name="", content="the checkout flow is frozen")

    await database_sync_to_async(_leave_note)()

    captured: dict = {}

    async def fake_run_multi_turn_research(*args, **kwargs):
        captured.update(kwargs)
        return _build_research_output()

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_user_id_for_team",
        lambda team_id: 1,
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.run_multi_turn_research",
        fake_run_multi_turn_research,
    )

    with (
        patch("products.signals.backend.temporal.agentic.report.Heartbeater"),
        patch("products.signals.backend.temporal.agentic.report.posthoganalytics.capture") as mock_capture,
    ):
        await run_agentic_report_activity(
            RunAgenticReportInput(
                team_id=ateam.id,
                report_id=str(report.id),
                signals=_build_signals(),
                repo_selection=RepoSelectionResult(repository="posthog/posthog", reason="test"),
            )
        )

    assert "scout-notes-list" in captured["steering_section"]
    steering_events = [
        call.kwargs
        for call in mock_capture.call_args_list
        if call.kwargs["event"] == "signals_research_steering_attached"
    ]
    assert len(steering_events) == 1
    assert steering_events[0]["properties"]["notes_attached"] == 0
    assert steering_events[0]["properties"]["nudge_rendered"] is True
    # The memory protocol is rendered from the same posture the sandbox token is minted with, so a
    # posture that stopped granting the scratchpad would silently drop the write half instead of
    # telling the run to remember with a tool the MCP server has stripped.
    assert grants_scratchpad_write(RESEARCH_MCP_SCOPES)
    assert steering_events[0]["properties"]["memory_protocol"] is True
    assert "scout-scratchpad-remember" in captured["steering_section"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_agentic_report_activity_keeps_quiet_when_reviewers_are_retained(monkeypatch, ateam):
    # A re-promotion that resolves nobody persists no empty list, so the earlier reviewers stay the
    # report's live set. Firing `unresolved` here would make the latest-event-per-report read call a
    # report reviewerless while its artefact still names someone.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )
    await database_sync_to_async(SignalReportArtefact.objects.create)(
        team=ateam,
        report=report,
        type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        content=json.dumps([{"github_login": "someone", "github_name": "Someone", "relevant_commits": []}]),
    )

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_user_id_for_team",
        lambda team_id: 1,
    )

    async def fake_run_multi_turn_research(*args, **kwargs):
        return _build_research_output()

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.run_multi_turn_research",
        fake_run_multi_turn_research,
    )

    with (
        patch("products.signals.backend.temporal.agentic.report.Heartbeater"),
        patch("products.signals.backend.report_generation.reviewer_telemetry.posthoganalytics.capture") as mock_capture,
    ):
        await run_agentic_report_activity(
            RunAgenticReportInput(
                team_id=ateam.id,
                report_id=str(report.id),
                signals=_build_signals(),
                repo_selection=RepoSelectionResult(
                    repository="posthog/posthog", reason="Single repository connected: posthog/posthog"
                ),
            )
        )

    # Reviewer events only: the shared `posthoganalytics` module means this mock also catches the
    # other events the activity fires, and this test is about the reviewer contract.
    assert [
        call.kwargs["event"]
        for call in mock_capture.call_args_list
        if call.kwargs["event"].startswith("signals_suggested_reviewers")
    ] == []


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,output_factory,expected",
    [
        # A valid chart → the JSON set to store.
        ("non_empty", _build_research_output_with_chart, [{"chart_id": "signups-drop"}]),
        # The run authored no charts (optional field omitted / dropped) → None, never a wipe of
        # whatever the report already showed.
        ("empty", _build_research_output, None),
        # The set busts the whole-set caps (duplicate id) → [] to clear, so a stale set can't sit
        # under the new summary.
        ("cap_bust", _build_research_output_with_duplicate_chart_ids, []),
    ],
)
async def test_run_agentic_report_activity_resolves_charts_payload(monkeypatch, ateam, name, output_factory, expected):
    # The activity resolves the charts payload but does not write it — the transition activity does,
    # atomically with the title/summary (see test_mark_report_ready_activity_applies_charts). So we
    # assert the resolved payload on the returned output rather than the report row.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.IN_PROGRESS, signal_count=2, total_weight=1.3
    )

    result = await _run_activity_with_output(monkeypatch, ateam, report, output_factory())

    if expected is None:
        assert result.charts is None
    else:
        assert [{"chart_id": chart["chart_id"]} for chart in result.charts] == expected


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,metrics_enabled,output_factory,expected",
    [
        ("enabled_non_empty", True, _build_research_output_with_metric, ["affected-users"]),
        ("disabled", False, _build_research_output_with_metric, None),
        # Metrics are the presentation step's whole authored set. Empty removes stale metrics from
        # the report, while feature-disabled remains the replay-safe preserve signal above.
        ("enabled_empty", True, _build_research_output, []),
        ("enabled_cap_bust", True, _build_research_output_with_duplicate_metric_ids, []),
    ],
)
async def test_run_agentic_report_activity_resolves_metrics_payload(
    monkeypatch: pytest.MonkeyPatch,
    ateam: Team,
    name: str,
    metrics_enabled: bool,
    output_factory: Callable[[], ReportResearchOutput],
    expected: list[str] | None,
) -> None:
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.IN_PROGRESS, signal_count=2, total_weight=1.3
    )

    result = await _run_activity_with_output(
        monkeypatch,
        ateam,
        report,
        output_factory(),
        metrics_enabled=metrics_enabled,
    )

    if expected is None:
        assert result.metrics is None
    else:
        assert [metric["metric_id"] for metric in result.metrics or []] == expected


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("has_previous_research", [False, True])
@pytest.mark.parametrize("has_query", [False, True])
@pytest.mark.parametrize("monitoring_enabled", [False, True])
async def test_run_agentic_report_activity_supplies_existing_checks_to_reresearch(
    monkeypatch, ateam, has_previous_research, has_query, monitoring_enabled
):
    monkeypatch.setattr(
        "products.signals.backend.report_content_gates.feature_enabled_or_false",
        lambda flag, *args, **kwargs: monitoring_enabled if flag == "signals-report-monitoring" else False,
    )
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.IN_PROGRESS, signal_count=2, total_weight=1.3
    )
    check = await database_sync_to_async(SignalReportCheck.objects.for_team(ateam.id).create)(
        team_id=ateam.id,
        report=report,
        title="Affected users stay at zero",
        kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
        config={
            "query": _metric().query if has_query else None,
            "baseline_value": 40,
            "comparison": {"operator": "lte", "value": 0},
            "monitoring": {
                "reference_period_minutes": 10080,
                "threshold_scaling": "fixed",
                "baseline_period_minutes": 10080,
            },
        },
        status=SignalReportCheck.Status.PENDING,
        next_run_at=timezone.now() + timedelta(days=7),
        expires_at=timezone.now() + timedelta(days=37),
        soak_minutes=7 * 24 * 60,
        approved_at=timezone.now(),
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report._load_previous_research",
        AsyncMock(return_value=_build_research_output() if has_previous_research else None),
    )
    research_kwargs: dict[str, object] = {}

    result = await _run_activity_with_output(
        monkeypatch, ateam, report, _build_research_output(), research_kwargs=research_kwargs
    )

    previous_checks = research_kwargs["previous_checks"]
    assert isinstance(previous_checks, list)
    assert isinstance(previous_checks[0], dict)
    assert previous_checks[0]["id"] == str(check.id)
    assert previous_checks[0]["approved"] is True
    assert ("baseline_value" in previous_checks[0]["config"]) is has_query
    assert ("monitoring" in previous_checks[0]["config"]) is monitoring_enabled
    assert research_kwargs["monitoring_enabled"] is monitoring_enabled
    assert result.checks_monitoring_enabled is monitoring_enabled
    assert result.checks_snapshot == {str(check.id): check.updated_at.isoformat()}


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,charts,expected",
    [
        # A resolved set replaces the column, in the same transaction as the ready transition.
        ("replace", [{"chart_id": "new", "title": "New", "query": {"kind": "InsightVizNode"}}], "replaced"),
        # None means "leave alone" — the report keeps whatever it had.
        ("leave_alone", None, "kept"),
        # [] clears (the resolver's cap-bust signal) — a stale set must not survive under new prose.
        ("clear", [], "cleared"),
    ],
)
async def test_mark_report_ready_activity_applies_charts(ateam, name, charts, expected):
    # Charts land in the same transaction as the title/summary the ready transition writes, so a
    # failure of that activity can never leave new charts under stale prose.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
        charts=[_EXISTING_CHART],
    )

    await mark_report_ready_activity(
        MarkReportReadyInput(
            team_id=ateam.id,
            report_id=str(report.id),
            title="Title",
            summary="Summary",
            processed_signal_count=2,
            charts=charts,
        )
    )

    stored = await database_sync_to_async(lambda: SignalReport.objects.get(id=report.id).charts)()
    if expected == "replaced":
        assert [chart["chart_id"] for chart in stored] == ["new"]
    elif expected == "kept":
        assert stored == [_EXISTING_CHART]
    else:
        assert stored == []


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize(
    "tags,expected",
    [
        (["Session Replay", "!!!"], ["session-replay"]),
        ([], []),
        (None, ["billing", "api"]),
    ],
)
async def test_report_transition_replaces_tags_with_the_prose(ateam, pending, tags, expected):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
        tags=["billing", "api"],
    )

    if pending:
        await mark_report_pending_input_activity(
            MarkReportPendingInput(
                team_id=ateam.id,
                report_id=str(report.id),
                title="Title",
                summary="Summary",
                reason="Requires human input",
                tags=tags,
            )
        )
    else:
        await mark_report_ready_activity(
            MarkReportReadyInput(
                team_id=ateam.id,
                report_id=str(report.id),
                title="Title",
                summary="Summary",
                processed_signal_count=2,
                tags=tags,
            )
        )

    stored = await database_sync_to_async(lambda: SignalReport.objects.get(id=report.id))()
    assert stored.title == "Title"
    assert stored.tags == expected


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,metrics,expected",
    [
        ("replace", [_metric("new-affected-users").model_dump(mode="json")], "replaced"),
        ("leave_alone", None, "kept"),
        ("clear", [], "cleared"),
    ],
)
async def test_mark_report_ready_activity_applies_metrics(ateam, name, metrics, expected):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
        metrics=[_EXISTING_METRIC],
    )

    await mark_report_ready_activity(
        MarkReportReadyInput(
            team_id=ateam.id,
            report_id=str(report.id),
            title="Title",
            summary="Summary",
            processed_signal_count=2,
            metrics=metrics,
        )
    )

    stored = await database_sync_to_async(lambda: SignalReport.objects.get(id=report.id).metrics)()
    if expected == "replaced":
        assert [metric["metric_id"] for metric in stored] == ["new-affected-users"]
    elif expected == "kept":
        assert stored == [_EXISTING_METRIC]
    else:
        assert stored == []


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "reconcile_checks,checks,retired,approval",
    [
        (False, [], False, None),
        (True, None, False, None),
        (True, [], True, None),
        (True, [], True, "before_research"),
        (True, [], False, "during_research"),
        (
            False,
            [{"title": "Legacy proposal", "kind": "agent", "config": {"instructions": "Check again."}}],
            False,
            "before_research",
        ),
        (
            True,
            [
                {
                    "title": "Invalid metric",
                    "kind": "metric_threshold",
                    "config": {"metric_id": "missing", "comparison": {"operator": "lte", "value": 5}},
                }
            ],
            False,
            None,
        ),
    ],
)
@pytest.mark.parametrize("pending_input", [False, True])
async def test_ready_transition_only_reconciles_explicit_new_check_payloads(
    ateam: Team,
    reconcile_checks: bool,
    checks: list[dict] | None,
    retired: bool,
    approval: str | None,
    pending_input: bool,
) -> None:
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )
    check = await database_sync_to_async(SignalReportCheck.objects.for_team(ateam.id).create)(
        team_id=ateam.id,
        report=report,
        title="The export error stays fixed",
        kind=SignalReportCheck.Kind.AGENT,
        config={"instructions": "Check for export errors."},
        status=SignalReportCheck.Status.PENDING,
        next_run_at=timezone.now() + timedelta(days=7),
        expires_at=timezone.now() + timedelta(days=37),
        soak_minutes=7 * 24 * 60,
    )
    if approval == "before_research":
        check.approved_at = timezone.now()
        await database_sync_to_async(check.save)(update_fields=["approved_at", "updated_at"])
    snapshot = {str(check.id): check.updated_at.isoformat()}
    if approval == "during_research":
        check.approved_at = timezone.now()
        await database_sync_to_async(check.save)(update_fields=["approved_at", "updated_at"])

    if pending_input:
        await mark_report_pending_input_activity(
            MarkReportPendingInput(
                team_id=ateam.id,
                report_id=str(report.id),
                title="Title",
                summary="Summary",
                reason="Needs input",
                checks=checks,
                checks_snapshot=snapshot,
                reconcile_checks=reconcile_checks,
                checks_summary="Reconciled summary",
            )
        )
    else:
        await mark_report_ready_activity(
            MarkReportReadyInput(
                team_id=ateam.id,
                report_id=str(report.id),
                title="Title",
                summary="Summary",
                processed_signal_count=2,
                checks=checks,
                checks_snapshot=snapshot,
                reconcile_checks=reconcile_checks,
                checks_summary="Reconciled summary",
            )
        )

    await database_sync_to_async(check.refresh_from_db)()
    assert (check.status == SignalReportCheck.Status.CANCELLED) is retired

    await database_sync_to_async(report.refresh_from_db)()
    assert report.summary == ("Reconciled summary" if retired else "Summary")


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_mark_report_pending_input_activity_applies_metrics_with_draft_prose(ateam):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
        metrics=[_EXISTING_METRIC],
    )
    new_metric = _metric("pending-affected-users").model_dump(mode="json")

    await mark_report_pending_input_activity(
        MarkReportPendingInput(
            team_id=ateam.id,
            report_id=str(report.id),
            title="Draft title",
            summary="Draft summary",
            reason="Needs input",
            metrics=[new_metric],
            checks=[
                {
                    "title": "Affected users stay below five",
                    "kind": "metric_threshold",
                    "soak_hours": 24,
                    "config": {"metric_id": "pending-affected-users", "comparison": {"operator": "lte", "value": 5}},
                }
            ],
            reconcile_checks=True,
        )
    )

    stored = await database_sync_to_async(lambda: SignalReport.objects.get(id=report.id))()
    assert stored.status == SignalReport.Status.PENDING_INPUT
    assert stored.title == "Draft title"
    assert stored.summary == "Draft summary"
    assert [metric["metric_id"] for metric in stored.metrics] == ["pending-affected-users"]
    check = await database_sync_to_async(SignalReportCheck.objects.for_team(ateam.id).get)(report=report)
    assert check.status == SignalReportCheck.Status.PENDING
    assert check.config["query"] == new_metric["query"]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("pending_input", [False, True])
async def test_report_transition_discards_legacy_goal_fields(ateam: Team, pending_input: bool) -> None:
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=2,
        total_weight=1.3,
    )
    metric = (
        _metric("measured-outcome")
        .model_copy(update={"goal_value": 0, "goal_direction": "at_most", "decision_window_days": 7})
        .model_dump(mode="json")
    )
    if pending_input:
        await mark_report_pending_input_activity(
            MarkReportPendingInput(
                team_id=ateam.id,
                report_id=str(report.id),
                title="Draft title",
                summary="Draft summary",
                reason="Needs input",
                metrics=[metric],
            )
        )
    else:
        await mark_report_ready_activity(
            MarkReportReadyInput(
                team_id=ateam.id,
                report_id=str(report.id),
                title="Title",
                summary="Summary",
                processed_signal_count=2,
                metrics=[metric],
            )
        )

    def stored_outcome() -> list[dict[str, object]]:
        updated_report = SignalReport.objects.get(id=report.id)
        return updated_report.metrics

    observations = await database_sync_to_async(stored_outcome)()
    assert observations[0]["metric_id"] == "measured-outcome"
    assert not any(field in observations[0] for field in REPORT_METRIC_GOAL_FIELDS)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "error,raised_type,error_type",
    [
        (RuntimeError("sandbox failed"), RuntimeError, None),
        (ValueError("No JSON in initial turn: end-turn text was prose"), ApplicationError, "output_parse_failed"),
    ],
)
async def test_run_agentic_report_activity_does_not_persist_partial_artefacts(
    monkeypatch, ateam, error: Exception, raised_type: type[Exception], error_type: str | None
):
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.IN_PROGRESS,
        signal_count=1,
        total_weight=0.8,
    )

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_user_id_for_team",
        lambda team_id: 1,
    )

    contexts: list[CustomPromptSandboxContext] = []

    async def fake_run_multi_turn_research(signals, context, **kwargs):
        contexts.append(context)
        raise error

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.run_multi_turn_research",
        fake_run_multi_turn_research,
    )

    with patch("products.signals.backend.temporal.agentic.report.Heartbeater"):
        with pytest.raises(raised_type, match=str(error)) as raised:
            await run_agentic_report_activity(
                RunAgenticReportInput(
                    team_id=ateam.id,
                    report_id=str(report.id),
                    signals=_build_signals()[:1],
                    repo_selection=RepoSelectionResult(repository="posthog/posthog", reason="test"),
                )
            )

        artefact_count = await database_sync_to_async(
            lambda: SignalReportArtefact.objects.filter(report=report).count()
        )()
        assert artefact_count == 0
    assert getattr(raised.value, "type", None) == error_type
    assert contexts[0].disable_repo_hooks


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("selected", [False, True])
async def test_research_returns_reviewer_decision_only_when_enabled(enabled: bool, selected: bool) -> None:
    decision = ResearchReviewerDecision.model_validate(
        {
            "reviewers": [{"user_uuid": "00000000-0000-4000-8000-000000000001", "reason": "Owns this component."}]
            if selected
            else [],
            "reason": "Checked ownership and corrections for this component.",
        }
    )
    finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)
    session = Mock(task=Mock(id="research-task-id"), end=AsyncMock())
    session.send_followup = AsyncMock(
        side_effect=[
            ActionabilityAssessment(
                explanation="No change needed.",
                actionability=ActionabilityChoice.NOT_ACTIONABLE,
                already_addressed=False,
            ),
            ReportPresentationOutput(title="Report", summary="Summary", reviewer_decision=decision),
        ]
    )
    with (
        patch(
            "products.tasks.backend.facade.agents.MultiTurnSession.start", AsyncMock(return_value=(session, finding))
        ),
        patch("products.signals.backend.task_run_artefacts.aappend_task_run_artefact", new_callable=AsyncMock),
    ):
        result = await run_multi_turn_research(
            _build_signals()[:1], Mock(team_id=1), reviewer_selection_enabled=enabled
        )
    assert result.reviewer_decision == (decision if enabled else None)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("correction_attempt,existing_check", [(1, False), (4, False), (None, False), (None, True)])
async def test_verification_correction_persists_before_pr_merge(
    ateam: Team, correction_attempt: int | None, existing_check: bool
) -> None:
    corrected = correction_attempt is not None
    report = await SignalReport.objects.acreate(
        team=ateam, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1
    )
    task = await Task.objects.acreate(team=ateam, title="Research verification")
    await LLMSkill.objects.acreate(team=ateam, name=FALLBACK_CHECK_SKILL_NAME, is_latest=True, deleted=False)
    await database_sync_to_async(
        lambda: SignalScoutConfig.objects.for_team(ateam.id).create(team=ateam, skill_name=FALLBACK_CHECK_SKILL_NAME)
    )()
    previous = None
    if existing_check:
        previous = await SignalReportCheck.objects.for_team(ateam.id).acreate(
            team_id=ateam.id,
            report=report,
            title="Existing verification",
            kind="agent",
            config={"instructions": "Verify the outcome."},
            status="pending",
            soak_minutes=360,
            next_run_at=timezone.now() + timedelta(hours=6),
            expires_at=timezone.now() + timedelta(days=30),
        )
    finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)
    proposal = {
        "current_state": "Confirm the issue in current evidence.",
        "outcome": "Confirm recovery after deployment.",
        "checks": [
            {
                "kind": "agent",
                "title": "Verify recovery",
                "soak_hours": 6,
                "config": {
                    "instructions": "Verify recovery with traffic.",
                    "probe_hints": [f"Probe {i}" for i in range(7)],
                },
            }
        ],
    }
    correction = json.loads(json.dumps(proposal))
    if corrected:
        correction["checks"][0]["config"]["probe_hints"] = ["Inspect traffic", "Confirm recovery"]
    replies = [
        json.dumps(
            {
                "explanation": "The issue needs a fix.",
                "actionability": "immediately_actionable",
                "already_addressed": False,
            }
        ),
        json.dumps({"explanation": "The issue affects users.", "priority": "P2", "dollar_value": 1000}),
        json.dumps({"title": "fix: restore recovery", "summary": "Users need the recovery fix."}),
    ]
    replies.extend([json.dumps(proposal)] * (correction_attempt if correction_attempt is not None else 5))
    if corrected:
        replies.append(json.dumps(correction))
    session = MultiTurnSession(task=task, task_run=Mock(id=uuid4()))
    with (
        patch.object(MultiTurnSession, "start", AsyncMock(return_value=(session, finding))),
        patch.object(MultiTurnSession, "send_followup_raw", AsyncMock(side_effect=replies)) as raw,
        patch.object(MultiTurnSession, "end", AsyncMock()),
        patch("products.signals.backend.task_run_artefacts.aappend_task_run_artefact", new_callable=AsyncMock),
    ):
        result = await run_multi_turn_research(
            _build_signals()[:1], Mock(team_id=ateam.id), signal_report_id=str(report.id), agent_checks_enabled=True
        )
    assert raw.await_count == 3 + (correction_attempt + 1 if correction_attempt is not None else 5)
    correction_prompt = raw.await_args_list[-1].args[0]
    assert "probe_hints" in correction_prompt
    assert "at most 5 items" in correction_prompt
    assert "7" in correction_prompt
    assert "Correct only the verification plan" in correction_prompt
    assert "Do not do more research" in correction_prompt
    assert result.effective_findings() == [finding]
    assert result.summary == "Users need the recovery fix."
    await mark_report_ready_activity(
        MarkReportReadyInput(
            team_id=ateam.id,
            report_id=str(report.id),
            title=result.title,
            summary=result.summary,
            processed_signal_count=1,
            checks=[check.model_dump(mode="json") for check in result.checks] if result.checks is not None else None,
            checks_error=result.checks_error,
            reconcile_checks=result.checks is not None,
            checks_task_id=str(task.id),
        )
    )
    authoring = await SignalReportArtefact.objects.filter(report=report, type="check_authoring").alatest("created_at")
    assert json.loads(authoring.content)["status"] == ("succeeded" if corrected else "failed")
    if corrected:
        check = await SignalReportCheck.objects.for_team(ateam.id).aget(report=report)
        assert check.soak_minutes == 360
        assert check.config["probe_hints"] == ["Inspect traffic", "Confirm recovery"]
    else:
        assert await SignalReportArtefact.objects.filter(
            report=report, type="note", content__contains="Could not configure"
        ).aexists()
        assert await SignalReportCheck.objects.for_team(ateam.id).filter(report=report).acount() == int(existing_check)
        if previous is not None:
            await previous.arefresh_from_db()
            assert previous.status == "pending"
            assert previous.title == "Existing verification"
            assert previous.config == {"instructions": "Verify the outcome."}
    with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True):
        pr = await database_sync_to_async(transaction.atomic()(link_pull_request))(
            report=report,
            details=PullRequestDetails(
                url="https://github.com/example/app/pull/1",
                repository="example/app",
                number=1,
                state="merged",
                merged=True,
                merged_at=timezone.now(),
            ),
            actor=ArtefactAttribution.system(),
            claim_id=None,
            notify_reviewers=False,
        )
        await database_sync_to_async(reconcile_reports_for_pull_request)(team_id=ateam.id, pr_id=str(pr.id))
    await report.arefresh_from_db()
    assert report.status == (
        SignalReport.Status.MONITORING if corrected or existing_check else SignalReport.Status.READY
    )
    if not corrected and not existing_check:
        report.status = SignalReport.Status.IN_PROGRESS
        await report.asave(update_fields=["status"])
        await mark_report_ready_activity(
            MarkReportReadyInput(
                team_id=ateam.id,
                report_id=str(report.id),
                title=result.title,
                summary=result.summary,
                processed_signal_count=1,
                checks=[],
                reconcile_checks=True,
            )
        )
        with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True):
            await database_sync_to_async(reconcile_reports_for_pull_request)(team_id=ateam.id, pr_id=str(pr.id))
        await report.arefresh_from_db()
        assert report.status == SignalReport.Status.RESOLVED


@parameterized.expand(
    [
        ("immediately_actionable", ActionabilityChoice.IMMEDIATELY_ACTIONABLE, None),
        ("requires_human_input", ActionabilityChoice.REQUIRES_HUMAN_INPUT, None),
        ("not_actionable", ActionabilityChoice.NOT_ACTIONABLE, None),
        ("timeout", ActionabilityChoice.IMMEDIATELY_ACTIONABLE, TimeoutError),
        ("validation_failure", ActionabilityChoice.IMMEDIATELY_ACTIONABLE, ValidationError),
        ("revised_metric_summary", ActionabilityChoice.IMMEDIATELY_ACTIONABLE, None),
        ("cancellation", ActionabilityChoice.IMMEDIATELY_ACTIONABLE, asyncio.CancelledError),
    ]
)
async def test_run_multi_turn_research_requests_verification_note_as_the_final_actionable_step(
    _name: str, actionability: ActionabilityChoice, failure: type[BaseException] | None
) -> None:
    session = Mock()
    session.task = Mock(id="research-task-id")
    session.end = AsyncMock()

    actionability_result = ActionabilityAssessment(
        explanation="The research found a concrete code path and measured impact.",
        actionability=actionability,
        already_addressed=False,
    )
    responses: list[
        ActionabilityAssessment | PriorityAssessment | ReportPresentationOutput | FixVerificationOutput | BaseException
    ] = [actionability_result]
    expected_labels = ["actionability"]
    priority_result: PriorityAssessment | None = None
    if actionability != ActionabilityChoice.NOT_ACTIONABLE:
        priority_result = PriorityAssessment(
            explanation="The measured impact supports this priority.",
            priority=Priority.P2,
            dollar_value=1000.0,
        )
        responses.append(priority_result)
        expected_labels.append("priority")
    presentation_result = ReportPresentationOutput(
        title="fix(onboarding): restore completion tracking",
        summary="Users cannot complete the tracked onboarding flow.",
    )
    responses.append(presentation_result)
    expected_labels.append("presentation")
    verification_error: BaseException | None = None
    if actionability != ActionabilityChoice.NOT_ACTIONABLE:
        expected_labels.append("fix_verification")
        if failure is ValidationError:
            with pytest.raises(ValidationError) as exc_info:
                FixVerificationOutput(current_state=" ", outcome="Confirm the outcome.")
            verification_error = exc_info.value
        elif failure is not None:
            verification_error = failure("Verification interrupted")
        responses.append(
            verification_error
            if verification_error is not None
            else FixVerificationOutput.model_validate(
                {
                    "current_state": "Run query-trends for onboarding_completed over the same 14-day window.",
                    "outcome": "Confirm event volume returns to the pre-regression baseline.",
                    **(
                        {
                            "checks": [
                                {
                                    "title": "Completion returns to baseline",
                                    "kind": "metric_threshold",
                                    "config": {
                                        "metric_id": "completion",
                                        "comparison": {"operator": "gte", "value": 80},
                                    },
                                }
                            ],
                            "summary": "Users cannot complete the tracked onboarding flow. Expected impact: completion returns to at least 80 users.",
                        }
                        if _name == "revised_metric_summary"
                        else {}
                    ),
                }
            )
        )
    session.send_followup = AsyncMock(side_effect=responses)
    first_finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)

    with (
        patch(
            "products.tasks.backend.facade.agents.MultiTurnSession.start",
            AsyncMock(return_value=(session, first_finding)),
        ) as start_session,
        patch("products.signals.backend.task_run_artefacts.aappend_task_run_artefact", new_callable=AsyncMock),
        patch("products.signals.backend.report_generation.research.logger.exception") as log_exception,
    ):
        if failure is asyncio.CancelledError:
            with pytest.raises(asyncio.CancelledError) as canceled:
                await run_multi_turn_research(_build_signals()[:1], Mock(team_id=1), signal_report_id="report-id")
            assert canceled.value is verification_error
        else:
            result = await run_multi_turn_research(
                _build_signals()[:1],
                Mock(team_id=1),
                signal_report_id="report-id",
                metrics_enabled=_name == "revised_metric_summary",
                monitoring_enabled=_name == "revised_metric_summary",
            )
            assert result.effective_findings() == [first_finding]
            assert result.effective_actionability() == actionability_result
            assert result.effective_priority() == priority_result
            assert result.title == presentation_result.title
            assert result.summary == "Users cannot complete the tracked onboarding flow."
            assert result.checks_summary == (
                "Users cannot complete the tracked onboarding flow. Expected impact: completion returns to at least 80 users."
                if _name == "revised_metric_summary"
                else None
            )
            assert result.research_task_id == "research-task-id"
            assert (result.checks_error is not None) is (failure is not None)
            if actionability != ActionabilityChoice.NOT_ACTIONABLE and failure is None:
                assert result.verification_note is not None
                if _name == "revised_metric_summary":
                    assert result.checks is not None
                    assert result.checks[0].config["comparison"]["value"] == 80
                else:
                    assert result.checks is None
                assert result.verification_note.note.startswith(
                    "## Verification plan\n\n### Confirm the current state\n\n"
                )
            else:
                assert result.verification_note is None

    preferred = _name == "revised_metric_summary"
    assert ("## Prepare metric-based follow-up checks" in start_session.call_args.kwargs["prompt"]) is preferred
    prompts = {call.kwargs["label"]: call.args[0] for call in session.send_followup.await_args_list}
    assert ("## Metrics for follow-up checks" in prompts["presentation"]) is preferred
    if "fix_verification" in prompts:
        assert ("70-80% confidence" in prompts["fix_verification"]) is preferred
    labels = [call.kwargs["label"] for call in session.send_followup.await_args_list]
    assert labels == expected_labels
    if failure is asyncio.CancelledError:
        session.end.assert_awaited_once_with(status="failed", error=str(verification_error), error_type=None)
    else:
        session.end.assert_awaited_once_with()
    if failure is not None and failure is not asyncio.CancelledError:
        log_exception.assert_called_once_with(
            "multi_turn_research: failed to generate fix verification note",
            extra={"research_task_id": "research-task-id", "team_id": 1, "report_id": "report-id"},
        )
    else:
        log_exception.assert_not_called()


@pytest.mark.asyncio
async def test_run_multi_turn_research_ends_session_when_followup_fails():
    signals = _build_signals()

    session = Mock()
    session.send_followup = AsyncMock(side_effect=RuntimeError("custom_prompt - poll_for_turn: timed out after 1800s"))
    session.end = AsyncMock()
    first_finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)

    with patch(
        "products.tasks.backend.facade.agents.MultiTurnSession.start",
        AsyncMock(return_value=(session, first_finding)),
    ):
        with pytest.raises(RuntimeError, match="poll_for_turn"):
            await run_multi_turn_research(signals, Mock())

    session.end.assert_awaited_once()
    assert session.end.await_args.kwargs["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supersede_outcome",
    [
        RuntimeError("custom_prompt - poll_for_turn: timed out after 1800s"),
        ImplementationAssessment(
            obsolete_pr_urls=["https://github.com/example/repo/pull/1"], reason="the root cause moved"
        ),
    ],
)
async def test_run_multi_turn_research_survives_a_failed_supersede_turn(supersede_outcome):
    """The supersede turn is asked last, after every finding, judgment, title and summary is in
    hand, and the decision is optional downstream. A raise there used to end the session as failed
    and discard a research run whose activity budget is four hours."""
    signals = _build_signals()
    previous = ReportResearchOutput(
        title="Old title",
        summary="Old summary",
        new_artefacts=[
            SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True),
            ActionabilityAssessment(
                explanation="Clear fix in the affected module.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            PriorityAssessment(explanation="Affects many sessions.", priority=Priority.P2),
        ],
    )
    presentation = ReportPresentationOutput(title="New title", summary="New summary")
    by_label = {
        "signal_2_of_2": SignalFinding(signal_id="sig-2", relevant_code_paths=[], data_queried="", verified=True),
        "actionability": ActionabilityUpdate(previous_assessment_correct=True),
        "priority": PriorityUpdate(previous_assessment_correct=True),
        "presentation": presentation,
        "fix_verification": FixVerificationOutput(current_state="Confirm the issue.", outcome="Confirm the fix."),
        "supersede": supersede_outcome,
    }

    async def fake_send_followup(
        message, model, *, label="", validation_context=None, json_retry_prompt=None, max_json_retries=1
    ):
        outcome = by_label[label]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    session = Mock()
    session.send_followup = AsyncMock(side_effect=fake_send_followup)
    session.end = AsyncMock()
    session.task = Mock(id="task-1")
    first_finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)

    with patch(
        "products.tasks.backend.facade.agents.MultiTurnSession.start",
        AsyncMock(return_value=(session, first_finding)),
    ):
        result = await run_multi_turn_research(
            signals,
            Mock(),
            previous_report_research=previous,
            implementation_context=ImplementationResearchContext(
                candidates=(
                    ImplementationTarget(
                        task_id=UUID(int=1),
                        run_id=UUID(int=2),
                        pr_url="https://github.com/example/repo/pull/1",
                        head_sha="abc",
                        automation_artefact_id=UUID(int=3),
                    ),
                ),
                run_count=2,
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )

    assert (result.title, result.summary) == ("New title", "New summary")
    assert result.verification_note == by_label["fix_verification"].to_note()
    session.end.assert_awaited_once()
    assert "status" not in session.end.await_args.kwargs
    decided = result.effective_implementation_decision()
    if isinstance(supersede_outcome, Exception):
        assert decided is None
    else:
        assert decided is not None
        assert decided.reason == supersede_outcome.reason
        assert [target.pr_url for target in decided.targets] == supersede_outcome.obsolete_pr_urls
        assert decided.research_run_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actionability", "expects_supersede_turn"),
    [
        (ActionabilityChoice.IMMEDIATELY_ACTIONABLE, True),
        (ActionabilityChoice.REQUIRES_HUMAN_INPUT, False),
        (ActionabilityChoice.NOT_ACTIONABLE, False),
    ],
)
async def test_run_multi_turn_research_only_asks_about_the_pr_when_actionable(actionability, expects_supersede_turn):
    """Auto-start is the decision's only consumer and it takes immediately-actionable reports only,
    so asking on the other two outcomes buys a sandbox turn nothing can read."""
    signals = _build_signals()
    previous = ReportResearchOutput(
        title="Old title",
        summary="Old summary",
        new_artefacts=[
            SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True),
            ActionabilityAssessment(
                explanation="Clear fix in the affected module.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            PriorityAssessment(explanation="Affects many sessions.", priority=Priority.P2),
        ],
    )
    by_label = {
        "signal_2_of_2": SignalFinding(signal_id="sig-2", relevant_code_paths=[], data_queried="", verified=True),
        "actionability": ActionabilityUpdate(
            previous_assessment_correct=False,
            assessment=ActionabilityAssessment(
                explanation="The evidence changed what this needs.",
                actionability=actionability,
                already_addressed=False,
            ),
        ),
        "priority": PriorityUpdate(previous_assessment_correct=True),
        "presentation": ReportPresentationOutput(title="New title", summary="New summary"),
        "fix_verification": FixVerificationOutput(current_state="Confirm the issue.", outcome="Confirm the fix."),
        "supersede": ImplementationAssessment(
            obsolete_pr_urls=["https://github.com/example/repo/pull/1"], reason="the root cause moved"
        ),
    }
    asked_labels: list[str] = []

    async def fake_send_followup(
        message, model, *, label="", validation_context=None, json_retry_prompt=None, max_json_retries=1
    ):
        asked_labels.append(label)
        return by_label[label]

    session = Mock()
    session.send_followup = AsyncMock(side_effect=fake_send_followup)
    session.end = AsyncMock()
    session.task = Mock(id="task-1")
    first_finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)

    with patch(
        "products.tasks.backend.facade.agents.MultiTurnSession.start",
        AsyncMock(return_value=(session, first_finding)),
    ):
        result = await run_multi_turn_research(
            signals,
            Mock(),
            previous_report_research=previous,
            implementation_context=ImplementationResearchContext(
                candidates=(
                    ImplementationTarget(
                        task_id=UUID(int=1),
                        run_id=UUID(int=2),
                        pr_url="https://github.com/example/repo/pull/1",
                        head_sha="abc",
                        automation_artefact_id=UUID(int=3),
                    ),
                ),
                run_count=2,
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )

    assert ("supersede" in asked_labels) is expects_supersede_turn
    assert (result.effective_implementation_decision() is not None) is expects_supersede_turn
    assert (result.verification_note is not None) is (actionability != ActionabilityChoice.NOT_ACTIONABLE)


def test_parse_artefact_content_parses_valid_content():
    actionability = ActionabilityAssessment(
        explanation="e", actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE, already_addressed=False
    )
    artefact = SignalReportArtefact(
        type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT, content=actionability.model_dump_json()
    )
    assert _parse_artefact_content(ActionabilityAssessment, artefact, "report-1") == actionability


def test_parse_artefact_content_raises_on_incompatible_schema():
    # No legacy path writes these artefacts, so a parse failure is our bug — fail loudly, don't skip.
    artefact = SignalReportArtefact(
        type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT, content='{"unexpected": "shape"}'
    )
    with pytest.raises(ValueError, match="incompatible with the current ActionabilityAssessment schema"):
        _parse_artefact_content(ActionabilityAssessment, artefact, "report-1")


def test_parse_stored_charts_skips_bad_rows_without_raising():
    # A re-research loads a report's stored charts to show back to the agent. A row that no longer
    # validates (a tightened schema, a legacy shape) must be dropped, not crash the re-promotion.
    valid = _chart().model_dump(mode="json")
    invalid = {"chart_id": "no-query"}  # missing required title/query
    assert [chart.chart_id for chart in _parse_stored_charts([valid, invalid], "report-1")] == ["signups-drop"]
    # A non-list (a legacy null / bad column value) is treated as no charts rather than raising.
    assert _parse_stored_charts(None, "report-1") == []


def test_parse_stored_metrics_skips_bad_rows_without_raising():
    valid = _metric().model_dump(mode="json")
    invalid = {"metric_id": "missing-measurement"}
    assert [metric.metric_id for metric in _parse_stored_metrics([valid, invalid], "report-1")] == ["affected-users"]
    assert _parse_stored_metrics(None, "report-1") == []


def _actionability(explanation: str) -> ActionabilityAssessment:
    return ActionabilityAssessment(
        explanation=explanation,
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
        already_addressed=False,
    )


def _priority(explanation: str) -> PriorityAssessment:
    return PriorityAssessment(explanation=explanation, priority=Priority.P1)


@pytest.mark.parametrize(
    ("response", "previous", "expected_explanation", "expected_is_new"),
    [
        # First run: a bare assessment is always new.
        (_actionability("fresh"), None, "fresh", True),
        # Update confirmed: the previous assessment is reused unchanged.
        (ActionabilityUpdate(previous_assessment_correct=True), _actionability("kept"), "kept", False),
        # Update replaced: the agent's new assessment supersedes the previous one.
        (
            ActionabilityUpdate(previous_assessment_correct=False, assessment=_actionability("new")),
            _actionability("old"),
            "new",
            True,
        ),
    ],
)
def test_resolve_actionability_response(response, previous, expected_explanation, expected_is_new):
    result, is_new = _resolve_actionability_response(response, previous)
    assert is_new is expected_is_new
    assert result.explanation == expected_explanation


@pytest.mark.parametrize(
    ("response", "previous", "expected_explanation", "expected_is_new"),
    [
        (_priority("fresh"), None, "fresh", True),
        (PriorityUpdate(previous_assessment_correct=True), _priority("kept"), "kept", False),
        (
            PriorityUpdate(previous_assessment_correct=False, assessment=_priority("new")),
            _priority("old"),
            "new",
            True,
        ),
    ],
)
def test_resolve_priority_response(response, previous, expected_explanation, expected_is_new):
    result, is_new = _resolve_priority_response(response, previous)
    assert is_new is expected_is_new
    assert result.explanation == expected_explanation
