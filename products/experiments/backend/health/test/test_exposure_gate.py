from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import ANY, MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.exceptions import ClickHouseClusterMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team
from posthog.models.user import User

from products.actions.backend.models.action import Action
from products.experiments.backend.health.context import SplitHistory
from products.experiments.backend.health.exposure_gate import (
    MAX_EXPOSURE_QUERIES,
    load_split_history,
    query_any_exposure,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import DEFAULT_EXPOSURE_EVENT
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

FLAG_KEY = "split-gate"
_BY_COHORT: dict[str, Any] = {
    "exposure_config": {
        "kind": "ExperimentEventExposureConfig",
        "event": "$feature_flag_called",
        "properties": [{"key": "id", "value": 1, "type": "cohort"}],
    }
}


def _split(control: int, test: int) -> list[dict[str, Any]]:
    return [{"key": "control", "rollout_percentage": control}, {"key": "test", "rollout_percentage": test}]


def _filters(variants: list[dict[str, Any]]) -> dict[str, Any]:
    return {"groups": [{"properties": [], "rollout_percentage": 100}], "multivariate": {"variants": variants}}


def _create_running_experiment(
    team: Team, user: User, *, launched_at: datetime, exposure_criteria: dict[str, Any] | None = None
) -> Experiment:
    flag = FeatureFlag.objects.create(team=team, created_by=user, key=FLAG_KEY, filters=_filters(_split(50, 50)))
    return Experiment.objects.create(
        team=team,
        name="Split gate",
        feature_flag=flag,
        start_date=launched_at,
        exposure_criteria=exposure_criteria or {},
    )


class TestLoadSplitHistory(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.launched_at = timezone.now() - timedelta(days=30)
        self.experiment = _create_running_experiment(self.team, self.user, launched_at=self.launched_at)

    def _log_split_changes(
        self, splits: list[list[dict[str, Any]]], *, first_at: datetime | None = None
    ) -> list[datetime]:
        first_at = first_at or self.launched_at + timedelta(days=1)
        changed_at = [first_at + timedelta(hours=index) for index in range(len(splits) - 1)]
        for at, before, after in zip(changed_at, splits, splits[1:]):
            ActivityLog.objects.create(
                team_id=self.team.id,
                scope="FeatureFlag",
                item_id=str(self.experiment.feature_flag_id),
                activity="updated",
                detail={
                    "changes": [
                        {
                            "type": "FeatureFlag",
                            "action": "changed",
                            "field": "filters",
                            "before": _filters(before),
                            "after": _filters(after),
                        }
                    ]
                },
                created_at=at,
            )
        return changed_at

    def _load(self, answers: list[bool | Exception] | Callable[..., bool]) -> tuple[SplitHistory | None, MagicMock]:
        with patch(
            "products.experiments.backend.health.exposure_gate.query_any_exposure", side_effect=answers
        ) as query:
            history = load_split_history(self.experiment)
        return history, query

    def test_changes_before_the_first_exposure_do_not_count(self) -> None:
        changed_at = self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30), _split(80, 20)])

        history, query = self._load([False, True])

        assert history is not None
        self.assertEqual([change.changed_at for change in history.counted_changes], changed_at[1:])
        self.assertIs(history.exposed_before_first, True)
        self.assertEqual(
            [(call.kwargs["window_start"], call.kwargs["window_end"]) for call in query.call_args_list],
            [(self.launched_at, changed_at[0]), (changed_at[0], changed_at[1])],
        )

    def test_no_exposure_before_any_change(self) -> None:
        self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30)])

        history, _ = self._load([False, False])

        assert history is not None
        self.assertEqual(history.counted_changes, ())

    @parameterized.expand(
        [
            ("same_split", _split(50, 50)),
            ("with_a_variant_left_at_zero", [*_split(50, 50), {"key": "blue", "rollout_percentage": 0}]),
        ]
    )
    def test_revert_asks_whether_anyone_was_exposed_in_between(
        self, _name: str, set_back_to: list[dict[str, Any]]
    ) -> None:
        changed_at = self._log_split_changes([_split(50, 50), _split(0, 100), set_back_to])

        history, query = self._load([True, False])

        assert history is not None
        self.assertIs(history.exposed_between, False)
        self.assertEqual(
            query.call_args.kwargs,
            {
                "window_start": changed_at[0],
                "window_end": changed_at[1],
                "variant_keys": ["control", "test"],
                "default_exposure_event": ANY,
            },
        )

    @parameterized.expand(
        [
            ("scan_too_expensive", ClickHouseQueryTimeOut(), False, 0),
            ("transient_memory_pressure", ClickHouseClusterMemoryLimitExceeded(), False, 1),
            ("unexpected_error", RuntimeError("unexpected"), True, 1),
        ]
    )
    def test_failed_query_counts_the_change_as_unknown_and_is_not_retried_on_the_next_load(
        self, _name: str, error: Exception, reported: bool, queries_two_hours_later: int
    ) -> None:
        changed_at = self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30)])

        with patch("products.experiments.backend.health.exposure_gate.capture_exception") as capture:
            history, _ = self._load([False, error])
        next_load, next_query = self._load([True])

        assert history is not None and next_load is not None
        self.assertEqual([change.changed_at for change in history.counted_changes], changed_at[1:])
        self.assertIsNone(history.exposed_before_first)
        self.assertIsNone(next_load.exposed_before_first)
        self.assertEqual(next_query.call_count, 0)
        self.assertEqual(capture.called, reported)
        with time_machine.travel(timezone.now() + timedelta(hours=2)):
            _, later_query = self._load([True])
        self.assertEqual(later_query.call_count, queries_two_hours_later)

    @parameterized.expand(
        [
            ("query_limit", 0, MAX_EXPOSURE_QUERIES),
            ("time_budget", 6, 2),
        ]
    )
    def test_request_limit_counts_the_next_change_as_unknown(
        self, _name: str, seconds_per_query: float, expected_queries: int
    ) -> None:
        changed_at = self._log_split_changes([_split(50, 50), _split(60, 40)] * 11 + [_split(50, 50)])
        clock = [0.0]

        def nobody_exposed(*_args: Any, **_kwargs: Any) -> bool:
            clock[0] += seconds_per_query
            return False

        with patch("products.experiments.backend.health.exposure_gate.monotonic", side_effect=lambda: clock[0]):
            history, query = self._load(nobody_exposed)

        assert history is not None
        self.assertEqual(query.call_count, expected_queries)
        self.assertEqual(history.counted_changes[0].changed_at, changed_at[expected_queries])
        self.assertIsNone(history.exposed_before_first)

    def test_editing_the_exposure_action_asks_again(self) -> None:
        action = Action.objects.create(team=self.team, name="Checkout", steps_json=[{"event": "checkout_viewed"}])
        self.experiment.exposure_criteria = {"exposure_config": {"kind": "ActionsNode", "id": action.id}}
        self.experiment.save()
        self._log_split_changes([_split(50, 50), _split(60, 40)])
        self._load([False])

        action.steps_json = [{"event": "checkout_completed"}]
        action.save()
        _, query = self._load([False])

        self.assertEqual(query.call_count, 1)

    @parameterized.expand(
        [
            ("exposed", True, timedelta(minutes=10), {}, timedelta(days=2), 0),
            ("nobody_in_a_settled_window", False, timedelta(hours=2), {}, timedelta(days=2), 0),
            ("nobody_in_a_recent_window_minutes_later", False, timedelta(minutes=10), {}, timedelta(minutes=1), 0),
            ("nobody_in_a_recent_window_later", False, timedelta(minutes=10), {}, timedelta(minutes=10), 1),
            ("nobody_with_a_cohort_filter", False, timedelta(hours=2), _BY_COHORT, timedelta(hours=2), 1),
            ("exposed_with_a_cohort_filter", True, timedelta(hours=2), _BY_COHORT, timedelta(days=2), 0),
        ]
    )
    def test_answer_cache(
        self,
        _name: str,
        answer: bool,
        change_age: timedelta,
        exposure_criteria: dict[str, Any],
        next_load_after: timedelta,
        expected_queries: int,
    ) -> None:
        self.experiment.exposure_criteria = exposure_criteria
        self.experiment.save()
        self._log_split_changes([_split(50, 50), _split(60, 40)], first_at=timezone.now() - change_age)
        self._load([answer])

        with time_machine.travel(timezone.now() + next_load_after):
            _, query = self._load([answer])

        self.assertEqual(query.call_count, expected_queries)

    def test_revert_through_a_flag_without_variants_leaves_in_between_unknown(self) -> None:
        self._log_split_changes([_split(50, 50), [], _split(50, 50)])

        history, query = self._load([True])

        assert history is not None
        self.assertIsNone(history.exposed_between)
        self.assertEqual(query.call_count, 1)


class TestQueryAnyExposure(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("exposure_before_the_change", None, "$feature_flag_called", "test", 3, True),
            ("exposure_after_the_change", None, "$feature_flag_called", "test", 0.5, False),
            ("variant_outside_the_keys", None, "$feature_flag_called", "blue", 3, False),
            (
                "custom_exposure_event",
                {
                    "exposure_config": {
                        "kind": "ExperimentEventExposureConfig",
                        "event": "checkout_viewed",
                        "properties": [],
                    }
                },
                "checkout_viewed",
                "test",
                3,
                True,
            ),
        ]
    )
    def test_query_any_exposure(
        self,
        _name: str,
        exposure_criteria: dict[str, Any] | None,
        event: str,
        variant: str,
        days_ago: float,
        expected: bool,
    ) -> None:
        now = timezone.now()
        experiment = _create_running_experiment(
            self.team, self.user, launched_at=now - timedelta(days=5), exposure_criteria=exposure_criteria
        )
        properties = (
            {"$feature_flag": FLAG_KEY, "$feature_flag_response": variant}
            if event == "$feature_flag_called"
            else {f"$feature/{FLAG_KEY}": variant}
        )
        _create_event(
            team=self.team,
            event=event,
            distinct_id="person-1",
            properties=properties,
            timestamp=now - timedelta(days=days_ago),
        )
        flush_persons_and_events()

        exposed = query_any_exposure(
            experiment,
            window_start=now - timedelta(days=5),
            window_end=now - timedelta(days=1),
            variant_keys=["control", "test"],
            default_exposure_event=DEFAULT_EXPOSURE_EVENT,
        )

        self.assertIs(exposed, expected)
