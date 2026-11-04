from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import InternalError
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalScratchpad
from products.signals.backend.tasks import (
    SCRATCHPAD_EXPIRY_GRACE_DAYS,
    prune_expired_scratchpad_entries,
    prune_expired_scratchpad_entries_task,
)


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

    @parameterized.expand(
        [
            ("stale_connection", "cannot execute DELETE in a read-only transaction", True),
            ("other_internal_error", "deadlock detected", False),
        ]
    )
    def test_task_reports_only_errors_that_are_not_a_stale_connection(
        self, _name: str, message: str, is_stale: bool
    ) -> None:
        with (
            patch(
                "products.signals.backend.tasks.prune_expired_scratchpad_entries",
                side_effect=InternalError(message),
            ),
            patch("products.signals.backend.tasks.connections") as connections,
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            prune_expired_scratchpad_entries_task()
        assert connections.close_all.called == is_stale
        assert capture.called == (not is_stale)
