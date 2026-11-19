import uuid
from datetime import datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.temporal.spend_cleanup import delete_expired_spend


class TestDeleteExpiredSpend(BaseTest):
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

            assert delete_expired_spend() == 1
            assert set(SignalSpend.objects.unscoped().values_list("id", flat=True)) == {at_cutoff.id, newer.id}
            assert delete_expired_spend() == 0

    @time_machine.travel("2026-11-19T12:00:00+00:00", tick=False)
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
            assert delete_expired_spend() == 3

        assert not SignalSpend.objects.unscoped().exists()
