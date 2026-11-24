from datetime import UTC, datetime
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

OLD_RUN = datetime(2026, 11, 1, tzinfo=UTC)
LAST_RUN = datetime(2026, 11, 5, tzinfo=UTC)
CHECKED = datetime(2026, 11, 20, tzinfo=UTC)


class TestBackfillSchemaLastCheckedAt(BaseTest):
    def _schema(self, name: str, **fields) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team, source_id=name, connection_id=name, status="Completed", source_type="Stripe"
        )
        return ExternalDataSchema.objects.create(team=self.team, source=source, name=name, **fields)

    def _job(self, schema: ExternalDataSchema, status: str, created_at: datetime) -> None:
        job = ExternalDataJob.objects.create(
            team=self.team, pipeline=schema.source, schema=schema, status=status, rows_synced=0
        )
        ExternalDataJob.objects.filter(pk=job.pk).update(created_at=created_at)

    @parameterized.expand([("preview", False), ("live_run", True)])
    def test_fills_the_start_of_the_newest_completed_job(self, _name: str, live_run: bool) -> None:
        # The legacy `last_full_run_at` is a completion time, so it must not become the check stamp.
        quiet = self._schema(
            "quiet", last_synced_at=OLD_RUN, sync_type_config={"last_full_run_at": "2026-11-05T00:10:00+00:00"}
        )
        self._job(quiet, ExternalDataJob.Status.COMPLETED, OLD_RUN)
        self._job(quiet, ExternalDataJob.Status.COMPLETED, LAST_RUN)
        self._job(quiet, ExternalDataJob.Status.FAILED, CHECKED)
        already_checked = self._schema("already_checked", last_checked_at=CHECKED)
        self._job(already_checked, ExternalDataJob.Status.COMPLETED, LAST_RUN)
        never_ran = self._schema("never_ran")

        call_command("backfill_schema_last_checked_at", *(["--live-run"] if live_run else []), stdout=StringIO())

        for schema in (quiet, already_checked, never_ran):
            schema.refresh_from_db()
        assert quiet.last_checked_at == (LAST_RUN if live_run else None)
        assert already_checked.last_checked_at == CHECKED
        assert never_ran.last_checked_at is None
