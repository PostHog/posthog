from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.precheck import PRECHECK_MAX_ROWS, evaluate_scout_precheck

NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
SKILL = "signals-scout-errors"
NEW_EVENTS_QUERY = "SELECT event FROM events WHERE event = 'boom' AND timestamp > {since} AND timestamp <= {now}"


@time_machine.travel(NOW, tick=False)
class TestEvaluateScoutPrecheck(ClickhouseTestMixin, BaseTest):
    def _config(self, query: str | None, max_quiet_minutes: int | None = None) -> SignalScoutConfig:
        config = SignalScoutConfig.all_teams.create(
            team=self.team, skill_name=SKILL, precheck_query=query, precheck_max_quiet_minutes=max_quiet_minutes
        )
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
        assert result.should_run is (outcome != "skip")
        properties = capture.call_args.kwargs["properties"]
        assert capture.call_args.kwargs["event"] == "scout_precheck_evaluated"
        assert (properties["outcome"], properties["row_count"]) == (outcome, row_count)

    def test_rows_are_capped(self) -> None:
        self._config("SELECT number FROM numbers(1000)")

        result, _ = self._evaluate()

        assert result is not None
        assert result.row_count == PRECHECK_MAX_ROWS
        assert result.rows_text is not None and len(result.rows_text.splitlines()) == PRECHECK_MAX_ROWS

    def test_query_error_runs_the_scout(self) -> None:
        self._config("SELECT nope FROM not_a_table WHERE timestamp > {since}")

        result, capture = self._evaluate()

        assert result is not None
        assert (result.outcome, result.should_run) == ("error", True)
        assert capture.call_args.kwargs["properties"]["error_type"] is not None

    def test_max_quiet_runs_without_the_query(self) -> None:
        self._config("SELECT nope FROM not_a_table", max_quiet_minutes=60)
        self._last_run(hours_ago=2)

        result, _ = self._evaluate()

        assert result is not None
        assert (result.outcome, result.reason) == ("run", "max_quiet")

    @parameterized.expand(
        [
            ("no_query", None, SignalScoutConfig.Status.ACTIVE),
            ("breaker_probe", "SELECT 1 WHERE 0", SignalScoutConfig.Status.PAUSED_BY_SYSTEM),
        ]
    )
    def test_no_precheck(self, _name, query, status) -> None:
        config = self._config(query)
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(
            status=status,
            enabled=status in SignalScoutConfig.RUNNABLE_STATUSES,
            pause_reason=None if status == SignalScoutConfig.Status.ACTIVE else "repeated_failures",
        )

        result, capture = self._evaluate()

        assert result is None
        capture.assert_not_called()
