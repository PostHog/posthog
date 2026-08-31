from datetime import timedelta

from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from posthog.models import Organization, Team, User

from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.activities import (
    _build_scheduled_proactive_snapshot_manifest,
    _get_due_subscriptions,
)
from products.exports.backend.temporal.subscriptions.types import BuildScheduledProactiveSnapshotManifestInputs

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


@override_settings(PULSE_PROACTIVE_ENABLED=True)
class TestDueSubscriptionsQueryCount(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Due subscriptions org")
        self.team = Team.objects.create(organization=self.organization, name="Due subscriptions team")
        self.user = User.objects.create(email="due-subscriptions@example.com", distinct_id="due-subscriptions")
        self.now = timezone.now()
        self.subscriptions = [
            create_subscription(
                team=self.team,
                created_by=self.user,
                prompt=f"Review subscription {index}",
                next_delivery_date=self.now,
            )
            for index in range(3)
        ]
        for subscription in self.subscriptions:
            subscription.enabled = True
            subscription.save(update_fields=["enabled"])
            Subscription.objects.filter(id=subscription.id).update(next_delivery_date=self.now)

    def _query_count(self) -> int:
        with CaptureQueriesContext(connection) as queries:
            _get_due_subscriptions(self.now + timedelta(minutes=1))
        return len(queries)

    def test_multiple_due_subscriptions_do_not_add_per_subscription_queries(self) -> None:
        three_subscription_queries = self._query_count()

        assert three_subscription_queries <= 6

    @patch("products.exports.backend.temporal.subscriptions.activities.build_scheduled_proactive_dispatch_manifest")
    def test_due_subscriptions_do_not_build_proactive_snapshots(self, build_snapshots) -> None:
        due = _get_due_subscriptions(self.now + timedelta(minutes=1))

        build_snapshots.assert_not_called()
        assert all(item.proactive_snapshot is None for item in due)

    @patch("products.exports.backend.temporal.subscriptions.activities.build_scheduled_proactive_dispatch_manifest")
    def test_proactive_snapshots_are_batched_into_one_schedule_manifest(self, build_manifest) -> None:
        build_manifest.return_value = "subscriptions/pulse/dispatch-manifests/v1/test.json"

        result = _build_scheduled_proactive_snapshot_manifest(
            BuildScheduledProactiveSnapshotManifestInputs(
                subscription_ids=[subscription.id for subscription in self.subscriptions]
            )
        )

        assert result == "subscriptions/pulse/dispatch-manifests/v1/test.json"
        build_manifest.assert_called_once()
        inputs = build_manifest.call_args.args[0]
        assert {input.subscription_id for input in inputs} == {subscription.id for subscription in self.subscriptions}
        assert {input.team_id for input in inputs} == {self.team.id}
        assert {input.actor_id for input in inputs} == {self.user.id}
