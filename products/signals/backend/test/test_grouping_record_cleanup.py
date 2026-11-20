import uuid
from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.signals.backend.models import SignalGroupingRecord
from products.signals.backend.temporal.grouping_record_cleanup import (
    GROUPING_RECORD_RETENTION,
    delete_expired_grouping_records,
)


class TestDeleteExpiredGroupingRecords(BaseTest):
    def _create_record(self, age: timedelta) -> uuid.UUID:
        signal_id = uuid.uuid4()
        with time_machine.travel(timezone.now() - age, tick=False):
            SignalGroupingRecord.objects.for_team(self.team.id).create(
                team_id=self.team.id, signal_id=signal_id, report_id=uuid.uuid4(), emitted_at=timezone.now()
            )
        return signal_id

    def test_deletes_only_records_past_retention(self) -> None:
        self._create_record(GROUPING_RECORD_RETENTION + timedelta(hours=1))
        self._create_record(GROUPING_RECORD_RETENTION + timedelta(days=3))
        kept = self._create_record(GROUPING_RECORD_RETENTION - timedelta(hours=1))

        with patch("products.signals.backend.temporal.grouping_record_cleanup._DELETE_BATCH_SIZE", 1):
            deleted = delete_expired_grouping_records()

        assert deleted == 2
        remaining = SignalGroupingRecord.objects.for_team(self.team.id).values_list("signal_id", flat=True)
        assert list(remaining) == [kept]
