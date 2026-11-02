from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.alerts.backend.facade.contracts import HogFunctionPathReason
from products.alerts.backend.facade.destinations import build_alert_destination_config
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration, list_configurations, upsert_configuration
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    DeliveryPath,
    DestinationType,
    SourceKind,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision
from products.logs.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    LOGS_ALERT_EVENT_IDS,
    LOGS_ALERT_SLACK_CONTEXT_ELEMENTS,
    EventKind,
)
from products.logs.backend.delivery_path_report import team_delivery_paths
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import platform_upsert_of
from products.logs.backend.platform_cutover import CutoverSkip, RollbackSkip, cut_over_team, roll_back_team

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
State = LogsAlertConfiguration.State
LEGACY_BODY_FLAG = "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled"
STOCK_HOG = "return event"
DESTINATION_DATA: dict[DestinationType, dict[str, Any]] = {
    DestinationType.SLACK: {"slack_workspace_id": 1, "slack_channel_id": "C-1"},
    DestinationType.WEBHOOK: {"webhook_url": "https://hooks.example.com/hook"},
    DestinationType.TEAMS: {"webhook_url": "https://example.webhook.office.com/webhookb2/a/IncomingWebhook/b/c"},
    DestinationType.PAGERDUTY: {"pagerduty_routing_key": "a" * 32},
}


def stock_destination(kind: EventKind, destination_type: DestinationType) -> tuple[str, dict[str, Any]]:
    payload = build_alert_destination_config(
        spec=EVENT_KIND_CONFIG[kind],
        alert_id="alert-1",
        alert_name="Checkout errors",
        data=cast(AlertDestinationData, {"type": destination_type, **DESTINATION_DATA[destination_type]}),
        slack_context_elements=LOGS_ALERT_SLACK_CONTEXT_ELEMENTS,
    ).payload
    return payload["template_id"], payload["inputs"]


_, WEBHOOK_INPUTS = stock_destination("firing", DestinationType.WEBHOOK)
_, SLACK_INPUTS = stock_destination("firing", DestinationType.SLACK)


class TestPlatformCutover(APIBaseTest):
    def _alert(self, **overrides: Any) -> LogsAlertConfiguration:
        fields: dict[str, Any] = {
            "team": self.team,
            "name": "Errors",
            "filters": {"severityLevels": ["error"]},
            "next_check_at": NOW + timedelta(minutes=3),
            "last_notified_at": NOW - timedelta(days=1),
            **overrides,
        }
        return LogsAlertConfiguration.objects.create(**fields)

    @parameterized.expand(
        [
            ("quiet", {}, "not_firing"),
            ("firing", {"state": State.FIRING}, "firing"),
            ("pending_resolve", {"state": State.PENDING_RESOLVE}, "firing"),
            (
                "snoozed_keeps_checking_muted",
                {"state": State.SNOOZED, "snooze_until": NOW + timedelta(hours=1)},
                "not_firing",
            ),
            ("broken", {"state": State.BROKEN, "consecutive_failures": 5}, "broken"),
            ("broken_never_scheduled", {"state": State.BROKEN, "next_check_at": None}, "broken"),
            ("disabled", {"enabled": False, "next_check_at": None}, "not_firing"),
            ("broken_past_due", {"state": State.BROKEN, "next_check_at": NOW - timedelta(hours=1)}, "broken"),
            (
                "snoozed_past_due",
                {"state": State.SNOOZED, "snooze_until": NOW + timedelta(hours=1), "next_check_at": NOW},
                "not_firing",
            ),
        ]
    )
    def test_an_alert_moves_with_its_state_and_schedule(
        self, _name: str, overrides: dict[str, Any], platform_state: str
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at) == ("platform", NOW)
        with team_scope(self.team.id):
            copy = platform_testing.copy_of(alert.id)
            instance = platform_testing.alert_for(copy.id)
        assert (copy.owner, copy.consecutive_failures, copy.next_check_at) == (
            "platform",
            alert.consecutive_failures,
            max(alert.next_check_at or NOW, NOW + timedelta(minutes=1)),
        )
        assert instance is not None
        assert (instance.state, instance.firing_started_at, instance.last_notified_at, instance.snooze_until) == (
            platform_state,
            None,
            alert.last_notified_at,
            alert.snooze_until,
        )

    @parameterized.expand(
        [
            ("check_due", {"next_check_at": NOW}, CutoverSkip.CHECK_DUE),
            ("never_scheduled", {"next_check_at": None}, CutoverSkip.CHECK_DUE),
        ]
    )
    def test_an_alert_that_cannot_move_now_stays_with_logs(
        self, _name: str, overrides: dict[str, Any], reason: CutoverSkip
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == "source"

    def test_an_alert_in_an_environment_stays_with_logs(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        alert = self._alert(team=environment)

        (result,) = cut_over_team(environment.id, now=NOW)

        assert result.skipped == CutoverSkip.ENVIRONMENT
        alert.refresh_from_db()
        assert alert.owner == "source"

    @parameterized.expand([("quiet", State.NOT_FIRING), ("firing", State.FIRING)])
    def test_a_refused_cutover_leaves_the_firing_platform_copy_as_it_was(self, _name: str, state: str) -> None:
        alert = self._alert(state=state)
        upsert_configuration(platform_upsert_of(alert))
        with team_scope(self.team.id):
            copy = platform_testing.copy_of(alert.id)
            platform_testing.start_firing(
                copy.id, team_id=self.team.id, at=NOW - timedelta(hours=1), sent_natively=True
            )
        LogsAlertConfiguration.objects.filter(id=alert.id).update(enabled=False, next_check_at=None)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == CutoverSkip.PLATFORM_FIRING
        view = get_configuration(team_id=self.team.id, source_kinds=[SourceKind.LOGS], configuration_id=copy.id)
        assert view is not None and view.enabled
        with team_scope(self.team.id):
            assert platform_testing.copy_of(alert.id).owner == "source"

    def test_a_dry_run_decides_as_a_real_run_and_changes_nothing(self) -> None:
        alert = self._alert()

        # Kafka is not transactional, so an event produced inside the dry run would outlive its rollback.
        with patch("products.cdp.backend.internal_events.produce_internal_event") as produced:
            (dry,) = cut_over_team(self.team.id, now=NOW, dry_run=True)

        produced.assert_not_called()
        assert dry.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at) == ("source", None)
        copies = list_configurations(team_id=self.team.id, source_kinds=[SourceKind.LOGS], limit=10, offset=0)
        assert copies.configurations == ()
        (real,) = cut_over_team(self.team.id, now=NOW)
        assert real.skipped == dry.skipped

    def test_a_second_run_leaves_a_moved_alert_alone(self) -> None:
        self._alert()
        cut_over_team(self.team.id, now=NOW)

        (result,) = cut_over_team(self.team.id, now=NOW + timedelta(minutes=1))

        assert result.skipped == CutoverSkip.ALREADY_MOVED

    def _moved(self, **overrides: Any) -> LogsAlertConfiguration:
        alert = self._alert(**overrides)
        cut_over_team(self.team.id, now=NOW)
        alert.refresh_from_db()
        return alert

    def test_rolling_back_after_the_shadow_carries_the_platform_state_back(self) -> None:
        alert = self._moved(state=State.BROKEN, consecutive_failures=5)
        later = NOW + timedelta(days=8)
        with team_scope(self.team.id):
            platform_testing.set_due_at(platform_testing.copy_of(alert.id).id, later + timedelta(minutes=2))

        (result,) = roll_back_team(self.team.id, now=later)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at, alert.state, alert.consecutive_failures, alert.next_check_at) == (
            "source",
            later,
            State.BROKEN,
            5,
            later + timedelta(minutes=2),
        )
        assert list(alert.events.values_list("kind", "state_before", "state_after")) == [
            (LogsAlertEvent.Kind.HANDBACK, State.BROKEN, State.BROKEN)
        ]
        with team_scope(self.team.id):
            assert platform_testing.copy_of(alert.id).owner == "source"

    def test_rolling_back_keeps_an_active_logs_snooze(self) -> None:
        alert = self._moved()
        LogsAlertConfiguration.objects.filter(id=alert.id).update(
            state=State.SNOOZED, snooze_until=NOW + timedelta(days=30)
        )
        later = NOW + timedelta(days=8)
        with team_scope(self.team.id):
            platform_testing.set_due_at(platform_testing.copy_of(alert.id).id, later + timedelta(minutes=2))

        (result,) = roll_back_team(self.team.id, now=later)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.state) == ("source", State.SNOOZED)

    @parameterized.expand(
        [
            ("never_moved", False, NOW + timedelta(days=8), RollbackSkip.NOT_MOVED),
            ("logs_check_due_during_shadow", True, NOW + timedelta(minutes=10), RollbackSkip.LOGS_CHECK_DUE),
        ]
    )
    def test_an_alert_that_cannot_move_back_now_stays(
        self, _name: str, moved: bool, at: datetime, reason: RollbackSkip
    ) -> None:
        alert = self._moved() if moved else self._alert()

        (result,) = roll_back_team(self.team.id, now=at)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == ("platform" if moved else "source")

    def _destination(
        self, alert_id: UUID | None, template_id: str, inputs: dict[str, Any], edit: dict[str, Any] | None = None
    ) -> HogFunction:
        function = HogFunction.objects.create(
            team=self.team,
            name="Alert destination",
            type="internal_destination",
            template_id=template_id,
            enabled=True,
            inputs=inputs,
            inputs_schema=[{"key": key, "type": "string", "secret": False} for key in inputs],
            hog=STOCK_HOG,
            filters={
                "source": "internal-events",
                "events": [{"id": LOGS_ALERT_EVENT_IDS[0], "type": "events"}],
                "properties": [{"key": "alert_id", "value": str(alert_id), "operator": "exact", "type": "event"}]
                if alert_id
                else [],
            },
        )
        if edit:
            HogFunctionRevision.objects.for_team(self.team.id).create(
                team=self.team,
                hog_function=function,
                version=1,
                content={
                    "hog": function.hog,
                    "inputs_schema": function.inputs_schema,
                    "inputs": function.inputs,
                    "filters": function.filters,
                    "mappings": function.mappings,
                    "masking": function.masking,
                },
            )
            HogFunction.objects.filter(pk=function.pk).update(version=2, **edit)
        return function

    @parameterized.expand(
        [
            (
                "rewritten_webhook_body",
                "template-webhook",
                WEBHOOK_INPUTS,
                {"inputs": {**WEBHOOK_INPUTS, "body": {"value": {"text": "relay"}}}},
                True,
                HogFunctionPathReason.CUSTOMIZED,
            ),
            (
                "edited_code",
                "template-webhook",
                WEBHOOK_INPUTS,
                {"hog": "fetch('https://relay.example.com')"},
                True,
                HogFunctionPathReason.CUSTOMIZED,
            ),
            (
                "stock_webhook_without_legacy_body",
                "template-webhook",
                WEBHOOK_INPUTS,
                {},
                False,
                HogFunctionPathReason.NEW_WEBHOOK_BODY,
            ),
            (
                "stock_webhook_with_unreadable_flag",
                "template-webhook",
                WEBHOOK_INPUTS,
                {},
                None,
                HogFunctionPathReason.WEBHOOK_BODY_UNKNOWN,
            ),
            (
                "header_native_delivery_drops",
                "template-webhook",
                WEBHOOK_INPUTS,
                {"inputs": {**WEBHOOK_INPUTS, "headers": {"value": {"Host": "internal.example.com"}}}},
                True,
                HogFunctionPathReason.CUSTOMIZED,
            ),
            (
                "body_written_before_the_first_save",
                "template-webhook",
                {**WEBHOOK_INPUTS, "body": {"value": {"embeds": [{"title": "{event.properties.alert_name}"}]}}},
                {},
                True,
                HogFunctionPathReason.CUSTOMIZED,
            ),
            (
                "no_body",
                "template-webhook",
                {key: value for key, value in WEBHOOK_INPUTS.items() if key != "body"},
                {},
                True,
                HogFunctionPathReason.CUSTOMIZED,
            ),
            (
                "secret_header",
                "template-webhook",
                WEBHOOK_INPUTS,
                {"encrypted_inputs": {"secret_headers": {"value": {"Authorization": "Bearer not-a-real-token"}}}},
                True,
                HogFunctionPathReason.CUSTOMIZED,
            ),
        ]
    )
    def test_a_destination_native_delivery_cannot_send_moves_on_the_hog_function_path(
        self,
        _name: str,
        template_id: str,
        inputs: dict[str, Any],
        edit: dict[str, Any],
        keeps_legacy_body: bool | None,
        reason: HogFunctionPathReason,
    ) -> None:
        held = self._alert()
        quiet = self._alert(name="Warnings")
        self._destination(held.id, template_id, inputs, edit)

        with patch(LEGACY_BODY_FLAG, return_value=keeps_legacy_body):
            paths = team_delivery_paths(self.team.id)
            results = cut_over_team(self.team.id, now=NOW)

        assert [(alert.alert_id, alert.choice.path, alert.choice.reason) for alert in paths.alerts] == [
            (held.id, DeliveryPath.HOG_FUNCTION, reason),
            (quiet.id, DeliveryPath.NATIVE, None),
        ]
        assert [result.skipped for result in results] == [None, None]
        assert set(
            LogsAlertConfiguration.objects.filter(id__in=[held.id, quiet.id]).values_list("owner", flat=True)
        ) == {"platform"}

    @parameterized.expand([("enabled", True), ("disabled", False)])
    def test_an_unbound_destination_puts_every_alert_on_the_hog_function_path(self, _name: str, enabled: bool) -> None:
        alert = self._alert()
        function = self._destination(None, "template-slack", SLACK_INPUTS, {"enabled": enabled})

        paths = team_delivery_paths(self.team.id)
        (result,) = cut_over_team(self.team.id, now=NOW)

        assert paths.unbound_functions == (function.id,)
        assert [(a.alert_id, a.choice.path, a.choice.reason) for a in paths.alerts] == [
            (alert.id, DeliveryPath.HOG_FUNCTION, HogFunctionPathReason.UNBOUND)
        ]
        assert result.skipped is None

    @parameterized.expand(
        [
            ("stock_slack", "template-slack", SLACK_INPUTS),
            ("stock_webhook_with_legacy_body", "template-webhook", WEBHOOK_INPUTS),
        ]
    )
    def test_a_team_moves_when_every_destination_is_ready(
        self, _name: str, template_id: str, inputs: dict[str, Any]
    ) -> None:
        alert = self._alert()
        self._destination(alert.id, template_id, inputs)

        with patch(LEGACY_BODY_FLAG, return_value=True):
            paths = team_delivery_paths(self.team.id)
            (result,) = cut_over_team(self.team.id, now=NOW)

        assert [(a.choice.path, a.choice.reason) for a in paths.alerts] == [(DeliveryPath.NATIVE, None)]
        assert result.skipped is None
        alert.refresh_from_db()
        assert alert.owner == "platform"
