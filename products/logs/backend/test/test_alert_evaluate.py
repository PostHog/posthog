import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError

from posthog import redis
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.temporal.alerts.admission import admit_evaluation_slots

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import (
    due_checks,
    list_configurations,
    record_outcomes,
    slot_of,
    snooze_group,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    CheckFailure,
    Grouping,
    GroupingMode,
    GroupOutcome,
    IncidentAction,
    PlatformAlertOutcome,
    PlatformConfigurationSnapshot,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import AlertState
from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.logs.backend.alert_check_query import (
    BatchedBucketedResult,
    BucketedCount,
    GroupCounts,
    GroupedRollingResult,
)
from products.logs.backend.alert_signal_emitter import PlatformAlertSignal, notified_alerts_for_platform
from products.logs.backend.alert_source_cycle import (
    BATCH_QUERY_BUDGET_SECONDS,
    BATCH_SLOT_LEASE_SECONDS,
    INFLIGHT_KEY,
    MAX_QUERY_SECONDS,
    evaluate_held_logs_batch,
    evaluate_logs_batch,
    grouping_key_of,
    take_logs_batch_slot,
)
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import backfill_platform_alert_configurations
from products.logs.backend.platform_source_config import filters_of
from products.logs.backend.temporal.alert_evaluate import (
    EVALUATE_SCHEDULE_TO_CLOSE,
    EVALUATE_START_TO_CLOSE,
    EVALUATION_BUDGET,
    TAKE_SLOT_START_TO_CLOSE,
    platform_signals,
)
from products.logs.backend.temporal.batch_slot import LogsBatchSlot

_MODULE = "products.logs.backend.alert_source_cycle"
CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}
_LOGS_OWNED_FIELDS = ("state", "consecutive_failures", "next_check_at", "last_notified_at", "snooze_until")
# Settings a check reads from the logs alert rather than from its platform copy.
_LEGACY_ALERT_FIELDS = ("evaluation_periods", "datapoints_to_alarm", "cooldown_minutes", "schedule_restriction")


_BY_SERVICE = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service_name",))


class TestLogsAlertEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 16, 10, tzinfo=UTC)
        # A backfilled copy delivers to the logs alert it came from, so its destinations name that id.
        self._legacy_ids: dict[UUID, UUID] = {}
        redis.get_client().delete(INFLIGHT_KEY)

    def _legacy_alert(self, source_config: dict[str, Any], **fields: Any) -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(
            team=self.team, name="API errors", filters=filters_of(source_config), **source_config["condition"], **fields
        )

    def _configuration(self, **overrides: Any) -> PlatformConfigurationSnapshot:
        """A platform copy, with the logs alert it was copied from, since every check reads that alert."""
        source_config = overrides.pop("source_config", {"condition": CONDITION})
        if "legacy_configuration_id" not in overrides:
            legacy_fields = {field: overrides[field] for field in _LEGACY_ALERT_FIELDS if field in overrides}
            overrides["legacy_configuration_id"] = self._legacy_alert(source_config, **legacy_fields).id
        defaults: dict[str, Any] = {
            "team_id": self.team.id,
            "name": "API errors",
            "source_kind": SourceKind.LOGS,
            "source_config": source_config,
            "check_interval_minutes": 10,
            "next_check_at": self.cutoff - timedelta(minutes=1),
        }
        defaults.update(overrides)
        with team_scope(self.team.id):
            configuration = platform_testing.create_configuration(**defaults)
        self._legacy_ids[configuration.id] = defaults["legacy_configuration_id"]
        return configuration

    def _run(
        self,
        *configurations: PlatformConfigurationSnapshot,
        query_error: Exception | None = None,
        now: datetime | None = None,
        count: int = 500,
        held: LogsBatchSlot | None = None,
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
            if held is not None:
                return evaluate_held_logs_batch(self.team.id, slot, now, held), query
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
                    {
                        "key": "alert_id",
                        "value": str(self._legacy_ids[configuration.id]),
                        "operator": "exact",
                        "type": "event",
                    }
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
            ("without_a_paging_destination", False, "source"),
            ("with_a_paging_destination", True, "source"),
            ("owned_by_the_platform", False, "platform"),
        ]
    )
    def test_a_breaching_configuration_fires_and_records_its_own_state(
        self, _name: str, paged: bool, owner: str
    ) -> None:
        configuration = self._configuration(owner=owner)
        if paged:
            self._add_incident_destination(configuration)

        evaluation, _ = self._run(configuration)
        self._record(evaluation)

        assert [(g.kind, g.value) for o in evaluation.outcomes for g in o.groups] == [(AlertEventKind.FIRING, 500.0)]
        assert [(d.sends_messages, d.incident_actions, d.owned_by_platform) for d in evaluation.deliveries] == [
            (True, {"": IncidentAction.TRIGGER} if paged else {}, owner == "platform")
        ]
        # The event a PagerDuty destination subscribes to, so the trigger reaches it.
        assert evaluation.deliveries[0].event_ids_by_incident_action["trigger"] == "$logs_alert_incident_opened"
        source_alert_url = evaluation.deliveries[0].source_alert_url
        assert source_alert_url is not None
        assert source_alert_url.endswith(f"/logs/alerts/{self._legacy_ids[configuration.id]}")
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

        evaluation, query = self._run(copied)

        assert [(g.kind, g.value) for o in evaluation.outcomes for g in o.groups] == [(AlertEventKind.FIRING, 500.0)]
        assert [alert.filters for alert in query.call_args.kwargs["alerts"]] == [{"serviceNames": ["api"]}]

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

    @parameterized.expand(
        [
            # A firing alert does not fire again, so recording the second outcome would retire its
            # breach with no delivery to announce it.
            ("over_the_delivery_cap", "MAX_DELIVERIES_PER_CYCLE", 1, 500, 1, 1),
            # A quiet check announces nothing and still costs bytes, so the budget counts it too.
            ("over_the_byte_budget", "MAX_BATCH_PAYLOAD_BYTES", 1, 0, 0, 2),
        ]
    )
    def test_a_check_the_batch_cannot_carry_leaves_its_alert_due(
        self, _name: str, bound: str, limit: int, count: int, delivered: int, omitted: int
    ) -> None:
        configurations = [self._configuration(), self._configuration()]

        with patch(f"{_MODULE}.{bound}", limit):
            evaluation, _ = self._run(*configurations, count=count)
        self._record(evaluation)

        assert (len(evaluation.deliveries), evaluation.omitted) == (delivered, omitted)
        with team_scope(self.team.id):
            still_due = platform_testing.count_still_due([c.id for c in configurations], at=self.cutoff)
        assert still_due == omitted

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

        assert [g.kind for o in unmuted.outcomes for g in o.groups] == [AlertEventKind.FIRING]

    def test_a_resolve_cooldown_holds_still_closes_the_incident(self) -> None:
        configuration = self._configuration(cooldown_minutes=60)
        self._add_incident_destination(configuration)
        fired, _ = self._run(configuration)
        record_outcomes(self.team.id, fired.outcomes, self.cutoff)
        with team_scope(self.team.id):
            configuration = platform_testing.configuration(configuration.id)

        later = datetime(2026, 9, 16, 10, 10, tzinfo=UTC)
        cleared, _ = self._run(configuration, now=later, count=0)

        assert [g.kind for o in cleared.outcomes for g in o.groups] == [AlertEventKind.CHECK]
        assert [(d.sends_messages, d.incident_actions) for d in cleared.deliveries] == [
            (False, {"": IncidentAction.RESOLVE})
        ]

    def _run_grouped(
        self, configuration: PlatformConfigurationSnapshot, counts: dict[str, int], *, now: datetime | None = None
    ) -> SourceBatchEvaluation:
        now = now or self.cutoff
        groups = [
            GroupCounts(labels={"service_name": service}, counts=[BucketedCount(timestamp=now, count=count)])
            for service, count in counts.items()
        ]
        with (
            patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_MODULE}.GroupedAlertCheckQuery") as query,
        ):
            # `counts` is in the order the query ranks groups, and the query keeps one row past its limit.
            query.return_value.execute_rolling_checks.side_effect = lambda *_args: GroupedRollingResult(
                groups=groups[: query.call_args.kwargs["limit"] + 1],
                period_starts=[now],
                query_duration_ms=1,
                truncated=len(groups) > query.call_args.kwargs["limit"],
            )
            return evaluate_logs_batch(self.team.id, slot_of(configuration.next_check_at, now), now)

    def test_an_open_group_with_a_hashed_key_resolves_only_when_the_query_was_not_cut(self) -> None:
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service_name",), max_instances=1)
        configuration = self._configuration(grouping=grouping.to_stored())
        long_name = "checkout-" * 40
        self._record(self._run_grouped(configuration, {long_name: 500}))

        def run_after(counts: dict[str, int]) -> dict[str, AlertEventKind]:
            with team_scope(self.team.id):
                platform_testing.set_due_at(configuration.id, self.cutoff - timedelta(minutes=1))
            (outcome,) = self._run_grouped(configuration, counts).outcomes
            return {group.labels.get("service_name", group.grouping_key[:7]): group.kind for group in outcome.groups}

        assert run_after({"api": 600, "web": 550, "cron": 520}) == {}
        assert run_after({"api": 600}) == {"sha256:": AlertEventKind.RESOLVED}

    def test_a_grouped_alert_overflows_at_its_cap_until_a_resolved_group_gives_up_its_slot(self) -> None:
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service_name",), max_instances=2)
        configuration = self._configuration(grouping=grouping.to_stored())

        first = self._run_grouped(configuration, {"api": 500, "worker": 400, "cron": 300, "web": 3})
        self._record(first)

        (outcome,) = first.outcomes
        (delivery,) = first.deliveries
        # The cap admits the two worst of the three breaching, and the third is reported although
        # a query cut at the cap would never have returned it.
        assert [(group.labels["service_name"], group.kind) for group in outcome.groups] == [
            ("api", AlertEventKind.FIRING),
            ("worker", AlertEventKind.FIRING),
        ]
        # The query cut `web` and anything after it, so more breaching groups may have been turned away.
        assert (outcome.overflow_is_lower_bound, delivery.overflowed, delivery.overflow_is_lower_bound) == (
            True,
            1,
            True,
        )

        with team_scope(self.team.id):
            platform_testing.set_due_at(configuration.id, self.cutoff - timedelta(minutes=1))
        second = self._run_grouped(configuration, {"api": 500})

        (outcome,) = second.outcomes
        assert {group.labels["service_name"]: group.kind for group in outcome.groups} == {
            "api": AlertEventKind.CHECK,
            "worker": AlertEventKind.RESOLVED,
        }
        self._record(second)

        def run_after(counts: dict[str, int]) -> tuple[dict[str, AlertEventKind], int, bool]:
            with team_scope(self.team.id):
                platform_testing.set_due_at(configuration.id, self.cutoff - timedelta(minutes=1))
            evaluation = self._run_grouped(configuration, counts)
            self._record(evaluation)
            (outcome,) = evaluation.outcomes
            return (
                {group.labels["service_name"]: group.kind for group in outcome.groups},
                outcome.overflowed,
                outcome.overflow_is_lower_bound,
            )

        # The resolved group is in this check's results, so it keeps its slot and the new breach overflows.
        assert run_after({"api": 500, "worker": 3, "cron": 300}) == (
            {"api": AlertEventKind.CHECK, "worker": AlertEventKind.CHECK},
            1,
            False,
        )
        assert run_after({"api": 500, "cron": 300}) == (
            {"api": AlertEventKind.CHECK, "cron": AlertEventKind.FIRING},
            0,
            False,
        )
        with team_scope(self.team.id):
            evicted = platform_testing.alert_for(
                configuration.id, grouping_key=grouping_key_of({"service_name": "worker"})
            )
        assert evicted is None

    def test_a_grouped_alert_switched_off_in_logs_keeps_its_open_groups(self) -> None:
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service_name",))
        configuration = self._configuration(grouping=grouping.to_stored())
        self._record(self._run_grouped(configuration, {"api": 500}))
        LogsAlertConfiguration.objects.filter(id=self._legacy_ids[configuration.id]).update(enabled=False)

        with team_scope(self.team.id):
            platform_testing.set_due_at(configuration.id, self.cutoff - timedelta(minutes=1))
        stopped = self._run_grouped(configuration, {})
        self._record(stopped)

        (outcome,) = stopped.outcomes
        with team_scope(self.team.id):
            (copy,) = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], limit=10, offset=0
            ).configurations
            open_group = platform_testing.alert_for(
                configuration.id, grouping_key=grouping_key_of({"service_name": "api"})
            )
            ungrouped = platform_testing.alert_for(configuration.id)
        assert (outcome.groups, outcome.disable, copy.enabled) == ((), True, False)
        assert open_group is not None and open_group.state == "firing"
        assert ungrouped is None

    def test_a_snoozed_group_holds_its_resolve_while_the_other_group_announces(self) -> None:
        configuration = self._configuration(owner="platform", grouping=_BY_SERVICE.to_stored())
        self._add_incident_destination(configuration)
        self._record(self._run_grouped(configuration, {"checkout": 500, "api": 500}))
        checkout, api = (grouping_key_of({"service_name": service}) for service in ("checkout", "api"))
        with time_machine.travel(self.cutoff, tick=False):
            snooze_group(
                team_id=self.team.id,
                source_kinds=[SourceKind.LOGS.value],
                configuration_id=configuration.id,
                grouping_key=checkout,
                snooze_until=self.cutoff + timedelta(hours=2),
            )
        with team_scope(self.team.id):
            platform_testing.set_due_at(configuration.id, self.cutoff - timedelta(minutes=1))

        cleared = self._run_grouped(configuration, {})

        (outcome,) = cleared.outcomes
        assert {g.grouping_key: (g.kind, g.muted_notification) for g in outcome.groups} == {
            checkout: (AlertEventKind.CHECK, "resolve"),
            api: (AlertEventKind.RESOLVED, ""),
        }
        # The snooze left the firing open, so the clear check closes the incident it opened.
        (delivery,) = cleared.deliveries
        assert delivery.incident_actions == {checkout: IncidentAction.RESOLVE, api: IncidentAction.RESOLVE}

    @parameterized.expand(
        [
            ("filter_group", {"condition": CONDITION, "filterGroup": {"type": "nonsense"}}),
            ("unknown_operator", {"condition": {**CONDITION, "threshold_operator": "equals"}}),
            ("zero_window", {"condition": {**CONDITION, "window_minutes": 0}}),
            ("null_filter_values", {"condition": CONDITION, "filterGroup": {"type": "AND", "values": None}}),
            ("grouped_by_an_attribute", {"condition": CONDITION}, ("http.route",)),
            ("grouped_below", {"condition": {**CONDITION, "threshold_operator": "below"}}, ("service_name",)),
        ]
    )
    def test_a_broken_config_stops_being_discovered(
        self, _name: str, source_config: dict[str, Any], grouping_keys: tuple[str, ...] = ()
    ) -> None:
        grouping = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=grouping_keys) if grouping_keys else Grouping()
        configuration = self._configuration(source_config=source_config, grouping=grouping.to_stored())
        healthy = self._configuration(name="Healthy")

        evaluation, query = self._run(configuration, healthy)
        self._record(evaluation)

        queried = {check.id for call in query.call_args_list for check in call.kwargs["alerts"]}
        assert queried == {healthy.id}
        with team_scope(self.team.id):
            assert platform_testing.configuration(configuration.id).check_status == AlertState.BROKEN
        assert due_checks(self.team.id, SourceKind.LOGS.value, self._slot(), self.cutoff + timedelta(hours=1)) == ()

    @parameterized.expand(
        [
            ("a_transient_error_holds_the_counter", ValueError("cluster busy"), 4, "ok"),
            ("an_invalid_query_escalates", ExposedHogQLError("unknown field"), 5, "broken"),
        ]
    )
    def test_a_failed_query_advances_the_schedule_instead_of_leaving_the_check_due(
        self, _name: str, error: Exception, expected_failures: int, expected_status: str
    ) -> None:
        configuration = self._configuration(consecutive_failures=4)

        evaluation, _ = self._run(configuration, query_error=error)
        self._record(evaluation)

        assert [o.consecutive_failures for o in evaluation.outcomes] == [expected_failures]
        with team_scope(self.team.id):
            # A failed check fails every group, so it writes the configuration and no instance.
            assert platform_testing.alert_for(configuration.id) is None
            configuration = platform_testing.configuration(configuration.id)
        assert configuration.check_status == expected_status
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    @parameterized.expand(
        [
            ("cohort_cut_short_by_an_earlier_query", Grouping(), True, 10, None),
            ("cohort_with_its_full_time_after_another", Grouping(), True, 0, 5),
            ("cohort_first_in_its_batch", Grouping(), False, 0, 5),
            ("grouped_cut_short_by_an_earlier_query", _BY_SERVICE, True, 10, None),
            ("grouped_with_its_full_time_after_another", _BY_SERVICE, True, 0, 5),
        ]
    )
    def test_a_query_out_of_time_counts_only_when_no_earlier_query_spent_its_time(
        self,
        _name: str,
        grouping: Grouping,
        after_another: bool,
        earlier_query_seconds: int,
        expected_failures: int | None,
    ) -> None:
        if after_another:
            self._configuration()
        slow = self._configuration(
            consecutive_failures=4,
            grouping=grouping.to_stored(),
            source_config={"condition": {**CONDITION, "window_minutes": 10}},
        )
        clock = [1000.0]
        cohort_calls: list[int] = []

        def cohort_query_run(*_args: Any, **_kwargs: Any) -> BatchedBucketedResult:
            # The first cohort is the earlier query when one runs; any later cohort is the slow one.
            cohort_calls.append(1)
            if after_another and grouping.mode == GroupingMode.SINGLE and len(cohort_calls) > 1:
                raise ClickHouseQueryTimeOut()
            if not after_another:
                raise ClickHouseQueryTimeOut()
            clock[0] += earlier_query_seconds
            return BatchedBucketedResult(per_alert={}, query_duration_ms=1)

        with (
            patch(f"{_MODULE}.time") as fake_time,
            patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_MODULE}.BatchedAlertCheckQuery") as cohort_query,
            patch(f"{_MODULE}.GroupedAlertCheckQuery") as grouped_query,
        ):
            fake_time.monotonic.side_effect = lambda: clock[0]
            cohort_query.return_value.execute_rolling_checks.side_effect = cohort_query_run
            grouped_query.return_value.execute_rolling_checks.side_effect = ClickHouseQueryTimeOut()
            evaluation = evaluate_logs_batch(self.team.id, self._slot(), self.cutoff)
        self._record(evaluation)

        failures = [o.consecutive_failures for o in evaluation.outcomes if o.configuration_id == slow.id]
        with team_scope(self.team.id):
            still_due = platform_testing.count_still_due([slow.id], at=self.cutoff)
        # A query cut short by an earlier one leaves its check due, so its slot comes back alone.
        assert (failures, still_due) == (([], 1) if expected_failures is None else ([expected_failures], 0))

    def test_a_failure_the_batch_cannot_record_leaves_the_whole_batch_due(self) -> None:
        configuration = self._configuration(consecutive_failures=4)

        with patch(f"{_MODULE}._delivery", side_effect=RuntimeError("something after the query failed")):
            with pytest.raises(RuntimeError):
                self._run(configuration, query_error=ExposedHogQLError("unknown field"))

        with team_scope(self.team.id):
            configuration = platform_testing.configuration(configuration.id)
            assert platform_testing.alert_for(configuration.id) is None
        assert configuration.next_check_at == self.cutoff - timedelta(minutes=1)

    @parameterized.expand(
        [
            ("edited_since_the_backfill", "edit", True, 1000),
            ("disabled_since_the_backfill", "disable", False, 10),
            ("deleted_since_the_backfill", "delete", False, 10),
        ]
    )
    def test_a_check_follows_the_logs_alert_as_it_is_now(
        self, _name: str, change: str, still_runs: bool, stored_threshold: int
    ) -> None:
        configuration = self._configuration()
        legacy = LogsAlertConfiguration.objects.get(id=self._legacy_ids[configuration.id])
        if change == "edit":
            # Copied as "above 10", which 500 logs breach. The logs alert now asks for over 1000.
            LogsAlertConfiguration.objects.filter(id=legacy.id).update(threshold_count=1000)
        elif change == "disable":
            LogsAlertConfiguration.objects.filter(id=legacy.id).update(enabled=False)
        else:
            legacy.delete()

        evaluation, query = self._run(configuration)
        self._record(evaluation)

        assert [g.kind for o in evaluation.outcomes for g in o.groups] == [AlertEventKind.CHECK]
        assert query.called is still_runs
        with team_scope(self.team.id):
            (copy,) = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], limit=10, offset=0
            ).configurations
        assert copy.enabled is still_runs
        # History and messages read the stored copy, so it has to state what the check evaluated.
        assert copy.source_config["condition"]["threshold_count"] == stored_threshold

    def test_a_copy_the_platform_owns_runs_as_stored_whatever_its_logs_row_says(self) -> None:
        configuration = self._configuration(owner="platform")
        # Stored as "above 10", which 500 logs breach. The logs row now says otherwise, and is off.
        LogsAlertConfiguration.objects.filter(id=self._legacy_ids[configuration.id]).update(
            threshold_count=1000, enabled=False
        )

        evaluation, query = self._run(configuration)

        assert [g.kind for o in evaluation.outcomes for g in o.groups] == [AlertEventKind.FIRING]
        assert query.called

    def test_a_copy_the_platform_owns_stops_when_its_logs_row_is_in_an_environment(self) -> None:
        configuration = self._configuration(owner="platform")
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        # The environment's logs live under its own team, which the project's query would not read.
        LogsAlertConfiguration.objects.filter(id=self._legacy_ids[configuration.id]).update(team=environment)

        evaluation, query = self._run(configuration)
        self._record(evaluation)

        assert query.called is False
        with team_scope(self.team.id):
            (copy,) = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], limit=10, offset=0
            ).configurations
        assert copy.enabled is False

    def test_a_redispatched_batch_does_not_share_the_slot_its_earlier_run_still_holds(self) -> None:
        configuration = self._configuration()
        # The earlier execution of this same batch, whose query outlived its activity.
        admit_evaluation_slots(
            [f"{self.team.id}:{self._slot()}"], limit=1, expires_at=time.time() + 60, key=INFLIGHT_KEY
        )

        with override_settings(ALERTS_PLATFORM_LOGS_MAX_INFLIGHT_BATCHES=1):
            deferred, query = self._run(configuration)

        assert (deferred.outcomes, query.called) == ((), False)

    def test_a_batch_waits_for_room_in_the_fleet_pool_and_frees_its_slot_when_done(self) -> None:
        configuration = self._configuration()
        admit_evaluation_slots(["another-team:slot"], limit=1, expires_at=time.time() + 60, key=INFLIGHT_KEY)

        with override_settings(ALERTS_PLATFORM_LOGS_MAX_INFLIGHT_BATCHES=1):
            deferred, query = self._run(configuration)
            assert (deferred.outcomes, deferred.omitted, query.called) == ((), 1, False)

            redis.get_client().delete(INFLIGHT_KEY)
            first, _ = self._run(configuration)
            # The first batch gave its slot back, or a pool of one would turn this one away.
            second, _ = self._run(configuration)

        assert [len(first.outcomes), len(second.outcomes)] == [1, 1]

    def test_a_slot_taken_ahead_of_the_evaluation_bounds_the_pool_and_is_freed_by_it(self) -> None:
        configuration = self._configuration()
        slot = self._slot()

        with override_settings(ALERTS_PLATFORM_LOGS_MAX_INFLIGHT_BATCHES=1):
            taken = take_logs_batch_slot(self.team.id, slot, self.cutoff, member="first", first=True, final=False)
            turned_away = take_logs_batch_slot(
                self.team.id, slot, self.cutoff, member="second", first=True, final=False
            )
            # A retried try names the same member, so it finds its slot instead of taking another.
            retried = take_logs_batch_slot(self.team.id, slot, self.cutoff, member="first", first=True, final=False)
            assert taken.slot is not None and retried.slot is not None
            assert (turned_away.due, turned_away.slot) == (True, None)

            # The retry rewrote the expiry, so the first take's expiry is stale, as when a timed-out
            # take attempt lands after its retry returned.
            evaluation, _ = self._run(configuration, held=taken.slot)
            after = take_logs_batch_slot(self.team.id, slot, self.cutoff, member="second", first=True, final=False)
            # "first" no longer holds a slot and "second" fills the pool.
            lapsed, lapsed_query = self._run(configuration, held=taken.slot)

        assert len(evaluation.outcomes) == 1
        # The evaluation gave the slot back, or a pool of one would still turn the second batch away.
        assert after.slot is not None
        assert lapsed.outcomes == () and not lapsed_query.called

    def test_a_logs_alert_with_unreadable_filters_breaks_alone(self) -> None:
        unreadable, healthy = self._configuration(), self._configuration()
        LogsAlertConfiguration.objects.filter(id=self._legacy_ids[unreadable.id]).update(filters=[])

        evaluation, _ = self._run(unreadable, healthy)

        states = {o.configuration_id: (o.failure or o.groups[0]).new_state for o in evaluation.outcomes}
        assert states == {unreadable.id: "broken", healthy.id: "firing"}

    def test_a_check_whose_copy_cannot_be_updated_evaluates_the_stored_copy(self) -> None:
        configuration = self._configuration()
        # Copied as "above 10", which 500 logs breach. The logs alert now asks for over 1000.
        LogsAlertConfiguration.objects.filter(id=self._legacy_ids[configuration.id]).update(threshold_count=1000)

        with patch(f"{_MODULE}.refresh_settings", side_effect=RuntimeError("database blip")):
            evaluation, _ = self._run(configuration)

        assert [g.new_state for o in evaluation.outcomes for g in o.groups] == ["firing"]

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
        # See `BATCH_SLOT_LEASE_SECONDS`.
        assert BATCH_SLOT_LEASE_SECONDS > (TAKE_SLOT_START_TO_CLOSE + EVALUATE_SCHEDULE_TO_CLOSE).total_seconds()


def _outcome(kind: AlertEventKind, *, notified: bool = True) -> PlatformAlertOutcome:
    # A broken check is a failure, which the platform reports on the outcome with no groups.
    if kind == AlertEventKind.BROKEN:
        return PlatformAlertOutcome(
            configuration_id=UUID("01936a2e-0000-7000-8000-000000000001"),
            evaluation_key="slot:x|window:y",
            consecutive_failures=5,
            failure=CheckFailure(kind=kind, new_state="broken", notified=notified),
        )
    return PlatformAlertOutcome(
        configuration_id=UUID("01936a2e-0000-7000-8000-000000000001"),
        evaluation_key="slot:x|window:y",
        consecutive_failures=0,
        groups=(
            GroupOutcome(
                grouping_key="",
                kind=kind,
                new_state="firing",
                notified=notified,
                value=500.0 if kind == AlertEventKind.FIRING else None,
            ),
        ),
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

    def test_each_firing_group_of_one_evaluation_signals_under_its_own_key(self) -> None:
        groups = tuple(
            GroupOutcome(
                grouping_key=grouping_key_of({"service_name": service}),
                kind=AlertEventKind.FIRING,
                new_state="firing",
                notified=True,
                value=500.0,
                labels={"service_name": service},
            )
            for service in ("api", "web")
        )
        outcome = replace(_outcome(AlertEventKind.FIRING), groups=groups)
        evaluation = SourceBatchEvaluation(outcomes=(outcome,), deliveries=(_delivery_for(owned_by_platform=True),))

        signals = platform_signals(evaluation)

        assert [s.labels for s in signals] == [{"service_name": "api"}, {"service_name": "web"}]
        assert len({s.idempotency_key for s in signals}) == 2


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
                PlatformAlertSignal(
                    alert_id=str(alert.id),
                    action="firing",
                    result_count=700,
                    consecutive_failures=0,
                    evaluation_key="k-1",
                    grouping_key='{"service_name":"web"}',
                    labels={"service_name": "web"},
                ),
            ],
        )

        assert [(n.alert_id, n.alert_name, n.threshold_count, n.result_count, n.filters) for n in notified] == [
            (str(alert.id), "API errors", 10, 500, {"serviceNames": ["api"]}),
            (str(alert.id), "API errors", 10, 700, {"serviceNames": ["api"]}),
        ]
        # A retried emission of the same announcement must not start a second signal, and a second
        # group of the same evaluation is not a retry.
        assert [n.idempotency_key for n in notified] == [
            f"{alert.id}:firing:k-1",
            f'{alert.id}:firing:k-1:{{"service_name":"web"}}',
        ]
        assert notified[1].group_labels == {"service_name": "web"}
