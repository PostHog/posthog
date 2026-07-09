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
    _report_meets_team_autostart_threshold,
    _resolve_autostart_assignee,
    _resolve_autostart_fallback_user,
    _resolve_triggering_user,
)
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportTask,
    SignalSourceConfig,
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


@pytest.mark.parametrize(
    ("report_priority", "team_default_priority", "expected"),
    [
        (Priority.P0, Priority.P2, True),  # above the team threshold → fallback may fire
        (Priority.P2, Priority.P2, True),  # at the team threshold → fallback may fire
        (Priority.P3, Priority.P2, False),  # below a stricter team threshold → gated out
        (Priority.P4, Priority.P4, True),  # default "all priorities" admits the lowest priority
    ],
)
def test_report_meets_team_autostart_threshold(report_priority, team_default_priority, expected):
    # Guards the reviewer-less fallback against auto-opening PRs for reports below the team's
    # configured default_autostart_priority (per-user priorities are intentionally ignored here).
    assert _report_meets_team_autostart_threshold(report_priority, team_default_priority) is expected


@pytest.mark.django_db
def test_resolve_autostart_fallback_user_prefers_earliest_active_enabler(organization, team):
    # Tier 1: run under the earliest active member who turned a signal source on. A departed /
    # deactivated enabler is skipped even though they enabled a source first (the task mints an
    # OAuth token as this user, so a disabled account can't run it).
    departed = User.objects.create(email="departed@example.com", is_active=False)
    OrganizationMembership.objects.create(user=departed, organization=organization)
    active_early = User.objects.create(email="early@example.com")
    OrganizationMembership.objects.create(user=active_early, organization=organization)
    active_late = User.objects.create(email="late@example.com")
    OrganizationMembership.objects.create(user=active_late, organization=organization)

    # Creation order fixes created_at ordering: departed first, then the two active members.
    SignalSourceConfig.objects.create(
        team=team, source_product="error_tracking", source_type="issue_created", created_by=departed
    )
    SignalSourceConfig.objects.create(
        team=team, source_product="error_tracking", source_type="issue_reopened", created_by=active_early
    )
    SignalSourceConfig.objects.create(
        team=team, source_product="error_tracking", source_type="issue_spiking", created_by=active_late
    )

    resolved = _resolve_autostart_fallback_user(team_id=team.id)

    assert resolved is not None
    assert resolved.id == active_early.id


@pytest.mark.django_db
def test_resolve_autostart_fallback_user_falls_back_to_org_owner(organization, team):
    # Tier 2: sources enabled by a system path leave created_by null, so there's no enabler to run
    # as. Attribute to the org owner, ahead of an admin, and never a plain member.
    SignalSourceConfig.objects.create(
        team=team, source_product="error_tracking", source_type="issue_created", created_by=None
    )
    member = User.objects.create(email="member@example.com")
    OrganizationMembership.objects.create(
        user=member, organization=organization, level=OrganizationMembership.Level.MEMBER
    )
    admin = User.objects.create(email="admin@example.com")
    OrganizationMembership.objects.create(
        user=admin, organization=organization, level=OrganizationMembership.Level.ADMIN
    )
    owner = User.objects.create(email="owner@example.com")
    OrganizationMembership.objects.create(
        user=owner, organization=organization, level=OrganizationMembership.Level.OWNER
    )

    resolved = _resolve_autostart_fallback_user(team_id=team.id)

    assert resolved is not None
    assert resolved.id == owner.id


@pytest.mark.django_db
def test_resolve_autostart_fallback_user_returns_none_without_enabler_or_admin(organization, team):
    # Tier 3 (fail-closed): a plain member with no enabled source and no elevated role is not an
    # eligible runner, so nothing auto-starts rather than picking an arbitrary member.
    member = User.objects.create(email="member@example.com")
    OrganizationMembership.objects.create(
        user=member, organization=organization, level=OrganizationMembership.Level.MEMBER
    )

    assert _resolve_autostart_fallback_user(team_id=team.id) is None


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
    assert call_kwargs["internal"] is True
    # The gate the second evaluation observed is the legacy SignalReportTask implementation link,
    # written in the same transaction as the task; the task_run artefact is the work-log entry
    # alongside.
    assert SignalReportTask.objects.filter(report=report, relationship=TASK_RUN_TYPE_IMPLEMENTATION).count() == 1
    assert (
        SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN).count() == 1
    )
    assert signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_IMPLEMENTATION) == [str(created_tasks[0].id)]
