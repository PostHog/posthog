import datetime as dt

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.history_window import (
    history_start_for_schema,
)

NOW = dt.datetime(2026, 7, 17, tzinfo=dt.UTC)


class TestHistoryStartForSchema(BaseTest):
    def _schema(self, **kwargs) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(team=self.team, source_type="GoogleAds", job_inputs={})
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="campaign_stats",
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "segments.date", "incremental_field_type": "date"},
            **kwargs,
        )

    def test_a_schema_that_never_synced_starts_its_window_now(self):
        schema = self._schema()

        assert self._resolve(schema) == NOW - dt.timedelta(days=2 * 365)

        schema.refresh_from_db()
        assert schema.history_start == NOW - dt.timedelta(days=2 * 365)

    def test_the_recorded_start_is_not_moved_by_a_later_run(self):
        # Recording it once is the whole mechanism. Re-deriving it per run is what this replaces.
        recorded = dt.datetime(2020, 2, 8, tzinfo=dt.UTC)
        schema = self._schema(history_start=recorded)

        assert self._resolve(schema) == recorded

    def _job(self, schema: ExternalDataSchema, *, running: bool = False) -> ExternalDataJob:
        return ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING if running else ExternalDataJob.Status.COMPLETED,
            rows_synced=0 if running else 1,
            workflow_id="wf",
        )

    def _resolve(self, schema: ExternalDataSchema) -> dt.datetime | None:
        """Call it the way the activity does: this run's job row already exists."""
        return history_start_for_schema(schema, self._job(schema, running=True).pk, now=NOW)

    def test_a_schema_already_syncing_records_nothing(self):
        # The lookback is only truthful for a schema with nothing yet. One already holding data
        # covers a range nobody recorded, so it reads as unbounded rather than as a guess.
        table = DataWarehouseTable.objects.create(team=self.team, name="campaign_stats", format="Delta")
        schema = self._schema(table=table)
        self._job(schema)

        assert self._resolve(schema) is None

        schema.refresh_from_db()
        assert schema.history_start is None

    def test_a_prior_run_that_landed_nothing_still_counts_as_a_first_sync(self):
        # A job row is created several activities before the import runs, and outlives every way a
        # run ends early — a billing limit, a cancellation, a deploy. Counting those would leave the
        # schema unrecorded forever and reading unbounded on every re-import.
        schema = self._schema()
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.BILLING_LIMIT_REACHED,
            rows_synced=0,
            workflow_id="wf",
        )

        assert self._resolve(schema) == NOW - dt.timedelta(days=2 * 365)

    def test_a_schema_whose_table_was_deleted_records_nothing(self):
        # `delete_table` nulls the table link on a schema that has synced for years, so the table
        # link cannot stand in for "never synced". Recording a lookback here writes down a narrower
        # range than the schema covered, which every later re-import would then honour.
        schema = self._schema()
        self._job(schema)

        assert self._resolve(schema) is None

        schema.refresh_from_db()
        assert schema.history_start is None

    def test_recording_skips_the_activity_log(self):
        # Pipeline bookkeeping, on a path where the extra read the audit trail needs fails the
        # import when the pooler has dropped the connection mid-sync.
        schema = self._schema()

        with mock.patch.object(ExternalDataSchema, "save", autospec=True) as saved:
            self._resolve(schema)

        assert saved.call_args.kwargs["skip_activity_log"] is True

    def test_a_source_without_a_window_records_nothing(self):
        source = ExternalDataSource.objects.create(team=self.team, source_type="Stripe", job_inputs={})
        schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="charges")

        assert self._resolve(schema) is None

        schema.refresh_from_db()
        assert schema.history_start is None

    def test_recording_does_not_write_the_rest_of_the_row(self):
        # The pipeline holds this instance from before the run linked its table, so a full save
        # would put back the values it was loaded with.
        schema = self._schema()
        ExternalDataSchema.objects.filter(pk=schema.pk).update(status="Completed")

        self._resolve(schema)

        schema.refresh_from_db()
        assert schema.status == "Completed"


@pytest.mark.parametrize("source_type", ["GoogleAds"])
def test_a_declared_window_is_reachable_through_the_registry(source_type: str) -> None:
    # The declaration has to be readable without importing the source module, which for Google Ads
    # would drag the vendor SDK onto a path that only wants a timedelta.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
    from products.warehouse_sources.backend.types import ExternalDataSourceType

    lookback = SourceRegistry.get_source(ExternalDataSourceType(source_type)).history_lookback

    assert lookback == dt.timedelta(days=2 * 365)
