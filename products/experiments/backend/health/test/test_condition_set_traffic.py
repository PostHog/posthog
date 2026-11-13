import time
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import time_machine
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    flush_persons_and_events,
)
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import param, parameterized

from posthog.exceptions import ClickHouseClusterMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models.instance_setting import override_instance_config
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.test.persons import create_group_type_mapping, create_person

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
    until=datetime(2026, 10, 8, tzinfo=UTC),
    team_timezone="UTC",
    people_by_set={1: 30, 2: 970},
    calls=2000,
    remotely_evaluated_calls=2000,
    people_assigned_outside=0,
)
TOO_FEW_PEOPLE = ConditionSetTraffic(
    since=datetime(2026, 10, 1, tzinfo=UTC),
    until=datetime(2026, 10, 8, tzinfo=UTC),
    team_timezone="UTC",
    people_by_set={1: 3, 2: 50},
    calls=100,
    remotely_evaluated_calls=100,
    people_assigned_outside=0,
)
_NO_VARIANT_REASONS = frozenset({"Out of rollout bound", "No matching condition set"})
_FlagCallStore = Literal["events", "exposure_copies", "flag_evaluations"]
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


def _create_running_experiment(
    team: Team, user: User, *, launched_at: datetime, aggregation_group_type_index: int | None = None
) -> Experiment:
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
            "aggregation_group_type_index": aggregation_group_type_index,
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
                answer = replace(answer, since=saved_at, until=timezone.now())
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
            (f"{name}_on_{events_table}_events", events_table == "native", *case)
            for name, *case in [
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
            for events_table in ("legacy", "native")
        ]
    )
    def test_query_condition_set_traffic(
        self,
        _name: str,
        team_reads_native_events: bool,
        calls: list[tuple[str, str | None, int | None, float]],
        expected: tuple[dict[int, int], int, int, int],
        locally_evaluated: frozenset[str] = frozenset(),
    ) -> None:
        now = timezone.now()
        experiment = _create_running_experiment(self.team, self.user, launched_at=now - timedelta(days=30))
        people = {
            distinct_id: create_person(team=self.team, distinct_ids=[distinct_id]).uuid
            for distinct_id in dict.fromkeys(distinct_id for distinct_id, *_ in calls)
        }
        for distinct_id, reason, version, days_ago in calls:
            self._call_flag(
                self.team,
                distinct_id,
                reason,
                version,
                now - timedelta(days=days_ago),
                # The native JSON events table holds no flag calls, so they are only in flag_evaluations.
                store="flag_evaluations" if team_reads_native_events else "events",
                person_id=people[distinct_id],
                locally_evaluated=distinct_id in locally_evaluated,
            )
        flush_persons_and_events()

        traffic = self._scan(experiment, now, native_teams=[self.team] if team_reads_native_events else [])

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
            param(
                "beside_a_team_that_reads_native_events",
                FlagEvaluationsMode.EVENTS,
                stores={"events"},
                other_team_reads_native_events=True,
            ),
            param(
                "organization_reads_flag_evaluations",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                stores={"events", "flag_evaluations"},
            ),
            param(
                "organization_has_flag_calls_only_in_flag_evaluations",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                stores={"flag_evaluations", "exposure_copies"},
            ),
            param(
                "native_events_and_flag_calls_only_in_flag_evaluations",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                stores={"flag_evaluations", "exposure_copies"},
                team_reads_native_events=True,
            ),
            param(
                "group_flag",
                FlagEvaluationsMode.EVENTS,
                stores={"events"},
                group_key="org-a",
            ),
            param(
                "group_flag_on_native_events",
                FlagEvaluationsMode.EVENTS,
                stores={"flag_evaluations"},
                team_reads_native_events=True,
                group_key="org-a",
            ),
        ]
    )
    def test_counts_each_call_once_wherever_ingestion_writes_it(
        self,
        _name: str,
        mode: FlagEvaluationsMode,
        *,
        stores: set[_FlagCallStore],
        team_reads_native_events: bool = False,
        other_team_reads_native_events: bool = False,
        group_key: str | None = None,
    ) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        now = timezone.now()
        group_type_index = None if group_key is None else 0
        if group_type_index is not None:
            create_group_type_mapping(
                team=self.team,
                project_id=self.team.project_id,
                group_type="organization",
                group_type_index=group_type_index,
                created_at=now - timedelta(days=30),
            )
        experiment = _create_running_experiment(
            self.team, self.user, launched_at=now - timedelta(days=30), aggregation_group_type_index=group_type_index
        )
        for distinct_id, reason, days_ago in [
            ("person-1", "Matched condition set 1", 2),
            ("person-2", "Matched condition set 2", 1),
            ("person-3", "Out of rollout bound", 1),
        ]:
            person_id = create_person(team=self.team, distinct_ids=[distinct_id]).uuid
            for store in stores:
                self._call_flag(
                    self.team,
                    distinct_id,
                    reason,
                    FLAG_VERSION,
                    now - timedelta(days=days_ago),
                    store=store,
                    person_id=person_id,
                    group_key=group_key,
                )
        flush_persons_and_events()
        native_teams = [self.team] if team_reads_native_events else []
        if other_team_reads_native_events:
            native_teams.append(Team.objects.create(organization=self.organization, name="Reads native events"))

        traffic = self._scan(experiment, now, native_teams=native_teams)

        expected_people_by_set = {1: 1, 2: 1} if group_key is None else {2: 1}
        self.assertEqual(
            (dict(traffic.people_by_set), traffic.calls, traffic.remotely_evaluated_calls),
            (expected_people_by_set, 2, 2),
        )

    def _scan(self, experiment: Experiment, now: datetime, *, native_teams: list[Team]) -> ConditionSetTraffic:
        # As on Cloud, where every catalog holds posthog.flag_evaluations. The allowlist moves single projects to the
        # native JSON events table, and the instance-wide switch stays off, also in CI's run on the native table.
        with (
            self.is_cloud(True),
            self.settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False),
            override_instance_config(
                "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", ",".join(str(team.pk) for team in native_teams)
            ),
        ):
            return query_condition_set_traffic(experiment, window_start=now - timedelta(days=7), window_end=now)

    def _call_flag(
        self,
        team: Team,
        distinct_id: str,
        reason: str | None,
        version: int | None,
        at: datetime,
        *,
        store: _FlagCallStore = "events",
        person_id: UUID | None = None,
        locally_evaluated: bool = False,
        group_key: str | None = None,
    ) -> None:
        response: str | bool = False if reason in _NO_VARIANT_REASONS else "test"
        properties: dict[str, Any] = {}
        if locally_evaluated:
            properties["locally_evaluated"] = True
        if reason is not None:
            properties["$feature_flag_reason"] = reason
        if version is not None:
            properties["$feature_flag_version"] = version
        if group_key is not None:
            properties["$group_0"] = group_key
        if store == "flag_evaluations":
            _create_flag_evaluations(
                team.pk,
                FLAG_KEY,
                timestamp=at,
                distinct_id=distinct_id,
                person_id=person_id,
                response=response,
                properties=properties,
            )
            return
        _create_event(
            team=team,
            event="$experiment_exposure" if store == "exposure_copies" else "$feature_flag_called",
            distinct_id=distinct_id,
            properties={**properties, "$feature_flag": FLAG_KEY, "$feature_flag_response": response},
            timestamp=at,
        )
