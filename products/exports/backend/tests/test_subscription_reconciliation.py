from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.models.subscription import Subscription
from products.exports.backend.subscription_reconciliation import reconcile_dashboard_subscriptions
from products.product_analytics.backend.models.insight import Insight


class TestSubscriptionReconciliation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Dashboard")
        self.first_insight = Insight.objects.create(team=self.team, name="First")
        self.second_insight = Insight.objects.create(team=self.team, name="Second")

    def _subscription(self, *insights: Insight, enabled: bool = True) -> Subscription:
        subscription = Subscription.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            target_type=Subscription.SubscriptionTarget.EMAIL,
            target_value=self.user.email,
            frequency=Subscription.SubscriptionFrequency.WEEKLY,
            start_date=timezone.now(),
            created_by=self.user,
            enabled=enabled,
        )
        subscription.dashboard_export_insights.set(insights)
        return subscription

    @patch("products.exports.backend.subscription_reconciliation.create_notification")
    def test_removes_one_of_multiple_selected_insights(self, create_notification) -> None:
        subscription = self._subscription(self.first_insight, self.second_insight)

        with self.captureOnCommitCallbacks(execute=True):
            result = reconcile_dashboard_subscriptions(
                dashboard_id=self.dashboard.id,
                removed_insight_ids={self.first_insight.id},
            )

        subscription.refresh_from_db()
        assert subscription.enabled
        assert list(subscription.dashboard_export_insights.values_list("id", flat=True)) == [self.second_insight.id]
        assert result.updated == (subscription,)
        assert result.paused == ()
        create_notification.assert_called_once()

    @patch("products.exports.backend.subscription_reconciliation.create_notification")
    def test_pauses_subscription_without_clearing_final_selection(self, create_notification) -> None:
        subscription = self._subscription(self.first_insight)

        with self.captureOnCommitCallbacks(execute=True):
            result = reconcile_dashboard_subscriptions(
                dashboard_id=self.dashboard.id,
                removed_insight_ids={self.first_insight.id},
            )

        subscription.refresh_from_db()
        assert not subscription.enabled
        assert list(subscription.dashboard_export_insights.values_list("id", flat=True)) == [self.first_insight.id]
        assert result.updated == ()
        assert result.paused == (subscription,)
        assert "paused" in create_notification.call_args.args[0].title.lower()

    @patch("products.exports.backend.subscription_reconciliation.create_notification")
    def test_dashboard_deletion_pauses_all_explicit_subscriptions(self, create_notification) -> None:
        subscription = self._subscription(self.first_insight, self.second_insight)

        with self.captureOnCommitCallbacks(execute=True):
            reconcile_dashboard_subscriptions(
                dashboard_id=self.dashboard.id,
                removed_insight_ids=set(),
                dashboard_deleted=True,
            )

        subscription.refresh_from_db()
        assert not subscription.enabled
        assert set(subscription.dashboard_export_insights.values_list("id", flat=True)) == {
            self.first_insight.id,
            self.second_insight.id,
        }
        create_notification.assert_called_once()

    @patch("products.exports.backend.subscription_reconciliation.create_notification")
    def test_ignores_unselected_insight_and_disabled_subscription(self, create_notification) -> None:
        active = self._subscription(self.first_insight)
        disabled = self._subscription(self.second_insight, enabled=False)

        result = reconcile_dashboard_subscriptions(
            dashboard_id=self.dashboard.id,
            removed_insight_ids={self.second_insight.id},
        )

        active.refresh_from_db()
        disabled.refresh_from_db()
        assert active.enabled
        assert not disabled.enabled
        assert result.updated == ()
        assert result.paused == ()
        create_notification.assert_not_called()
