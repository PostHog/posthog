import uuid
import datetime as dt
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import create_configuration, record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    PlatformAlertConfigurationEdit,
    PlatformAlertOutcome,
    SourceKind,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueChange,
    ErrorTrackingIssueFingerprintV2,
)
from products.error_tracking.backend.platform_alerts.evaluation import evaluate_error_tracking_alert_batch
from products.error_tracking.backend.platform_alerts.source_config import ISSUE_GROUPING
from products.error_tracking.backend.temporal.lifecycle.event_properties import IssueCreatedEventNotFoundError

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
        issue_id: uuid.UUID | None = None,
        assignee: dict[str, str] | None = None,
        actor: str | None = None,
    ) -> str:
        actor = actor or ("ingestion" if event_uuid or kind == "created" else "user")
        issue_id = issue_id or uuid.uuid4()
        change = ErrorTrackingIssueChange.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            issue_id=issue_id,
            kind=kind,
            data=data or {},
            snapshot={
                "status": status,
                "severity": None,
                "name": name,
                "assignee": assignee,
                "first_seen": "2026-11-01T00:00:00+00:00",
            },
            operation_id=uuid.uuid4(),
            bulk=bulk,
            actor_type=actor,
            actor_user_id=self.user.id if actor == "user" else None,
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
        self,
        source_config: dict[str, Any],
        *,
        cutoff: dt.datetime = _ON_TIME,
        firing: tuple[str, ...] = (),
        due_at: dt.datetime = DUE_AT,
        schedule_restriction: dict[str, Any] | None = None,
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
                    schedule_restriction=schedule_restriction,
                    evaluation_periods=1,
                    datapoints_to_alarm=1,
                    cooldown_minutes=0,
                ),
                created_by_id=self.user.id,
            ).id
            platform_testing.set_due_at(configuration_id, due_at)
            for key in firing:
                announced = DUE_AT - dt.timedelta(minutes=1)
                platform_testing.start_firing(
                    configuration_id, team_id=self.team.id, at=announced, grouping_key=key, notified_at=announced
                )
            return evaluate_error_tracking_alert_batch(self.team.id, slot_of(due_at, cutoff), cutoff).outcomes

    def _firing_keys(self, outcome: PlatformAlertOutcome) -> set[str]:
        return {group.grouping_key for group in outcome.groups if group.kind == AlertEventKind.FIRING}

    def test_each_matching_change_in_the_window_fires_its_issue(self) -> None:
        # The window ends a settle margin before the cutoff and starts one interval earlier.
        in_window = DUE_AT - dt.timedelta(seconds=90)
        new_issue = self._change("created", at=in_window)
        self._change("created", at=DUE_AT - dt.timedelta(minutes=5))
        self._change("created", at=DUE_AT - dt.timedelta(seconds=30))
        self._change("created", at=in_window, bulk=True)
        # A split's new issues are a person regrouping known errors, not a new one.
        self._change("created", at=in_window, actor="user")
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
            # Negated operators match an empty exception, so these catch an empty one passed for a missing one.
            ("negated_exception_property", {"key": "$lib", "value": ["web"], "operator": "is_not"}, False),
            ("exception_property_not_set", {"key": "$lib", "operator": "is_not_set"}, False),
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

    def test_a_failed_read_is_recorded_and_the_next_check_reads_its_window(self) -> None:
        issue = self._change("created", at=DUE_AT - dt.timedelta(seconds=90), event_uuid=uuid.uuid4())
        source_config = {
            "condition": {"triggers": ["issue_created"]},
            "filters": {"properties": [{"key": "$lib", "value": ["web"], "operator": "exact", "type": "event"}]},
        }
        fetch = "products.error_tracking.backend.platform_alerts.evaluation.fetch_event_properties"
        with patch(fetch, side_effect=ConnectionError("valkey is down")):
            [failed] = self._outcomes(source_config)
        assert failed.failure is not None

        with team_scope(self.team.id):
            record_outcomes(self.team.id, [failed], DUE_AT)
            next_due = platform_testing.configuration(failed.configuration_id).next_check_at
        assert next_due is not None and next_due > DUE_AT
        with patch(fetch, return_value={"$lib": "web"}), team_scope(self.team.id):
            [retried] = evaluate_error_tracking_alert_batch(
                self.team.id, slot_of(next_due, next_due), next_due
            ).outcomes

        assert self._firing_keys(retried) == {issue}

    @parameterized.expand(
        [
            # The platform schedules no check in quiet hours, so the first one after them reads back to the
            # last check before them.
            ("after_quiet_hours", DUE_AT, DUE_AT - dt.timedelta(minutes=50), True),
            # A check an edit put in quiet hours reads nothing, and the first one after them reads its changes.
            ("inside_quiet_hours", DUE_AT - dt.timedelta(minutes=30), DUE_AT - dt.timedelta(minutes=50), False),
        ]
    )
    def test_quiet_hours_defer_changes_to_the_first_check_after_them(
        self, _name: str, due_at: dt.datetime, changed_at: dt.datetime, fires: bool
    ) -> None:
        issue = self._change("created", at=changed_at)

        [outcome] = self._outcomes(
            {"condition": {"triggers": ["issue_created"]}},
            due_at=due_at,
            cutoff=due_at,
            schedule_restriction={"blocked_windows": [{"start": "08:00", "end": "09:00"}]},
        )

        assert self._firing_keys(outcome) == ({issue} if fires else set())

    def test_an_edit_off_the_minute_does_not_skip_changes(self) -> None:
        # An edit moved the due time 40 seconds past the minute; the window still starts at the end of
        # the previous check's window, not 40 seconds after it.
        issue = self._change("created", at=DUE_AT - dt.timedelta(seconds=110))
        due_at = DUE_AT + dt.timedelta(seconds=40)

        [outcome] = self._outcomes(
            {"condition": {"triggers": ["issue_created"]}}, due_at=due_at, cutoff=DUE_AT + dt.timedelta(minutes=1)
        )

        assert self._firing_keys(outcome) == {issue}

    def test_a_message_links_the_issue_by_fingerprint(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fingerprint-a")
        self._change("created", at=DUE_AT - dt.timedelta(seconds=90), issue_id=issue.id)

        [outcome] = self._outcomes({"condition": {"triggers": ["issue_created"]}})

        assert [group.source_detail for group in outcome.groups] == [{"fingerprint": "fingerprint-a"}]

    def test_a_check_past_the_batch_budget_records_nothing(self) -> None:
        self._change("created", at=DUE_AT - dt.timedelta(seconds=90))
        self.enterContext(patch("products.error_tracking.backend.platform_alerts.evaluation.BATCH_BUDGET_SECONDS", 0))

        assert self._outcomes({"condition": {"triggers": ["issue_created"]}}) == ()

    def test_an_older_change_that_matches_the_filters_still_fires_its_issue(self) -> None:
        issue = uuid.uuid4()
        self._change(
            "assignee_changed",
            at=DUE_AT - dt.timedelta(seconds=100),
            issue_id=issue,
            assignee={"type": "user", "id": "1"},
        )
        self._change(
            "assignee_changed",
            at=DUE_AT - dt.timedelta(seconds=80),
            issue_id=issue,
            assignee={"type": "user", "id": "2"},
        )

        fired = self._fired(
            {
                "condition": {"triggers": ["issue_assigned"]},
                "filters": {
                    "properties": [
                        {"key": "assignee", "value": ['{"type":"user","id":1}'], "operator": "exact", "type": "event"}
                    ]
                },
            }
        )

        assert fired == {str(issue)}

    def test_a_missing_exception_leaves_issue_filters_to_decide(self) -> None:
        issue = self._change("created", at=DUE_AT - dt.timedelta(seconds=90), event_uuid=uuid.uuid4())
        self.enterContext(
            patch(
                "products.error_tracking.backend.platform_alerts.evaluation.fetch_event_properties",
                side_effect=IssueCreatedEventNotFoundError("gone"),
            )
        )

        fired = self._fired(
            {
                "condition": {"triggers": ["issue_created"]},
                "filters": {
                    "properties": [{"key": "name", "value": "TypeError", "operator": "icontains", "type": "event"}]
                },
            }
        )

        assert fired == {issue}
