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
from posthog.test.persons import create_person

from products.experiments.backend.facade.contracts import ExperimentHealthFlagChangeKind, ExperimentHealthReaderAccess
from products.experiments.backend.health.context import (
    MIN_EXPOSED_UNITS_TO_WARN,
    BucketingChange,
    BucketingSetting,
    ChangeWindow,
    ConditionsChange,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    SplitChange,
)
from products.experiments.backend.health.exposure_gate import (
    MAX_EXPOSURE_QUERIES,
    MAX_OVERRIDE_WINDOWS,
    load_flag_history,
    query_any_exposure,
    query_exposed_units,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import DEFAULT_EXPOSURE_EVENT
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

FLAG_KEY = "split-gate"
FULL_ACCESS = ExperimentHealthReaderAccess(
    can_read_flag_history=True, can_query_events=True, denied_event_properties=frozenset()
)
_BY_EVENT_PROPERTY: dict[str, Any] = {
    "exposure_config": {
        "kind": "ExperimentEventExposureConfig",
        "event": "$feature_flag_called",
        "properties": [{"key": "plan", "value": "pro", "operator": "exact", "type": "event"}],
    }
}
_BY_ACTION: dict[str, Any] = {"exposure_config": {"kind": "ActionsNode", "id": 1}}
_UNREADABLE: dict[str, Any] = {"exposure_config": {"kind": "ExperimentEventExposureConfig"}}


_EVERYONE: dict[str, Any] = {"properties": [], "rollout_percentage": 100}


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


class TestLoadFlagHistory(BaseTest):
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

    def _log_change(self, at: datetime, **fields: tuple[Any, Any]) -> None:
        ActivityLog.objects.create(
            team_id=self.team.id,
            scope="FeatureFlag",
            item_id=str(self.experiment.feature_flag_id),
            activity="updated",
            detail={
                "changes": [
                    {"type": "FeatureFlag", "action": "changed", "field": field, "before": before, "after": after}
                    for field, (before, after) in fields.items()
                ]
            },
            created_at=at,
        )

    def _load(
        self,
        answers: list[bool | Exception] | Callable[..., bool],
        *,
        units: list[int | Exception] | Callable[..., int] | None = None,
        reader_access: ExperimentHealthReaderAccess = FULL_ACCESS,
    ) -> tuple[FlagHistory | FlagHistoryNotChecked | None, MagicMock]:
        with (
            patch("products.experiments.backend.health.exposure_gate.query_any_exposure", side_effect=answers) as query,
            patch(
                "products.experiments.backend.health.exposure_gate.query_exposed_units",
                side_effect=units,
                return_value=MIN_EXPOSED_UNITS_TO_WARN,
            ) as units_query,
        ):
            history = load_flag_history(self.experiment, reader_access=reader_access)
        self.units_query = units_query
        return history, query

    def test_changes_before_the_first_exposure_do_not_count(self) -> None:
        changed_at = self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30), _split(80, 20)])

        history, query = self._load([False, True])

        assert isinstance(history, FlagHistory)
        self.assertEqual([change.changed_at for change in history.counted(SplitChange)], changed_at[1:])
        self.assertIs(history.exposed_before_first, True)
        self.assertEqual(
            [(call.kwargs["window_start"], call.kwargs["window_end"]) for call in query.call_args_list],
            [(self.launched_at, changed_at[0]), (changed_at[0], changed_at[1])],
        )

    def test_every_kind_of_change_shares_one_walk(self) -> None:
        first_at = self.launched_at + timedelta(days=1)
        changed_at = [first_at, first_at + timedelta(hours=1), first_at + timedelta(hours=2)]
        with_a_second_condition = {
            **_filters(_split(50, 50)),
            "groups": [{"properties": [], "rollout_percentage": 100}, {"properties": [], "rollout_percentage": 50}],
        }
        self._log_change(changed_at[0], filters=(_filters(_split(50, 50)), with_a_second_condition))
        self._log_change(changed_at[1], bucketing_identifier=("distinct_id", "device_id"))
        self._log_change(
            changed_at[2],
            filters=(
                {**_filters(_split(50, 50)), "aggregation_group_type_index": None},
                {**_filters(_split(60, 40)), "aggregation_group_type_index": 0},
            ),
        )

        history, query = self._load([False, True])

        assert isinstance(history, FlagHistory)
        self.assertEqual([change.changed_at for change in history.of_kind(ConditionsChange)], changed_at[:1])
        self.assertEqual(history.counted(ConditionsChange), ())
        self.assertEqual(
            [(change.changed_at, change.setting) for change in history.counted(BucketingChange)],
            [
                (changed_at[1], BucketingSetting.BUCKETING_IDENTIFIER),
                (changed_at[2], BucketingSetting.AGGREGATION),
            ],
        )
        self.assertEqual([change.changed_at for change in history.counted(SplitChange)], changed_at[2:])
        self.assertEqual(query.call_count, 2)

    def test_each_window_asks_with_the_key_the_flag_had_then(self) -> None:
        first_at = self.launched_at + timedelta(days=1)
        changed_at = [first_at, first_at + timedelta(hours=1)]
        self._log_change(changed_at[0], key=("first-key", "second-key"))
        self._log_change(changed_at[1], key=("second-key", FLAG_KEY))

        history, query = self._load([False, True])

        assert isinstance(history, FlagHistory)
        self.assertEqual([call.kwargs["flag_key"] for call in query.call_args_list], ["first-key", "second-key"])
        self.assertEqual([change.changed_at for change in history.counted(BucketingChange)], changed_at[1:])

    def test_a_key_set_back_asks_between_with_the_key_in_between(self) -> None:
        first_at = self.launched_at + timedelta(days=1)
        changed_at = [first_at, first_at + timedelta(minutes=6)]
        self._log_change(changed_at[0], key=(FLAG_KEY, "renamed"))
        self._log_change(changed_at[1], key=("renamed", FLAG_KEY))

        history, query = self._load([True, False])

        assert isinstance(history, FlagHistory)
        self.assertIs(history.exposed_between.get(ExperimentHealthFlagChangeKind.BUCKETING), False)
        self.assertEqual(
            (query.call_args.kwargs["flag_key"], query.call_args.kwargs["window_start"]), ("renamed", changed_at[0])
        )

    def test_counts_the_units_exposed_before_the_last_counted_change_of_each_kind(self) -> None:
        first_at = self.launched_at + timedelta(days=1)
        changed_at = [first_at, first_at + timedelta(hours=1), first_at + timedelta(hours=2)]
        self._log_change(changed_at[0], key=("first-key", FLAG_KEY))
        self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30)], first_at=changed_at[1])

        history, _ = self._load(
            [True], units=lambda *_args, **kwargs: 2 if kwargs["window_end"] == changed_at[0] else 3
        )

        assert isinstance(history, FlagHistory)
        self.assertEqual(
            history.exposed_units_before_last,
            {ExperimentHealthFlagChangeKind.SPLIT: 3, ExperimentHealthFlagChangeKind.BUCKETING: 2},
        )
        self.assertEqual(
            [
                (call.kwargs["window_start"], call.kwargs["window_end"], call.kwargs["served"])
                for call in self.units_query.call_args_list
            ],
            [
                (
                    self.launched_at,
                    changed_at[2],
                    (("first-key", ("control", "test")), (FLAG_KEY, ("control", "test"))),
                ),
                (self.launched_at, changed_at[0], (("first-key", ("control", "test")),)),
            ],
        )

    def test_a_count_is_cached_apart_from_the_exposure_answer_of_the_same_window(self) -> None:
        self._log_split_changes([_split(50, 50), _split(60, 40)])
        first, _ = self._load([True], units=[3])

        with patch("products.experiments.backend.health.exposure_gate.cache", wraps=cache) as cache_spy:
            second, query = self._load([])

        assert isinstance(first, FlagHistory) and isinstance(second, FlagHistory)
        self.assertEqual(first.exposed_units_before_last, {ExperimentHealthFlagChangeKind.SPLIT: 3})
        self.assertEqual(second.exposed_units_before_last, {ExperimentHealthFlagChangeKind.SPLIT: 3})
        self.assertEqual((query.call_count, self.units_query.call_count), (0, 0))
        self.assertEqual((cache_spy.get_many.call_count, cache_spy.get.call_count), (1, 0))

    @parameterized.expand(
        [
            ("variant_property", frozenset({"$feature_flag_response"}), (0, None, None)),
            ("group_key", frozenset({"$group_0"}), (0, None, None)),
            ("unrelated_property", frozenset({"$browser"}), (0, None, None)),
            ("no_denied_property", frozenset(), (1, True, 3)),
        ]
    )
    def test_a_reader_denied_any_event_property_gets_no_exposure_answer(
        self, _name: str, denied: frozenset[str], expected: tuple[int, bool | None, int | None]
    ) -> None:
        changed_at = self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30)])
        self._load([False, True], units=[3])

        history, query = self._load(
            [],
            reader_access=ExperimentHealthReaderAccess(
                can_read_flag_history=True, can_query_events=True, denied_event_properties=denied
            ),
        )

        assert isinstance(history, FlagHistory)
        counted_from, exposed_before_first, units = expected
        self.assertEqual(
            (history.counted_since, history.exposed_before_first, history.exposed_units_before_last),
            (changed_at[counted_from], exposed_before_first, {ExperimentHealthFlagChangeKind.SPLIT: units}),
        )
        self.assertEqual((query.call_count, self.units_query.call_count), (0, 0))

    def test_no_exposure_before_any_change(self) -> None:
        self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30)])

        history, _ = self._load([False, False])

        assert isinstance(history, FlagHistory)
        self.assertEqual(history.counted(SplitChange), ())

    @parameterized.expand(
        [
            ("default_exposure", {}),
            (
                "custom_event_without_property_filters",
                {"exposure_config": {"kind": "ExperimentEventExposureConfig", "event": "checkout", "properties": []}},
            ),
            (
                "activation_event_on_the_default_exposure",
                {
                    "activation_config": {
                        "kind": "ExperimentEventExposureConfig",
                        "event": "checkout",
                        "properties": [{"key": "plan", "value": "pro", "operator": "exact", "type": "event"}],
                    }
                },
            ),
        ]
    )
    def test_criteria_that_name_an_event_are_checked_against_exposures(
        self, _name: str, exposure_criteria: dict[str, Any]
    ) -> None:
        self.experiment.exposure_criteria = exposure_criteria
        self.experiment.save()
        self._log_split_changes([_split(50, 50), _split(60, 40)])

        history, query = self._load([True])

        assert isinstance(history, FlagHistory)
        self.assertIs(history.exposed_before_first, True)
        self.assertEqual(query.call_count, 1)

    @parameterized.expand([("too_many_saves", 101, 1), ("too_many_conditions", 1, 101)])
    def test_a_history_past_the_bounds_is_not_read(self, reason: str, saves: int, conditions: int) -> None:
        first_at = self.launched_at + timedelta(days=1)
        filters = [
            {**_filters(_split(60, 40) if index % 2 else _split(50, 50)), "groups": [_EVERYONE] * conditions}
            for index in range(saves + 1)
        ]
        for index, (before, after) in enumerate(zip(filters, filters[1:])):
            self._log_change(first_at + timedelta(minutes=index), filters=(before, after))

        history, query = self._load([True])

        assert isinstance(history, FlagHistoryNotChecked)
        self.assertEqual((history.reason, history.changes), (FlagHistoryNotCheckedReason(reason), ()))
        self.assertEqual(query.call_count, 0)

    def test_an_override_set_and_removed_asks_whether_anyone_was_exposed_while_it_was_in_place(self) -> None:
        first_at = self.launched_at + timedelta(days=1)
        changed_at = [first_at, first_at + timedelta(hours=1), first_at + timedelta(hours=2)]
        pro = {"properties": [{"key": "plan", "value": ["pro"], "operator": "exact", "type": "person"}]}
        groups = [[_EVERYONE], [{**_EVERYONE, "variant": "test"}], [_EVERYONE], [_EVERYONE, pro]]
        for at, before, after in zip(changed_at, groups, groups[1:]):
            self._log_change(
                at,
                filters=({**_filters(_split(50, 50)), "groups": before}, {**_filters(_split(50, 50)), "groups": after}),
            )

        history, query = self._load([True, False])

        assert isinstance(history, FlagHistory)
        self.assertEqual(
            history.exposed_during_overrides, {ChangeWindow(start=changed_at[0], end=changed_at[1]): False}
        )
        self.assertEqual(query.call_count, 2)

    def test_override_windows_past_the_bound_are_not_asked(self) -> None:
        first_at = self.launched_at + timedelta(days=1)
        unpinned: list[dict[str, Any]] = [
            {"properties": [{"key": "plan", "value": [f"plan {index}"], "operator": "exact", "type": "person"}]}
            for index in range(MAX_OVERRIDE_WINDOWS + 1)
        ]
        groups = [unpinned]
        for pinned_index in range(len(unpinned)):
            groups.append(
                [
                    {**condition, "variant": "test"} if index == pinned_index else condition
                    for index, condition in enumerate(unpinned)
                ]
            )
            groups.append(unpinned)
        for minute, (before, after) in enumerate(zip(groups, groups[1:])):
            self._log_change(
                first_at + timedelta(minutes=minute),
                filters=({**_filters(_split(50, 50)), "groups": before}, {**_filters(_split(50, 50)), "groups": after}),
            )

        history, _ = self._load(lambda **kwargs: kwargs["window_start"] == self.launched_at)

        assert isinstance(history, FlagHistory)
        self.assertEqual(len(history.exposed_during_overrides), MAX_OVERRIDE_WINDOWS)

    @parameterized.expand(
        [
            ("exposure_filters", _BY_EVENT_PROPERTY, True, True, FlagHistoryNotCheckedReason.EXPOSURE_FILTERS),
            ("exposure_action", _BY_ACTION, True, True, FlagHistoryNotCheckedReason.EXPOSURE_ACTION),
            ("exposure_criteria", _UNREADABLE, True, True, FlagHistoryNotCheckedReason.EXPOSURE_CRITERIA),
            ("no_query_access", {}, True, False, FlagHistoryNotCheckedReason.NO_QUERY_ACCESS),
            (
                "filters_without_query_access",
                _BY_EVENT_PROPERTY,
                True,
                False,
                FlagHistoryNotCheckedReason.EXPOSURE_FILTERS,
            ),
            ("no_history_access", {}, False, True, FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS),
        ]
    )
    def test_split_changes_that_cannot_be_checked(
        self,
        _name: str,
        exposure_criteria: dict[str, Any],
        can_read_flag_history: bool,
        can_query_events: bool,
        expected_reason: FlagHistoryNotCheckedReason,
    ) -> None:
        self.experiment.exposure_criteria = exposure_criteria
        self.experiment.save()
        changed_at = self._log_split_changes([_split(50, 50), _split(60, 40), _split(70, 30)])

        history, query = self._load(
            [True],
            reader_access=ExperimentHealthReaderAccess(
                can_read_flag_history=can_read_flag_history,
                can_query_events=can_query_events,
                denied_event_properties=frozenset(),
            ),
        )

        assert isinstance(history, FlagHistoryNotChecked)
        self.assertEqual(history.reason, expected_reason)
        expected_changes = changed_at if can_read_flag_history else []
        self.assertEqual([change.changed_at for change in history.of_kind(SplitChange)], expected_changes)
        self.assertEqual(query.call_count, 0)

    @parameterized.expand(
        [
            ("exposure_filters", _BY_EVENT_PROPERTY, FULL_ACCESS),
            (
                "no_query_access",
                {},
                ExperimentHealthReaderAccess(
                    can_read_flag_history=True, can_query_events=False, denied_event_properties=frozenset()
                ),
            ),
        ]
    )
    def test_flag_without_split_changes_needs_no_check(
        self, _name: str, exposure_criteria: dict[str, Any], reader_access: ExperimentHealthReaderAccess
    ) -> None:
        self.experiment.exposure_criteria = exposure_criteria
        self.experiment.save()

        history, _ = self._load([], reader_access=reader_access)

        assert isinstance(history, FlagHistory)
        self.assertEqual(history.counted(SplitChange), ())

    @parameterized.expand(
        [
            ("same_split", _filters(_split(50, 50)), [ExperimentHealthFlagChangeKind.SPLIT]),
            (
                "with_a_variant_left_at_zero",
                _filters([*_split(50, 50), {"key": "blue", "rollout_percentage": 0}]),
                [ExperimentHealthFlagChangeKind.SPLIT],
            ),
            # Both kinds ask about the same window, and the second must not query again.
            (
                "with_the_conditions_set_back_too",
                _filters(_split(50, 50)),
                [ExperimentHealthFlagChangeKind.SPLIT, ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS],
            ),
        ]
    )
    def test_revert_asks_whether_anyone_was_exposed_in_between(
        self, _name: str, set_back_to: dict[str, Any], set_back_kinds: list[ExperimentHealthFlagChangeKind]
    ) -> None:
        first_at = self.launched_at + timedelta(days=1)
        changed_at = [first_at, first_at + timedelta(hours=1)]
        changed = _filters(_split(0, 100))
        if ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS in set_back_kinds:
            changed["groups"] = [{"properties": [], "rollout_percentage": 100, "variant": "test"}]
        self._log_change(changed_at[0], filters=(_filters(_split(50, 50)), changed))
        self._log_change(changed_at[1], filters=(changed, set_back_to))

        history, query = self._load([True, False])

        assert isinstance(history, FlagHistory)
        self.assertEqual(history.exposed_between, dict.fromkeys(set_back_kinds, False))
        self.assertEqual(query.call_count, 2)
        self.assertEqual(
            query.call_args.kwargs,
            {
                "flag_key": FLAG_KEY,
                "window_start": changed_at[0],
                "window_end": changed_at[1],
                "variant_keys": ("control", "test"),
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

        assert isinstance(history, FlagHistory) and isinstance(next_load, FlagHistory)
        self.assertEqual([change.changed_at for change in history.counted(SplitChange)], changed_at[1:])
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

        assert isinstance(history, FlagHistory)
        self.assertEqual(query.call_count, expected_queries)
        self.assertEqual(history.counted(SplitChange)[0].changed_at, changed_at[expected_queries])
        self.assertIsNone(history.exposed_before_first)
        self.assertEqual(history.exposed_units_before_last, {ExperimentHealthFlagChangeKind.SPLIT: None})
        self.assertEqual(self.units_query.call_count, 0)

    def test_cached_walk_reads_the_cache_once(self) -> None:
        self._log_split_changes([_split(50, 50), _split(60, 40)] * 5)
        self._load([False] * 9)

        with patch("products.experiments.backend.health.exposure_gate.cache", wraps=cache) as cache_spy:
            history, query = self._load([])

        assert isinstance(history, FlagHistory)
        self.assertEqual(history.counted(SplitChange), ())
        self.assertEqual(query.call_count, 0)
        self.assertEqual((cache_spy.get_many.call_count, cache_spy.get.call_count), (1, 0))

    @parameterized.expand(
        [
            ("exposed", True, 5, timedelta(minutes=10), timedelta(days=2), 0, 0),
            ("nobody_in_a_settled_window", False, None, timedelta(hours=2), timedelta(days=2), 0, 0),
            ("nobody_in_a_recent_window_minutes_later", False, None, timedelta(minutes=10), timedelta(minutes=1), 0, 0),
            ("nobody_in_a_recent_window_later", False, None, timedelta(minutes=10), timedelta(minutes=10), 1, 0),
            ("few_units_in_a_settled_window", True, 3, timedelta(hours=2), timedelta(days=2), 0, 0),
            ("few_units_in_a_recent_window_later", True, 3, timedelta(minutes=10), timedelta(minutes=10), 0, 1),
        ]
    )
    def test_answer_cache(
        self,
        _name: str,
        answer: bool,
        units: int | None,
        change_age: timedelta,
        next_load_after: timedelta,
        expected_queries: int,
        expected_units_queries: int,
    ) -> None:
        self._log_split_changes([_split(50, 50), _split(60, 40)], first_at=timezone.now() - change_age)
        self._load([answer], units=None if units is None else [units])

        with time_machine.travel(timezone.now() + next_load_after):
            _, query = self._load([answer], units=None if units is None else [units])

        self.assertEqual((query.call_count, self.units_query.call_count), (expected_queries, expected_units_queries))

    def test_revert_through_a_flag_without_variants_leaves_in_between_unknown(self) -> None:
        self._log_split_changes([_split(50, 50), [], _split(50, 50)])

        history, query = self._load([True])

        assert isinstance(history, FlagHistory)
        self.assertIsNone(history.exposed_between.get(ExperimentHealthFlagChangeKind.SPLIT))
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
            flag_key=FLAG_KEY,
            window_start=now - timedelta(days=5),
            window_end=now - timedelta(days=1),
            variant_keys=["control", "test"],
            default_exposure_event=DEFAULT_EXPOSURE_EVENT,
        )

        self.assertIs(exposed, expected)


class TestQueryExposedUnits(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("capped", None, [(f"person-{index}", FLAG_KEY, "test", None) for index in range(7)], 5),
            (
                "each_person_once_under_every_key",
                None,
                [
                    ("person-1", "old-key", "control", None),
                    ("person-1", FLAG_KEY, "control", None),
                    ("person-2", FLAG_KEY, "test", None),
                    ("person-3", FLAG_KEY, "blue", None),
                ],
                2,
            ),
            (
                "groups_with_a_group_key",
                0,
                [
                    ("person-1", FLAG_KEY, "test", "org-1"),
                    ("person-2", FLAG_KEY, "control", "org-1"),
                    ("person-3", FLAG_KEY, "test", "org-2"),
                    ("person-4", FLAG_KEY, "test", None),
                ],
                2,
            ),
        ]
    )
    def test_query_exposed_units(
        self,
        _name: str,
        group_type_index: int | None,
        exposures: list[tuple[str, str, str, str | None]],
        expected: int,
    ) -> None:
        now = timezone.now()
        experiment = _create_running_experiment(self.team, self.user, launched_at=now - timedelta(days=5))
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, *_ in exposures):
            create_person(team=self.team, distinct_ids=[distinct_id])
        for distinct_id, flag_key, variant, group_key in exposures:
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=distinct_id,
                properties={
                    "$feature_flag": flag_key,
                    "$feature_flag_response": variant,
                    **({"$group_0": group_key} if group_key else {}),
                },
                timestamp=now - timedelta(days=3),
            )
        flush_persons_and_events()

        units = query_exposed_units(
            experiment,
            window_start=now - timedelta(days=5),
            window_end=now - timedelta(days=1),
            served=[("old-key", ["control", "test"]), (FLAG_KEY, ["control", "test"])],
            group_type_index=group_type_index,
            default_exposure_event=DEFAULT_EXPOSURE_EVENT,
        )

        self.assertEqual(units, expected)
