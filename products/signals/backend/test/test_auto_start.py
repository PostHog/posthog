import uuid

import pytest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.sync import database_sync_to_async

from products.signals.backend.auto_start import (
    ReviewerContent,
    _resolve_autostart_assignee,
    maybe_autostart_implementation_task,
)
from products.signals.backend.models import SignalReport, SignalSourceConfig, SignalUserAutonomyConfig
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)

AUTO_START_MODULE = "products.signals.backend.auto_start"
SCOUT = SignalSourceConfig.SourceProduct.SIGNALS_SCOUT.value


class _CreateAndRunReached(Exception):
    """Sentinel: raised from the patched Task.create_and_run to prove the gate let autostart through."""


@pytest_asyncio.fixture
async def aorganization():
    org = await sync_to_async(Organization.objects.create)(name=f"autostart-org-{uuid.uuid4().hex[:8]}")
    yield org
    await sync_to_async(org.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name="autostart-team")
    yield team
    await sync_to_async(team.delete)()


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
@pytest.mark.parametrize(
    ("source_products", "can_see", "should_proceed"),
    [
        ([SCOUT], False, False),  # scout-only + assignee not in rollout → held back
        ([SCOUT], True, True),  # scout-only + assignee flagged in → proceeds
        (["error_tracking"], False, True),  # non-scout report → gate does not apply
        (["error_tracking", SCOUT], False, True),  # cross-source keeps its rolled-out source → proceeds
    ],
)
async def test_autostart_holds_scout_only_reports_until_inbox_rollout(
    aorganization, ateam, source_products, can_see, should_proceed
):
    # Async DB writes here aren't rolled back between parametrized cases, so keep the user unique.
    suffix = uuid.uuid4().hex[:8]
    user = await database_sync_to_async(_create_org_member_with_github)(
        f"octo-{suffix}@example.com", aorganization, f"octo-{suffix}"
    )
    report = await database_sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.READY, title="t", summary="s", source_products=source_products
    )

    async def _call():
        await maybe_autostart_implementation_task(
            team_id=ateam.id,
            report_id=str(report.id),
            repository="owner/repo",
            title="t",
            summary="s",
            actionability=ActionabilityAssessment(
                explanation="x", actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE, already_addressed=False
            ),
            reviewers_content=[_reviewer("octo")],
            priority=PriorityAssessment(explanation="x", priority=Priority.P0),
        )

    with (
        patch(f"{AUTO_START_MODULE}._resolve_autostart_assignee", return_value=user),
        patch(f"{AUTO_START_MODULE}.user_can_see_signals_scout_reports", return_value=can_see),
        patch(f"{AUTO_START_MODULE}.Task.create_and_run", side_effect=_CreateAndRunReached) as create_mock,
    ):
        if should_proceed:
            with pytest.raises(_CreateAndRunReached):
                await _call()
        else:
            await _call()
            create_mock.assert_not_called()
