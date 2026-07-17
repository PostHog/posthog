from datetime import UTC, date, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.growth.backend.product_push.cadence import (
    campaign_ends_at,
    is_cooldown_over,
    is_grace_period_over,
    is_pin_due,
    is_retry_eligible,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


class TestProductPushCadence(SimpleTestCase):
    @parameterized.expand(
        [
            ("day_9_still_in_grace", datetime(2026, 6, 22, 13, 0, tzinfo=UTC), False),
            ("day_10_exactly_over", datetime(2026, 6, 21, 12, 0, tzinfo=UTC), True),
            ("day_11_over", datetime(2026, 6, 20, 12, 0, tzinfo=UTC), True),
        ]
    )
    def test_grace_period_boundary(self, _name: str, org_created_at: datetime, expected: bool) -> None:
        assert is_grace_period_over(org_created_at, NOW) is expected

    @parameterized.expand(
        [
            ("no_prior_campaign", None, True),
            ("day_6_still_cooling", datetime(2026, 6, 25, 13, 0, tzinfo=UTC), False),
            ("day_7_exactly_over", datetime(2026, 6, 24, 12, 0, tzinfo=UTC), True),
        ]
    )
    def test_cooldown_boundary(self, _name: str, last_ended_at: datetime | None, expected: bool) -> None:
        assert is_cooldown_over(last_ended_at, NOW) is expected

    @parameterized.expand(
        [
            ("no_pin_always_due", None, True),
            ("today_due", date(2026, 7, 1), True),
            ("tomorrow_not_due", date(2026, 7, 2), False),
        ]
    )
    def test_pin_due(self, _name: str, scheduled_for: date | None, expected: bool) -> None:
        assert is_pin_due(scheduled_for, NOW) is expected

    @parameterized.expand(
        [
            ("day_89_still_cooling", datetime(2026, 4, 3, 13, 0, tzinfo=UTC), False),
            ("day_90_exactly_eligible", datetime(2026, 4, 2, 12, 0, tzinfo=UTC), True),
        ]
    )
    def test_retry_boundary(self, _name: str, ended_at: datetime, expected: bool) -> None:
        assert is_retry_eligible(ended_at, NOW) is expected

    def test_campaign_runs_14_days_from_its_own_start(self) -> None:
        assert campaign_ends_at(NOW) == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
