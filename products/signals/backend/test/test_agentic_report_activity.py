import json
import random
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, Mock, patch

from django.db import OperationalError

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration
from posthog.sync import database_sync_to_async

from products.signals.backend.auto_start import ReviewerContent
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_charts import ReportChart
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    ActionabilityUpdate,
    Priority,
    PriorityAssessment,
    PriorityUpdate,
    ProposedReviewer,
    ReportPresentationOutput,
    ReportResearchOutput,
    SignalFinding,
    SuggestedReviewersProposal,
    _resolve_actionability_response,
    _resolve_priority_response,
    run_multi_turn_research,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.reviewer_corrections import ReviewerCorrection
from products.signals.backend.temporal.agentic.report import (
    RunAgenticReportInput,
    _parse_artefact_content,
    _parse_stored_charts,
    _resolve_reviewers_content,
    _reviewers_from_proposals,
    run_agentic_report_activity,
)
from products.signals.backend.temporal.agentic.select_repository import (
    SelectRepositoryInput,
    select_repository_activity,
)
from products.signals.backend.temporal.summary import MarkReportReadyInput, mark_report_ready_activity
from products.signals.backend.temporal.types import SignalData


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


_EXISTING_CHART = {
    "chart_id": "existing",
    "title": "Existing chart",
    "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
}


async def _run_activity_with_output(monkeypatch, ateam, report, output, *, charts_enabled=True):
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.resolve_user_id_for_team",
        lambda team_id: 1,
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report._team_report_charts_enabled",
        lambda team_id: charts_enabled,
    )

    async def fake_run_multi_turn_research(*args, **kwargs):
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
            SelectRepositoryInput(team_id=ateam.id, report_id="test-report-id", signals=_build_signals())
        )

    assert result.repository == "posthog/posthog"
    assert "Single repository" in result.reason


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_select_repository_activity_reuses_previous_selection(monkeypatch, ateam):
    previous = RepoSelectionResult(repository="posthog/posthog", reason="Previously selected")

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
            SelectRepositoryInput(team_id=ateam.id, report_id="test-report-id", signals=_build_signals())
        )

    assert result is previous
    assert not select_repo_called


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_select_repository_activity_retries_transient_db_drop(monkeypatch, ateam):
    # A pooled pgbouncer connection dropped mid-request raises OperationalError on the
    # activity's early read. The retry-once guard must evict the dead connection and
    # succeed on the second attempt rather than letting it escape as error-tracking noise.
    previous = RepoSelectionResult(repository="posthog/posthog", reason="Previously selected")
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
            SelectRepositoryInput(team_id=ateam.id, report_id="test-report-id", signals=_build_signals())
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
            SelectRepositoryInput(team_id=ateam.id, report_id="test-report-id", signals=_build_signals())
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
            SelectRepositoryInput(team_id=ateam.id, report_id="test-report-id", signals=_build_signals())
        )

    assert result.repository == "posthog/posthog"
    assert captured_user_id == [user.id], "user_id should come from the UserIntegration owner"


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

    with patch("products.signals.backend.temporal.agentic.report.Heartbeater"):
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
        assert result.choice == ActionabilityChoice.IMMEDIATELY_ACTIONABLE
        assert result.priority == Priority.P1
        assert result.already_addressed is False
        assert result.repository == "posthog/posthog"

        artefacts = await database_sync_to_async(
            lambda: list(SignalReportArtefact.objects.filter(report=report).order_by("type", "created_at"))
        )()
        assert [artefact.type for artefact in artefacts] == [
            SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
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

        priority_content = json.loads(artefacts[1].content)
        assert priority_content == {
            "priority": "P1",
            "explanation": "The regression affects a core onboarding flow and should be addressed quickly.",
            "dollar_value": 5000.0,
        }

        repo_selection_content = json.loads(artefacts[2].content)
        assert repo_selection_content == {
            "repository": "posthog/posthog",
            "reason": "Single repository connected: posthog/posthog",
            "task_id": None,
        }

        finding_contents = [json.loads(artefact.content) for artefact in artefacts[3:]]
        assert [finding["signal_id"] for finding in finding_contents] == ["sig-1", "sig-2"]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,charts_enabled,output_factory,expected",
    [
        # Opted-in + a valid chart → the JSON set to store.
        ("enabled_non_empty", True, _build_research_output_with_chart, [{"chart_id": "signups-drop"}]),
        # Not opted in → None (leave the column alone), even though the mocked run returned a chart.
        ("disabled", False, _build_research_output_with_chart, None),
        # Opted-in but the run authored no charts (optional field omitted / dropped) → None, never a
        # wipe of whatever the report already showed.
        ("enabled_empty", True, _build_research_output, None),
        # Opted-in but the set busts the whole-set caps (duplicate id) → [] to clear, so a stale set
        # can't sit under the new summary.
        ("enabled_cap_bust", True, _build_research_output_with_duplicate_chart_ids, []),
    ],
)
async def test_run_agentic_report_activity_resolves_charts_payload(
    monkeypatch, ateam, name, charts_enabled, output_factory, expected
):
    # The activity resolves the charts payload but does not write it — the transition activity does,
    # atomically with the title/summary (see test_mark_report_ready_activity_applies_charts). So we
    # assert the resolved payload on the returned output rather than the report row.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.IN_PROGRESS, signal_count=2, total_weight=1.3
    )

    result = await _run_activity_with_output(
        monkeypatch, ateam, report, output_factory(), charts_enabled=charts_enabled
    )

    if expected is None:
        assert result.charts is None
    else:
        assert [{"chart_id": chart["chart_id"]} for chart in result.charts] == expected


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
async def test_run_agentic_report_activity_does_not_persist_partial_artefacts(monkeypatch, ateam):
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

    async def fake_run_multi_turn_research(*args, **kwargs):
        raise RuntimeError("sandbox failed")

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.run_multi_turn_research",
        fake_run_multi_turn_research,
    )

    with patch("products.signals.backend.temporal.agentic.report.Heartbeater"):
        with pytest.raises(RuntimeError, match="sandbox failed"):
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


def _ranked_reviewer_content(login: str = "alice", name: str | None = "Alice") -> ReviewerContent:
    return ReviewerContent(
        github_login=login,
        github_name=name,
        relevant_commits=[{"sha": "abc1234", "url": "https://github.com/x/y/commit/abc1234", "reason": "authored it"}],
        reason=None,
        is_skill_owner=False,
    )


def _correction(after: list[str], before: list[str] | None = None) -> ReviewerCorrection:
    return ReviewerCorrection(
        report_id="corrected-report-1",
        report_title="fix(signals): a similar report",
        before=before or [],
        after=after,
        at="2026-07-01T00:00:00+00:00",
    )


def test_reviewers_from_proposals_keeps_only_evidence_backed_logins():
    # The whole point of validation: an agent-proposed login persists only when the ranking, org
    # membership, or a human correction backs it — a hallucinated login must never route a report.
    proposals = [
        ProposedReviewer(github_login="@Alice", reason="authored the causative commit"),
        ProposedReviewer(github_login="carol", reason="human correction on a similar report"),
        ProposedReviewer(github_login="dana", reason="owns the affected surface"),
        ProposedReviewer(github_login="mallory", reason="sounds plausible"),
    ]
    member = Mock(first_name="Dana", last_name="Doe")
    with patch(
        "products.signals.backend.temporal.agentic.report.get_org_member_github_login_to_user_map",
        return_value={"dana": member},
    ):
        result = _reviewers_from_proposals(
            team_id=1,
            proposals=proposals,
            deterministic=[_ranked_reviewer_content("alice")],
            corrections=[_correction(after=["carol"])],
        )

    assert [reviewer["github_login"] for reviewer in result] == ["alice", "carol", "dana"]
    # A pick the ranking agrees with keeps its commit evidence and resolved name.
    assert result[0]["relevant_commits"][0]["sha"] == "abc1234"
    assert result[0]["github_name"] == "Alice"
    assert result[0]["reason"] == "authored the causative commit"
    # A correction-backed pick has no commit trail but keeps the agent's reason.
    assert result[1]["relevant_commits"] == []
    # An org-member pick resolves its display name from the member record.
    assert result[2]["github_name"] == "Dana Doe"


def test_reviewers_from_proposals_dedupes_and_caps():
    logins = ["alice", "alice", "bob", "carol", "dave"]
    proposals = [ProposedReviewer(github_login=login, reason="correction precedent") for login in logins]
    with patch(
        "products.signals.backend.temporal.agentic.report.get_org_member_github_login_to_user_map",
        return_value={},
    ):
        result = _reviewers_from_proposals(
            team_id=1,
            proposals=proposals,
            deterministic=[],
            corrections=[_correction(after=["alice", "bob", "carol", "dave"])],
        )
    assert [reviewer["github_login"] for reviewer in result] == ["alice", "bob", "carol"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("proposal_logins", "expected_logins", "expected_from_agent"),
    [
        # A validated agent pick wins over the deterministic ranking.
        (["carol"], ["carol"], True),
        # An all-invalid proposal falls back to the deterministic ranking.
        (["mallory"], ["alice"], False),
        # No proposal at all (turn disabled or failed) also falls back.
        ([], ["alice"], False),
    ],
)
async def test_resolve_reviewers_content_falls_back_to_deterministic(
    proposal_logins, expected_logins, expected_from_agent
):
    result = _build_research_output().model_copy(
        update={
            "suggested_reviewers": [
                ProposedReviewer(github_login=login, reason="correction precedent") for login in proposal_logins
            ]
        }
    )
    with patch(
        "products.signals.backend.temporal.agentic.report.get_org_member_github_login_to_user_map",
        return_value={},
    ):
        reviewers, from_agent = await _resolve_reviewers_content(
            1,
            "posthog/posthog",
            result,
            [_ranked_reviewer_content("alice")],
            [_correction(after=["carol"])],
        )
    assert [reviewer["github_login"] for reviewer in reviewers] == expected_logins
    assert from_agent is expected_from_agent


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_run_agentic_report_activity_persists_agent_reviewers_without_new_findings(monkeypatch, ateam):
    # On a re-research where every finding was confirmed unchanged, deterministic reviewers are not
    # re-persisted — but agent-decided reviewers must be, since correction precedent can change the
    # right routing between runs. Regression guard for the `has_new_finding or reviewers_from_agent`
    # persistence gate.
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.IN_PROGRESS, signal_count=2, total_weight=1.3
    )
    base = _build_research_output()
    output = base.model_copy(
        update={
            "new_artefacts": [],
            "old_artefacts": base.new_artefacts,
            "suggested_reviewers": [
                ProposedReviewer(github_login="carol", reason="human correction on a similar report")
            ],
        }
    )

    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report._team_agentic_reviewers_enabled",
        lambda team_id: True,
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.report.recent_reviewer_corrections",
        lambda team_id: [_correction(after=["carol"])],
    )

    await _run_activity_with_output(monkeypatch, ateam, report, output)

    artefacts = await database_sync_to_async(
        lambda: list(
            SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
            )
        )
    )()
    assert len(artefacts) == 1
    stored = json.loads(artefacts[0].content)
    assert [entry["github_login"] for entry in stored] == ["carol"]
    assert stored[0]["reason"] == "human correction on a similar report"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reviewers_turn_result", "expected_logins"),
    [
        # A successful turn lands the proposal on the research output.
        (
            SuggestedReviewersProposal(
                suggested_reviewers=[ProposedReviewer(github_login="alice", reason="authored it")]
            ),
            ["alice"],
        ),
        # A failed turn is swallowed: the run still completes with an empty proposal (the caller
        # then falls back to deterministic reviewers) instead of losing the whole research output.
        (RuntimeError("reviewers turn timed out"), []),
    ],
)
async def test_run_multi_turn_research_reviewers_turn(reviewers_turn_result, expected_logins):
    signals = _build_signals()

    session = Mock()
    session.task = Mock(id="task-1")
    session.end = AsyncMock()
    session.send_followup = AsyncMock(
        side_effect=[
            SignalFinding(signal_id="sig-2", relevant_code_paths=[], data_queried="", verified=True),
            ActionabilityAssessment(
                explanation="clear", actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE, already_addressed=False
            ),
            PriorityAssessment(explanation="core flow", priority=Priority.P1),
            reviewers_turn_result,
            ReportPresentationOutput(title="Report title", summary="Report summary"),
        ]
    )
    first_finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)

    with patch(
        "products.tasks.backend.facade.agents.MultiTurnSession.start",
        AsyncMock(return_value=(session, first_finding)),
    ):
        result = await run_multi_turn_research(signals, Mock(), suggest_reviewers=True)

    assert result.title == "Report title"
    assert [reviewer.github_login for reviewer in result.suggested_reviewers] == expected_logins
    session.end.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_run_multi_turn_research_skips_reviewers_turn_when_not_actionable():
    # The inbox hides reviewers on not-actionable reports, so the turn must not run (or cost
    # anything) there — mirroring how the priority turn is skipped.
    signals = _build_signals()[:1]

    session = Mock()
    session.task = Mock(id="task-1")
    session.end = AsyncMock()
    session.send_followup = AsyncMock(
        side_effect=[
            ActionabilityAssessment(
                explanation="too vague", actionability=ActionabilityChoice.NOT_ACTIONABLE, already_addressed=False
            ),
            ReportPresentationOutput(title="Report title", summary="Report summary"),
        ]
    )
    first_finding = SignalFinding(signal_id="sig-1", relevant_code_paths=[], data_queried="", verified=True)

    with patch(
        "products.tasks.backend.facade.agents.MultiTurnSession.start",
        AsyncMock(return_value=(session, first_finding)),
    ):
        result = await run_multi_turn_research(signals, Mock(), suggest_reviewers=True)

    assert result.suggested_reviewers == []
    assert session.send_followup.await_count == 2
