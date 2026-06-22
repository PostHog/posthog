import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.auto_start import (
    ReviewerContent,
    _resolve_autostart_assignee,
    maybe_autostart_implementation_task,
)
from products.signals.backend.models import SignalReportTask, SignalUserAutonomyConfig
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
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


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_autostart_tags_implementation_ai_stage(ateam):
    """The autostart implementation run is tagged ai_stage="implementation" so its
    $ai_generation traces are attributed instead of landing in the "(none)" bucket."""
    assignee = SimpleNamespace(id=123)
    created = SimpleNamespace(task_id=uuid.uuid4(), team_id=ateam.id, latest_run=object())
    create_and_run_task = MagicMock(return_value=created)

    with (
        patch.object(tasks_facade, "create_and_run_task", create_and_run_task),
        patch("products.signals.backend.auto_start._resolve_autostart_assignee", return_value=assignee),
        patch.object(SignalReportTask.objects, "acreate", AsyncMock()),
    ):
        await maybe_autostart_implementation_task(
            team_id=ateam.id,
            report_id=str(uuid.uuid4()),
            repository="PostHog/posthog",
            title="Fix the thing",
            summary="A short summary",
            actionability=ActionabilityAssessment(
                explanation="Clearly actionable.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            reviewers_content=[_reviewer("octocat")],
            priority=PriorityAssessment(explanation="High impact.", priority=Priority.P0),
        )

    create_and_run_task.assert_called_once()
    kwargs = create_and_run_task.call_args.kwargs
    assert kwargs["origin_product"] == tasks_facade.TaskOriginProduct.SIGNAL_REPORT
    assert kwargs["ai_stage"] == "implementation"
