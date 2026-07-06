from types import SimpleNamespace

import pytest
from unittest.mock import patch

from django.apps import apps

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.auto_start import (
    ReviewerContent,
    _create_implementation_task_if_absent,
    _resolve_autostart_assignee,
    _resolve_triggering_user,
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
    ("user_autostart_priority", "team_default_priority", "report_priority", "expect_match"),
    [
        (Priority.P2, Priority.P0, Priority.P0, True),  # personal config: report at/above threshold → match
        (Priority.P1, Priority.P0, Priority.P3, False),  # personal config: report below threshold → no match
        (None, Priority.P4, Priority.P4, True),  # no config → team default "all priorities" → match
        (None, Priority.P0, Priority.P3, False),  # no config → falls back to a stricter team default → no match
    ],
)
def test_resolve_autostart_assignee(
    organization, team, user_autostart_priority, team_default_priority, report_priority, expect_match
):
    # Effective threshold is the reviewer's personal config when set, else the team default — so the
    # no-config rows guard against assuming the *personal* default is all-priorities (which would
    # ignore a team's stricter default).
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    if user_autostart_priority is not None:
        SignalUserAutonomyConfig.objects.create(user=user, autostart_priority=user_autostart_priority.value)

    assignee = _resolve_autostart_assignee(
        team_id=team.id,
        report_priority=report_priority,
        reviewers_content=[_reviewer("octocat")],
        team_default_priority=team_default_priority,
    )

    if expect_match:
        assert assignee is not None
        assert assignee.id == user.id
    else:
        assert assignee is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("autostart_priority", "report_priority", "expect_user"),
    [
        (None, Priority.P4, True),  # no personal config → team default (P4) → runs as the triggering user
        (Priority.P0, Priority.P3, False),  # the triggering user's own strict threshold isn't met
    ],
)
def test_resolve_triggering_user_runs_as_self(organization, team, autostart_priority, report_priority, expect_user):
    # A user-triggered auto-start resolves to the triggering user themselves (subject to their own
    # threshold), never a named colleague — the core reviewer-impersonation guard.
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    if autostart_priority is not None:
        SignalUserAutonomyConfig.objects.create(user=user, autostart_priority=autostart_priority.value)

    resolved = _resolve_triggering_user(
        team_id=team.id,
        user_id=user.id,
        report_priority=report_priority,
        team_default_priority=Priority.P4,
    )

    if expect_user:
        assert resolved is not None
        assert resolved.id == user.id
    else:
        assert resolved is None


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
        "base_branch": None,
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
    # Pipeline-spawned implementation runs are internal so they stay out of the default task list.
    assert call_kwargs["internal"] is True
    # The gate the second evaluation observed is the legacy SignalReportTask implementation link,
    # written in the same transaction as the task; the task_run artefact is the work-log entry
    # alongside.
    assert SignalReportTask.objects.filter(report=report, relationship=TASK_RUN_TYPE_IMPLEMENTATION).count() == 1
    assert (
        SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN).count() == 1
    )
    assert signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_IMPLEMENTATION) == [str(created_tasks[0].id)]
