from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest

from posthog.models import User

from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.api import insight_short_ids_subscribed_by
from products.subscriptions.backend.models.subscription import Subscription
from products.subscriptions.backend.tests.subscriptions_test_factory import create_subscription


class TestInsightShortIdsSubscribedBy(BaseTest):
    def test_lists_active_insight_subscriptions_the_user_receives(self) -> None:
        now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        me = self.user.email
        rows: dict[str, dict[str, Any]] = {
            "mine": {"created_by": self.user, "target_value": me},
            "sent_to_me": {"created_by": other, "target_value": f"other@example.com, {me.upper()}"},
            "my_slack": {"created_by": self.user, "target_type": "slack", "target_value": "C0123"},
            "sent_by_me": {"created_by": self.user, "target_value": "other@example.com"},
            "other_slack": {"created_by": other, "target_type": "slack", "target_value": "C0456"},
            "paused": {"created_by": self.user, "target_value": me, "enabled": False},
            "ended": {"created_by": self.user, "target_value": me, "until_date": now - timedelta(days=1)},
            "deleted": {"created_by": self.user, "target_value": me, "deleted": True},
            "exhausted": {"created_by": self.user, "target_value": me},
        }
        for short_id, fields in rows.items():
            insight = Insight.objects.create(team=self.team, short_id=short_id[:12])
            create_subscription(team=self.team, insight=insight, **fields)
        Subscription.objects.filter(insight__short_id="exhausted").update(next_delivery_date=None)

        found = insight_short_ids_subscribed_by(team_id=self.team.id, user_id=self.user.id, email=me, now=now, limit=10)

        assert sorted(found) == ["mine", "my_slack", "sent_to_me"]
