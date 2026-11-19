import uuid
import asyncio
from datetime import datetime, timedelta

import time_machine
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.models import Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.temporal.spend_cleanup import _delete_expired_spend_batch, delete_expired_spend_activity


class TestDeleteExpiredSpend(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_spend(self, created_at: datetime, team_id: int | None = None) -> SignalSpend:
        team_id = self.team.id if team_id is None else team_id
        with time_machine.travel(created_at, tick=False):
            return SignalSpend.objects.for_team(team_id).create(
                team_id=team_id, kind=SignalSpend.Kind.AD_HOC, signal_id=uuid.uuid4()
            )

    @parameterized.expand(
        [
            ("2026-11-19T12:00:00+00:00", "2026-08-19T12:00:00+00:00"),
            ("2026-05-31T12:00:00+00:00", "2026-02-28T12:00:00+00:00"),
        ]
    )
    def test_deletes_only_receipts_older_than_three_calendar_months(self, now: str, cutoff: str) -> None:
        cutoff_at = datetime.fromisoformat(cutoff)
        with time_machine.travel(now, tick=False):
            self._create_spend(cutoff_at - timedelta(microseconds=1))
            at_cutoff = self._create_spend(cutoff_at)
            newer = self._create_spend(cutoff_at + timedelta(days=1))

            assert asyncio.run(ActivityEnvironment().run(delete_expired_spend_activity)) == 1
            assert set(SignalSpend.objects.unscoped().values_list("id", flat=True)) == {at_cutoff.id, newer.id}
            assert asyncio.run(ActivityEnvironment().run(delete_expired_spend_activity)) == 0

    def test_deletes_all_accounting_states_across_teams_and_batches(self) -> None:
        old = timezone.now() - timedelta(days=120)
        finalized = self._create_spend(old)
        SignalSpend.objects.for_team(self.team.id).filter(id=finalized.id).update(finalized_at=timezone.now())
        pending = self._create_spend(old)
        SignalSpend.objects.for_team(self.team.id).filter(id=pending.id).update(accounting_pending=True)
        other_team = Team.objects.create(organization=self.organization)
        failed = self._create_spend(old, team_id=other_team.id)
        SignalSpend.objects.for_team(other_team.id).filter(id=failed.id).update(
            accounting_failed=True, billing_exempt=True
        )

        with patch("products.signals.backend.temporal.spend_cleanup._DELETE_BATCH_SIZE", 2):
            assert asyncio.run(ActivityEnvironment().run(delete_expired_spend_activity)) == 3

        assert not SignalSpend.objects.unscoped().exists()

    def test_cancellation_stops_after_the_current_batch(self) -> None:
        for _ in range(3):
            self._create_spend(timezone.now() - timedelta(days=120))

        async def cancel_during_cleanup() -> None:
            environment = ActivityEnvironment()
            loop = asyncio.get_running_loop()

            def delete_batch_and_cancel(cutoff: datetime) -> int:
                deleted = _delete_expired_spend_batch(cutoff)
                loop.call_soon_threadsafe(environment.cancel)
                return deleted

            with (
                patch("products.signals.backend.temporal.spend_cleanup._DELETE_BATCH_SIZE", 1),
                patch(
                    "products.signals.backend.temporal.spend_cleanup._delete_expired_spend_batch",
                    side_effect=delete_batch_and_cancel,
                ),
                self.assertRaises(asyncio.CancelledError),
            ):
                await environment.run(delete_expired_spend_activity)

        asyncio.run(cancel_during_cleanup())
        assert SignalSpend.objects.unscoped().count() == 2
