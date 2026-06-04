import random

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team, User

from products.signals.backend.auto_start import ReviewerContent, maybe_autostart_implementation_task
from products.signals.backend.cursor_dispatch import CursorDispatchError, CursorDispatchResult
from products.signals.backend.models import CodingAgent, SignalReport, SignalReportTask, SignalTeamConfig
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)

ASSIGNEE_PATH = "products.signals.backend.auto_start._resolve_autostart_assignee"
FLAG_PATH = "products.signals.backend.auto_start.posthoganalytics.feature_enabled"
DISPATCH_PATH = "products.signals.backend.auto_start.dispatch_report_to_cursor"
CREATE_AND_RUN_PATH = "products.tasks.backend.models.Task.create_and_run"
SIGNAL_REPORT_TASK_CREATE_PATH = "products.signals.backend.auto_start.SignalReportTask.objects.create"


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsCursorRoutingOrg-{random.randint(1, 99999)}",
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsCursorRoutingTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


@pytest_asyncio.fixture
async def auser():
    user = await sync_to_async(User.objects.create)(
        email=f"signals-cursor-{random.randint(1, 99999)}@example.com",
        distinct_id=f"distinct-{random.randint(1, 99999)}",
    )
    yield user
    await sync_to_async(user.delete)()


@pytest_asyncio.fixture
async def areport(ateam):
    report = await sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.READY,
        title="Checkout 500s",
        summary="Users hit a 500 on the checkout page",
        signal_count=2,
        total_weight=1.0,
    )
    yield report


def _actionability() -> ActionabilityAssessment:
    return ActionabilityAssessment(
        explanation="Clear code path and supporting evidence.",
        actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
        already_addressed=False,
    )


def _priority() -> PriorityAssessment:
    return PriorityAssessment(explanation="Affects revenue.", priority=Priority.P1)


def _reviewers() -> list[ReviewerContent]:
    return [{"github_login": "octocat", "github_name": "Octo Cat", "relevant_commits": []}]


async def _set_default_agent(team, agent) -> None:
    await sync_to_async(SignalTeamConfig.objects.update_or_create)(team=team, defaults={"default_coding_agent": agent})


async def _run(team, report, user):
    await maybe_autostart_implementation_task(
        team_id=team.id,
        report_id=str(report.id),
        repository="PostHog/posthog",
        title="Checkout 500s",
        summary="Users hit a 500 on the checkout page",
        actionability=_actionability(),
        reviewers_content=_reviewers(),
        priority=_priority(),
    )


def _internal_task_mock() -> MagicMock:
    task = MagicMock()
    task.id = "task-1"
    task.runs.order_by.return_value.first.return_value = MagicMock()
    return task


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_routes_to_cursor_when_team_default_is_cursor(ateam, areport, auser):
    await _set_default_agent(ateam, CodingAgent.CURSOR)
    with (
        patch(ASSIGNEE_PATH, return_value=auser),
        patch(FLAG_PATH, return_value=True),
        patch(
            DISPATCH_PATH,
            return_value=CursorDispatchResult(agent_id="bc-1", agent_url="u", agent_status="ACTIVE"),
        ) as mock_dispatch,
        patch(CREATE_AND_RUN_PATH) as mock_create_and_run,
        override_settings(CURSOR_API_KEY="test-key", SITE_URL="https://us.posthog.com"),
    ):
        await _run(ateam, areport, auser)

    mock_dispatch.assert_called_once()
    call = mock_dispatch.call_args
    assert call.args[0].id == areport.id
    assert call.kwargs["api_key"] == "test-key"
    assert call.kwargs["site_url"] == "https://us.posthog.com"
    mock_create_and_run.assert_not_called()

    task_exists = await SignalReportTask.objects.filter(report_id=areport.id).aexists()
    assert task_exists is False


# The decoupling: Cursor is connected (key resolves) and the flag is on, but the team default is
# NOT cursor — autonomy must still use the internal runner, never Cursor.
@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("set_default_explicitly", [True, False])
async def test_cursor_connected_but_default_not_cursor_uses_internal(ateam, areport, auser, set_default_explicitly):
    if set_default_explicitly:
        await _set_default_agent(ateam, CodingAgent.POSTHOG_CODE)
    with (
        patch(ASSIGNEE_PATH, return_value=auser),
        patch(FLAG_PATH, return_value=True),
        patch(DISPATCH_PATH) as mock_dispatch,
        patch(CREATE_AND_RUN_PATH, return_value=_internal_task_mock()) as mock_create_and_run,
        patch(SIGNAL_REPORT_TASK_CREATE_PATH, new=MagicMock()),
        override_settings(CURSOR_API_KEY="test-key", SITE_URL="https://us.posthog.com"),
    ):
        await _run(ateam, areport, auser)

    mock_create_and_run.assert_called_once()
    mock_dispatch.assert_not_called()


# Default is cursor, but a routing prerequisite is missing (flag off, or no resolvable key) →
# fall back to the internal runner rather than silently dropping the report.
@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("flag_enabled,cursor_key", [(False, "test-key"), (True, "")])
async def test_default_cursor_falls_back_to_internal_when_prereqs_missing(
    ateam, areport, auser, flag_enabled, cursor_key
):
    await _set_default_agent(ateam, CodingAgent.CURSOR)
    with (
        patch(ASSIGNEE_PATH, return_value=auser),
        patch(FLAG_PATH, return_value=flag_enabled),
        patch(DISPATCH_PATH) as mock_dispatch,
        patch(CREATE_AND_RUN_PATH, return_value=_internal_task_mock()) as mock_create_and_run,
        patch(SIGNAL_REPORT_TASK_CREATE_PATH, new=MagicMock()),
        override_settings(CURSOR_API_KEY=cursor_key, SITE_URL="https://us.posthog.com"),
    ):
        await _run(ateam, areport, auser)

    mock_create_and_run.assert_called_once()
    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_cursor_dispatch_error_is_swallowed(ateam, areport, auser):
    await _set_default_agent(ateam, CodingAgent.CURSOR)
    with (
        patch(ASSIGNEE_PATH, return_value=auser),
        patch(FLAG_PATH, return_value=True),
        patch(DISPATCH_PATH, side_effect=CursorDispatchError("boom")) as mock_dispatch,
        patch(CREATE_AND_RUN_PATH) as mock_create_and_run,
        override_settings(CURSOR_API_KEY="test-key", SITE_URL="https://us.posthog.com"),
    ):
        await _run(ateam, areport, auser)

    mock_dispatch.assert_called_once()
    mock_create_and_run.assert_not_called()
