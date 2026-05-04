import json
import random
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    ReportResearchOutput,
    SignalFinding,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic.report import RunAgenticReportInput, run_agentic_report_activity
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
    return ReportResearchOutput(
        title="Onboarding funnel completion tracking may be regressing",
        summary="Signals point to a likely regression around onboarding completion event tracking.",
        findings=[
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
        ],
        actionability=ActionabilityAssessment(
            explanation="The issue has a clear code path and supporting event-volume evidence.",
            actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
            already_addressed=False,
        ),
        priority=PriorityAssessment(
            explanation="The regression affects a core onboarding flow and should be addressed quickly.",
            priority=Priority.P1,
        ),
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
        "products.signals.backend.temporal.agentic.select_repository._resolve_team_repo_context",
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
async def test_select_repository_activity_no_repo(monkeypatch, ateam):
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository._load_previous_repo_selection",
        lambda report_id: None,
    )
    monkeypatch.setattr(
        "products.signals.backend.temporal.agentic.select_repository._resolve_team_repo_context",
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
        }

        repo_selection_content = json.loads(artefacts[2].content)
        assert repo_selection_content == {
            "repository": "posthog/posthog",
            "reason": "Single repository connected: posthog/posthog",
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
