from datetime import timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import Mock, patch

from django.apps import apps
from django.utils import timezone

from asgiref.sync import async_to_sync
from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.artefact_schemas import Commit
from products.signals.backend.auto_start import (
    ReviewerContent,
    _build_autostart_task_description,
    _create_implementation_task_if_absent,
    _latest_artefact_as,
    _repository_default_branch,
    _resolve_autostart_assignee,
)
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportTask,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.research import Priority
from products.signals.backend.task_run_artefacts import TASK_RUN_TYPE_IMPLEMENTATION, signals_task_ids
from products.tasks.backend.facade import api as tasks_facade


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-auto-start-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-auto-start-team")


def _create_org_member_with_github(email: str, organization: Organization, login: str) -> User:
    user = User.objects.create(email=email)
    OrganizationMembership.objects.create(user=user, organization=organization)
    UserSocialAuth.objects.create(user=user, provider="github", uid=f"github-{login}", extra_data={"login": login})
    return user


def _reviewer(login: str) -> ReviewerContent:
    return ReviewerContent(github_login=login, github_name=None, relevant_commits=[])


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("autostart_priority", "report_priority", "expect_match"),
    [
        (Priority.P2, Priority.P0, True),  # report priority at/above threshold → match
        (Priority.P1, Priority.P3, False),  # report priority below threshold → no match
    ],
)
def test_resolve_autostart_assignee(organization, team, autostart_priority, report_priority, expect_match):
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    SignalUserAutonomyConfig.objects.create(user=user, autostart_priority=autostart_priority.value)

    assignee = _resolve_autostart_assignee(
        team_id=team.id,
        report_priority=report_priority,
        reviewers_content=[_reviewer("octocat")],
        team_default_priority=Priority.P0,
    )

    if expect_match:
        assert assignee is not None
        assert assignee.id == user.id
    else:
        assert assignee is None


@pytest.mark.django_db
def test_create_implementation_task_if_absent_is_idempotent(organization, team):
    # The locked create guards against duplicate auto-start tasks: a second evaluation that
    # observes the link row must no-op rather than spawn another Task / draft PR. It also asserts
    # the facade is invoked with the SIGNAL_REPORT origin and ai_stage="implementation" so the
    # run's $ai_generation traces are attributed rather than landing in the "(none)" bucket.
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )

    created_tasks = []

    def _fake_create_and_run_task(**kwargs):
        task = Task.objects.create(
            team=team,
            title=kwargs["title"],
            description=kwargs["description"],
            created_by=user,
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        run = TaskRun.objects.create(task=task, team=team)
        created_tasks.append(task)
        return SimpleNamespace(task_id=task.id, team_id=team.id, latest_run=SimpleNamespace(id=run.id))

    kwargs = {
        "team_id": team.id,
        "report_id": str(report.id),
        "title": "t",
        "description": "d",
        "user_id": user.id,
        "repository": "owner/repo",
        "branch": None,
        "pr_base_branch": None,
    }
    with patch.object(tasks_facade, "create_and_run_task", side_effect=_fake_create_and_run_task) as mock_create:
        first = _create_implementation_task_if_absent(**kwargs)
        second = _create_implementation_task_if_absent(**kwargs)

    assert first is True
    assert second is False
    assert mock_create.call_count == 1
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["origin_product"] == tasks_facade.TaskOriginProduct.SIGNAL_REPORT
    assert call_kwargs["ai_stage"] == "implementation"
    # The gate the second evaluation observed is the legacy SignalReportTask implementation link,
    # written in the same transaction as the task; the task_run artefact is the work-log entry
    # alongside.
    assert SignalReportTask.objects.filter(report=report, relationship=TASK_RUN_TYPE_IMPLEMENTATION).count() == 1
    assert (
        SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN).count() == 1
    )
    assert signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_IMPLEMENTATION) == [str(created_tasks[0].id)]


def test_build_autostart_task_description_uses_research_branch_when_present():
    commit = Commit(
        repository="owner/repo",
        branch="posthog-self-driving/fix-foo",
        commit_sha="abc123f",
        message="fix: foo",
    )
    description = _build_autostart_task_description(
        report_id="report-1",
        summary="Something broke",
        repository="owner/repo",
        priority=None,
        research_commit=commit,
    )
    assert "posthog-self-driving/fix-foo" in description
    assert "abc123f" in description
    assert "open a draft PR if good" in description
    assert "Babysit CI" in description


@pytest.mark.django_db
def test_latest_artefact_as_returns_newest_commit(team):
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )
    older = Commit(repository="owner/repo", branch="posthog-self-driving/old", commit_sha="111", message="old")
    newer = Commit(repository="owner/repo", branch="posthog-self-driving/new", commit_sha="222", message="new")
    older_artefact = SignalReportArtefact.objects.create(
        report=report,
        team=team,
        type=SignalReportArtefact.ArtefactType.COMMIT,
        content=older.model_dump_json(),
    )
    SignalReportArtefact.objects.filter(pk=older_artefact.pk).update(created_at=timezone.now() - timedelta(hours=1))
    SignalReportArtefact.objects.create(
        report=report,
        team=team,
        type=SignalReportArtefact.ArtefactType.COMMIT,
        content=newer.model_dump_json(),
    )

    result = async_to_sync(_latest_artefact_as)(str(report.id), SignalReportArtefact.ArtefactType.COMMIT, Commit)

    assert result is not None
    assert result.branch == "posthog-self-driving/new"


@pytest.mark.django_db
def test_create_implementation_task_passes_research_branch_and_pr_base(team, organization):
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )
    task = Task.objects.create(
        team=team,
        title="t",
        description="d",
        created_by=user,
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
    )
    run = TaskRun.objects.create(task=task, team=team)

    with patch.object(tasks_facade, "create_and_run_task") as mock_create:
        mock_create.return_value = SimpleNamespace(
            task_id=task.id, team_id=team.id, latest_run=SimpleNamespace(id=run.id)
        )
        _create_implementation_task_if_absent(
            team_id=team.id,
            report_id=str(report.id),
            title="t",
            description="d",
            user_id=user.id,
            repository="owner/repo",
            branch="posthog-self-driving/fix-foo",
            pr_base_branch="main",
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["branch"] == "posthog-self-driving/fix-foo"
    assert call_kwargs["pr_base_branch"] == "main"


@pytest.mark.parametrize(
    ("github", "expected"),
    [
        (Mock(get_default_branch=Mock(return_value="main")), "main"),
        (None, None),
        (Mock(get_default_branch=Mock(side_effect=RuntimeError("github down"))), None),
    ],
)
def test_repository_default_branch(github, expected):
    with patch("products.signals.backend.auto_start.GitHubIntegration") as mock_github_cls:
        mock_github_cls.first_for_team_repository.return_value = github
        assert _repository_default_branch(1, "owner/repo") == expected


@pytest.mark.django_db
def test_create_implementation_task_handoff_without_config_does_not_infer_feature_branch(team, organization):
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )
    task = Task.objects.create(
        team=team,
        title="t",
        description="d",
        created_by=user,
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
    )
    run = TaskRun.objects.create(task=task, team=team)

    with patch.object(tasks_facade, "create_and_run_task") as mock_create:
        mock_create.return_value = SimpleNamespace(
            task_id=task.id, team_id=team.id, latest_run=SimpleNamespace(id=run.id)
        )
        _create_implementation_task_if_absent(
            team_id=team.id,
            report_id=str(report.id),
            title="t",
            description="d",
            user_id=user.id,
            repository="owner/repo",
            branch="posthog-self-driving/fix-foo",
            pr_base_branch=None,
        )

    assert mock_create.call_args.kwargs["branch"] == "posthog-self-driving/fix-foo"
    assert mock_create.call_args.kwargs["pr_base_branch"] is None
