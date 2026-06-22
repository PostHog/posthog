import pytest
from unittest.mock import patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend import auto_start
from products.signals.backend.auto_start import (
    ReviewerContent,
    _create_implementation_task_if_absent,
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
from products.tasks.backend.models import Task, TaskRun


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
    # observes the link row must no-op rather than spawn another Task / draft PR.
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )

    def _fake_create_and_run(**kwargs):
        task = Task.objects.create(
            team=team,
            title=kwargs["title"],
            description=kwargs["description"],
            created_by=user,
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        TaskRun.objects.create(task=task, team=team)
        return task

    kwargs = {
        "team_id": team.id,
        "report_id": str(report.id),
        "title": "t",
        "description": "d",
        "user_id": user.id,
        "repository": "owner/repo",
        "base_branch": None,
    }
    with patch.object(auto_start.Task, "create_and_run", side_effect=_fake_create_and_run) as mock_create:
        first = _create_implementation_task_if_absent(**kwargs)
        second = _create_implementation_task_if_absent(**kwargs)

    assert first is not None
    assert second is None
    assert mock_create.call_count == 1
    # The gate the second evaluation observed is the legacy SignalReportTask implementation link,
    # written in the same transaction as the task; the task_run artefact is the work-log entry
    # alongside.
    assert (
        SignalReportTask.objects.filter(report=report, task=first, relationship=TASK_RUN_TYPE_IMPLEMENTATION).count()
        == 1
    )
    assert (
        SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN).count() == 1
    )
    assert signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_IMPLEMENTATION) == [str(first.id)]
