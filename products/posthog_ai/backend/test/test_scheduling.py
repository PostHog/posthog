from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from products.posthog_ai.backend.models import TrackedQuestion
from products.posthog_ai.backend.services.scheduling import compute_next_run_at


class TestScheduling(BaseTest):
    def test_daily_advances_by_one_day(self) -> None:
        now = timezone.now()
        next_run = compute_next_run_at(cadence=TrackedQuestion.Cadence.DAILY, anchor=now, team=self.team)
        self.assertGreater(next_run, now)
        self.assertLess(next_run - now, timedelta(days=2))

    def test_weekly_advances_by_about_a_week(self) -> None:
        now = timezone.now()
        next_run = compute_next_run_at(cadence=TrackedQuestion.Cadence.WEEKLY, anchor=now, team=self.team)
        self.assertGreater(next_run - now, timedelta(days=6))
        self.assertLess(next_run - now, timedelta(days=8))

    def test_monthly_advances_by_at_least_27_days(self) -> None:
        now = timezone.now()
        next_run = compute_next_run_at(cadence=TrackedQuestion.Cadence.MONTHLY, anchor=now, team=self.team)
        self.assertGreater(next_run - now, timedelta(days=27))

    def test_unknown_cadence_falls_back_to_weekly(self) -> None:
        now = timezone.now()
        next_run = compute_next_run_at(cadence="bogus", anchor=now, team=self.team)
        self.assertGreater(next_run - now, timedelta(days=6))
