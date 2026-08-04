from __future__ import annotations

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
MAX_PIE_SEGMENTS = 12
MAX_CHART_POINTS = 20
MAX_LABEL_CHARS = 20


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


def _render(state: StatsState | None) -> dict:
    return render_home_view(
        effective=AIPreferences(),
        user_row=None,
        workspace_row=None,
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
        assert not _blocks_of_type(view, "data_visualization")
        assert not _blocks_of_type(view, "data_table")
        assert "Workspace activity" not in str(view)

    def test_empty_window_renders_controls_without_charts(self):
        view = _render(StatsState(window_days=30))
        assert "Workspace activity" in str(view)
        # An empty window has no series to plot; a chart with no data is invalid.
        assert not _blocks_of_type(view, "data_visualization")
        assert not _blocks_of_type(view, "data_table")

    def test_model_pie_folds_the_tail_and_stays_within_slack_caps(self):
        models = tuple(ModelUsage(model=f"model-{i}", runtime_adapter="claude", value=20 - i) for i in range(15))
        view = _render(StatsState(tasks_started=100, models=models))

        pie = next(c for c in _blocks_of_type(view, "data_visualization") if c["chart"]["type"] == "pie")
        segments = pie["chart"]["segments"]

        assert len(segments) <= MAX_PIE_SEGMENTS
        assert segments[-1]["label"] == "Other"
        # Nothing may be dropped: the folded tail carries the models that didn't fit.
        assert sum(s["value"] for s in segments) == sum(m.value for m in models)
        # Slack rejects a segment whose value isn't positive.
        assert all(s["value"] > 0 for s in segments)

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
        pie = next(c for c in _blocks_of_type(view, "data_visualization") if c["chart"]["type"] == "pie")
        assert all(len(s["label"]) <= MAX_LABEL_CHARS for s in pie["chart"]["segments"])

    def test_every_trend_series_carries_a_point_per_axis_category(self):
        trend = tuple(TrendBucket(label=f"Day {i:02d}", opened=1, merged=1) for i in range(4))
        view = _render(StatsState(tasks_started=4, tasks_with_pr=4, trend=trend))

        bar = next(c for c in _blocks_of_type(view, "data_visualization") if c["chart"]["type"] == "bar")
        categories = bar["chart"]["axis_config"]["categories"]

        for series in bar["chart"]["series"]:
            # Slack rejects a series that skips any axis category.
            assert [p["label"] for p in series["data"]] == categories

    def test_trend_chart_omitted_when_the_window_produced_no_prs(self):
        trend = (TrendBucket(label="Jul 07", opened=0, merged=0),)
        view = _render(StatsState(tasks_started=3, tasks_with_pr=0, trend=trend))
        assert not [c for c in _blocks_of_type(view, "data_visualization") if c["chart"]["type"] == "bar"]

    def test_leaderboard_numbers_carry_both_display_text_and_sort_value(self):
        view = _render(StatsState(tasks_started=9, people=(PersonRow(name="Vojta", tasks=9, merged=6),)))

        table = _blocks_of_type(view, "data_table")[0]
        data_row = table["rows"][1]

        assert data_row[0] == {"type": "raw_text", "text": "Vojta"}
        # Slack sorts on `value` and renders `text`; omitting either is rejected.
        assert data_row[1] == {"type": "raw_number", "text": "9", "value": 9}
        assert data_row[2] == {"type": "raw_number", "text": "6", "value": 6}


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
    @pytest.mark.parametrize(
        "is_admin, stats_flag_on, expected_visible",
        [
            (True, True, True),
            (False, True, False),
            (True, False, False),
            (False, False, False),
        ],
    )
    def test_card_needs_both_admin_and_its_own_flag(
        self, slack_integration, mock_slack_client, flag_on, is_admin, stats_flag_on, expected_visible
    ):
        with (
            patch(
                "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin",
                return_value=is_admin,
            ),
            patch(
                "products.slack_app.backend.services.slack_app_home.is_slack_app_home_stats_enabled",
                return_value=stats_flag_on,
            ),
        ):
            handle_app_home_opened({"user": SLACK_USER}, WORKSPACE)

        view = mock_slack_client.views_publish.call_args.kwargs["view"]
        assert ("Workspace activity" in str(view)) is expected_visible
