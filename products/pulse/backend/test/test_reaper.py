import datetime as dt

from posthog.test.base import BaseTest

from django.utils import timezone

from products.pulse.backend.models import ProductBrief
from products.pulse.backend.reaper import STALE_AFTER, mark_stale_briefs_failed


class TestStaleBriefReaper(BaseTest):
    def _brief(self, status: str, age: dt.timedelta) -> ProductBrief:
        brief = ProductBrief.objects.for_team(self.team.pk).create(
            team=self.team, status=status, trigger=ProductBrief.Trigger.ON_DEMAND, period_days=7
        )
        # .update() bypasses auto_now, so it actually backdates the row.
        ProductBrief.all_teams.filter(id=brief.id).update(updated_at=timezone.now() - age)
        return brief

    def test_reaps_only_briefs_stuck_generating_past_the_window(self) -> None:
        stale = self._brief(ProductBrief.Status.GENERATING, STALE_AFTER + dt.timedelta(minutes=5))
        fresh = self._brief(ProductBrief.Status.GENERATING, dt.timedelta(minutes=1))
        # A terminal brief older than the window must never be touched — only GENERATING is a candidate.
        old_ready = self._brief(ProductBrief.Status.READY, STALE_AFTER + dt.timedelta(hours=2))

        reaped = mark_stale_briefs_failed()

        assert reaped == 1
        stale.refresh_from_db()
        fresh.refresh_from_db()
        old_ready.refresh_from_db()
        assert stale.status == ProductBrief.Status.FAILED
        assert stale.error
        assert fresh.status == ProductBrief.Status.GENERATING
        assert old_ready.status == ProductBrief.Status.READY
