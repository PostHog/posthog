from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest

from posthog.models import User

from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.api import insight_short_ids_subscribed_by
from products.subscriptions.backend.tests.subscriptions_test_factory import create_subscription


class TestInsightShortIdsSubscribedBy(BaseTest):
    def test_lists_live_insight_subscriptions_you_created(self) -> None:
        now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        rows: dict[str, dict[str, Any]] = {
            "live": {"created_by": self.user},
            "until_later": {"created_by": self.user, "until_date": now + timedelta(days=1)},
            "ended": {"created_by": self.user, "until_date": now - timedelta(days=1)},
            "deleted": {"created_by": self.user, "deleted": True},
            "theirs": {"created_by": other},
        }
        for short_id, fields in rows.items():
            insight = Insight.objects.create(team=self.team, short_id=short_id[:12])
            create_subscription(team=self.team, insight=insight, **fields)

        found = insight_short_ids_subscribed_by(team_id=self.team.id, user_id=self.user.id, now=now, limit=10)

        assert sorted(found) == ["live", "until_later"]
