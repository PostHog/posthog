from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import due_checks, record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    IncidentAction,
    PlatformAlertOutcome,
    PlatformConfigurationSnapshot,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import AlertState
from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.logs.backend.alert_check_query import BatchedBucketedResult, BucketedCount
from products.logs.backend.alert_signal_emitter import PlatformAlertSignal, notified_alerts_for_platform
from products.logs.backend.alert_source_cycle import BATCH_QUERY_BUDGET_SECONDS, MAX_QUERY_SECONDS, evaluate_logs_batch
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import backfill_platform_alert_configurations
from products.logs.backend.temporal.alert_evaluate import (
    EVALUATE_SCHEDULE_TO_CLOSE,
    EVALUATE_START_TO_CLOSE,
    EVALUATION_BUDGET,
    platform_signals,
)

_MODULE = "products.logs.backend.alert_source_cycle"
CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}
_LOGS_OWNED_FIELDS = ("state", "consecutive_failures", "next_check_at", "last_notified_at", "snooze_until")


class TestLogsAlertEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 16, 10, tzinfo=UTC)

    def _configuration(self, **overrides: Any) -> PlatformConfigurationSnapshot:
        defaults: dict[str, Any] = {
            "team_id": self.team.id,
            "name": "API errors",
            "source_kind": SourceKind.LOGS,
            "source_config": {"condition": CONDITION},
            "check_interval_minutes": 10,
            "next_check_at": self.cutoff - timedelta(minutes=1),
        }
        defaults.update(overrides)
        with team_scope(self.team.id):
            return platform_testing.create_configuration(**defaults)

    def _run(
        self,
        *configurations: PlatformConfigurationSnapshot,
        query_error: Exception | None = None,
        now: datetime | None = None,
        count: int = 500,
    ) -> tuple[SourceBatchEvaluation, MagicMock]:
        now = now or self.cutoff
        breaching = {str(c.id): [BucketedCount(timestamp=now, count=count)] for c in configurations}
        with (
            patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_MODULE}.BatchedAlertCheckQuery") as query,
        ):
            if query_error is not None:
                query.return_value.execute_rolling_checks.side_effect = query_error
            else:
                query.return_value.execute_rolling_checks.return_value = BatchedBucketedResult(
                    per_alert=breaching, query_duration_ms=1
                )
            slot = slot_of(configurations[0].next_check_at, now)
            return evaluate_logs_batch(self.team.id, slot, now), query

    def _add_incident_destination(self, configuration: PlatformConfigurationSnapshot) -> None:
        HogFunction.objects.create(
            team=self.team,
            type="internal_destination",
            name="PagerDuty",
            template_id="template-pagerduty",
            hog="return event",
            enabled=True,
            filters={
                "source": "internal-events",
                "events": [{"id": "$logs_alert_incident_closed", "type": "events"}],
                "properties": [
                    {"key": "alert_id", "value": str(configuration.id), "operator": "exact", "type": "event"}
                ],
            },
        )

    def _slot(self) -> str:
        return slot_of(self.cutoff - timedelta(minutes=1), self.cutoff)

    def _record(self, evaluation: SourceBatchEvaluation) -> None:
        """The write the platform's own activity runs after the evaluation returns.

        Deliberately outside `team_scope`: that activity has no ambient scope, and these models
        are fail-closed, so a write here through a bare manager raises.
        """
        record_outcomes(self.team.id, evaluation.outcomes, self.cutoff)

    @parameterized.expand(
        [
            ("without_a_paging_destination", False, "source", None),
            ("with_a_paging_destination", True, "source", None),
            ("owned_by_the_platform", False, "platform", None),
            ("copied_from_a_logs_alert", False, "source", UUID("01936a2e-0000-7000-8000-00000000abcd")),
        ]
    )
    def test_a_breaching_configuration_fires_and_records_its_own_state(
        self, _name: str, paged: bool, owner: str, legacy_id: UUID | None
    ) -> None:
        configuration = self._configuration(owner=owner, legacy_configuration_id=legacy_id)
        if paged:
            self._add_incident_destination(configuration)

        evaluation, _ = self._run(configuration)
        self._record(evaluation)

        assert [(o.kind, o.value) for o in evaluation.outcomes] == [(AlertEventKind.FIRING, 500.0)]
        assert [(d.sends_messages, d.incident_actions, d.owned_by_platform) for d in evaluation.deliveries] == [
            (True, {"": IncidentAction.TRIGGER} if paged else {}, owner == "platform")
        ]
        # The event a PagerDuty destination subscribes to, so the trigger reaches it.
        assert evaluation.deliveries[0].event_ids_by_incident_action["trigger"] == "$logs_alert_incident_opened"
        # Only an alert copied from a logs alert has a logs alert page to link to.
        source_alert_url = evaluation.deliveries[0].source_alert_url
        assert (source_alert_url.endswith(f"/logs/alerts/{legacy_id}") if source_alert_url else None) == (
            True if legacy_id else None
        )
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
            configuration = platform_testing.configuration(configuration.id)
        assert alert.state == AlertState.FIRING
        assert alert.last_notified_at is not None
        # The schedule advanced, so the next tick does not rediscover this configuration.
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_checks_that_can_share_a_query_carry_one_schedule_group(self) -> None:
        same_a = self._configuration(name="A")
        same_b = self._configuration(name="B")
        longer_window = self._configuration(name="C", source_config={"condition": {**CONDITION, "window_minutes": 60}})
        more_periods = self._configuration(name="D", evaluation_periods=3, datapoints_to_alarm=1)

        evaluation, _ = self._run(same_a, same_b, longer_window, more_periods)

        group = {o.configuration_id: o.schedule_group for o in evaluation.outcomes}
        assert group[same_a.id] == group[same_b.id]
        assert len({group[same_a.id], group[longer_window.id], group[more_periods.id]}) == 3

    @parameterized.expand([("below_a_high_bound", 1000, "below"), ("above_zero", 0, "above")])
    def test_a_backfilled_alert_evaluates_against_the_bound_it_was_copied_with(
        self, _name: str, threshold_count: int, threshold_operator: str
    ) -> None:
        LogsAlertConfiguration.objects.create(
            team=self.team,
            name="API errors",
            threshold_count=threshold_count,
            threshold_operator=threshold_operator,
            window_minutes=5,
            filters={"serviceNames": ["api"]},
            next_check_at=self.cutoff - timedelta(minutes=1),
        )
        backfill_platform_alert_configurations(team_id=self.team.id)
        with team_scope(self.team.id):
            (check,) = due_checks(self.team.id, SourceKind.LOGS.value, self._slot(), self.cutoff)
            copied = platform_testing.configuration(check.id)

        evaluation, _ = self._run(copied)

        assert [(o.kind, o.value) for o in evaluation.outcomes] == [(AlertEventKind.FIRING, 500.0)]

    def test_a_cohort_query_is_capped_below_the_batch_budget(self) -> None:
        _, query = self._run(self._configuration())

        # An uncapped query runs to the class default, which is above the whole batch's budget.
        capped = query.call_args.kwargs["max_execution_time"]
        assert 0 < capped <= MAX_QUERY_SECONDS

    def test_the_evaluation_writes_nothing_until_its_outcomes_are_recorded(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration)

        assert evaluation.deliveries
        with team_scope(self.team.id):
            configuration = platform_testing.configuration(configuration.id)
            assert platform_testing.alert_for(configuration.id) is None
        assert configuration.next_check_at == self.cutoff - timedelta(minutes=1)

    def test_a_delivery_the_batch_cannot_carry_leaves_its_alert_due(self) -> None:
        configurations = [self._configuration(), self._configuration()]

        with patch(f"{_MODULE}.MAX_DELIVERIES_PER_CYCLE", 1):
            evaluation, _ = self._run(*configurations)
        self._record(evaluation)

        # A firing alert does not fire again, so recording the second outcome would retire its
        # breach with no delivery to announce it.
        assert len(evaluation.deliveries) == 1
        assert evaluation.omitted == 1
        with team_scope(self.team.id):
            still_due = platform_testing.count_still_due([c.id for c in configurations], at=self.cutoff)
        assert still_due == 1

    def test_two_scheduled_checks_clamped_to_one_window_keep_distinct_keys(self) -> None:
        # `resolve_alert_date_to` clamps the window end to the ingestion checkpoint, so a
        # checkpoint that has not moved gives two consecutive checks the same window. Keyed on the
        # window alone they read as one evaluation, and a reader deduplicating on the key drops
        # the second.
        configuration = self._configuration()
        # Inside CHECKPOINT_MAX_STALENESS and behind both scheduled times, so both checks clamp
        # their window end to it.
        frozen_checkpoint = self.cutoff - timedelta(minutes=3)

        def run_at(next_check_at: datetime) -> str:
            with team_scope(self.team.id):
                platform_testing.set_due_at(configuration.id, next_check_at)
            with (
                patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=frozen_checkpoint),
                patch(f"{_MODULE}.BatchedAlertCheckQuery") as query,
            ):
                query.return_value.execute_rolling_checks.return_value = BatchedBucketedResult(
                    per_alert={str(configuration.id): [BucketedCount(timestamp=self.cutoff, count=500)]},
                    query_duration_ms=1,
                )
                slot = slot_of(next_check_at, self.cutoff)
                evaluation = evaluate_logs_batch(self.team.id, slot, self.cutoff)
            return evaluation.outcomes[0].evaluation_key

        first = run_at(self.cutoff - timedelta(minutes=2))
        second = run_at(self.cutoff - timedelta(minutes=1))

        assert first != second

    def test_a_check_inside_quiet_hours_runs_and_holds_its_announcement(self) -> None:
        configuration = self._configuration(
            schedule_restriction={"blocked_windows": [{"start": "09:00", "end": "12:00"}]}
        )
        self._add_incident_destination(configuration)

        evaluation, query = self._run(configuration)
        self._record(evaluation)

        query.assert_called_once()
        # Quiet hours hold the message, never the incident: the only delivery carries the trigger.
        assert [(d.sends_messages, d.incident_actions) for d in evaluation.deliveries] == [
            (False, {"": IncidentAction.TRIGGER})
        ]
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
            configuration = platform_testing.configuration(configuration.id)
        # An incident wholly inside the window must still leave a trace, and must not move the cooldown.
        assert alert.state == AlertState.FIRING
        assert alert.last_notified_at is None
        assert alert.firing_started_at == self.cutoff
        # Parked at the end of the window would leave the alert unevaluated until noon.
        assert configuration.next_check_at is not None
        assert self.cutoff < configuration.next_check_at < datetime(2026, 9, 16, 11, tzinfo=UTC)

        # The first check after the window announces the fire the mute held. Without the held
        # firing reaching it, a FIRING alert does not fire again on its own and stays silent.
        unmuted, _ = self._run(configuration, now=datetime(2026, 9, 16, 12, 30, tzinfo=UTC))

        assert [o.kind for o in unmuted.outcomes] == [AlertEventKind.FIRING]

    def test_a_resolve_cooldown_holds_still_closes_the_incident(self) -> None:
        configuration = self._configuration(cooldown_minutes=60)
        self._add_incident_destination(configuration)
        fired, _ = self._run(configuration)
        record_outcomes(self.team.id, fired.outcomes, self.cutoff)
        with team_scope(self.team.id):
            configuration = platform_testing.configuration(configuration.id)

        later = datetime(2026, 9, 16, 10, 10, tzinfo=UTC)
        cleared, _ = self._run(configuration, now=later, count=0)

        assert [o.kind for o in cleared.outcomes] == [AlertEventKind.CHECK]
        assert [(d.sends_messages, d.incident_actions) for d in cleared.deliveries] == [
            (False, {"": IncidentAction.RESOLVE})
        ]

    @parameterized.expand(
        [
            ("filter_group", {"condition": CONDITION, "filterGroup": {"type": "nonsense"}}),
            ("missing_condition", {}),
            ("null_condition", {"condition": None}),
            ("unknown_operator", {"condition": {**CONDITION, "threshold_operator": "equals"}}),
            ("non_numeric_window", {"condition": {**CONDITION, "window_minutes": "5"}}),
            ("zero_window", {"condition": {**CONDITION, "window_minutes": 0}}),
            ("null_filter_values", {"condition": CONDITION, "filterGroup": {"type": "AND", "values": None}}),
        ]
    )
    def test_a_broken_config_stops_being_discovered(self, _name: str, source_config: dict[str, Any]) -> None:
        configuration = self._configuration(source_config=source_config)
        healthy = self._configuration(name="Healthy")

        evaluation, query = self._run(configuration, healthy)
        self._record(evaluation)

        queried = {check.id for call in query.call_args_list for check in call.kwargs["alerts"]}
        assert queried == {healthy.id}
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
        assert alert.state == AlertState.BROKEN
        assert due_checks(self.team.id, SourceKind.LOGS.value, self._slot(), self.cutoff + timedelta(hours=1)) == ()

    @parameterized.expand(
        [
            ("a_transient_error_holds_the_counter", ValueError("cluster busy"), 4, "not_firing"),
            ("an_invalid_query_escalates", ExposedHogQLError("unknown field"), 5, "broken"),
        ]
    )
    def test_a_failed_query_advances_the_schedule_instead_of_leaving_the_check_due(
        self, _name: str, error: Exception, expected_failures: int, expected_state: str
    ) -> None:
        configuration = self._configuration(consecutive_failures=4)

        evaluation, _ = self._run(configuration, query_error=error)
        self._record(evaluation)

        assert [o.consecutive_failures for o in evaluation.outcomes] == [expected_failures]
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
            configuration = platform_testing.configuration(configuration.id)
        assert alert.state == expected_state
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_a_failure_the_batch_cannot_record_leaves_the_whole_batch_due(self) -> None:
        configuration = self._configuration(consecutive_failures=4)

        with patch(f"{_MODULE}._delivery", side_effect=RuntimeError("something after the query failed")):
            with pytest.raises(RuntimeError):
                self._run(configuration, query_error=ExposedHogQLError("unknown field"))

        with team_scope(self.team.id):
            configuration = platform_testing.configuration(configuration.id)
            assert platform_testing.alert_for(configuration.id) is None
        assert configuration.next_check_at == self.cutoff - timedelta(minutes=1)

    def test_the_logs_product_rows_are_never_written(self) -> None:
        legacy = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="API errors",
            threshold_count=10,
            threshold_operator="above",
            window_minutes=5,
            filters={},
            next_check_at=self.cutoff - timedelta(minutes=1),
        )
        before = LogsAlertConfiguration.objects.values(*_LOGS_OWNED_FIELDS).get(id=legacy.id)

        evaluation, _ = self._run(self._configuration(legacy_configuration_id=legacy.id))
        self._record(evaluation)

        # The logs fleet evaluates this same alert on its own queue. Writing its rows here would
        # transition an alert twice and notify a person twice for one breach.
        assert LogsAlertConfiguration.objects.values(*_LOGS_OWNED_FIELDS).get(id=legacy.id) == before
        assert not LogsAlertEvent.objects.filter(alert=legacy).exists()

    @parameterized.expand([("single_period", 1, 5), ("three_periods", 3, 25)])
    def test_the_scanned_range_covers_every_rolling_window(
        self, _name: str, evaluation_periods: int, expected_lookback_minutes: int
    ) -> None:
        configuration = self._configuration(evaluation_periods=evaluation_periods, check_interval_minutes=10)

        _, query = self._run(configuration)

        kwargs = query.call_args.kwargs
        assert kwargs["date_to"] - kwargs["date_from"] == timedelta(minutes=expected_lookback_minutes)

    def test_a_preview_and_its_recorded_outcome_name_the_same_evaluation(self) -> None:
        configuration = self._configuration(next_check_at=None)

        evaluation, _ = self._run(configuration)

        # A preview carries the recorded key unchanged, so a delivery can address the row the
        # check wrote. The slot is in the key because two checks of one alert can clamp to the
        # same window end, and a key without it makes them one evaluation to any reader.
        expected = f"slot:{self.cutoff.isoformat()}|window:{self.cutoff.isoformat()}"
        assert evaluation.outcomes[0].evaluation_key == expected
        assert [d.evaluation_key for d in evaluation.deliveries] == [expected]


class TestEvaluationTimeoutLadder(SimpleTestCase):
    """Constants only, so this takes no database."""

    def test_the_evaluation_timeout_ladder_holds(self) -> None:
        # Each bound here has been wrong once. The activity sat under the query, and two
        # activities declared eighty seconds inside a forty-second workflow. A timeout that
        # lands between deciding and recording loses a batch that decided to fire, and nothing
        # else in the tree notices.
        # ClickHouse ends a slow query, not the activity timing out with the query still running.
        assert EVALUATE_START_TO_CLOSE.total_seconds() > BATCH_QUERY_BUDGET_SECONDS > MAX_QUERY_SECONDS
        # Temporal bounds an attempt by whichever timeout expires first, so queue time must not be
        # what shortens the run below the query budget.
        assert EVALUATE_SCHEDULE_TO_CLOSE > EVALUATE_START_TO_CLOSE
        assert (EVALUATE_SCHEDULE_TO_CLOSE - EVALUATE_START_TO_CLOSE).total_seconds() >= BATCH_QUERY_BUDGET_SECONDS / 2
        # The platform's own timeout holds both activities and still leaves room for the deliveries.
        assert source_evaluation_timeout(SourceKind.LOGS) > EVALUATION_BUDGET


def _outcome(kind: AlertEventKind, *, notified: bool = True) -> PlatformAlertOutcome:
    return PlatformAlertOutcome(
        configuration_id=UUID("01936a2e-0000-7000-8000-000000000001"),
        evaluation_key="slot:x|window:y",
        kind=kind,
        new_state="firing",
        notified=notified,
        consecutive_failures=5 if kind == AlertEventKind.BROKEN else 0,
        value=500.0 if kind == AlertEventKind.FIRING else None,
    )


def _delivery_for(*, owned_by_platform: bool, sends_messages: bool = True) -> AlertDeliveryRequest:
    return AlertDeliveryRequest(
        source=SourceKind.LOGS,
        team_id=1,
        configuration_id="01936a2e-0000-7000-8000-000000000001",
        evaluation_key="slot:x|window:y",
        destination_alert_id="legacy-1",
        event_ids_by_kind={},
        owned_by_platform=owned_by_platform,
        sends_messages=sends_messages,
    )


class TestPlatformAlertSignals(SimpleTestCase):
    @parameterized.expand(
        [
            ("a_platform_owned_firing", AlertEventKind.FIRING, True, True, True, [("firing", 500, 0)]),
            ("a_platform_owned_auto_disable", AlertEventKind.BROKEN, False, True, True, [("broken", None, 5)]),
            ("a_firing_the_logs_stack_still_owns", AlertEventKind.FIRING, True, False, True, []),
            ("a_broken_config_held_back", AlertEventKind.BROKEN, False, True, False, []),
            ("a_resolve", AlertEventKind.RESOLVED, True, True, True, []),
        ]
    )
    def test_only_announced_firings_and_auto_disables_of_platform_owned_alerts_signal(
        self,
        _name: str,
        kind: AlertEventKind,
        notified: bool,
        owned: bool,
        sends_messages: bool,
        expected: list[tuple[Any, ...]],
    ) -> None:
        evaluation = SourceBatchEvaluation(
            outcomes=(_outcome(kind, notified=notified),),
            deliveries=(_delivery_for(owned_by_platform=owned, sends_messages=sends_messages),),
        )

        signals = platform_signals(evaluation)

        assert all(signal.alert_id == "legacy-1" for signal in signals)
        assert [(s.action, s.result_count, s.consecutive_failures) for s in signals] == expected


class TestPlatformAlertSignalFacts(APIBaseTest):
    def test_a_signal_carries_the_logs_alert_as_it_is_and_skips_a_deleted_one(self) -> None:
        alert = LogsAlertConfiguration.objects.create(
            team=self.team, name="API errors", filters={"serviceNames": ["api"]}, threshold_count=10, window_minutes=5
        )

        notified = notified_alerts_for_platform(
            self.team.id,
            [
                PlatformAlertSignal(
                    alert_id=str(alert.id),
                    action="firing",
                    result_count=500,
                    consecutive_failures=0,
                    evaluation_key="k-1",
                ),
                PlatformAlertSignal(
                    alert_id=str(uuid4()), action="firing", result_count=1, consecutive_failures=0, evaluation_key="k-1"
                ),
            ],
        )

        assert [(n.alert_id, n.alert_name, n.threshold_count, n.result_count, n.filters) for n in notified] == [
            (str(alert.id), "API errors", 10, 500, {"serviceNames": ["api"]})
        ]
        # A retried emission of the same announcement must not start a second signal.
        assert notified[0].idempotency_key == f"{alert.id}:firing:k-1"
