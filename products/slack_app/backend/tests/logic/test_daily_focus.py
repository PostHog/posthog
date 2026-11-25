from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest
import time_machine
from unittest.mock import patch

from django.core.cache import cache

from posthog.models.integration import Integration

from products.slack_app.backend.logic.daily_focus import (
    DailyFocusAccess,
    claim_due_daily_focus,
    daily_focus_access,
    next_run_after,
    previous_run_before,
    turn_on_daily_focus_on_mention,
)
from products.slack_app.backend.models import SlackDailyFocus, SlackUserProfileCache
from products.slack_app.backend.temporal.activities.slack_app_work_focus import find_slack_app_work_focus_activity
from products.slack_app.backend.temporal.types import SlackAppWorkFocusInputs
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID

PRAGUE = ZoneInfo("Europe/Prague")
NINE = time(9, 0)


@pytest.mark.parametrize(
    "now, zone, expected",
    [
        # Friday after the run waits for Monday, and the weekend never runs.
        (datetime(2026, 11, 6, 10, 0, tzinfo=PRAGUE), PRAGUE, datetime(2026, 11, 9, 8, 0, tzinfo=UTC)),
        (datetime(2026, 11, 7, 8, 0, tzinfo=PRAGUE), PRAGUE, datetime(2026, 11, 9, 8, 0, tzinfo=UTC)),
        (datetime(2026, 11, 9, 8, 0, tzinfo=PRAGUE), PRAGUE, datetime(2026, 11, 9, 8, 0, tzinfo=UTC)),
        # The clocks move on Sunday 29 March, so 9:00 on Monday is an hour earlier in UTC.
        (datetime(2026, 3, 27, 10, 0, tzinfo=PRAGUE), PRAGUE, datetime(2026, 3, 30, 7, 0, tzinfo=UTC)),
        (
            datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
            ZoneInfo("Asia/Kolkata"),
            datetime(2026, 11, 9, 3, 30, tzinfo=UTC),
        ),
    ],
)
def test_the_next_run_is_the_next_workday_at_nine_local_time(now: datetime, zone: ZoneInfo, expected: datetime) -> None:
    assert next_run_after(now, zone, NINE) == expected


@pytest.mark.parametrize(
    "scheduled, expected",
    [
        (datetime(2026, 11, 9, 9, 0, tzinfo=PRAGUE), datetime(2026, 11, 6, 8, 0, tzinfo=UTC)),
        (datetime(2026, 11, 10, 9, 0, tzinfo=PRAGUE), datetime(2026, 11, 9, 8, 0, tzinfo=UTC)),
    ],
)
def test_a_run_reads_back_to_the_previous_workday_run(scheduled: datetime, expected: datetime) -> None:
    assert previous_run_before(scheduled, PRAGUE, NINE) == expected


@pytest.mark.django_db
def test_a_due_person_runs_once_and_moves_to_the_next_workday(org_team_user) -> None:
    _, team, _ = org_team_user
    integration = Integration.objects.create(team=team, kind="slack", integration_id=SLACK_TEAM_ID)
    monday_nine = datetime(2026, 11, 9, 9, 0, tzinfo=PRAGUE)
    friday_nine = datetime(2026, 11, 6, 9, 0, tzinfo=PRAGUE)
    for slack_user_id, next_run_at, last_run_at in [
        ("U_DUE", monday_nine, None),
        # The person moved their time from 07:00 to 09:00, so the run reads from the 07:00 run, not from 09:00.
        ("U_MOVED", monday_nine, datetime(2026, 11, 6, 7, 0, tzinfo=PRAGUE)),
        # Friday's run never started, because the sweep was down until now. Monday's run still goes out.
        ("U_MISSED", friday_nine, None),
        ("U_LATER", datetime(2026, 11, 9, 10, 0, tzinfo=PRAGUE), None),
        ("U_OFF", None, None),
    ]:
        SlackDailyFocus.objects.for_team(team.id).create(
            team=team,
            slack_workspace_id=SLACK_TEAM_ID,
            slack_user_id=slack_user_id,
            integration_id=integration.id,
            next_run_at=next_run_at,
            last_run_at=last_run_at,
        )
        SlackUserProfileCache.objects.create(integration=integration, slack_user_id=slack_user_id, tz="Europe/Prague")
    now = datetime(2026, 11, 9, 9, 2, tzinfo=PRAGUE)

    due = claim_due_daily_focus(now, spacing_seconds=12)

    assert sorted((run.slack_user_id, run.since) for run in due) == [
        ("U_DUE", int(friday_nine.timestamp())),
        ("U_MOVED", int(datetime(2026, 11, 6, 7, 0, tzinfo=PRAGUE).timestamp())),
    ]
    # Both runs share the workspace's search budget, so the second one waits.
    assert sorted(run.start_delay_seconds for run in due) == [0, 12]
    assert SlackDailyFocus.objects.unscoped().get(slack_user_id="U_DUE").next_run_at == datetime(
        2026, 11, 10, 8, 0, tzinfo=UTC
    )
    assert [(run.slack_user_id, run.since) for run in claim_due_daily_focus(now)] == [
        ("U_MISSED", int(friday_nine.timestamp()))
    ]
    assert claim_due_daily_focus(now) == []


@pytest.mark.django_db
def test_a_run_whose_installation_is_gone_turns_the_daily_work_focus_off(org_team_user) -> None:
    _, team, _ = org_team_user
    row = SlackDailyFocus.objects.for_team(team.id).create(
        team=team,
        slack_workspace_id=SLACK_TEAM_ID,
        slack_user_id="U_GONE",
        integration_id=999_999,
        at=time(8, 30),
        next_run_at=datetime(2026, 11, 10, 7, 30, tzinfo=UTC),
    )

    outcome = find_slack_app_work_focus_activity(
        SlackAppWorkFocusInputs(integration_id=999_999, slack_team_id=SLACK_TEAM_ID, slack_user_id="U_GONE", since=1)
    )

    assert outcome == "integration_gone"
    row.refresh_from_db()
    # The picked time stays for when the person turns it on again from an installation that remains.
    assert row.next_run_at is None and row.at == time(8, 30)


@pytest.mark.django_db
def test_a_daily_run_queued_without_its_claimed_time_sends_nothing(workspace_integration) -> None:
    outcome = find_slack_app_work_focus_activity(
        SlackAppWorkFocusInputs(
            integration_id=workspace_integration.id, slack_team_id=SLACK_TEAM_ID, slack_user_id="U_QUEUED", since=1
        )
    )

    assert outcome == "superseded"


@pytest.mark.parametrize(
    "linked, scopes, daily_flag, search_flag, expected",
    [
        (True, "search:read.public", True, True, DailyFocusAccess.READY),
        # The link predates the search scopes, and a new link would ask for them.
        (True, "users:read", True, True, DailyFocusAccess.RELINK),
        # A new link would not ask for them either, so there is nothing to prompt.
        (True, "users:read", True, False, DailyFocusAccess.NONE),
        (True, "users:read", False, True, DailyFocusAccess.NONE),
        (False, "", True, True, DailyFocusAccess.NONE),
    ],
    ids=["can search", "needs relink", "relink would not help", "flag off", "not linked"],
)
@pytest.mark.django_db
def test_daily_focus_access_tells_a_relink_from_no_access(
    org_team_user, workspace_integration, link_user, linked, scopes, daily_flag, search_flag, expected
) -> None:
    _, _, user = org_team_user
    if linked:
        link_user(user, user_scopes=scopes)
    flags = {"slack-app-daily-work-focus": daily_flag, "slack-app-link-search-scopes": search_flag}

    with patch("posthoganalytics.feature_enabled", side_effect=lambda key, *a, **k: flags[key]):
        assert daily_focus_access(workspace_integration, SLACK_USER_ID) is expected


@pytest.mark.parametrize(
    "turned_off_before, expected_next_run",
    [(False, datetime(2026, 11, 10, 8, 0, tzinfo=UTC)), (True, None)],
    ids=["never chose", "turned it off"],
)
@pytest.mark.django_db
def test_a_mention_turns_it_on_once_a_day_for_a_person_who_never_chose(
    workspace_integration, link_user, org_team_user, turned_off_before, expected_next_run
) -> None:
    _, team, user = org_team_user
    cache.clear()
    link_user(user, user_scopes="search:read.public")
    SlackUserProfileCache.objects.create(
        integration=workspace_integration,
        slack_user_id=SLACK_USER_ID,
        tz="Europe/Prague",
        refreshed_at=datetime(2026, 11, 9, 11, 30, tzinfo=UTC),
    )
    if turned_off_before:
        SlackDailyFocus.objects.for_team(team.id).create(
            team_id=team.id,
            slack_workspace_id=SLACK_TEAM_ID,
            slack_user_id=SLACK_USER_ID,
            integration_id=workspace_integration.id,
            next_run_at=None,
        )

    with (
        time_machine.travel(datetime(2026, 11, 9, 12, 0, tzinfo=UTC), tick=False),
        patch("posthoganalytics.feature_enabled", return_value=True) as flag,
        patch("products.slack_app.backend.logic.daily_focus.capture_slack_event"),
    ):
        turn_on_daily_focus_on_mention(workspace_integration, SLACK_USER_ID)
        checks = flag.call_count
        # The rest of the day's mentions cost a cache read: no row read, no flag check.
        turn_on_daily_focus_on_mention(workspace_integration, SLACK_USER_ID)
        assert flag.call_count == checks

    row = SlackDailyFocus.objects.unscoped().get(slack_workspace_id=SLACK_TEAM_ID, slack_user_id=SLACK_USER_ID)
    assert row.next_run_at == expected_next_run
