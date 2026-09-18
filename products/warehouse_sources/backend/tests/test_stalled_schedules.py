from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.stalled_schedules import (
    REPAIRED_SCHEMA_ERROR,
    find_stalled_schemas,
    repair_stalled_schema,
)
from products.warehouse_sources.backend.tasks.tasks import (
    STALLED_SCHEMA_SCHEDULES_GAUGE,
    sweep_stalled_schema_schedules,
)


class TestStalledSchedules(BaseTest):
    def _source(self, **overrides) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_type=overrides.pop("source_type", "Supabase"),
            job_inputs=overrides.pop("job_inputs", {}),
            **overrides,
        )

    def _schema(
        self,
        source: ExternalDataSource | None = None,
        *,
        synced_ago: timedelta = timedelta(days=1),
        sync_frequency_interval: timedelta | None = timedelta(hours=6),
        **overrides,
    ) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=source or self._source(),
            name=overrides.pop("name", "users"),
            sync_frequency_interval=sync_frequency_interval,
            last_synced_at=None if synced_ago is None else timezone.now() - synced_ago,
            status=overrides.pop("status", ExternalDataSchema.Status.COMPLETED),
            **overrides,
        )

    @parameterized.expand(
        [
            ("just synced", timedelta(hours=6), timedelta(hours=1), False),
            ("inside three intervals", timedelta(hours=6), timedelta(hours=10), False),
            ("past three intervals", timedelta(hours=6), timedelta(hours=20), True),
            # The two-hour floor keeps a single slow run on a five-minute schema from qualifying.
            ("five minute under the floor", timedelta(minutes=5), timedelta(hours=1), False),
            ("five minute past the floor", timedelta(minutes=5), timedelta(hours=3), True),
            # A null interval falls back to the column default of six hours.
            ("null interval uses the default", None, timedelta(hours=20), True),
        ]
    )
    def test_stall_window_scales_with_the_schema_cadence(
        self, _name: str, interval: timedelta | None, synced_ago: timedelta, expected: bool
    ) -> None:
        schema = self._schema(synced_ago=synced_ago, sync_frequency_interval=interval)

        found = {s.schema_id for s in find_stalled_schemas()}

        assert (str(schema.id) in found) is expected

    @parameterized.expand(
        [
            ("sync turned off", {"should_sync": False}, {}),
            ("deleted schema", {"deleted": True}, {}),
            # A failing schema carries its error on the row and reaches the failure digest.
            ("already failing", {"status": ExternalDataSchema.Status.FAILED}, {}),
            ("billing limited", {"status": ExternalDataSchema.Status.BILLING_LIMIT_REACHED}, {}),
            ("paused by the user", {"status": ExternalDataSchema.Status.PAUSED}, {}),
            # Nothing has ever completed, so the schema may still be on its first snapshot.
            ("never synced", {"synced_ago": None}, {}),
            ("deleted source", {}, {"deleted": True}),
            # A direct-query source has no schedule to stall.
            ("direct query source", {}, {"access_method": ExternalDataSource.AccessMethod.DIRECT}),
        ]
    )
    def test_schemas_without_a_stalled_schedule_are_not_reported(
        self, _name: str, schema_overrides: dict, source_overrides: dict
    ) -> None:
        source = self._source(**source_overrides)
        schema = self._schema(source, **{"synced_ago": timedelta(days=5), **schema_overrides})

        found = {s.schema_id for s in find_stalled_schemas()}

        assert str(schema.id) not in found

    def test_a_schema_with_a_running_job_is_a_wedged_run_not_a_stalled_schedule(self) -> None:
        schema = self._schema(synced_ago=timedelta(days=5))
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        stalled = {s.schema_id: s for s in find_stalled_schemas()}

        # Rescheduling would not help: its workflow has to be terminated first, which is what
        # unstick_external_data_jobs does.
        assert stalled[str(schema.id)].kind == "stuck_job"
        assert stalled[str(schema.id)].repairable_here is False

    def test_a_buffered_cdc_schema_is_reported_but_not_repairable_here(self) -> None:
        source = self._source(job_inputs={"cdc_ingest_mode": "buffered"})
        schema = self._schema(source, synced_ago=timedelta(days=5))

        stalled = {s.schema_id: s for s in find_stalled_schemas()}

        # Its schedule paces buffer consumption, so restarting it out of sequence merges files
        # against a table the buffered lane already writes.
        assert stalled[str(schema.id)].kind == "no_runs"
        assert stalled[str(schema.id)].repairable_here is False

    def test_repair_clears_a_stale_running_status_and_reschedules_without_billing_a_run(self) -> None:
        schema = self._schema(synced_ago=timedelta(days=5), status=ExternalDataSchema.Status.RUNNING)
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            repair_stalled_schema(stalled)

        schema.refresh_from_db()
        # The scheduler skips a tick while the schema reads Running, so leaving the status behind
        # would reschedule a schema that still never runs.
        assert schema.status == ExternalDataSchema.Status.FAILED
        assert schema.latest_error == REPAIRED_SCHEMA_ERROR
        # Scheduled runs bill, so the repair waits for the schema's own next tick.
        assert mock_sync.call_args.kwargs["trigger_immediately"] is False
        assert mock_sync.call_args.kwargs["should_sync"] is True


class TestStalledScheduleSweep(BaseTest):
    def test_the_sweep_reports_stalled_schemas_without_repairing_them(self) -> None:
        # Restarting a sync reaches into a customer's database, and the predicate cannot tell a
        # schedule paused by accident from one an operator paused during an incident. Repair stays
        # behind the management command, where a person confirms the list first.
        source = ExternalDataSource.objects.create(team=self.team, source_type="Supabase", job_inputs={})
        ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="users",
            sync_frequency_interval=timedelta(minutes=5),
            last_synced_at=timezone.now() - timedelta(days=5),
            status=ExternalDataSchema.Status.COMPLETED,
        )

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            sweep_stalled_schema_schedules()

        mock_sync.assert_not_called()
        assert STALLED_SCHEMA_SCHEDULES_GAUGE.labels(kind="no_runs")._value.get() == 1
