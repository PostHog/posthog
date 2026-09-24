from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from confluent_kafka import KafkaError, KafkaException
from parameterized import parameterized

from posthog.kafka_client.client import ProduceResult
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog

from products.error_tracking.backend.logic.auto_resolve_sync import retry_auto_resolve_sync
from products.error_tracking.backend.logic.issue_mutations import auto_resolve_issues
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
)


@time_machine.travel("2026-09-24T12:00:00Z", tick=False)
class TestAutoResolveSync(BaseTest):
    def _create_pending_issue(self, issue_id: UUID, team: Team | None = None) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=issue_id,
            team=team or self.team,
            status=ErrorTrackingIssue.Status.RESOLVED,
            name="TypeError",
            auto_resolve_sync_requested_at=timezone.now(),
        )
        ErrorTrackingIssueFingerprintV2.objects.create(
            team_id=issue.team_id, issue=issue, fingerprint=f"fp::{issue.id}"
        )
        return issue

    @parameterized.expand([("enqueue", RuntimeError), ("delivery", KafkaException), ("timeout", TimeoutError)])
    def test_failed_delivery_retries_latest_state_with_auto_resolve_disabled(
        self, failure: str, error_type: type[Exception]
    ) -> None:
        issue = self._create_pending_issue(UUID(int=1))
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=None)
        failed_result = ProduceResult(topic="test")
        if failure == "delivery":
            failed_result.set_result(KafkaError(KafkaError._VALUE_SERIALIZATION), None)

        with (
            self.settings(TEST=False),
            patch("products.error_tracking.backend.models.get_producer") as get_producer,
            patch("products.error_tracking.backend.logic.lifecycle_events.produce_internal_event") as produce_lifecycle,
        ):
            producer = get_producer.return_value
            if failure == "enqueue":
                producer.produce.side_effect = RuntimeError("Kafka unavailable")
            else:
                producer.produce.return_value = failed_result

            with self.assertRaises(error_type):
                retry_auto_resolve_sync(self.team.id)

            issue = ErrorTrackingIssue.objects.get(team_id=self.team.id, id=issue.id)
            assert issue.status == ErrorTrackingIssue.Status.RESOLVED
            assert issue.auto_resolve_sync_requested_at is not None

            ErrorTrackingIssue.objects.filter(team_id=self.team.id, id=issue.id).update(
                status=ErrorTrackingIssue.Status.ACTIVE, state_updated_at=timezone.now()
            )
            producer.produce.reset_mock(side_effect=True)
            delivered_result = ProduceResult(topic="test")
            delivered_result.set_result(None, None)
            producer.produce.return_value = delivered_result
            retry_auto_resolve_sync(self.team.id)
            retry_auto_resolve_sync(self.team.id)

            issue = ErrorTrackingIssue.objects.get(team_id=self.team.id, id=issue.id)
            assert issue.status == ErrorTrackingIssue.Status.ACTIVE
            assert issue.auto_resolve_sync_requested_at is None
            producer.produce.assert_called_once()
            assert producer.produce.call_args.kwargs["data"]["issue_status"] == ErrorTrackingIssue.Status.ACTIVE
            produce_lifecycle.assert_not_called()

        assert not ActivityLog.objects.filter(team_id=self.team.id, scope="ErrorTrackingIssue").exists()

    def test_resolution_survives_sync_failure_and_retry_does_not_repeat_lifecycle(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError")
        ErrorTrackingIssue.objects.filter(team_id=self.team.id, id=issue.id).update(
            created_at=timezone.now() - timedelta(days=10),
            state_updated_at=timezone.now() - timedelta(days=10),
            last_received_at=timezone.now() - timedelta(days=10),
        )
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=f"fp::{issue.id}")
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=3)

        with (
            self.settings(TEST=False),
            patch("products.error_tracking.backend.models.get_producer") as get_producer,
            patch("products.error_tracking.backend.logic.lifecycle_events.produce_internal_event") as produce_lifecycle,
        ):
            producer = get_producer.return_value
            producer.produce.side_effect = RuntimeError("Kafka unavailable")
            with self.captureOnCommitCallbacks(execute=True), self.assertRaisesRegex(RuntimeError, "Kafka unavailable"):
                auto_resolve_issues(self.team.id, [issue.id], cutoff=timezone.now() - timedelta(days=3), days=3)

            issue = ErrorTrackingIssue.objects.get(team_id=self.team.id, id=issue.id)
            assert issue.status == ErrorTrackingIssue.Status.RESOLVED
            assert issue.auto_resolve_sync_requested_at is not None
            produce_lifecycle.assert_called_once()
            assert produce_lifecycle.call_args.kwargs["event"].event == "$error_tracking_issue_resolved"
            assert produce_lifecycle.call_args.kwargs["event"].properties["resolved_reason"] == "inactivity"

            delivered_result = ProduceResult(topic="test")
            delivered_result.set_result(None, None)
            producer.produce.reset_mock(side_effect=True)
            producer.produce.return_value = delivered_result
            with self.captureOnCommitCallbacks(execute=True):
                retry_auto_resolve_sync(self.team.id)
                retry_auto_resolve_sync(self.team.id)

            issue = ErrorTrackingIssue.objects.get(team_id=self.team.id, id=issue.id)
            assert issue.status == ErrorTrackingIssue.Status.RESOLVED
            assert issue.auto_resolve_sync_requested_at is None
            producer.produce.assert_called_once()
            assert producer.produce.call_args.kwargs["data"]["issue_status"] == ErrorTrackingIssue.Status.RESOLVED
            produce_lifecycle.assert_called_once()

        assert (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="ErrorTrackingIssue", activity="updated", item_id=str(issue.id)
            ).count()
            == 1
        )

    def test_sync_is_bounded_and_scoped_to_team(self) -> None:
        third = self._create_pending_issue(UUID(int=3))
        first = self._create_pending_issue(UUID(int=1))
        second = self._create_pending_issue(UUID(int=2))
        other_team = Team.objects.create(organization=self.organization)
        other_issue = self._create_pending_issue(UUID(int=4), team=other_team)
        delivered_result = ProduceResult(topic="test")
        delivered_result.set_result(None, None)

        with (
            self.settings(TEST=False),
            patch("products.error_tracking.backend.logic.auto_resolve_sync.MAX_ISSUES_PER_SYNC", 2),
            patch("products.error_tracking.backend.models.get_producer") as get_producer,
        ):
            producer = get_producer.return_value
            producer.produce.return_value = delivered_result
            retry_auto_resolve_sync(self.team.id)

            synced_ids = {call.kwargs["data"]["issue_id"] for call in producer.produce.call_args_list}
            assert synced_ids == {str(first.id), str(second.id)}
            assert set(
                ErrorTrackingIssue.objects.filter(
                    team_id=self.team.id, auto_resolve_sync_requested_at__isnull=False
                ).values_list("id", flat=True)
            ) == {third.id}
            other_issue.refresh_from_db()
            assert other_issue.auto_resolve_sync_requested_at is not None

            producer.produce.reset_mock()
            retry_auto_resolve_sync(self.team.id)
            producer.produce.assert_called_once()
            assert producer.produce.call_args.kwargs["data"]["issue_id"] == str(third.id)

        assert not ErrorTrackingIssue.objects.filter(
            team_id=self.team.id, auto_resolve_sync_requested_at__isnull=False
        ).exists()
