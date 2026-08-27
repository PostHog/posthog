from types import SimpleNamespace

import pytest
from unittest.mock import patch

from django.apps import apps

from asgiref.sync import sync_to_async

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.artefact_schemas import NoteArtefact, RelatedTo, SignalFinding
from products.signals.backend.auto_start import maybe_autostart_implementation_task
from products.signals.backend.models import (
    ArtefactAttribution,
    SignalReport,
    SignalReportArtefact,
    SignalReportTask,
    SignalSourceConfig,
)
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.sibling_overlap import find_sibling_with_same_fix, record_sibling_fix_skip
from products.signals.backend.task_run_artefacts import TASK_RUN_TYPE_IMPLEMENTATION
from products.tasks.backend.facade import api as tasks_facade

_PROVIDERS = "frontend/src/providers.tsx"
_COMMIT = "a1b2c3d"


def _finding(signal_id: str, *, paths: list[str], commits: list[str]) -> SignalFinding:
    return SignalFinding(
        signal_id=signal_id,
        relevant_code_paths=paths,
        relevant_commit_hashes=dict.fromkeys(commits, "introduced the unguarded init"),
        data_queried="none",
        verified=True,
    )


def _report_with_findings(team: Team, findings: list[SignalFinding]) -> SignalReport:
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )
    for finding in findings:
        SignalReportArtefact.append_finding(
            team_id=team.id, report_id=str(report.id), content=finding, attribution=ArtefactAttribution.system()
        )
    return report


def _start_implementation(team: Team, report: SignalReport) -> None:
    Task = apps.get_model("tasks", "Task")
    task = Task.objects.create(team=team, title="Implementation: t", description="d")
    SignalReportTask.objects.create(team=team, report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("sibling_finding", "sibling_implemented", "expect_task"),
    [
        # Same causative commit, different files: the overlap grouping could never have caught,
        # and the case that opened three pull requests for one line of code in production.
        (_finding("sib", paths=["frontend/src/other.tsx"], commits=[_COMMIT]), True, False),
        # Same primary file, no shared commit.
        (_finding("sib", paths=[_PROVIDERS], commits=["9999999"]), True, False),
        # The shared file is a supporting path on the sibling, not its subject, so the two reports
        # are neighbours rather than the same fix.
        (_finding("sib", paths=["frontend/src/other.tsx", _PROVIDERS], commits=["9999999"]), True, True),
        # Nothing in common at all.
        (_finding("sib", paths=["backend/api.py"], commits=["9999999"]), True, True),
        # Overlapping, but nobody is implementing the sibling. Standing down here would leave the
        # fix with no pull request from either report.
        (_finding("sib", paths=[_PROVIDERS], commits=[_COMMIT]), False, True),
    ],
)
async def test_autostart_defers_to_a_sibling_already_being_fixed(sibling_finding, sibling_implemented, expect_task):
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")

    def _setup() -> tuple[Team, SignalReport, SignalReport]:
        organization = Organization.objects.create(name="sibling-org")
        team = Team.objects.create(organization=organization, name="sibling-team")
        enabler = User.objects.create(email="sibling-enabler@example.com")
        OrganizationMembership.objects.create(user=enabler, organization=organization)
        SignalSourceConfig.objects.create(
            team=team, source_product="error_tracking", source_type="issue_created", created_by=enabler
        )
        sibling = _report_with_findings(team, [sibling_finding])
        if sibling_implemented:
            _start_implementation(team, sibling)
        report = _report_with_findings(team, [_finding("new", paths=[_PROVIDERS, "package.json"], commits=[_COMMIT])])
        return team, report, sibling

    team, report, sibling = await sync_to_async(_setup)()

    def _fake_create_and_run_task(**kwargs):
        task = Task.objects.create(
            team_id=team.id,
            title=kwargs["title"],
            description=kwargs["description"],
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        run = TaskRun.objects.create(task=task, team_id=team.id)
        return SimpleNamespace(task_id=task.id, team_id=team.id, latest_run=SimpleNamespace(id=run.id))

    with (
        patch.object(tasks_facade, "create_and_run_task", side_effect=_fake_create_and_run_task) as mock_create,
        patch("products.signals.backend.auto_start.resolve_agent_runtime", return_value=AgentRuntime()),
    ):
        await maybe_autostart_implementation_task(
            team_id=team.id,
            report_id=str(report.id),
            repository="owner/repo",
            title="t",
            summary="s",
            actionability=ActionabilityAssessment(
                explanation="Clear fix in the affected module.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            reviewers_content=[],
            priority=PriorityAssessment(explanation="Affects many sessions.", priority=Priority.P2),
        )

    assert (mock_create.call_count == 1) is expect_task

    def _links() -> list[str]:
        return [
            RelatedTo.model_validate_json(content).report_id
            for content in SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.RELATED_TO
            ).values_list("content", flat=True)
        ]

    # A skip has to say so in the inbox, and link the report that is shipping the fix.
    assert await sync_to_async(_links)() == ([] if expect_task else [str(sibling.id)])


@pytest.mark.django_db
def test_recording_a_sibling_skip_is_written_once_per_sibling():
    # Auto-start re-runs whenever a report's reviewers change, so an unguarded write would add a
    # note and a link to both reports on every edit.
    organization = Organization.objects.create(name="record-org")
    team = Team.objects.create(organization=organization, name="record-team")
    sibling = _report_with_findings(team, [_finding("sib", paths=[_PROVIDERS], commits=[_COMMIT])])
    _start_implementation(team, sibling)
    report = _report_with_findings(team, [_finding("new", paths=[_PROVIDERS], commits=["9999999"])])

    match = find_sibling_with_same_fix(team_id=team.id, report_id=str(report.id))
    assert match is not None
    assert match.report_id == str(sibling.id)
    assert match.overlap.value == _PROVIDERS

    record_sibling_fix_skip(team_id=team.id, report_id=str(report.id), sibling=match)
    record_sibling_fix_skip(team_id=team.id, report_id=str(report.id), sibling=match)

    notes = SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.NOTE)
    assert notes.count() == 1
    assert _PROVIDERS in NoteArtefact.model_validate_json(notes.get().content).note
    assert (
        SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.RELATED_TO).count()
        == 1
    )
    # The link is symmetric, so the report doing the work shows what deferred to it.
    assert (
        SignalReportArtefact.objects.filter(report=sibling, type=SignalReportArtefact.ArtefactType.RELATED_TO).count()
        == 1
    )
