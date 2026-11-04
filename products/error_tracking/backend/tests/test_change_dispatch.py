from collections.abc import Callable
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from confluent_kafka import KafkaError
from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.kafka_client.client import ProduceResult
from posthog.models.team import Team
from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.change_dispatch import dispatch_pending_changes
from products.error_tracking.backend.logic.change_subscriptions import Subscription, WorkflowSink
from products.error_tracking.backend.logic.issue_mutations import (
    assign_issue,
    bulk_update_issues,
    merge_issues,
    split_issue,
    update_issue,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueChange,
    ErrorTrackingIssueFingerprintV2,
)

FLAG = "products.error_tracking.backend.logic.issue_changes.issue_change_log_enabled"
OLD_PRODUCER = "products.error_tracking.backend.logic.lifecycle_events.produce_internal_event"
DISPATCHER_PRODUCER = "products.error_tracking.backend.logic.change_events.produce_internal_event"
FLUSH = "products.error_tracking.backend.logic.change_events.flush_internal_events_producer"
CONNECT = "products.error_tracking.backend.logic.change_subscriptions.async_connect"
# The old producer stamps the issue's created_at, the snapshot the earliest fingerprint first_seen.
# Issue id lists name different issues in the two teams; their length is compared instead.
NOT_COMPARED = {"first_seen", "merged_issue_ids", "split_issue_ids"}


def _delivered() -> ProduceResult:
    result = ProduceResult(topic="cdp_internal_events")
    result.set_result(None, None)
    return result


def _failed(code: int = KafkaError._MSG_TIMED_OUT) -> ProduceResult:  # type: ignore[attr-defined]
    result = ProduceResult(topic="cdp_internal_events")
    result.set_result(KafkaError(code), None)
    return result


def _captured(producer: MagicMock) -> list[tuple[str, dict[str, Any], dict[str, Any] | None]]:
    events = []
    for call in producer.call_args_list:
        event, person = call.kwargs["event"], call.kwargs["person"]
        properties = {key: value for key, value in event.properties.items() if key not in NOT_COMPARED}
        for id_list in ("merged_issue_ids", "split_issue_ids"):
            if id_list in event.properties:
                properties[f"{id_list}_count"] = len(event.properties[id_list])
        events.append((event.event, properties, person.properties if person else None))
    return events


class TestChangeDispatch(BaseTest):
    def _issue(
        self, team: Team, fingerprints: list[str], name: str = "TypeError: boom", **fields: Any
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=team, name=name, description="at line 1", **fields)
        for fingerprint in fingerprints:
            ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=fingerprint)
        return issue

    def _resolve(self, team: Team) -> None:
        issue = self._issue(team, ["fp"])
        update_issue(team.id, issue.id, fields={"status": "resolved"}, user=self.user, was_impersonated=False)

    def _resolve_with_long_name(self, team: Team) -> None:
        issue = self._issue(team, ["fp"], name="TypeError: " + "x" * 600)
        update_issue(team.id, issue.id, fields={"status": "resolved"}, user=self.user, was_impersonated=False)

    def _assign_then_unassign(self, team: Team) -> None:
        issue = self._issue(team, ["fp"])
        assign_issue(team.id, issue.id, {"type": "user", "id": self.user.id}, user=self.user, was_impersonated=False)
        assign_issue(team.id, issue.id, None, user=self.user, was_impersonated=False)

    def _merge(self, team: Team) -> None:
        target, source = self._issue(team, ["target_fp"]), self._issue(team, ["source_fp"])
        merge_issues(team.id, target.id, [str(source.id)], user=self.user, was_impersonated=False)

    def _split(self, team: Team) -> None:
        issue = self._issue(team, ["fp_one", "fp_two"])
        split_issue(team.id, issue.id, [{"fingerprint": "fp_two"}], user=self.user, was_impersonated=False)

    def _bulk_suppress(self, team: Team) -> None:
        issues = [self._issue(team, [f"fp{i}"]) for i in range(2)]
        bulk_update_issues(
            team.id,
            [str(issue.id) for issue in issues],
            action="set_status",
            status="suppressed",
            assignee=None,
            user=self.user,
            was_impersonated=False,
        )

    @parameterized.expand(
        [
            ("resolve", "_resolve"),
            ("resolve_with_long_name", "_resolve_with_long_name"),
            ("assign_then_unassign", "_assign_then_unassign"),
            ("merge", "_merge"),
            ("split", "_split"),
            ("bulk_suppress", "_bulk_suppress"),
        ]
    )
    def test_dispatcher_emits_the_events_the_mutation_used_to_emit(self, _name: str, mutation: str) -> None:
        run: Callable[[Team], None] = getattr(self, mutation)
        dispatch_team = Team.objects.create(organization=self.organization)

        with patch(FLAG, return_value=False), patch(OLD_PRODUCER) as old_producer:
            with self.captureOnCommitCallbacks(execute=True):
                run(self.team)

        with (
            patch(FLAG, return_value=True),
            patch(OLD_PRODUCER) as skipped_producer,
            patch(DISPATCHER_PRODUCER, side_effect=lambda **_: _delivered()) as dispatcher_producer,
            patch(FLUSH),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                run(dispatch_team)
            dispatch_pending_changes(time_budget=timedelta(seconds=30))

        skipped_producer.assert_not_called()
        assert _captured(dispatcher_producer) == _captured(old_producer)
        changes = ErrorTrackingIssueChange.objects.for_team(dispatch_team.id)
        emitted_uuids = {call.kwargs["event"].uuid for call in dispatcher_producer.call_args_list}
        assert emitted_uuids <= {str(change.id) for change in changes}
        assert not changes.filter(dispatched_at__isnull=True).exists()

    @patch(FLAG, return_value=True)
    def test_change_without_an_event_is_dispatched_without_emitting(self, _flag: MagicMock) -> None:
        issue = self._issue(self.team, ["fp"])
        update_issue(self.team.id, issue.id, fields={"severity": "high"}, user=self.user, was_impersonated=False)

        with patch(DISPATCHER_PRODUCER) as producer, patch(FLUSH):
            outcome = dispatch_pending_changes(time_budget=timedelta(seconds=30))

        producer.assert_not_called()
        assert (outcome.dispatched, outcome.delivered) == (1, 0)

    @parameterized.expand(
        [
            ("timed_out_is_retried", KafkaError._MSG_TIMED_OUT, False),  # type: ignore[attr-defined]
            ("too_large_is_dropped", KafkaError.MSG_SIZE_TOO_LARGE, True),  # type: ignore[attr-defined]
        ]
    )
    @patch(FLAG, return_value=True)
    def test_rejected_event_stays_in_the_outbox_unless_retrying_cannot_help(
        self, _name: str, code: int, expect_dispatched: bool, _flag: MagicMock
    ) -> None:
        issue = self._issue(self.team, ["fp"])
        update_issue(self.team.id, issue.id, fields={"status": "resolved"}, user=self.user, was_impersonated=False)

        with patch(DISPATCHER_PRODUCER, side_effect=lambda **_: _failed(code)), patch(FLUSH):
            outcome = dispatch_pending_changes(time_budget=timedelta(seconds=30))

        assert (outcome.dispatched, outcome.undelivered) == (int(expect_dispatched), int(not expect_dispatched))
        [change] = ErrorTrackingIssueChange.objects.for_team(self.team.id)
        assert (change.dispatched_at is not None) == expect_dispatched

    @patch(FLAG, return_value=True)
    def test_actor_who_left_the_organization_is_not_sent(self, _flag: MagicMock) -> None:
        issue = self._issue(self.team, ["fp"])
        update_issue(self.team.id, issue.id, fields={"status": "resolved"}, user=self.user, was_impersonated=False)
        self.organization.memberships.filter(user=self.user).delete()

        with patch(DISPATCHER_PRODUCER, side_effect=lambda **_: _delivered()) as producer, patch(FLUSH):
            dispatch_pending_changes(time_budget=timedelta(seconds=30))

        [call] = producer.call_args_list
        assert call.kwargs["person"] is None

    @patch(FLAG, return_value=True)
    def test_malformed_rows_are_dropped_without_blocking_other_changes(self, _flag: MagicMock) -> None:
        broken_team = Team.objects.create(organization=self.organization)
        for team_id, snapshot in ((broken_team.id, {}), (self.team.id, {"assignee": {"type": "user", "id": "x"}})):
            ErrorTrackingIssueChange.objects.for_team(team_id).create(
                team_id=team_id,
                issue_id=uuid7(),
                kind=ErrorTrackingIssueChange.Kind.ASSIGNEE_CHANGED,
                data={},
                snapshot=snapshot,
                operation_id=uuid7(),
                actor_type=ErrorTrackingIssueChange.ActorType.INGESTION,
            )
        issue = self._issue(self.team, ["fp"])
        update_issue(self.team.id, issue.id, fields={"status": "resolved"}, user=self.user, was_impersonated=False)

        with patch(DISPATCHER_PRODUCER, side_effect=lambda **_: _delivered()) as producer, patch(FLUSH):
            outcome = dispatch_pending_changes(time_budget=timedelta(seconds=30))

        assert outcome.dispatched == 3
        assert [call.kwargs["event"].event for call in producer.call_args_list] == ["$error_tracking_issue_resolved"]
        assert not ErrorTrackingIssueChange.objects.unscoped().filter(dispatched_at__isnull=True).exists()

    @parameterized.expand(
        [
            ("accepted", None, 0),
            ("already_started", WorkflowAlreadyStartedError("wf", "type"), 0),
            ("rejected", RuntimeError("temporal unavailable"), 1),
        ]
    )
    @patch(FLAG, return_value=True)
    def test_workflow_subscription_starts_one_delayed_workflow_per_change(
        self, _name: str, start_error: Exception | None, expected_undelivered: int, _flag: MagicMock
    ) -> None:
        issue = self._issue(self.team, ["fp"])
        update_issue(self.team.id, issue.id, fields={"status": "resolved"}, user=self.user, was_impersonated=False)
        [change] = ErrorTrackingIssueChange.objects.for_team(self.team.id)
        subscription = Subscription(
            key="impact-summary",
            kinds=frozenset({ErrorTrackingIssueChange.Kind.STATUS_CHANGED}),
            sink=WorkflowSink(workflow="impact-summary", task_queue="analysis", start_delay=timedelta(hours=1)),
        )
        client = MagicMock()
        client.start_workflow = AsyncMock(side_effect=start_error)

        with patch(CONNECT, AsyncMock(return_value=client)):
            outcome = dispatch_pending_changes(time_budget=timedelta(seconds=30), subscriptions=[subscription])

        assert outcome.undelivered == expected_undelivered
        start = client.start_workflow.call_args
        assert start.kwargs["id"] == f"error-tracking-change-impact-summary-{change.id}"
        assert timedelta(minutes=59) < start.kwargs["start_delay"] <= timedelta(hours=1)
        assert start.args[1].change_id == str(change.id)
        change.refresh_from_db()
        assert (change.dispatched_at is None) == bool(expected_undelivered)
