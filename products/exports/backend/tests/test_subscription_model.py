from datetime import UTC, datetime

from django.test import SimpleTestCase

from products.exports.backend.models.subscription import Subscription


class TestSubscriptionSchedule(SimpleTestCase):
    def test_weekly_schedule_ignores_stale_monthly_position(self) -> None:
        subscription = Subscription(
            frequency=Subscription.SubscriptionFrequency.WEEKLY,
            interval=1,
            start_date=datetime(2026, 8, 3, 9, tzinfo=UTC),
            byweekday=["monday", "wednesday", "friday"],
            bysetpos=1,
        )

        assert subscription.summary == "sent every week on Monday, Wednesday and Friday"
        assert list(subscription.rrule[:3]) == [
            datetime(2026, 8, 3, 9, tzinfo=UTC),
            datetime(2026, 8, 5, 9, tzinfo=UTC),
            datetime(2026, 8, 7, 9, tzinfo=UTC),
        ]
