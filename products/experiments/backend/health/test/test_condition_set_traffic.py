import time
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.exceptions import ClickHouseClusterMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.test.persons import create_person

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.health.condition_set_traffic import (
    load_condition_set_traffic,
    query_condition_set_traffic,
)
from products.experiments.backend.health.context import ConditionSetTraffic, load_health_context
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

FLAG_KEY = "pinned-share"
FLAG_VERSION = 3
FULL_ACCESS = ExperimentHealthReaderAccess(
    can_read_flag_history=True, can_query_events=True, denied_event_properties=frozenset()
)
TRAFFIC = ConditionSetTraffic(
    since=datetime(2026, 10, 1, tzinfo=UTC),
    team_timezone="UTC",
    people_by_set={1: 30, 2: 970},
    calls=2000,
    remotely_evaluated_calls=2000,
    people_assigned_outside=0,
)
TOO_FEW_PEOPLE = ConditionSetTraffic(
    since=datetime(2026, 10, 1, tzinfo=UTC),
    team_timezone="UTC",
    people_by_set={1: 3, 2: 50},
    calls=100,
    remotely_evaluated_calls=100,
    people_assigned_outside=0,
)
_NO_VARIANT_REASONS = frozenset({"Out of rollout bound", "No matching condition set"})
_STAFF_PINNED_TO_TEST: dict[str, Any] = {
    "properties": [{"key": "email", "value": "@example.com", "operator": "icontains", "type": "person"}],
    "rollout_percentage": 100,
    "variant": "test",
}
# Set 1 pins a 0% holdout, so its 500 people do not count toward the minimum.
TOO_FEW_PEOPLE_BESIDE_A_HOLDOUT = replace(TOO_FEW_PEOPLE, people_by_set={1: 500, 2: 3, 3: 50})
_HOLDOUT_FILTERS: dict[str, Any] = {
    "groups": [
        {**_STAFF_PINNED_TO_TEST, "variant": "holdout"},
        {
            "properties": [{"key": "$device_type", "value": "iOS", "operator": "exact", "type": "person"}],
            "rollout_percentage": 100,
            "variant": "test",
        },
        {"properties": [], "rollout_percentage": 100},
    ],
    "multivariate": {
        "variants": [
            {"key": "control", "rollout_percentage": 50},
            {"key": "test", "rollout_percentage": 50},
            {"key": "holdout", "rollout_percentage": 0},
        ]
    },
}


_ZERO_ROLLOUT_FILTERS: dict[str, Any] = {
    "groups": [{"properties": [], "rollout_percentage": 0}],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
    },
}
NO_ONE_ASSIGNED_OUTSIDE = replace(TRAFFIC, people_by_set={}, remotely_evaluated_calls=0, calls=0)
ASSIGNED_OUTSIDE = replace(NO_ONE_ASSIGNED_OUTSIDE, calls=900, people_assigned_outside=300)


def _create_running_experiment(team: Team, user: User, *, launched_at: datetime) -> Experiment:
    flag = FeatureFlag.objects.create(
        team=team,
        created_by=user,
        key=FLAG_KEY,
        version=FLAG_VERSION,
        filters={
            "groups": [_STAFF_PINNED_TO_TEST, {"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
            },
        },
    )
    return Experiment.objects.create(team=team, name="Pinned share", feature_flag=flag, start_date=launched_at)


class TestLoadConditionSetTraffic(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.experiment = _create_running_experiment(
            self.team, self.user, launched_at=timezone.now() - timedelta(days=30)
        )

    def _load(
        self, answer: ConditionSetTraffic | Exception, *, reader_access: ExperimentHealthReaderAccess = FULL_ACCESS
    ) -> tuple[ConditionSetTraffic | None, MagicMock]:
        with patch(
            "products.experiments.backend.health.condition_set_traffic.query_condition_set_traffic",
            side_effect=[answer],
        ) as query:
            traffic = load_condition_set_traffic(
                self.experiment, load_health_context(self.experiment), reader_access=reader_access
            )
        return traffic, query

    @parameterized.expand(
        [
            ("no_query_access", replace(FULL_ACCESS, can_query_events=False)),
            ("denied_the_reason", replace(FULL_ACCESS, denied_event_properties=frozenset({"$feature_flag_reason"}))),
        ]
    )
    def test_reader_who_cannot_read_the_flag_calls_gets_no_traffic(
        self, _name: str, reader_access: ExperimentHealthReaderAccess
    ) -> None:
        traffic, query = self._load(TRAFFIC, reader_access=reader_access)

        self.assertEqual((traffic, query.call_count), (None, 0))

    @parameterized.expand(
        [
            ("pinned_condition", None, 1),
            ("zero_rollout", _ZERO_ROLLOUT_FILTERS, 1),
            (
                "no_pin_and_a_rollout",
                {**_ZERO_ROLLOUT_FILTERS, "groups": [{"properties": [], "rollout_percentage": 100}]},
                0,
            ),
        ]
    )
    def test_scans_only_for_a_check_that_reads_the_calls(
        self, _name: str, flag_filters: dict[str, Any] | None, expected_queries: int
    ) -> None:
        if flag_filters is not None:
            FeatureFlag.objects.filter(pk=self.experiment.feature_flag_id).update(filters=flag_filters)
            self.experiment = Experiment.objects.get(pk=self.experiment.pk)

        _, query = self._load(TRAFFIC)

        self.assertEqual(query.call_count, expected_queries)

    @parameterized.expand(
        [
            ("since_launch", timedelta(days=2), timedelta(days=3), "launch"),
            ("since_the_last_save", timedelta(days=30), timedelta(hours=2), "save"),
            ("last_seven_days", timedelta(days=30), timedelta(days=20), "window"),
        ]
    )
    def test_window_starts_at_the_latest_of_launch_last_save_and_seven_days_ago(
        self, _name: str, launched_ago: timedelta, saved_ago: timedelta, expected_start: str
    ) -> None:
        now = timezone.now()
        Experiment.objects.filter(pk=self.experiment.pk).update(start_date=now - launched_ago)
        FeatureFlag.objects.filter(pk=self.experiment.feature_flag_id).update(updated_at=now - saved_ago)
        self.experiment = Experiment.objects.get(pk=self.experiment.pk)

        with time_machine.travel(now, tick=False):
            _, query = self._load(TRAFFIC)

        starts = {"launch": now - launched_ago, "save": now - saved_ago, "window": now - timedelta(days=7)}
        self.assertEqual(query.call_args.kwargs["window_start"], starts[expected_start])

    @parameterized.expand(
        [
            ("enough_people_hours_later", TRAFFIC, timedelta(hours=12), 0),
            ("enough_people_a_day_later", TRAFFIC, timedelta(days=1, minutes=1), 1),
            ("too_few_people_minutes_later", TOO_FEW_PEOPLE, timedelta(minutes=30), 0),
            ("too_few_people_an_hour_later", TOO_FEW_PEOPLE, timedelta(hours=1, minutes=1), 1),
            (
                "too_few_people_beside_a_holdout_an_hour_later",
                TOO_FEW_PEOPLE_BESIDE_A_HOLDOUT,
                timedelta(hours=1, minutes=1),
                1,
                _HOLDOUT_FILTERS,
            ),
            (
                "no_one_assigned_outside_in_a_young_window_an_hour_later",
                NO_ONE_ASSIGNED_OUTSIDE,
                timedelta(hours=1, minutes=1),
                1,
                _ZERO_ROLLOUT_FILTERS,
                timedelta(hours=2),
            ),
            (
                "no_one_assigned_outside_in_a_full_window_hours_later",
                NO_ONE_ASSIGNED_OUTSIDE,
                timedelta(hours=12),
                0,
                _ZERO_ROLLOUT_FILTERS,
            ),
            (
                "assigned_outside_in_a_young_window_hours_later",
                ASSIGNED_OUTSIDE,
                timedelta(hours=12),
                0,
                _ZERO_ROLLOUT_FILTERS,
                timedelta(hours=2),
            ),
        ]
    )
    def test_answer_cache(
        self,
        _name: str,
        answer: ConditionSetTraffic,
        next_load_after: timedelta,
        expected_queries: int,
        flag_filters: dict[str, Any] | None = None,
        saved_ago: timedelta | None = None,
    ) -> None:
        if flag_filters is not None:
            saved_at = timezone.now() - saved_ago if saved_ago is not None else None
            FeatureFlag.objects.filter(pk=self.experiment.feature_flag_id).update(
                filters=flag_filters, **({"updated_at": saved_at} if saved_at is not None else {})
            )
            self.experiment = Experiment.objects.get(pk=self.experiment.pk)
            if saved_at is not None:
                answer = replace(answer, since=saved_at)
        first, _ = self._load(answer)

        with time_machine.travel(timezone.now() + next_load_after):
            next_load, query = self._load(answer)

        self.assertEqual((first, next_load, query.call_count), (answer, answer, expected_queries))

    @parameterized.expand(
        [
            ("scan_succeeds", TRAFFIC, TRAFFIC),
            ("scan_fails", RuntimeError("unexpected"), None),
        ]
    )
    def test_concurrent_load_waits_for_the_scan_in_flight(
        self, _name: str, scan_answer: ConditionSetTraffic | Exception, expected: ConditionSetTraffic | None
    ) -> None:
        ctx = load_health_context(self.experiment)
        scanning = threading.Event()
        second_load_waits = threading.Event()
        first_load: list[ConditionSetTraffic | None] = []

        def scan(*_args: Any, **_kwargs: Any) -> ConditionSetTraffic:
            scanning.set()
            second_load_waits.wait(timeout=5)
            if isinstance(scan_answer, Exception):
                raise scan_answer
            return scan_answer

        def wait_a_moment(_seconds: float) -> None:
            second_load_waits.set()
            time.sleep(0.01)

        with (
            patch(
                "products.experiments.backend.health.condition_set_traffic.query_condition_set_traffic",
                side_effect=scan,
            ) as query,
            patch("products.experiments.backend.health.condition_set_traffic.sleep", side_effect=wait_a_moment),
            patch("products.experiments.backend.health.exposure_gate.capture_exception"),
        ):
            first = threading.Thread(
                target=lambda: first_load.append(
                    load_condition_set_traffic(self.experiment, ctx, reader_access=FULL_ACCESS)
                )
            )
            first.start()
            scanning.wait(timeout=5)
            second_load = load_condition_set_traffic(self.experiment, ctx, reader_access=FULL_ACCESS)
            first.join(timeout=5)

        self.assertEqual((first_load, second_load, query.call_count), ([expected], expected, 1))

    def test_concurrent_load_stops_waiting_after_the_query_timeout(self) -> None:
        ctx = load_health_context(self.experiment)
        scanning = threading.Event()
        release_scan = threading.Event()

        def scan(*_args: Any, **_kwargs: Any) -> ConditionSetTraffic:
            scanning.set()
            release_scan.wait(timeout=5)
            return TRAFFIC

        with (
            patch(
                "products.experiments.backend.health.condition_set_traffic.query_condition_set_traffic",
                side_effect=scan,
            ) as query,
            patch("products.experiments.backend.health.condition_set_traffic._WAIT_FOR_SCAN_SECONDS", 0.05),
        ):
            first = threading.Thread(
                target=lambda: load_condition_set_traffic(self.experiment, ctx, reader_access=FULL_ACCESS)
            )
            first.start()
            scanning.wait(timeout=5)
            second_load = load_condition_set_traffic(self.experiment, ctx, reader_access=FULL_ACCESS)
            release_scan.set()
            first.join(timeout=5)

        self.assertEqual((second_load, query.call_count), (None, 1))

    @parameterized.expand(
        [
            ("scan_too_expensive", ClickHouseQueryTimeOut(), False, 0),
            ("transient_memory_pressure", ClickHouseClusterMemoryLimitExceeded(), False, 1),
            ("unexpected_error", RuntimeError("unexpected"), True, 1),
        ]
    )
    def test_failed_query_is_unknown_and_not_retried_on_the_next_load(
        self, _name: str, error: Exception, reported: bool, queries_two_hours_later: int
    ) -> None:
        with patch("products.experiments.backend.health.exposure_gate.capture_exception") as capture:
            traffic, _ = self._load(error)
        next_load, next_query = self._load(TRAFFIC)
        with time_machine.travel(timezone.now() + timedelta(hours=2)):
            _, later_query = self._load(TRAFFIC)

        self.assertEqual(
            (traffic, next_load, next_query.call_count, capture.called, later_query.call_count),
            (None, None, 0, reported, queries_two_hours_later),
        )


class TestQueryConditionSetTraffic(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            (
                "calls_of_another_flag_version_name_no_set",
                [
                    ("person-1", "Matched condition set 1", FLAG_VERSION, 1),
                    ("person-2", "Matched condition set 1", 2, 1),
                ],
                ({1: 1}, 2, 2, 0),
            ),
            (
                "calls_evaluated_outside_the_flag_service_name_no_set",
                [
                    ("person-1", "Matched condition set 2", FLAG_VERSION, 1),
                    ("person-2", None, None, 1),
                    ("person-3", "Evaluated locally", None, 1),
                    ("person-4", None, None, 1),
                    ("person-5", None, None, 6.99),
                ],
                ({2: 1}, 5, 1, 1),
                frozenset({"person-4"}),
            ),
            (
                "calls_that_return_no_variant_do_not_count",
                [
                    ("person-1", "Out of rollout bound", FLAG_VERSION, 1),
                    ("person-2", "Matched condition set 2", FLAG_VERSION, 1),
                ],
                ({2: 1}, 1, 1, 0),
            ),
            (
                "person_counts_once_under_the_latest_set",
                [
                    ("person-1", "Matched condition set 1", FLAG_VERSION, 2),
                    ("person-1", "Matched condition set 2", FLAG_VERSION, 1),
                ],
                ({2: 1}, 2, 2, 0),
            ),
            (
                "calls_outside_the_window",
                [
                    ("person-1", "Matched condition set 1", FLAG_VERSION, 1),
                    ("person-2", "Matched condition set 1", FLAG_VERSION, 8),
                ],
                ({1: 1}, 1, 1, 0),
            ),
        ]
    )
    def test_query_condition_set_traffic(
        self,
        _name: str,
        calls: list[tuple[str, str | None, int | None, float]],
        expected: tuple[dict[int, int], int, int, int],
        locally_evaluated: frozenset[str] = frozenset(),
    ) -> None:
        now = timezone.now()
        experiment = _create_running_experiment(self.team, self.user, launched_at=now - timedelta(days=30))
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, *_ in calls):
            create_person(team=self.team, distinct_ids=[distinct_id])
        for distinct_id, reason, version, days_ago in calls:
            self._call_flag(
                distinct_id,
                reason,
                version,
                now - timedelta(days=days_ago),
                locally_evaluated=distinct_id in locally_evaluated,
            )
        flush_persons_and_events()

        traffic = query_condition_set_traffic(experiment, window_start=now - timedelta(days=7), window_end=now)

        self.assertEqual(
            (
                dict(traffic.people_by_set),
                traffic.calls,
                traffic.remotely_evaluated_calls,
                traffic.people_assigned_outside,
            ),
            expected,
        )

    @parameterized.expand(
        [
            ("events", FlagEvaluationsMode.EVENTS, ({}, 0, 0)),
            ("flag_evaluations_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, ({1: 1}, 1, 1)),
        ]
    )
    def test_reads_the_exposure_copy_only_where_flag_calls_leave_events(
        self, _name: str, mode: FlagEvaluationsMode, expected: tuple[dict[int, int], int, int]
    ) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        now = timezone.now()
        experiment = _create_running_experiment(self.team, self.user, launched_at=now - timedelta(days=30))
        create_person(team=self.team, distinct_ids=["person-1"])
        self._call_flag(
            "person-1", "Matched condition set 1", FLAG_VERSION, now - timedelta(days=1), event="$experiment_exposure"
        )
        flush_persons_and_events()

        traffic = query_condition_set_traffic(experiment, window_start=now - timedelta(days=7), window_end=now)

        self.assertEqual((dict(traffic.people_by_set), traffic.calls, traffic.remotely_evaluated_calls), expected)

    def _call_flag(
        self,
        distinct_id: str,
        reason: str | None,
        version: int | None,
        at: datetime,
        *,
        event: str = "$feature_flag_called",
        locally_evaluated: bool = False,
    ) -> None:
        properties: dict[str, Any] = {
            "$feature_flag": FLAG_KEY,
            "$feature_flag_response": False if reason in _NO_VARIANT_REASONS else "test",
        }
        if locally_evaluated:
            properties["locally_evaluated"] = True
        if reason is not None:
            properties["$feature_flag_reason"] = reason
        if version is not None:
            properties["$feature_flag_version"] = version
        _create_event(team=self.team, event=event, distinct_id=distinct_id, properties=properties, timestamp=at)
