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

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    ActionabilityUpdate,
    Priority,
    PriorityAssessment,
    PriorityUpdate,
    ReportResearchOutput,
    SignalFinding,
    _resolve_actionability_response,
    _resolve_priority_response,
    run_multi_turn_research,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic.report import (
    RunAgenticReportInput,
    _parse_artefact_content,
    run_agentic_report_activity,
)
from products.signals.backend.temporal.agentic.select_repository import (
    SelectRepositoryInput,
    select_repository_activity,
)
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
        "products.signals.backend.temporal.agentic.select_repository._load_previous_repo_selection",
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
        "products.signals.backend.temporal.agentic.select_repository._load_previous_repo_selection",
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
        "products.signals.backend.temporal.agentic.select_repository._load_previous_repo_selection",
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
        "products.signals.backend.temporal.agentic.select_repository._load_previous_repo_selection",
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
    # PostHog Code installs land in `UserIntegration`, never on `Integration`. Before the cascade
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
        "products.signals.backend.temporal.agentic.select_repository._load_previous_repo_selection",
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
