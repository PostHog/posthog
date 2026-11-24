from datetime import UTC, datetime
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

SYNCED = datetime(2026, 11, 1, tzinfo=UTC)
LEGACY_RUN = datetime(2026, 11, 5, tzinfo=UTC)
CHECKED = datetime(2026, 11, 20, tzinfo=UTC)


class TestBackfillSchemaLastCheckedAt(BaseTest):
    def _schema(self, name: str, **fields) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team, source_id=name, connection_id=name, status="Completed", source_type="Stripe"
        )
        return ExternalDataSchema.objects.create(team=self.team, source=source, name=name, **fields)

    @parameterized.expand([("preview", False), ("live_run", True)])
    def test_fills_only_schemas_without_a_check_stamp(self, _name: str, live_run: bool) -> None:
        empty_run = self._schema(
            "empty_run",
            last_synced_at=SYNCED,
            sync_type_config={"last_full_run_at": LEGACY_RUN.isoformat()},
        )
        already_checked = self._schema(
            "already_checked",
            last_synced_at=SYNCED,
            last_checked_at=CHECKED,
            sync_type_config={"last_full_run_at": "2026-12-01T00:00:00+00:00"},
        )
        never_ran = self._schema("never_ran")

        call_command("backfill_schema_last_checked_at", *(["--live-run"] if live_run else []), stdout=StringIO())

        for schema in (empty_run, already_checked, never_ran):
            schema.refresh_from_db()
        # The later legacy run wins over the older sync stamp.
        assert empty_run.last_checked_at == (LEGACY_RUN if live_run else None)
        assert already_checked.last_checked_at == CHECKED
        assert never_ran.last_checked_at is None
