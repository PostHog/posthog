import json
import datetime as dt
from typing import Any
from uuid import UUID

from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import create_configuration, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    Grouping,
    GroupingMode,
    PlatformAlertConfigurationEdit,
    PlatformAlertOutcome,
    SourceKind,
)
from products.alerts_platform.backend.facade.grouping import bounded_grouping_key, is_hashed_grouping_key
from products.tracing.backend.alerts.check_query import CheckResult
from products.tracing.backend.alerts.evaluation import evaluate_traces_alert_batch
from products.tracing.backend.tests.test_keyset_pagination import _TraceSpansTestBase

# The check reads the five minutes before this, its due time.
DUE_AT = dt.datetime(2026, 6, 2, 9, 0, 0, tzinfo=dt.UTC)
_SERVER, _CLIENT = 2, 3
_BY_SERVICE = ("service_name",)


class TestTracesAlertEvaluation(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

    def setUp(self) -> None:
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS trace_spans")
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.enterContext(
            patch("products.tracing.backend.alerts.evaluation.fetch_traces_checkpoint", return_value=None)
        )
        self._rows: list[tuple[Any, ...]] = []

    def _spans(
        self,
        service: str,
        count: int,
        *,
        minutes_before_due: float = 2,
        duration_ms: float = 10.0,
        errors: int = 0,
        kind: int = _SERVER,
        name: str = "GET /",
    ) -> None:
        at = DUE_AT.replace(tzinfo=None) - dt.timedelta(minutes=minutes_before_due)
        for i in range(count):
            index = len(self._rows)
            self._rows.append(
                (
                    f"019e8800-0000-0000-0000-{index:012d}",
                    self.team.id,
                    f"trace-{index}",
                    f"span-{index}",
                    # A client span has a parent, so only its kind decides whether it is a request.
                    "cGFyZW50" if kind == _CLIENT else "",
                    name,
                    kind,
                    at,
                    at + dt.timedelta(milliseconds=duration_ms),
                    at,
                    2 if i < errors else 0,
                    service,
                    {},
                )
            )

    def _evaluate(
        self,
        condition: dict[str, Any],
        *,
        filters: dict[str, Any] | None = None,
        grouping: Grouping | None = None,
        evaluation_periods: int = 1,
        datapoints_to_alarm: int = 1,
        firing_keys: tuple[str, ...] = (),
    ) -> PlatformAlertOutcome:
        self._insert()
        configuration_id = self._configure(
            condition,
            filters=filters,
            grouping=grouping,
            evaluation_periods=evaluation_periods,
            datapoints_to_alarm=datapoints_to_alarm,
        )
        with team_scope(self.team.id):
            for key in firing_keys:
                platform_testing.start_firing(
                    configuration_id, team_id=self.team.id, at=DUE_AT - dt.timedelta(hours=1), grouping_key=key
                )
        (outcome,) = self._run()
        return outcome

    def _insert(self) -> None:
        if self._rows:
            sync_execute(
                "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, timestamp, "
                "end_time, observed_timestamp, status_code, service_name, resource_attributes) VALUES",
                self._rows,
            )

    def _configure(
        self,
        condition: dict[str, Any],
        *,
        filters: dict[str, Any] | None = None,
        grouping: Grouping | None = None,
        evaluation_periods: int = 1,
        datapoints_to_alarm: int = 1,
    ) -> UUID:
        with team_scope(self.team.id):
            configuration_id = create_configuration(
                team_id=self.team.id,
                source_kind=SourceKind.TRACES,
                edit=PlatformAlertConfigurationEdit(
                    name="Checkout",
                    enabled=True,
                    source_config={"filters": filters or {}, "condition": {"window_minutes": 5, **condition}},
                    grouping=grouping or Grouping(),
                    schedule_restriction=None,
                    evaluation_periods=evaluation_periods,
                    datapoints_to_alarm=datapoints_to_alarm,
                    cooldown_minutes=0,
                ),
                created_by_id=self.user.id,
            ).id
            platform_testing.set_due_at(configuration_id, DUE_AT)
        return configuration_id

    def _run(self) -> tuple[PlatformAlertOutcome, ...]:
        cutoff = DUE_AT + dt.timedelta(minutes=1)
        with team_scope(self.team.id):
            return evaluate_traces_alert_batch(self.team.id, slot_of(DUE_AT, cutoff), cutoff).outcomes

    def _fired(self, outcome: PlatformAlertOutcome) -> dict[str, float | None]:
        return {group.grouping_key: group.value for group in outcome.groups if group.kind == AlertEventKind.FIRING}

    def _service_key(self, service: str) -> str:
        return bounded_grouping_key(json.dumps({"service_name": service}, separators=(",", ":")))

    @parameterized.expand(
        [
            # Client spans are the service's own outbound calls, so counting them would double count.
            ("request_count", {"measure": "request_count", "threshold": 9}, 10.0),
            ("error_count", {"measure": "error_count", "threshold": 2}, 3.0),
            ("error_rate", {"measure": "error_rate", "threshold": 0.2}, 0.3),
            ("p95_latency_in_ms", {"measure": "latency", "percentile": 95, "threshold": 100}, 250.0),
        ]
    )
    def test_a_breach_over_entry_spans_fires_with_the_value_in_its_unit(
        self, _name: str, condition: dict[str, Any], value: float
    ) -> None:
        self._spans("checkout", 10, errors=3, duration_ms=250)
        self._spans("checkout", 50, errors=50, duration_ms=5000, kind=_CLIENT)

        outcome = self._evaluate({"threshold_operator": "above", **condition})

        assert self._fired(outcome) == {"": value}

    @parameterized.expand(
        [
            ("error_rate", {"measure": "error_rate", "threshold": 0.5}),
            ("latency", {"measure": "latency", "percentile": 99, "threshold": 100}),
        ]
    )
    def test_a_window_with_no_requests_reaches_no_breach(self, _name: str, condition: dict[str, Any]) -> None:
        self._spans("checkout", 10, minutes_before_due=30)

        outcome = self._evaluate({"threshold_operator": "below", **condition})

        assert self._fired(outcome) == {}
        assert outcome.failure is None

    def test_a_grouped_alert_fires_only_for_the_breaching_service(self) -> None:
        self._spans("checkout", 10, errors=5)
        self._spans("search", 10)

        outcome = self._evaluate(
            {"measure": "error_count", "threshold": 0, "threshold_operator": "above"},
            grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service_name",)),
        )

        assert {json.loads(key)["service_name"] for key in self._fired(outcome)} == {"checkout"}

    def test_an_n_of_m_alert_counts_each_cadence_stepped_window(self) -> None:
        # Three five-minute windows stepped back one minute each all hold spans 4.5 minutes old.
        self._spans("checkout", 10, minutes_before_due=4.5)

        outcome = self._evaluate(
            {"measure": "request_count", "threshold": 5, "threshold_operator": "above"},
            evaluation_periods=3,
            datapoints_to_alarm=3,
        )

        assert self._fired(outcome) == {"": 10.0}

    def test_a_query_that_fails_records_a_failed_check(self) -> None:
        with patch(
            "products.tracing.backend.alerts.evaluation.run_check_query", side_effect=RuntimeError("cluster gone")
        ):
            outcome = self._evaluate({"measure": "request_count", "threshold": 1, "threshold_operator": "above"})

        assert outcome.failure is not None

    def test_a_grouped_n_of_m_breach_outranks_groups_that_only_spiked_once(self) -> None:
        # 5.5 minutes old lands in the two older of three windows stepped back a minute each, and
        # 0.5 minutes old only in the newest, so each spike ranks above the steady breach on its newest value.
        self._spans("steady", 10, minutes_before_due=5.5)
        for service in ("spike-a", "spike-b", "spike-c"):
            self._spans(service, 1, minutes_before_due=0.5)

        outcome = self._evaluate(
            {"measure": "request_count", "threshold": 5, "threshold_operator": "above"},
            grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=_BY_SERVICE, max_instances=1),
            evaluation_periods=3,
            datapoints_to_alarm=2,
        )

        assert list(self._fired(outcome)) == [self._service_key("steady")]

    def test_a_breaching_group_past_the_cap_counts_as_overflow(self) -> None:
        self._spans("checkout", 10)
        self._spans("search", 10)

        outcome = self._evaluate(
            {"measure": "request_count", "threshold": 5, "threshold_operator": "above"},
            grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=_BY_SERVICE, max_instances=1),
        )

        assert (len(self._fired(outcome)), outcome.overflowed) == (1, 1)

    @parameterized.expand(
        [
            # Three breaching services fill the cut result, so the open one returns only when it ranks first.
            ("recovered_behind_a_cut", "checkout", 1),
            # A hashed key keeps no labels, so only a complete result shows the group went quiet.
            ("hashed_and_quiet", "s" * 300, 0),
        ]
    )
    def test_an_open_group_that_recovered_resolves(self, _name: str, service: str, requests: int) -> None:
        self._spans(service, requests)
        if requests:
            for other in ("search", "cart", "login"):
                self._spans(other, 10)
        key = self._service_key(service)
        assert is_hashed_grouping_key(key) == (requests == 0)

        outcome = self._evaluate(
            {"measure": "request_count", "threshold": 5, "threshold_operator": "above"},
            grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=_BY_SERVICE, max_instances=1),
            firing_keys=(key,),
        )

        assert {group.grouping_key: group.new_state for group in outcome.groups}.get(key) == "not_firing"

    @parameterized.expand(
        [
            # The batch's first query had the full time, so its timeout counts toward BROKEN.
            ("first_in_its_batch", 1, [True]),
            # A query an earlier one left short of time has no outcome, so its check stays due.
            ("after_another_query", 2, [False]),
        ]
    )
    def test_a_query_timeout_counts_only_with_the_full_time(
        self, _name: str, checks: int, expected_failed: list[bool]
    ) -> None:
        condition = {"measure": "request_count", "threshold": 1, "threshold_operator": "above"}
        for _ in range(checks):
            self._configure(condition)
        clock = [1000.0]
        calls: list[int] = []

        def query(*_args: Any, **_kwargs: Any) -> CheckResult:
            calls.append(1)
            if len(calls) < checks:
                clock[0] += 10
                return CheckResult(groups=(), query_duration_ms=1, truncated=False)
            raise ClickHouseQueryTimeOut()

        with (
            patch("products.tracing.backend.alerts.evaluation.time") as fake_time,
            patch("products.tracing.backend.alerts.evaluation.run_check_query", side_effect=query),
        ):
            fake_time.monotonic.side_effect = lambda: clock[0]
            outcomes = self._run()

        assert [outcome.failure is not None for outcome in outcomes] == expected_failed
