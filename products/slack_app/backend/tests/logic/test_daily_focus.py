from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from posthog.models.integration import Integration

from products.slack_app.backend.logic.daily_focus import claim_due_daily_focus, next_run_after, previous_run_before
from products.slack_app.backend.models import SlackSettings, SlackUserProfileCache
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID

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
    for slack_user_id, enabled, next_run_at in [
        ("U_DUE", True, monday_nine),
        ("U_LATER", True, datetime(2026, 11, 9, 10, 0, tzinfo=PRAGUE)),
        ("U_OFF", False, None),
    ]:
        SlackSettings.objects.create(
            slack_workspace_id=SLACK_TEAM_ID,
            slack_user_id=slack_user_id,
            daily_focus_enabled=enabled,
            daily_focus_next_run_at=next_run_at,
            daily_focus_integration_id=integration.id,
        )
        SlackUserProfileCache.objects.create(integration=integration, slack_user_id=slack_user_id, tz="Europe/Prague")
    now = datetime(2026, 11, 9, 9, 2, tzinfo=PRAGUE)

    due = claim_due_daily_focus(now)

    assert [(run.slack_user_id, run.since) for run in due] == [
        ("U_DUE", int(datetime(2026, 11, 6, 9, 0, tzinfo=PRAGUE).timestamp()))
    ]
    assert SlackSettings.objects.get(slack_user_id="U_DUE").daily_focus_next_run_at == datetime(
        2026, 11, 10, 8, 0, tzinfo=UTC
    )
    # A sweep that runs again before the next workday finds nobody, so nobody gets the day twice.
    assert claim_due_daily_focus(now) == []
