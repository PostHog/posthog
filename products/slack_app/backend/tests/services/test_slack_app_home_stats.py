from __future__ import annotations

import re
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.cache import cache
from django.utils import timezone

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackThreadTaskMapping, SlackUserProfileCache
from products.slack_app.backend.services.slack_app_home import handle_app_home_opened, render_home_view
from products.slack_app.backend.services.slack_app_home_stats import (
    DEFAULT_STATS_WINDOW_DAYS,
    ModelUsage,
    PersonRow,
    StatsState,
    TrendBucket,
    build_stats_state,
    coerce_window_days,
)
from products.slack_app.backend.services.slack_settings import AIPreferences

WORKSPACE = "T_STATS"
SLACK_USER = "U_ADMIN"

# Slack's documented Block Kit caps. Exceeding any of them makes `views.publish` fail with
# `invalid_blocks`, which takes down the whole Home tab and not just this card.
MAX_MODEL_ROWS = 6
MAX_CHART_POINTS = 20
MAX_LABEL_CHARS = 14
MAX_SECTION_FIELDS = 10


@pytest.fixture(autouse=True)
def _clear_stats_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def slack_integration(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=WORKSPACE,
        sensitive_config={"access_token": "xoxb"},
    )


@pytest.fixture
def mock_slack_client():
    fake_client = MagicMock()
    with patch("products.slack_app.backend.services.slack_app_home.SlackIntegration") as cls:
        instance = MagicMock()
        instance.client = fake_client
        cls.return_value = instance
        yield fake_client


@pytest.fixture
def flag_on():
    with patch(
        "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled",
        return_value=True,
    ):
        yield


@pytest.fixture
def admin_user():
    with patch(
        "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin",
        return_value=True,
    ):
        yield


def _mk_task_with_run(
    *,
    team,
    integration,
    slack_user_id: str = SLACK_USER,
    channel: str = "C1",
    thread_ts: str = "1.1",
    status: str = "completed",
    pr_url: str | None = None,
    pr_merged: bool = False,
    model: str | None = "claude-opus-5",
    created_at=None,
) -> SlackThreadTaskMapping:
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")

    task = Task.objects.create(team=team, title="t")
    output: dict = {}
    if pr_url:
        output["pr_url"] = pr_url
        output["pr_merged"] = pr_merged
    state = {"model": model, "runtime_adapter": "claude"} if model else {}
    task_run = TaskRun.objects.create(team=team, task=task, status=status, output=output, state=state)

    mapping = SlackThreadTaskMapping.objects.create(
        team=team,
        integration=integration,
        slack_workspace_id=WORKSPACE,
        channel=channel,
        thread_ts=thread_ts,
        task=task,
        task_run=task_run,
        mentioning_slack_user_id=slack_user_id,
    )
    if created_at is not None:
        # `created_at` is auto_now_add, so backdating has to bypass the model save.
        SlackThreadTaskMapping.objects.filter(pk=mapping.pk).update(created_at=created_at)
        mapping.refresh_from_db()
    return mapping


def _blocks_of_type(view: dict, block_type: str) -> list[dict]:
    return [b for b in view["blocks"] if b["type"] == block_type]


def _fields_blocks(view: dict) -> list[dict]:
    return [b for b in view["blocks"] if b["type"] == "section" and "fields" in b]


def _kpi_grid(view: dict) -> dict:
    return next(b for b in _fields_blocks(view) if any(f["text"].startswith("*Tasks*") for f in b["fields"]))


def _breakdowns_block(view: dict) -> dict:
    return next(b for b in _fields_blocks(view) if any(f["text"].startswith("*Models*") for f in b["fields"]))


def _column(view: dict, heading: str) -> str:
    return next(f["text"] for b in _fields_blocks(view) for f in b["fields"] if f["text"].startswith(heading))


def _render(state: StatsState | None) -> dict:
    return render_home_view(
        effective=AIPreferences(),
        user_row=None,
        is_admin=True,
        stats_state=state,
    )


class TestWindowCoercion:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("7", 7),
            ("30", 30),
            ("90", 90),
            (90, 90),
            ("99999", DEFAULT_STATS_WINDOW_DAYS),
            ("-1", DEFAULT_STATS_WINDOW_DAYS),
            ("nonsense", DEFAULT_STATS_WINDOW_DAYS),
            (None, DEFAULT_STATS_WINDOW_DAYS),
        ],
    )
    def test_untrusted_window_is_clamped_to_an_offered_option(self, raw, expected):
        assert coerce_window_days(raw) == expected


class TestStatsCardRendering:
    def test_card_omitted_when_state_is_none(self):
        view = _render(None)
        assert "Workspace activity" not in str(view)

    def test_empty_window_renders_controls_without_charts(self):
        view = _render(StatsState(window_days=30))
        assert "Workspace activity" in str(view)
        # An empty window has nothing to plot and nobody to list.
        assert "*Models*" not in str(view)
        assert "*Most active*" not in str(view)

    def test_model_bars_fold_the_tail_without_losing_counts(self):
        models = tuple(ModelUsage(model=f"model-{i}", runtime_adapter="claude", value=20 - i) for i in range(15))
        view = _render(StatsState(tasks_started=100, models=models))

        column = _column(view, "*Models*")
        lines = [line for line in column.splitlines() if line and not line.startswith(("*", "`"))]

        assert len(lines) <= MAX_MODEL_ROWS
        assert lines[-1].startswith("Other")
        # The folded tail carries the models that didn't get their own row.
        counted = sum(int(line.rsplit(" ", 1)[-1]) for line in lines)
        assert counted == sum(m.value for m in models)

    def test_card_sits_below_the_welcome_and_above_the_settings(self):
        view = _render(StatsState(tasks_started=1))
        rendered = [str(block) for block in view["blocks"]]

        welcome_at = next(i for i, b in enumerate(rendered) if "Welcome to PostHog" in b)
        stats_at = next(i for i, b in enumerate(rendered) if "Workspace activity" in b)
        model_at = next(i for i, b in enumerate(rendered) if "AI model" in b)

        # An admin opens the tab for the activity; routing and model are set once and
        # rarely revisited, so they must not push it below the fold.
        assert welcome_at < stats_at < model_at

    def test_headline_renders_as_a_two_column_field_grid(self):
        view = _render(
            StatsState(
                tasks_started=24,
                tasks_with_pr=18,
                tasks_merged=11,
                active_people=5,
                median_cycle_seconds=840,
            )
        )
        grid = _kpi_grid(view)

        # Slack lays `fields` out in two columns and rejects more than 10 cells; a stack of
        # sections instead would cost one full-width row per KPI.
        assert len(grid["fields"]) <= MAX_SECTION_FIELDS
        rendered = [f["text"] for f in grid["fields"]]
        assert "*Tasks*\n24" in rendered
        assert "*Merge rate*\n61%" in rendered
        assert "*Median run*\n14m" in rendered
        assert "*People*\n5" in rendered

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (None, "—"),
            (45, "45s"),
            (840, "14m"),
            (3600, "1h"),
            (7500, "2h 5m"),
            (259200, "3d"),
        ],
    )
    def test_durations_render_compactly(self, seconds, expected):
        view = _render(StatsState(tasks_started=1, median_cycle_seconds=seconds))
        assert f"*Median run*\n{expected}" in [f["text"] for f in _kpi_grid(view)["fields"]]

    def test_long_model_ids_are_truncated_to_the_label_cap(self):
        view = _render(
            StatsState(
                tasks_started=1,
                models=(
                    ModelUsage(
                        model="anthropic/claude-sonnet-4-5-with-an-absurdly-long-name",
                        runtime_adapter="claude",
                        value=1,
                    ),
                ),
            )
        )
        labels = [
            line.split(" ")[0]
            for line in _column(view, "*Models*").splitlines()
            if line and not line.startswith(("*", "`"))
        ]
        # A long label would push the bar column out of alignment inside the fenced block.
        assert all(len(label) <= MAX_LABEL_CHARS for label in labels)

    def test_trend_sparklines_scale_both_series_against_one_peak(self):
        trend = (
            TrendBucket(label="Jul 07", opened=8, merged=0),
            TrendBucket(label="Jul 14", opened=0, merged=4),
        )
        view = _render(StatsState(tasks_started=12, tasks_with_pr=8, trend=trend))

        text = next(b["elements"][0]["text"] for b in view["blocks"] if b["type"] == "context" and "*PRs*" in str(b))
        opened, merged = re.findall(r"`([^`]+)`", text)

        assert len(opened) == len(merged) == len(trend)
        # Shared peak: merged's 4 must read as half of opened's 8, not as its own maximum.
        assert opened[0] == "█" and merged[0] == "▁"
        assert merged[1] < opened[0]
        assert "Jul 07 → Jul 14" in text

    def test_trend_omitted_when_the_window_produced_no_prs(self):
        trend = (TrendBucket(label="Jul 07", opened=0, merged=0),)
        view = _render(StatsState(tasks_started=3, tasks_with_pr=0, trend=trend))
        assert not [b for b in view["blocks"] if b["type"] == "context" and "*PRs*" in str(b)]

    def test_models_and_people_render_as_two_columns_of_one_block(self):
        view = _render(
            StatsState(
                tasks_started=9,
                models=(ModelUsage(model="claude-opus-5", runtime_adapter="claude", value=9),),
                people=(PersonRow(name="Vojta", tasks=9, merged=6), PersonRow(name="Anna", tasks=4, merged=1)),
            )
        )

        # `section.fields` is the only two-column layout Block Kit offers, so both
        # breakdowns have to share one block to sit side by side.
        block = _breakdowns_block(view)
        columns = [f["text"] for f in block["fields"]]

        assert len(columns) == 2
        assert columns[0].startswith("*Models*")
        assert columns[1].startswith("*Most active*")
        assert "Vojta" in columns[1] and "Anna" in columns[1]

    def test_leaderboard_columns_stay_aligned_under_a_long_name(self):
        people = (PersonRow(name="A", tasks=9, merged=6), PersonRow(name="Bartholomew Wigglesworth", tasks=4, merged=1))
        view = _render(StatsState(tasks_started=13, people=people))

        column = _column(view, "*Most active*")
        rows = [line for line in column.splitlines() if line and not line.startswith(("*", "`"))]

        # Names are padded to a common width inside the fenced block, so the count
        # columns line up rather than drifting with each name's length.
        assert len({len(row) for row in rows}) == 1


class TestResolveStatsState:
    def test_counts_prs_and_merges_off_the_same_tasks(self, slack_integration):
        team = slack_integration.team
        _mk_task_with_run(team=team, integration=slack_integration, thread_ts="1.1", pr_url="u/1", pr_merged=True)
        _mk_task_with_run(team=team, integration=slack_integration, thread_ts="1.2", pr_url="u/2", pr_merged=False)
        _mk_task_with_run(team=team, integration=slack_integration, thread_ts="1.3", pr_url=None)

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        assert state.tasks_started == 3
        assert state.tasks_with_pr == 2
        assert state.tasks_merged == 1
        assert state.merge_rate_percent == 50

    def test_merge_rate_survives_a_later_run_that_produced_no_pr(self, slack_integration):
        team = slack_integration.team
        TaskRun = apps.get_model("tasks", "TaskRun")
        mapping = _mk_task_with_run(
            team=team, integration=slack_integration, pr_url="u/1", pr_merged=True, status="completed"
        )
        # A follow-up run on the same task that never opened a PR. Counting "opened a PR"
        # off the latest run of any kind would drop this task from the denominator while
        # the merge helper still counts it, pushing the rate above 100%.
        TaskRun.objects.create(team=team, task=mapping.task, status="failed", output={}, state={})

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        assert state.tasks_with_pr == 1
        assert state.tasks_merged == 1
        assert state.merge_rate_percent == 100

    def test_median_run_time_ignores_runs_that_did_not_complete(self, slack_integration):
        team = slack_integration.team
        TaskRun = apps.get_model("tasks", "TaskRun")
        # Completed runs of 10 and 30 minutes, plus a failed one that ran for a week. The
        # failed run stopped at an arbitrary point, so letting it in would swamp the median.
        for index, (status, minutes) in enumerate([("completed", 10), ("completed", 30), ("failed", 10080)]):
            mapping = _mk_task_with_run(team=team, integration=slack_integration, thread_ts=f"1.{index}", status=status)
            TaskRun.objects.filter(pk=mapping.task_run_id).update(
                completed_at=mapping.task_run.created_at + timedelta(minutes=minutes)
            )

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        assert state.median_cycle_seconds == 20 * 60

    def test_active_people_counts_everyone_not_just_the_leaderboard(self, slack_integration):
        team = slack_integration.team
        for index in range(3):
            _mk_task_with_run(
                team=team,
                integration=slack_integration,
                thread_ts=f"1.{index}",
                slack_user_id=f"U_PERSON_{index}",
            )

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        assert state.active_people == 3

    def test_model_usage_is_aggregated_from_the_latest_run_state(self, slack_integration):
        team = slack_integration.team
        for index, model in enumerate(["claude-opus-5", "claude-opus-5", "gpt-5-codex"]):
            _mk_task_with_run(team=team, integration=slack_integration, thread_ts=f"1.{index}", model=model)

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        assert [(usage.model, usage.value) for usage in state.models] == [
            ("claude-opus-5", 2),
            ("gpt-5-codex", 1),
        ]

    def test_merge_rate_is_none_when_nothing_opened_a_pr(self, slack_integration):
        team = slack_integration.team
        _mk_task_with_run(team=team, integration=slack_integration, pr_url=None)

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        assert state.tasks_with_pr == 0
        assert state.merge_rate_percent is None

    def test_excludes_tasks_from_teams_the_viewer_cannot_access(self, slack_integration):
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        other_integration = Integration.objects.create(
            team=other_team,
            kind="slack",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb"},
        )
        _mk_task_with_run(team=slack_integration.team, integration=slack_integration, thread_ts="1.1")
        _mk_task_with_run(team=other_team, integration=other_integration, thread_ts="2.1", channel="C2")

        state = build_stats_state(
            slack_workspace_id=WORKSPACE,
            accessible_team_ids={slack_integration.team_id},
        )

        assert state.tasks_started == 1

    def test_excludes_activity_older_than_the_window(self, slack_integration):
        team = slack_integration.team
        _mk_task_with_run(team=team, integration=slack_integration, thread_ts="1.1")
        _mk_task_with_run(
            team=team,
            integration=slack_integration,
            thread_ts="1.2",
            created_at=timezone.now() - timedelta(days=45),
        )

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id}, window_days=30)

        assert state.tasks_started == 1

    def test_every_started_task_lands_in_exactly_one_outcome_bucket(self, slack_integration):
        team = slack_integration.team
        for index, status in enumerate(["completed", "failed", "cancelled", "in_progress", "queued"]):
            _mk_task_with_run(team=team, integration=slack_integration, thread_ts=f"1.{index}", status=status)

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        assert sum(outcome.value for outcome in state.outcomes) == state.tasks_started

    @pytest.mark.parametrize("window_days", [7, 30, 90])
    def test_trend_buckets_stay_within_the_chart_point_cap(self, slack_integration, window_days):
        team = slack_integration.team
        _mk_task_with_run(team=team, integration=slack_integration, pr_url="u/1", pr_merged=True)

        state = build_stats_state(
            slack_workspace_id=WORKSPACE,
            accessible_team_ids={team.id},
            window_days=window_days,
        )

        assert 0 < len(state.trend) <= MAX_CHART_POINTS

    def test_leaderboard_resolves_slack_ids_to_cached_names(self, slack_integration):
        team = slack_integration.team
        SlackUserProfileCache.objects.create(
            integration=slack_integration,
            slack_user_id=SLACK_USER,
            real_name="Vojta Bartos",
        )
        _mk_task_with_run(team=team, integration=slack_integration, thread_ts="1.1", pr_url="u/1", pr_merged=True)
        _mk_task_with_run(team=team, integration=slack_integration, thread_ts="1.2", slack_user_id="U_UNKNOWN")

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids={team.id})

        by_name = {person.name: person for person in state.people}
        assert by_name["Vojta Bartos"].tasks == 1
        assert by_name["Vojta Bartos"].merged == 1
        # No cached profile — falling back to the raw id beats dropping the row.
        assert by_name["U_UNKNOWN"].tasks == 1

    def test_no_accessible_teams_yields_an_empty_card(self, slack_integration):
        _mk_task_with_run(team=slack_integration.team, integration=slack_integration)

        state = build_stats_state(slack_workspace_id=WORKSPACE, accessible_team_ids=set())

        assert not state.has_data


class TestStatsCardGating:
    @pytest.mark.parametrize("is_admin, expected_visible", [(True, True), (False, False)])
    def test_card_is_admin_only(self, slack_integration, mock_slack_client, flag_on, is_admin, expected_visible):
        with patch(
            "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin",
            return_value=is_admin,
        ):
            handle_app_home_opened({"user": SLACK_USER}, WORKSPACE, integration=slack_integration)

        view = mock_slack_client.views_publish.call_args.kwargs["view"]
        assert ("Workspace activity" in str(view)) is expected_visible
