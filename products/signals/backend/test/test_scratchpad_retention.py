from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import InternalError
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalScratchpad, SignalScratchpadRevision
from products.signals.backend.tasks import (
    SCRATCHPAD_EXPIRY_GRACE_DAYS,
    SCRATCHPAD_REVISION_RETENTION_DAYS,
    SCRATCHPAD_REVISIONS_PER_KEY,
    prune_expired_scratchpad_entries,
    prune_expired_scratchpad_entries_task,
    prune_scratchpad_revisions,
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

    @time_machine.travel("2026-06-01T12:00:00Z", tick=False)
    def test_prunes_revisions_past_the_retention_window_or_the_per_key_cap(self) -> None:
        now = timezone.now()
        ages = {
            **{("busy", f"v{i}"): timedelta(minutes=i) for i in range(SCRATCHPAD_REVISIONS_PER_KEY + 2)},
            ("quiet", "recent"): timedelta(days=1),
            ("quiet", "old"): timedelta(days=SCRATCHPAD_REVISION_RETENTION_DAYS + 1),
        }
        with team_scope(self.team.id):
            for (key, content), age in ages.items():
                revision = SignalScratchpadRevision.objects.create(
                    team=self.team, key=key, content=content, change=SignalScratchpadRevision.Change.OVERWRITE
                )
                SignalScratchpadRevision.objects.filter(pk=revision.pk).update(changed_at=now - age)

        deleted = prune_scratchpad_revisions()

        assert deleted == 3
        survivors = set(SignalScratchpadRevision.objects.unscoped().values_list("key", "content"))
        assert survivors == {("busy", f"v{i}") for i in range(SCRATCHPAD_REVISIONS_PER_KEY)} | {("quiet", "recent")}

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
