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

from posthog.models import OrganizationMembership, Team, User

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
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

    def test_project_outside_the_rollout_runs_as_before(self) -> None:
        result, capture = self._evaluate(rollout_percent=0)

        assert result is None
        capture.assert_not_called()


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
            ("nothing_configured", None, None, "skip", "no_rows", 0),
            ("config_without_events", None, [], "skip", "no_rows", 0),
            ("revenue_events_only", None, [{"eventName": "purchase", "revenueProperty": "amount"}], "run", "rows", 1),
            ("stripe_source_only", "Stripe", None, "run", "rows", 1),
            ("non_payment_source", "Postgres", None, "skip", "no_rows", 0),
        ]
    )
    def test_revenue_default_gates_the_run(self, _name, source_type, events, outcome, reason, row_count) -> None:
        if source_type is not None:
            ExternalDataSource.objects.create(
                team=self.team, source_id="s1", connection_id="c1", status="Running", source_type=source_type
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
