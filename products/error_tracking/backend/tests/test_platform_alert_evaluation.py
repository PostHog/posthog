import uuid
import datetime as dt
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import create_configuration, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    PlatformAlertConfigurationEdit,
    PlatformAlertOutcome,
    SourceKind,
)
from products.error_tracking.backend.models import ErrorTrackingIssueChange
from products.error_tracking.backend.platform_alerts.evaluation import evaluate_error_tracking_alert_batch
from products.error_tracking.backend.platform_alerts.source_config import ISSUE_GROUPING

DUE_AT = dt.datetime(2026, 11, 17, 9, 0, tzinfo=dt.UTC)
_ON_TIME = DUE_AT


class TestErrorTrackingAlertEvaluation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

    def _change(
        self,
        kind: str,
        *,
        at: dt.datetime,
        name: str = "TypeError: x is undefined",
        status: str = "active",
        data: dict[str, Any] | None = None,
        bulk: bool = False,
        event_uuid: uuid.UUID | None = None,
    ) -> str:
        issue_id = uuid.uuid4()
        change = ErrorTrackingIssueChange.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            issue_id=issue_id,
            kind=kind,
            data=data or {},
            snapshot={
                "status": status,
                "severity": None,
                "name": name,
                "assignee": None,
                "first_seen": "2026-11-01T00:00:00+00:00",
            },
            operation_id=uuid.uuid4(),
            bulk=bulk,
            actor_type="ingestion" if event_uuid else "user",
            actor_user_id=None if event_uuid else self.user.id,
            event_uuid=event_uuid,
            event_timestamp=at if event_uuid else None,
        )
        # `created_at` is set on insert, so the row's time is written after.
        ErrorTrackingIssueChange.objects.for_team(self.team.id).filter(id=change.id).update(created_at=at)
        return str(issue_id)

    def _fired(
        self, source_config: dict[str, Any], *, cutoff: dt.datetime = _ON_TIME, firing: tuple[str, ...] = ()
    ) -> set[str]:
        outcomes = self._outcomes(source_config, cutoff=cutoff, firing=firing)
        assert len(outcomes) == 1
        return self._firing_keys(outcomes[0])

    def _outcomes(
        self, source_config: dict[str, Any], *, cutoff: dt.datetime = _ON_TIME, firing: tuple[str, ...] = ()
    ) -> tuple[PlatformAlertOutcome, ...]:
        with team_scope(self.team.id):
            configuration_id = create_configuration(
                team_id=self.team.id,
                source_kind=SourceKind.ERROR_TRACKING,
                edit=PlatformAlertConfigurationEdit(
                    name="New issues",
                    enabled=True,
                    source_config=source_config,
                    grouping=ISSUE_GROUPING,
                    schedule_restriction=None,
                    evaluation_periods=1,
                    datapoints_to_alarm=1,
                    cooldown_minutes=0,
                ),
                created_by_id=self.user.id,
            ).id
            platform_testing.set_due_at(configuration_id, DUE_AT)
            for key in firing:
                announced = DUE_AT - dt.timedelta(minutes=1)
                platform_testing.start_firing(
                    configuration_id, team_id=self.team.id, at=announced, grouping_key=key, notified_at=announced
                )
            return evaluate_error_tracking_alert_batch(self.team.id, slot_of(DUE_AT, cutoff), cutoff).outcomes

    def _firing_keys(self, outcome: PlatformAlertOutcome) -> set[str]:
        return {group.grouping_key for group in outcome.groups if group.kind == AlertEventKind.FIRING}

    def test_each_matching_change_in_the_window_fires_its_issue(self) -> None:
        # The window ends a settle margin before the cutoff and starts one interval earlier.
        in_window = DUE_AT - dt.timedelta(seconds=90)
        new_issue = self._change("created", at=in_window)
        self._change("created", at=DUE_AT - dt.timedelta(minutes=5))
        self._change("created", at=DUE_AT - dt.timedelta(seconds=30))
        self._change("created", at=in_window, bulk=True)
        self._change("status_changed", at=in_window, data={"previous": "resolved"})

        fired = self._fired({"condition": {"triggers": ["issue_created"]}})

        assert fired == {new_issue}

    def test_a_late_check_reads_every_change_since_its_due_time(self) -> None:
        # A check that ran ten minutes late must not drop the changes of the ticks it missed.
        missed_tick = self._change("created", at=DUE_AT + dt.timedelta(minutes=5))

        fired = self._fired({"condition": {"triggers": ["issue_created"]}}, cutoff=DUE_AT + dt.timedelta(minutes=10))

        assert fired == {missed_tick}

    @parameterized.expand(
        [
            ("resolved_issue_comes_back", "status_changed", "active", {"previous": "resolved"}, True),
            ("issue_resolved", "status_changed", "resolved", {"previous": "active"}, False),
        ]
    )
    def test_a_reopen_fires_only_when_the_issue_becomes_active(
        self, _name: str, kind: str, status: str, data: dict[str, Any], fires: bool
    ) -> None:
        issue = self._change(kind, at=DUE_AT - dt.timedelta(seconds=90), status=status, data=data)

        fired = self._fired({"condition": {"triggers": ["issue_reopened"]}})

        assert fired == ({issue} if fires else set())

    @parameterized.expand(
        [
            ("issue_property_matches", {"key": "name", "value": "TypeError", "operator": "icontains"}, True),
            ("issue_property_excludes", {"key": "name", "value": "ValueError", "operator": "icontains"}, False),
            # The native producers send the display-cased status, so existing filters are written that way.
            ("status_as_displayed", {"key": "status", "value": ["Active"], "operator": "exact"}, True),
            # A manual change has no exception, so a filter on the exception fails closed.
            ("exception_property_without_exception", {"key": "$lib", "value": ["web"], "operator": "exact"}, False),
        ]
    )
    def test_filters_decide_which_changes_fire(self, _name: str, property_filter: dict[str, Any], fires: bool) -> None:
        issue = self._change("created", at=DUE_AT - dt.timedelta(seconds=90))

        fired = self._fired(
            {
                "condition": {"triggers": ["issue_created"]},
                "filters": {"properties": [{**property_filter, "type": "event"}]},
            }
        )

        assert fired == ({issue} if fires else set())

    def test_a_new_change_on_an_issue_still_firing_is_announced(self) -> None:
        # Created in the previous check, then assigned in this one: both are news.
        issue = self._change("assignee_changed", at=DUE_AT - dt.timedelta(seconds=90))
        ErrorTrackingIssueChange.objects.for_team(self.team.id).filter(issue_id=issue).update(
            snapshot={"status": "active", "name": "TypeError", "assignee": {"type": "user", "id": "1"}}
        )

        fired = self._fired({"condition": {"triggers": ["issue_assigned"]}}, firing=(issue,))

        assert fired == {issue}

    def test_a_read_that_fails_records_nothing_so_the_window_is_read_again(self) -> None:
        self._change("created", at=DUE_AT - dt.timedelta(seconds=90), event_uuid=uuid.uuid4())
        self.enterContext(
            patch(
                "products.error_tracking.backend.platform_alerts.evaluation.fetch_event_properties",
                side_effect=ConnectionError("valkey is down"),
            )
        )

        outcomes = self._outcomes(
            {
                "condition": {"triggers": ["issue_created"]},
                "filters": {"properties": [{"key": "$lib", "value": ["web"], "operator": "exact", "type": "event"}]},
            }
        )

        assert outcomes == ()

    def test_a_check_past_the_batch_budget_records_nothing(self) -> None:
        self._change("created", at=DUE_AT - dt.timedelta(seconds=90))
        self.enterContext(patch("products.error_tracking.backend.platform_alerts.evaluation.BATCH_BUDGET_SECONDS", 0))

        assert self._outcomes({"condition": {"triggers": ["issue_created"]}}) == ()
