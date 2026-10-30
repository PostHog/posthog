from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    NonAtomicBaseTest,
    _create_event,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models import OrganizationMembership, Team, User
from posthog.models.scoping import team_scope
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.customer_analytics.backend.facade.testing import create_account
from products.experiments.backend.facade.testing import create_experiment
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY
from products.signals.backend.scout_harness.precheck import (
    PRECHECK_MAX_ROWS,
    evaluate_scout_precheck,
    precheck_interval_minutes,
    resolve_effective_precheck,
)
from products.skills.backend.models.skills import LLMSkill
from products.warehouse_sources.backend.facade.models import ExternalDataSource

NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
SKILL = "signals-scout-errors"
NEW_EVENTS_QUERY = "SELECT event FROM events WHERE event = 'boom' AND timestamp > {since} AND timestamp <= {now}"
# An access-scoped system table: a query with no user is denied it.
DASHBOARDS_QUERY = "SELECT count() FROM system.dashboards"
SURVEYS_SKILL = "signals-scout-surveys"
REVENUE_SKILL = "signals-scout-revenue-analytics"
ROLLOUT_PERCENT = "products.signals.backend.scout_harness.precheck.precheck_default_rollout_percent"


@time_machine.travel(NOW, tick=False)
class TestEvaluateScoutPrecheck(ClickhouseTestMixin, BaseTest):
    def _config(self, query: str | None) -> SignalScoutConfig:
        config = SignalScoutConfig.all_teams.create(team=self.team, skill_name=SKILL, precheck_query=query)
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(created_at=NOW - timedelta(days=7))
        return config

    def _last_run(self, hours_ago: float, *, trial: bool = False) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team, title="scout run", description="", origin_product=Task.OriginProduct.SIGNALS_SCOUT
        )
        run = SignalScoutRun.all_teams.create(
            team=self.team,
            task_run=TaskRun.objects.create(task=task, team=self.team),
            skill_name=SKILL,
            skill_version=1,
            metadata={"scout_trial": {}} if trial else {},
        )
        SignalScoutRun.all_teams.filter(pk=run.pk).update(created_at=NOW - timedelta(hours=hours_ago))

    def _event(self, hours_ago: float) -> None:
        _create_event(team=self.team, event="boom", distinct_id="d1", timestamp=NOW - timedelta(hours=hours_ago))

    def _evaluate(self):
        with patch("products.signals.backend.scout_harness.precheck.posthoganalytics.capture") as capture:
            result = evaluate_scout_precheck(self.team.pk, SKILL)
        return result, capture

    @parameterized.expand(
        [
            # The only event is older than the last run that ran, so `{since}` hides it.
            ("nothing_since_last_run", [5], "skip", "no_rows", 0),
            ("new_event_since_last_run", [5, 1], "run", "rows", 1),
        ]
    )
    def test_since_is_the_last_run_that_ran(self, _name, event_hours_ago, outcome, reason, row_count) -> None:
        self._config(NEW_EVENTS_QUERY)
        self._last_run(hours_ago=2)
        # A trial run does not move `{since}`.
        self._last_run(hours_ago=0.5, trial=True)
        for hours_ago in event_hours_ago:
            self._event(hours_ago)
        flush_persons_and_events()

        result, capture = self._evaluate()

        assert result is not None
        assert (result.outcome, result.reason, result.row_count) == (outcome, reason, row_count)
        properties = capture.call_args.kwargs["properties"]
        assert capture.call_args.kwargs["event"] == "scout_precheck_evaluated"
        assert (properties["outcome"], properties["row_count"]) == (outcome, row_count)
        stored = SignalScoutConfig.all_teams.get(team=self.team, skill_name=SKILL)
        assert (stored.last_precheck_at, stored.last_precheck_outcome, stored.last_precheck_row_count) == (
            NOW,
            outcome,
            row_count,
        )

    @parameterized.expand(
        [
            ("no_limit", "SELECT number FROM numbers(1000)"),
            ("larger_limit", "SELECT number FROM numbers(1000) LIMIT 500"),
            ("union", "SELECT number FROM numbers(40) UNION ALL SELECT number FROM numbers(40)"),
        ]
    )
    def test_rows_are_capped(self, _name, query) -> None:
        self._config(query)

        result, _ = self._evaluate()

        assert result is not None
        assert result.row_count == PRECHECK_MAX_ROWS
        assert result.rows_text is not None and len(result.rows_text.splitlines()) == PRECHECK_MAX_ROWS

    def test_reads_access_scoped_system_tables_as_the_acting_user(self) -> None:
        self._config(DASHBOARDS_QUERY)

        result, capture = self._evaluate()

        assert result is not None
        assert (result.outcome, result.reason) == ("skip", "false_value")
        assert capture.call_args.kwargs["properties"]["acting_user_id"] == self.user.pk

    def test_query_error_runs_the_scout(self) -> None:
        self._config("SELECT nope FROM not_a_table WHERE timestamp > {since}")

        result, capture = self._evaluate()

        assert result is not None
        assert (result.outcome, result.should_run) == ("error", True)
        assert capture.call_args.kwargs["properties"]["error_type"] is not None

    @parameterized.expand(
        [
            ("zero_count", "SELECT count() FROM numbers(0)", "skip", "false_value"),
            ("false", "SELECT false", "skip", "false_value"),
            ("null", "SELECT NULL", "skip", "false_value"),
            ("empty_string", "SELECT ''", "skip", "false_value"),
            ("nonzero_count", "SELECT count() FROM numbers(3)", "run", "rows"),
            ("true", "SELECT true", "run", "rows"),
            ("zero_with_a_second_column", "SELECT 0, 'x'", "run", "rows"),
            ("two_zero_rows", "SELECT 0 FROM numbers(2)", "run", "rows"),
        ]
    )
    def test_single_false_value_skips(self, _name, query, outcome, reason) -> None:
        self._config(query)

        result, _ = self._evaluate()

        assert result is not None
        assert (result.outcome, result.reason) == (outcome, reason)

    @parameterized.expand(
        [
            ("no_query", None, SignalScoutConfig.Status.ACTIVE, True),
            ("breaker_probe", "SELECT 1 WHERE 0", SignalScoutConfig.Status.PAUSED_BY_SYSTEM, True),
            ("no_member_can_act", "SELECT 1 WHERE 0", SignalScoutConfig.Status.ACTIVE, False),
        ]
    )
    def test_no_precheck(self, _name, query, status, has_member) -> None:
        if not has_member:
            OrganizationMembership.objects.filter(organization=self.organization).delete()
        config = self._config(query)
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(
            status=status,
            enabled=status in SignalScoutConfig.RUNNABLE_STATUSES,
            pause_reason=None if status == SignalScoutConfig.Status.ACTIVE else "repeated_failures",
        )

        result, capture = self._evaluate()

        assert result is None
        capture.assert_not_called()


@time_machine.travel(NOW, tick=False)
class TestSkillDefaultPrecheck(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        LLMSkill.objects.create(
            team=self.team, name=SURVEYS_SKILL, description="", body="", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        config = SignalScoutConfig.all_teams.create(team=self.team, skill_name=SURVEYS_SKILL)
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(created_at=NOW - timedelta(hours=2))

    def _evaluate(self, rollout_percent: int):
        with (
            patch(ROLLOUT_PERCENT, return_value=rollout_percent),
            patch("products.signals.backend.scout_harness.precheck.posthoganalytics.capture") as capture,
        ):
            result = evaluate_scout_precheck(self.team.pk, SURVEYS_SKILL)
        return result, capture

    @parameterized.expand(
        [
            ("no_survey_events", [], 2, "skip", 0),
            ("survey_shown_without_answers", ["survey shown"], 2, "run", 1),
            # Quiet for longer than two daily intervals, so the backstop row starts the run.
            ("backstop", [], 50, "run", 1),
        ]
    )
    def test_surveys_default_gates_the_run(self, _name, events, quiet_hours, outcome, row_count) -> None:
        SignalScoutConfig.all_teams.filter(team=self.team).update(created_at=NOW - timedelta(hours=quiet_hours))
        for event in events:
            _create_event(
                team=self.team,
                event=event,
                distinct_id="d1",
                timestamp=NOW - timedelta(hours=1),
                properties={"$survey_id": "s1"},
            )
        flush_persons_and_events()

        result, capture = self._evaluate(rollout_percent=100)

        assert result is not None
        assert (result.outcome, result.row_count, result.query_source) == (outcome, row_count, "skill_default")
        properties = capture.call_args.kwargs["properties"]
        assert properties["query_source"] == "skill_default"
        assert properties["rollout_bucket"] is not None

    @parameterized.expand(
        [
            ("ai_observability_active", "signals-scout-ai-observability", "$ai_span", 24 * 6, "run"),
            ("ai_observability_quiet", "signals-scout-ai-observability", "$ai_span", 24 * 8, "skip"),
            ("csp_active", "signals-scout-csp-violations", "$csp_violation", 24 * 6, "run"),
            ("csp_quiet", "signals-scout-csp-violations", "$csp_violation", 24 * 8, "skip"),
            ("mcp_active", "signals-scout-mcp-tool-calls", "$mcp_tool_call", 24 * 6, "run"),
            ("mcp_quiet", "signals-scout-mcp-tool-calls", "$mcp_tool_call", 24 * 8, "skip"),
            ("conversations_active", "signals-scout-conversations", "$conversation_message_sent", 24 * 29, "run"),
            ("conversations_quiet", "signals-scout-conversations", "$conversation_ticket_created", 24 * 31, "skip"),
            ("conversations_widget_event", "signals-scout-conversations", "$conversations_widget_opened", 1, "skip"),
            ("web_vitals_active", "signals-scout-web-vitals", "$web_vitals", 24 * 6, "run"),
            ("web_vitals_quiet", "signals-scout-web-vitals", "$web_vitals", 24 * 8, "skip"),
            ("web_analytics_active", "signals-scout-web-analytics", "$pageview", 24 * 6, "run"),
            ("web_analytics_quiet", "signals-scout-web-analytics", "$pageview", 24 * 8, "skip"),
            ("error_tracking_active", "signals-scout-error-tracking", "$exception", 24 * 6, "run"),
            ("error_tracking_quiet", "signals-scout-error-tracking", "$exception", 24 * 8, "skip"),
        ]
    )
    def test_product_presence_defaults_skip_only_on_absence(self, _name, skill, event, hours_ago, outcome) -> None:
        LLMSkill.objects.create(
            team=self.team, name=skill, description="", body="", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        SignalScoutConfig.all_teams.create(team=self.team, skill_name=skill)
        _create_event(team=self.team, event=event, distinct_id="d1", timestamp=NOW - timedelta(hours=hours_ago))
        flush_persons_and_events()

        with (
            patch(ROLLOUT_PERCENT, return_value=100),
            patch("products.signals.backend.scout_harness.precheck.posthoganalytics.capture"),
        ):
            result = evaluate_scout_precheck(self.team.pk, skill)

        assert result is not None
        assert (result.outcome, result.query_source) == (outcome, "skill_default")

    def test_apm_default_skips_only_without_spans_in_the_last_day(self) -> None:
        skill = "signals-scout-apm"
        LLMSkill.objects.create(
            team=self.team, name=skill, description="", body="", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        SignalScoutConfig.all_teams.create(team=self.team, skill_name=skill)

        def evaluate():
            with (
                patch(ROLLOUT_PERCENT, return_value=100),
                patch("products.signals.backend.scout_harness.precheck.posthoganalytics.capture"),
            ):
                return evaluate_scout_precheck(self.team.pk, skill)

        outcomes = []
        for hours_ago in (25, 23):
            timestamp = (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S.%f")
            sync_execute(
                "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
                "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES "
                f"(generateUUIDv4(), {self.team.pk}, 't{hours_ago}', 's{hours_ago}', '', 'GET /api', 2, "
                f"'{timestamp}', '{timestamp}', '{timestamp}', 0, 'web')"
            )
            result = evaluate()
            assert result is not None
            outcomes.append((result.outcome, result.query_source))

        assert outcomes == [("skip", "skill_default"), ("run", "skill_default")]

    @parameterized.expand(
        [
            # Recordings stopped 20 days ago: a capture cliff the scout must still see.
            ("capture_cliff", 24 * 20, "run"),
            ("stale", 24 * 31, "skip"),
            ("future_dated", -24 * 3, "skip"),
        ]
    )
    def test_session_replay_default_skips_only_without_recent_recordings(self, _name, hours_ago, outcome) -> None:
        skill = "signals-scout-session-replay"
        LLMSkill.objects.create(
            team=self.team, name=skill, description="", body="", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        SignalScoutConfig.all_teams.create(team=self.team, skill_name=skill)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            first_timestamp=NOW - timedelta(hours=hours_ago),
            last_timestamp=NOW - timedelta(hours=hours_ago) + timedelta(minutes=5),
            ensure_analytics_event_in_session=False,
        )

        with (
            patch(ROLLOUT_PERCENT, return_value=100),
            patch("products.signals.backend.scout_harness.precheck.posthoganalytics.capture"),
        ):
            result = evaluate_scout_precheck(self.team.pk, skill)

        assert result is not None
        assert (result.outcome, result.query_source) == (outcome, "skill_default")

    def test_project_outside_the_rollout_runs_as_before(self) -> None:
        result, capture = self._evaluate(rollout_percent=0)

        assert result is None
        capture.assert_not_called()


# Non-atomic: ClickHouse reads `system.*` tables over its own Postgres connection, so rows must be committed.
@time_machine.travel(NOW, tick=False)
class TestSystemTableSkillDefaults(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _seed_task_run(self, origin_product: str) -> None:
        Channel = apps.get_model("tasks", "Channel")
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        with team_scope(self.team.pk):
            channel = Channel.objects.create(team=self.team, name=f"space_{origin_product}")
        task = Task.objects.create(
            team=self.team, channel=channel, title="t", description="", origin_product=origin_product
        )
        TaskRun.objects.create(task=task, team=self.team)

    def _seed_experiment(self, *, started: bool, days_since_update: int) -> None:
        FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")
        flag = FeatureFlag.objects.create(team=self.team, key=f"exp_flag_{started}_{days_since_update}")
        create_experiment(
            team_id=self.team.id,
            name="e",
            feature_flag_id=flag.id,
            start_date=NOW - timedelta(days=60) if started else None,
            updated_at=NOW - timedelta(days=days_since_update),
        )

    def _seed_report(self, status: str, *, days_since_update: int) -> None:
        report = SignalReport.objects.create(team=self.team, status=status, title="r")
        SignalReport.objects.filter(pk=report.pk).update(updated_at=NOW - timedelta(days=days_since_update))

    def _seed_scanner(self, *, enabled: bool) -> None:
        apps.get_model("replay_vision", "ReplayScanner").objects.create(
            team=self.team,
            name="s",
            scanner_type="monitor",
            scanner_config={"prompt": "p"},
            model="gemini-3.8-flash",
            enabled=enabled,
        )

    @parameterized.expand(
        [
            ("customer_analytics_no_accounts", "signals-scout-customer-analytics", None, "skip"),
            ("customer_analytics_accounts", "signals-scout-customer-analytics", "account", "run"),
            ("feature_flags_absent", "signals-scout-feature-flags", None, "skip"),
            ("feature_flags_roster", "signals-scout-feature-flags", "flag", "run"),
            ("feature_flags_calls_only", "signals-scout-feature-flags", "flag_call", "run"),
            ("experiments_absent", "signals-scout-experiments", None, "skip"),
            ("experiments_old_draft", "signals-scout-experiments", "old_draft", "skip"),
            ("experiments_recent_draft", "signals-scout-experiments", "recent_draft", "run"),
            ("experiments_running", "signals-scout-experiments", "running", "run"),
            ("tasks_absent", "signals-scout-tasks", None, "skip"),
            ("tasks_scout_runs_only", "signals-scout-tasks", "scout_run", "skip"),
            ("tasks_user_runs", "signals-scout-tasks", "user_run", "run"),
            ("inbox_validation_absent", "signals-scout-inbox-validation", None, "skip"),
            ("inbox_validation_old_resolution", "signals-scout-inbox-validation", "resolved_15d", "skip"),
            ("inbox_validation_recent_unresolved", "signals-scout-inbox-validation", "ready_1d", "skip"),
            ("inbox_validation_recent_resolution", "signals-scout-inbox-validation", "resolved_13d", "run"),
            ("replay_vision_absent", "signals-scout-replay-vision", None, "skip"),
            ("replay_vision_disabled_scanner", "signals-scout-replay-vision", "disabled_scanner", "skip"),
            ("replay_vision_old_observation", "signals-scout-replay-vision", "observation_31d", "skip"),
            ("replay_vision_enabled_scanner", "signals-scout-replay-vision", "enabled_scanner", "run"),
            ("replay_vision_observations_only", "signals-scout-replay-vision", "observation_29d", "run"),
        ]
    )
    def test_system_table_defaults_skip_only_on_absence(self, _name, skill, seed, outcome) -> None:
        LLMSkill.objects.create(
            team=self.team, name=skill, description="", body="", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        SignalScoutConfig.all_teams.create(team=self.team, skill_name=skill)
        if seed == "account":
            create_account(team_id=self.team.pk, name="a", external_id="a")
        elif seed == "flag":
            apps.get_model("feature_flags", "FeatureFlag").objects.create(team=self.team, key="f")
        elif seed == "flag_call":
            _create_event(
                team=self.team, event="$feature_flag_called", distinct_id="d1", timestamp=NOW - timedelta(days=6)
            )
            flush_persons_and_events()
        elif seed == "old_draft":
            self._seed_experiment(started=False, days_since_update=31)
        elif seed == "recent_draft":
            self._seed_experiment(started=False, days_since_update=29)
        elif seed == "running":
            self._seed_experiment(started=True, days_since_update=90)
        elif seed == "scout_run":
            self._seed_task_run("signals_scout")
        elif seed == "user_run":
            self._seed_task_run("user_created")
        elif seed == "resolved_15d":
            self._seed_report(SignalReport.Status.RESOLVED, days_since_update=15)
        elif seed == "ready_1d":
            self._seed_report(SignalReport.Status.READY, days_since_update=1)
        elif seed == "resolved_13d":
            self._seed_report(SignalReport.Status.RESOLVED, days_since_update=13)
        elif seed in ("enabled_scanner", "disabled_scanner"):
            self._seed_scanner(enabled=seed == "enabled_scanner")
        elif seed in ("observation_29d", "observation_31d"):
            _create_event(
                team=self.team,
                event="$recording_observed",
                distinct_id="d1",
                timestamp=NOW - timedelta(days=29 if seed == "observation_29d" else 31),
            )
            flush_persons_and_events()

        with (
            patch(ROLLOUT_PERCENT, return_value=100),
            patch("products.signals.backend.scout_harness.precheck.posthoganalytics.capture") as capture,
        ):
            result = evaluate_scout_precheck(self.team.pk, skill)

        assert result is not None
        assert (result.outcome, result.query_source) == (outcome, "skill_default")
        assert capture.call_args.kwargs["properties"].get("error_type") is None


@time_machine.travel(NOW, tick=False)
class TestRevenueDefaultPrecheck(NonAtomicBaseTest):
    # The system tables read Postgres through ClickHouse, which sees only committed rows.
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        LLMSkill.objects.create(
            team=self.team, name=REVENUE_SKILL, description="", body="", metadata={"seeded_by": HARNESS_SEEDED_BY}
        )
        SignalScoutConfig.all_teams.create(team=self.team, skill_name=REVENUE_SKILL)

    @parameterized.expand(
        [
            ("nothing_configured", None, False, None, "skip", "no_rows", 0),
            ("config_without_events", None, False, [], "skip", "no_rows", 0),
            (
                "revenue_events_only",
                None,
                False,
                [{"eventName": "purchase", "revenueProperty": "amount"}],
                "run",
                "rows",
                1,
            ),
            ("stripe_source_only", "Stripe", False, None, "run", "rows", 1),
            ("deleted_stripe_source", "Stripe", True, None, "skip", "no_rows", 0),
            ("non_payment_source", "Postgres", False, None, "skip", "no_rows", 0),
        ]
    )
    def test_revenue_default_gates_the_run(
        self, _name, source_type, deleted, events, outcome, reason, row_count
    ) -> None:
        if source_type is not None:
            ExternalDataSource.objects.create(
                team=self.team,
                source_id="s1",
                connection_id="c1",
                status="Running",
                source_type=source_type,
                deleted=deleted,
            )
        if events is not None:
            config = self.team.revenue_analytics_config
            config.events = events
            config.save()

        with (
            patch(ROLLOUT_PERCENT, return_value=100),
            patch("products.signals.backend.scout_harness.precheck.posthoganalytics.capture"),
        ):
            result = evaluate_scout_precheck(self.team.pk, REVENUE_SKILL)

        assert result is not None
        assert (result.outcome, result.reason, result.row_count) == (outcome, reason, row_count)


class TestResolveEffectivePrecheck(SimpleTestCase):
    @parameterized.expand(
        [
            ("disabled_wins_over_everything", True, "SELECT 1", True, 100, None, "off"),
            ("own_query_wins_over_default", False, "SELECT 1", True, 100, "SELECT 1", "config"),
            ("default_inside_rollout", False, None, True, 100, "default", "skill_default"),
            ("default_outside_rollout", False, None, True, 0, None, "off"),
            ("custom_skill_inherits_nothing", False, None, False, 100, None, "off"),
        ]
    )
    def test_precedence(self, _name, disabled, own_query, is_canonical, percent, query, source) -> None:
        config = SignalScoutConfig(
            team_id=1, skill_name=SURVEYS_SKILL, precheck_query=own_query, precheck_disabled=disabled
        )
        with (
            patch(ROLLOUT_PERCENT, return_value=percent),
            patch(
                "products.signals.backend.scout_harness.precheck.canonical_precheck_query_for",
                return_value="default",
            ),
        ):
            effective = resolve_effective_precheck(config, is_canonical=is_canonical)

        assert (effective.query, effective.source) == (query, source)

    @parameterized.expand(
        [
            ("rolling", None, 360, 360),
            ("daily_cron", "0 9 * * *", 1440, 1440),
            ("twice_daily_cron_between_slots", "0 9,17 * * *", 1440, 480),
            ("invalid_cron_falls_back", "not a cron", 90, 90),
        ]
    )
    def test_interval_minutes(self, _name, cron, interval, expected) -> None:
        config = SignalScoutConfig(run_cron_schedule=cron, run_interval_minutes=interval)

        assert precheck_interval_minutes(config, Team(timezone="UTC"), NOW) == expected


@time_machine.travel(NOW, tick=False)
class TestScoutPrecheckTestAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.config = SignalScoutConfig.all_teams.create(team=self.team, skill_name=SKILL)
        SignalScoutConfig.all_teams.filter(pk=self.config.pk).update(created_at=NOW - timedelta(days=7))
        _create_event(team=self.team, event="boom", distinct_id="d1", timestamp=NOW - timedelta(hours=1))
        flush_persons_and_events()

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/signals/scout/configs/{self.config.id}/{suffix}"

    @parameterized.expand(
        [
            ("saved_query_finds_rows", NEW_EVENTS_QUERY, {}, True, "rows", 1, False),
            (
                "body_query_overrides_saved",
                NEW_EVENTS_QUERY,
                {"precheck_query": "SELECT 1 FROM events WHERE event = 'other' AND timestamp > {since}"},
                False,
                "no_rows",
                0,
                False,
            ),
            (
                "reads_system_tables_as_the_requester",
                None,
                {"precheck_query": DASHBOARDS_QUERY},
                False,
                "false_value",
                1,
                False,
            ),
            (
                "query_error_runs_the_scout",
                None,
                {"precheck_query": "SELECT nope FROM not_a_table"},
                True,
                "query_error",
                0,
                True,
            ),
        ]
    )
    def test_precheck_test_runs_the_query_without_a_run(
        self, _name, saved_query, body, would_run, reason, row_count, has_error
    ) -> None:
        self.client.patch(self._url(), {"precheck_query": saved_query}, format="json")

        with patch("products.signals.backend.temporal.agentic.scout_scheduler.start_manual_signals_scout_run") as start:
            response = self.client.post(self._url("precheck_test/"), body, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert (data["would_run"], data["reason"], data["row_count"]) == (would_run, reason, row_count)
        assert (data["error"] is not None) is has_error
        assert data["acting_user"] is None
        start.assert_not_called()
        assert not SignalScoutRun.all_teams.filter(team=self.team).exists()

    def test_precheck_test_names_the_acting_user_when_it_is_someone_else(self) -> None:
        other = User.objects.create_and_join(self.organization, "scout-owner@example.com", None)
        SignalScoutConfig.all_teams.filter(pk=self.config.pk).update(enabled_by=other)

        response = self.client.post(self._url("precheck_test/"), {"precheck_query": NEW_EVENTS_QUERY}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["acting_user"]["id"] == other.id

    def test_precheck_test_without_any_query_is_rejected(self) -> None:
        response = self.client.post(self._url("precheck_test/"), {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
