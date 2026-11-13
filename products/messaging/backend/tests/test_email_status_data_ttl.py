from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.test.waiting import wait_until

from products.messaging.backend.facade.clickhouse import EMAIL_STATUS_DATA_TTL_SQL
from products.messaging.backend.models.email_status_sql import (
    EMAIL_STATUS_DATA_TABLE,
    EMAIL_STATUS_READ_TTL_DAYS,
    EMAIL_STATUS_TTL_DAYS,
)


class TestEmailStatusDataTTL(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {EMAIL_STATUS_DATA_TABLE}")
        self.addCleanup(sync_execute, f"TRUNCATE TABLE {EMAIL_STATUS_DATA_TABLE}")
        self.addCleanup(sync_execute, f"ALTER TABLE {EMAIL_STATUS_DATA_TABLE} REMOVE TTL")

    def test_the_ttl_migration_moves_the_expiry_of_parts_already_stored(self):
        sync_execute(
            f"ALTER TABLE {EMAIL_STATUS_DATA_TABLE} MODIFY TTL toDate(created_at) + INTERVAL {EMAIL_STATUS_TTL_DAYS} DAY "
            "SETTINGS materialize_ttl_after_modify = 0"
        )
        created_at = datetime.now(UTC) - timedelta(days=20)
        self._store_a_status(created_at)
        assert self._part_expiry_dates() == [created_at.date() + timedelta(days=EMAIL_STATUS_TTL_DAYS)]

        sync_execute(EMAIL_STATUS_DATA_TTL_SQL())
        wait_until(self._no_mutation_waits, timeout=30, message="the TTL recalculation never finished")

        assert self._part_expiry_dates() == [created_at.date() + timedelta(days=EMAIL_STATUS_READ_TTL_DAYS)]

    def _store_a_status(self, created_at: datetime) -> None:
        sync_execute(
            f"""
            INSERT INTO {EMAIL_STATUS_DATA_TABLE}
                (team_id, message_id, status, version, created_at, status_at, _timestamp, _offset, _partition)
            VALUES
            """,
            [
                {
                    "team_id": self.team.id,
                    "message_id": str(uuid4()),
                    "status": "delivered",
                    "version": 1,
                    "created_at": created_at,
                    "status_at": created_at,
                    "_timestamp": created_at,
                    "_offset": 0,
                    "_partition": 0,
                }
            ],
        )

    def _part_expiry_dates(self) -> list[date]:
        rows = sync_execute(
            """
            SELECT toDate(delete_ttl_info_max)
            FROM system.parts
            WHERE database = currentDatabase() AND table = %(table)s AND active
            ORDER BY partition
            """,
            {"table": EMAIL_STATUS_DATA_TABLE},
        )
        return [row[0] for row in rows]

    def _no_mutation_waits(self) -> bool:
        rows = sync_execute(
            """
            SELECT count()
            FROM system.mutations
            WHERE database = currentDatabase() AND table = %(table)s AND NOT is_done
            """,
            {"table": EMAIL_STATUS_DATA_TABLE},
        )
        return rows[0][0] == 0
