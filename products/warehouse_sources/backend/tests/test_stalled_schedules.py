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
            # A paused per-schema schedule is a streaming CDC schema's steady state:
            # CDCExtractionWorkflow owns it and pauses it again on its own next tick
            # (CDCHandledExternally). A source marked cdc_broken can drift the schema's status
            # away from FAILED, so this is excluded here rather than relying on that status.
            (
                "streaming cdc schema",
                {"sync_type": ExternalDataSchema.SyncType.CDC, "sync_type_config": {"cdc_mode": "streaming"}},
                {},
            ),
            # cdc_halted is a configuration marker independent of should_sync and status: a
            # broken source's schema can still read should_sync=True and a self-reporting status.
            ("cdc broken source", {"sync_type_config": {"cdc_broken": True}}, {}),
            ("cdc extraction paused", {"sync_type_config": {"cdc_extraction_paused": True}}, {}),
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

    def test_a_schema_with_no_sync_interval_is_reported_but_not_repairable_here(self) -> None:
        # get_sync_schedule passes sync_frequency_interval straight into ScheduleIntervalSpec,
        # where a null value raises. Reporting it is still useful; repairing it would just fail.
        schema = self._schema(synced_ago=timedelta(days=5), sync_frequency_interval=None)

        stalled = {s.schema_id: s for s in find_stalled_schemas()}

        assert stalled[str(schema.id)].kind == "no_runs"
        assert stalled[str(schema.id)].has_sync_interval is False
        assert stalled[str(schema.id)].repairable_here is False

    def test_a_schema_paused_for_an_admin_run_is_reported_but_not_repairable_here(self) -> None:
        # ad_hoc_sync.py and the admin action pause the schedule and set this marker for an
        # in-flight non-scheduled run, clearing it themselves once that run completes
        # successfully. It surviving to a stall check means unpausing here could race that run.
        schema = self._schema(
            synced_ago=timedelta(days=5),
            sync_type_config={"admin_unpause_schedule_after_run": True},
        )

        stalled = {s.schema_id: s for s in find_stalled_schemas()}

        assert stalled[str(schema.id)].kind == "no_runs"
        assert stalled[str(schema.id)].admin_paused is True
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

    def test_repair_stamps_last_error_notified_at_to_avoid_a_stale_renotify(self) -> None:
        # get_team_ids_with_recent_sync_failures renotifies once last_error_notified_at is more
        # than seven days old, with no newer failed job required. Without a fresh stamp here, a
        # schema that failed and was notified long ago, then recovered, would have this repaint
        # read as "still failing" and send the failure digest instead of the informational message.
        old_notification = timezone.now() - timedelta(days=30)
        schema = self._schema(
            synced_ago=timedelta(days=5),
            status=ExternalDataSchema.Status.RUNNING,
            last_error_notified_at=old_notification,
        )
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow"):
            repair_stalled_schema(stalled)

        schema.refresh_from_db()
        assert schema.last_error_notified_at is not None
        assert schema.last_error_notified_at > old_notification

    def test_repair_skips_a_schema_disabled_since_it_was_discovered(self) -> None:
        # The confirmation prompt in the management command alone can put minutes between
        # discovery and this call. A schema a user disabled in that window must stay paused,
        # not get rescheduled out from under them by a stale should_sync=True snapshot.
        schema = self._schema(synced_ago=timedelta(days=5))
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        schema.should_sync = False
        schema.save(update_fields=["should_sync"])

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            repair_stalled_schema(stalled)

        mock_sync.assert_not_called()

    def test_repair_skips_a_schema_deleted_since_it_was_discovered(self) -> None:
        # Deleting a schema does not itself flip should_sync, so a schema deleted in the window
        # between discovery and repair can still read should_sync=True here.
        schema = self._schema(synced_ago=timedelta(days=5))
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        schema.deleted = True
        schema.save(update_fields=["deleted"])

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            repair_stalled_schema(stalled)

        mock_sync.assert_not_called()

    def test_repair_skips_a_schema_paused_for_an_admin_run_since_it_was_discovered(self) -> None:
        # Same window as should_sync above: an admin-triggered run can pause the schedule and set
        # this marker after discovery. Unpausing here would race the admin run's own workflow.
        schema = self._schema(synced_ago=timedelta(days=5))
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        schema.sync_type_config = {"admin_unpause_schedule_after_run": True}
        schema.save(update_fields=["sync_type_config"])

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            repair_stalled_schema(stalled)

        mock_sync.assert_not_called()

    def test_repair_skips_a_schema_whose_sync_interval_is_null(self) -> None:
        # get_sync_schedule crashes on a null interval; skip rather than fail every time.
        schema = self._schema(synced_ago=timedelta(days=5))
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        schema.sync_frequency_interval = None
        schema.save(update_fields=["sync_frequency_interval"])

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            repair_stalled_schema(stalled)

        mock_sync.assert_not_called()

    def test_repair_skips_a_schema_that_flipped_to_cdc_streaming_since_it_was_discovered(self) -> None:
        # initial_sync_complete (and so the snapshot-to-streaming flip) can land in the window
        # between discovery and this call. A paused schedule is streaming's steady state, so
        # unpausing it here would just race CDCExtractionWorkflow for nothing.
        schema = self._schema(synced_ago=timedelta(days=5), sync_type=ExternalDataSchema.SyncType.CDC)
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        schema.sync_type_config = {"cdc_mode": "streaming"}
        schema.save(update_fields=["sync_type_config"])

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            repair_stalled_schema(stalled)

        mock_sync.assert_not_called()

    def test_repair_skips_a_schema_marked_cdc_broken_since_it_was_discovered(self) -> None:
        # The halt marker exists precisely to stop anything else from touching the schedule
        # until repair_cdc clears it, so it is re-checked for the same staleness reason as the
        # other guards even though the queryset already excludes it up front.
        schema = self._schema(synced_ago=timedelta(days=5), sync_type=ExternalDataSchema.SyncType.CDC)
        stalled = next(s for s in find_stalled_schemas() if s.schema_id == str(schema.id))

        schema.sync_type_config = {"cdc_broken": True}
        schema.save(update_fields=["sync_type_config"])

        with patch("products.data_warehouse.backend.facade.api.sync_external_data_job_workflow") as mock_sync:
            repair_stalled_schema(stalled)

        mock_sync.assert_not_called()


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
