from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.test.waiting import wait_until

from products.messaging.backend.facade.clickhouse import EMAIL_STATUS_DATA_TTL_SQL
from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_DATA_TABLE, EMAIL_STATUS_TTL_DAYS


class TestEmailStatusDataTTL(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {EMAIL_STATUS_DATA_TABLE}")
        self.addCleanup(sync_execute, f"TRUNCATE TABLE {EMAIL_STATUS_DATA_TABLE}")
        self.addCleanup(sync_execute, f"ALTER TABLE {EMAIL_STATUS_DATA_TABLE} REMOVE TTL")

    def test_the_ttl_migration_keeps_stored_statuses_61_days(self):
        now = datetime.now(UTC)
        kept = self._store_a_status(now - timedelta(days=40))
        self._store_a_status(now - timedelta(days=70))
        sync_execute(
            f"ALTER TABLE {EMAIL_STATUS_DATA_TABLE} MODIFY TTL toDate(created_at) + INTERVAL {EMAIL_STATUS_TTL_DAYS} DAY "
            "SETTINGS materialize_ttl_after_modify = 0"
        )

        sync_execute(EMAIL_STATUS_DATA_TTL_SQL())
        wait_until(self._no_mutation_waits, timeout=30, message="the TTL recalculation never finished")

        assert self._stored_message_ids() == [kept]

    def _store_a_status(self, created_at: datetime) -> str:
        message_id = str(uuid4())
        sync_execute(
            f"""
            INSERT INTO {EMAIL_STATUS_DATA_TABLE}
                (team_id, message_id, status, version, created_at, status_at, _timestamp, _offset, _partition)
            VALUES
            """,
            [
                {
                    "team_id": self.team.id,
                    "message_id": message_id,
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
        return message_id

    def _stored_message_ids(self) -> list[str]:
        rows = sync_execute(
            f"SELECT message_id FROM {EMAIL_STATUS_DATA_TABLE} FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.id},
        )
        return [str(row[0]) for row in rows]

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
