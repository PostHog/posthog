from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalScratchpad
from products.signals.backend.tasks import SCRATCHPAD_EXPIRY_GRACE_DAYS, prune_expired_scratchpad_entries


class TestPruneExpiredScratchpadEntries(BaseTest):
    def test_prunes_only_entries_whose_expiry_is_past_the_grace(self) -> None:
        now = timezone.now()
        grace = timedelta(days=SCRATCHPAD_EXPIRY_GRACE_DAYS)
        with team_scope(self.team.id):
            SignalScratchpad.objects.create(team=self.team, key="durable", content="x", expires_at=None)
            SignalScratchpad.objects.create(team=self.team, key="live", content="x", expires_at=now + timedelta(days=1))
            SignalScratchpad.objects.create(
                team=self.team, key="within_grace", content="x", expires_at=now - timedelta(days=1)
            )
            SignalScratchpad.objects.create(
                team=self.team, key="past_grace", content="x", expires_at=now - grace - timedelta(days=1)
            )

        deleted = prune_expired_scratchpad_entries()

        assert deleted == 1
        survivors = set(SignalScratchpad.objects.unscoped().values_list("key", flat=True))
        assert survivors == {"durable", "live", "within_grace"}
