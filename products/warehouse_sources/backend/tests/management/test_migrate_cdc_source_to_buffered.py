import io
from contextlib import contextmanager

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import build_buffer_file_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_jobs import COMPANION_RETIRED_ERROR

_CMD = "products.warehouse_sources.backend.management.commands.migrate_cdc_source_to_buffered"


@contextmanager
def _mocked_side_effects(
    oldest_batch_age: float | None = None,
    buffer_keys: list[str] | None = None,
    buffer_keys_by_schema: dict[str, list[str]] | None = None,
    extraction_running: bool = False,
):
    """Stub every outside effect: Temporal schedules, the sourcebatch probe, the flag, and S3.

    `buffer_keys` is what any prefix listing returns; None means the prefix does not exist, which is
    both a clean purge and a drained buffer. `buffer_keys_by_schema` answers per schema id instead,
    for the prefixes that hold different files.
    """
    s3 = MagicMock()
    if buffer_keys_by_schema is not None:

        def _ls(prefix, **kwargs):
            for schema_id, keys in buffer_keys_by_schema.items():
                if schema_id in prefix:
                    return keys
            raise FileNotFoundError(prefix)

        s3.ls.side_effect = _ls
    elif buffer_keys is None:
        s3.ls.side_effect = FileNotFoundError()
    else:
        s3.ls.return_value = buffer_keys
    with (
        patch(f"{_CMD}.psycopg.Connection.connect") as mock_connect,
        patch(f"{_CMD}.BatchQueue.get_oldest_non_terminal_batch_age_seconds", return_value=oldest_batch_age),
        patch(f"{_CMD}.purge_buffer_prefix") as mock_purge,
        patch("products.data_warehouse.backend.facade.api.get_s3_client", return_value=s3),
        patch(
            "products.data_warehouse.backend.facade.api.cdc_extraction_schedule_has_running_action",
            return_value=extraction_running,
        ),
        patch("products.data_warehouse.backend.facade.api.pause_cdc_extraction_schedule") as mock_pause,
        patch("products.data_warehouse.backend.facade.api.unpause_cdc_extraction_schedule") as mock_unpause,
        patch("products.data_warehouse.backend.facade.api.pause_external_data_schedule") as mock_pause_schema,
        patch("products.data_warehouse.backend.facade.api.unpause_external_data_schedule") as mock_unpause_schema,
    ):
        mock_connect.return_value = MagicMock()
        yield {
            "purge": mock_purge,
            "pause": mock_pause,
            "unpause": mock_unpause,
            "pause_schema": mock_pause_schema,
            "unpause_schema": mock_unpause_schema,
            "s3": s3,
        }


class TestMigrateCDCSourceToBuffered(BaseTest):
    def _source(self, ingest_mode: str | None = None) -> ExternalDataSource:
        job_inputs: dict = {"cdc_enabled": True}
        if ingest_mode:
            job_inputs["cdc_ingest_mode"] = ingest_mode
        return ExternalDataSource.objects.create(team=self.team, source_type="Postgres", job_inputs=job_inputs)

    def _schema(self, source: ExternalDataSource, name: str, table_mode: str = "consolidated", **overrides):
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name=name,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={
                "cdc_mode": overrides.get("cdc_mode", "streaming"),
                "cdc_table_mode": table_mode,
            },
            initial_sync_complete=overrides.get("initial_sync_complete", True),
            table=overrides.get("table"),
        )

    def _run(self, source, **kwargs) -> str:
        out = io.StringIO()
        call_command("migrate_cdc_source_to_buffered", source_id=str(source.id), stdout=out, **kwargs)
        return out.getvalue()

    def test_flipping_sets_buffered_and_purges_pre_flip_files(self):
        source = self._source()
        schema = self._schema(source, "users")

        with _mocked_side_effects() as mocks:
            self._run(source)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "buffered"
        # Pre-flip files were already delivered by the legacy lane; replaying them would re-apply
        # rows against a position the guard has no watermark for yet.
        assert mocks["purge"].call_args.args[:2] == (self.team.pk, str(schema.id))
        mocks["pause"].assert_called_once()
        mocks["unpause"].assert_called_once()
        mocks["unpause_schema"].assert_called_once_with(str(schema.id))

    @parameterized.expand([("flip", None, "buffered"), ("rollback", "buffered", "legacy")])
    def test_the_mode_is_written_without_saving_the_source(self, _name, ingest_mode, expected_mode):
        source = self._source(ingest_mode=ingest_mode)
        self._schema(source, "users")

        with _mocked_side_effects():
            with patch.object(ExternalDataSource, "save", side_effect=AssertionError("source.save must not run")):
                self._run(source, rollback=ingest_mode == "buffered")

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == expected_mode
        assert source.job_inputs["cdc_buffered_before"]

    def test_flip_aborts_when_a_buffer_file_survives_the_purge(self):
        # The purge itself is best-effort; a surviving file would replay legacy-delivered rows
        # against a lane with no watermark, silently. Abort with the mode unchanged.
        source = self._source()
        schema = self._schema(source, "users")
        leftover = f"bucket/cdc_producer/x/{build_buffer_file_name(1, 2, 0)}"

        with _mocked_side_effects(buffer_keys=[leftover]) as mocks:
            with pytest.raises(CommandError, match="survived the purge"):
                self._run(source)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        # The mode never changed, so the source is the legacy source it was before the command
        # ran. Keeping its schedules paused would stop the customer's syncs with nothing to
        # report it: no run starts, so there is no job row and no error.
        mocks["unpause_schema"].assert_called_once_with(str(schema.id))
        mocks["unpause"].assert_not_called()

    def test_flip_restores_already_paused_schedules_when_a_later_pause_fails(self):
        # `_pause_schema_schedules_strict` pauses schemas one at a time; a later one failing must
        # not strand the ones that already paused. The mode never changed, so the source is still
        # legacy, and leaving any of its schedules paused would stop syncs with nothing anywhere
        # reporting it.
        source = self._source()
        first = self._schema(source, "users")
        second = self._schema(source, "events")

        with _mocked_side_effects() as mocks:
            mocks["pause_schema"].side_effect = [None, Exception("boom")]
            with pytest.raises(CommandError, match="Could not pause the schedule"):
                self._run(source)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        assert mocks["pause_schema"].call_count == 2
        assert {c.args[0] for c in mocks["unpause_schema"].call_args_list} == {str(first.id), str(second.id)}

    def test_flip_restores_schedules_and_the_mode_when_marking_schemas_served_fails(self):
        # `source.save` and `_mark_schemas` run inside one transaction specifically so a failure
        # partway through marking rolls `job_inputs` back to legacy too, instead of leaving the
        # source buffered with only some schemas marked served and every schedule still paused.
        source = self._source()
        schema = self._schema(source, "users")

        with _mocked_side_effects() as mocks:
            with patch(f"{_CMD}.update_sync_type_config_keys", side_effect=Exception("boom")):
                with pytest.raises(Exception, match="boom"):
                    self._run(source)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        mocks["unpause_schema"].assert_called_once_with(str(schema.id))

    def test_rollback_drains_the_buffer_then_pauses_the_consumer_before_the_mode_flips(self):
        source = self._source(ingest_mode="buffered")
        schema = self._schema(source, "users")

        with _mocked_side_effects() as mocks:
            self._run(source, rollback=True)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "legacy"
        # Fully-applied leftovers stay: the position guard no-ops a replay, the TTL clears them.
        mocks["purge"].assert_not_called()
        mocks["pause_schema"].assert_called_once_with(str(schema.id))
        # Step 4 paused them, so the rollback has to hand them back, or the source lands on legacy
        # delivery with nothing scheduled to load it.
        mocks["unpause_schema"].assert_called_once_with(str(schema.id))

    def test_restoring_schedules_leaves_a_schema_that_stopped_syncing_paused(self):
        # A drain wait runs for minutes, and a user who turns a schema off in that window must not
        # have it turned back on by the abort path.
        source = self._source()
        staying = self._schema(source, "users")
        disabled = self._schema(source, "events")
        leftover = f"bucket/cdc_producer/x/{build_buffer_file_name(1, 2, 0)}"
        ExternalDataSchema.objects.filter(id=disabled.id).update(should_sync=False)

        with _mocked_side_effects(buffer_keys=[leftover]) as mocks:
            with pytest.raises(CommandError, match="survived the purge"):
                self._run(source)

        mocks["unpause_schema"].assert_called_once_with(str(staying.id))

    def test_rollback_refuses_while_the_buffer_holds_unapplied_changes(self):
        # The buffer tail is WAL the slot already advanced past — flipping to legacy before the
        # consumer applies it loses that WAL for good.
        source = self._source(ingest_mode="buffered")
        self._schema(source, "users")
        unapplied = f"bucket/cdc_producer/x/{build_buffer_file_name(100, 200, 0)}"

        with _mocked_side_effects(buffer_keys=[unapplied]) as mocks:
            with pytest.raises(CommandError, match="lose them"):
                self._run(source, rollback=True, drain_timeout=0)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "buffered"
        # Consumer schedules must still be live so they can catch up for the re-run.
        mocks["pause_schema"].assert_not_called()
        mocks["unpause_schema"].assert_not_called()

    def test_rollback_ignores_prefixes_the_buffered_lane_never_served(self):
        # A legacy schema's prefix holds shadow copies no consumer ever reads, so scanning it would
        # wedge every rollback of a hybrid source with capture left paused.
        source = self._source(ingest_mode="buffered")
        self._schema(source, "users")
        snapshotting = self._schema(source, "events", cdc_mode="snapshot")
        shadow = f"bucket/cdc_producer/x/{build_buffer_file_name(100, 200, 0)}"

        with _mocked_side_effects(buffer_keys_by_schema={str(snapshotting.id): [shadow]}):
            self._run(source, rollback=True, drain_timeout=0)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "legacy"

    @parameterized.expand([("a_file_remains", True), ("prefix_is_empty", False)])
    def test_rollback_waits_until_the_consumer_has_deleted_every_file(self, _name, blocks: bool):
        # The consumer deletes a file once the job that read it completes, so an empty prefix is
        # its own proof that every change reached every table the mode feeds. A file that is still
        # there can be an unread tail — one transaction shares its commit position across files.
        source = self._source(ingest_mode="buffered")
        self._schema(source, "users")
        remaining = [f"bucket/cdc_producer/x/{build_buffer_file_name(100, 200, 0)}"] if blocks else []

        with _mocked_side_effects(buffer_keys=remaining):
            if blocks:
                with pytest.raises(CommandError, match="not yet applied"):
                    self._run(source, rollback=True, drain_timeout=0)
            else:
                self._run(source, rollback=True, drain_timeout=0)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == ("buffered" if blocks else "legacy")

    def test_a_rollback_records_that_the_source_has_been_buffered(self):
        # A source flipped before this marker existed only gains it here, and that is exactly the
        # source that would otherwise be refused its next flip.
        source = self._source(ingest_mode="buffered")
        self._schema(source, "users")
        history = self._schema(source, "events", table_mode="cdc_only")
        disabled_history = self._schema(source, "audit", table_mode="both")
        disabled_history.should_sync = False
        disabled_history.save()

        with _mocked_side_effects():
            self._run(source, rollback=True)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "legacy"
        assert source.job_inputs["cdc_buffered_before"]
        for schema in (history, disabled_history):
            schema.refresh_from_db()
            assert schema.sync_type_config["cdc_buffered_before"] is True

    def test_rollback_restores_schedules_even_when_the_extraction_unpause_fails(self):
        # The per-schema restore runs before the single Temporal call that unpauses extraction, so
        # a raise from that call does not also strand the per-schema schedules a second time.
        source = self._source(ingest_mode="buffered")
        schema = self._schema(source, "users")

        with _mocked_side_effects() as mocks:
            mocks["unpause"].side_effect = Exception("boom")
            with pytest.raises(Exception, match="boom"):
                self._run(source, rollback=True)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "legacy"
        mocks["unpause_schema"].assert_called_once_with(str(schema.id))

    def test_a_flip_after_a_rollback_is_not_refused_for_our_own_column(self):
        # Rollback leaves `_ph_cdc_seq` in the warehouse table and puts the source back on legacy,
        # so the column looks exactly like a source-owned one. Refusing here would strand the
        # source for good, telling the operator to rename a column the source does not have.
        source = self._source(ingest_mode="legacy")
        source.job_inputs = {**source.job_inputs, "cdc_buffered_before": True}
        source.save(update_fields=["job_inputs"])
        table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="users",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/users/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField"}, CDC_SEQ_COLUMN: {"hogql": "IntegerDatabaseField"}},
        )
        self._schema(source, "users", table=table)

        with _mocked_side_effects():
            self._run(source)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "buffered"

    def test_a_first_flip_records_that_the_source_has_been_buffered(self):
        source = self._source(ingest_mode="legacy")
        self._schema(source, "users")

        with _mocked_side_effects():
            self._run(source)

        source.refresh_from_db()
        assert source.job_inputs["cdc_buffered_before"]

    def test_a_reflip_is_allowed_once_the_reserved_column_is_ours(self):
        # The buffered lane writes `_ph_cdc_seq` into the warehouse table, so on a source already
        # buffered the column is there for our own reasons — capture would have hard-errored on a
        # real collision before any file existed.
        source = self._source(ingest_mode="buffered")
        table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="users",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/users/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField"}, CDC_SEQ_COLUMN: {"hogql": "IntegerDatabaseField"}},
        )
        self._schema(source, "users", table=table)

        with _mocked_side_effects():
            self._run(source)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "buffered"

    def test_every_streaming_table_mode_flips_together(self):
        source = self._source()
        consolidated = self._schema(source, "users")
        companion = self._schema(source, "events", table_mode="cdc_only")
        both = self._schema(source, "orders", table_mode="both")

        with _mocked_side_effects() as mocks:
            self._run(source)

        purged = [call.args[1] for call in mocks["purge"].call_args_list]
        assert sorted(purged) == sorted([str(consolidated.id), str(companion.id), str(both.id)])
        assert mocks["unpause_schema"].call_count == 3

    def test_a_hybrid_source_leaves_its_ineligible_schemas_on_legacy(self):
        source = self._source()
        eligible = self._schema(source, "users")
        snapshotting = self._schema(source, "events", cdc_mode="snapshot")

        with _mocked_side_effects() as mocks:
            output = self._run(source)

        assert "staying on legacy" in output
        # Every CDC prefix is purged, not just the eligible ones: a schema still snapshotting
        # becomes eligible on its first completed sync and would inherit whatever it left behind.
        purged = [call.args[1] for call in mocks["purge"].call_args_list]
        assert sorted(purged) == sorted([str(eligible.id), str(snapshotting.id)])
        mocks["unpause_schema"].assert_called_once_with(str(eligible.id))

    def test_a_still_snapshotting_schema_is_not_eligible(self):
        source = self._source()
        self._schema(source, "users", cdc_mode="snapshot")

        with _mocked_side_effects():
            with pytest.raises(CommandError, match="No schema on this source serves the buffered lane"):
                self._run(source)

        # Refusing must leave the source wholly on legacy, not half-flipped.
        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs

    def test_dry_run_changes_nothing_and_reports_the_cadence(self):
        source = self._source()
        self._schema(source, "users")

        with _mocked_side_effects() as mocks:
            output = self._run(source, dry_run=True)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        assert "Dry run" in output
        # Default schema interval is not the 5min platform cadence — the report must say so.
        assert "not at the 5min platform cadence" in output
        mocks["pause"].assert_not_called()
        mocks["purge"].assert_not_called()

    def test_a_reserved_seq_column_on_the_source_table_refuses_the_flip(self):
        # The batcher cannot stamp the engine position over a same-named source column, and capture
        # hard-errors on it — refusing here keeps the source out of a flip-then-break loop.
        source = self._source()
        table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="users",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/users/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField"}, CDC_SEQ_COLUMN: {"hogql": "IntegerDatabaseField"}},
        )
        self._schema(source, "users", table=table)

        with _mocked_side_effects():
            with pytest.raises(CommandError, match="reserved for change ordering"):
                self._run(source)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs

    def test_flipping_records_the_buffered_lane_and_rollback_keeps_the_record(self):
        source = self._source()
        history = self._schema(source, "events", table_mode="cdc_only")
        with _mocked_side_effects():
            self._run(source)
        history.refresh_from_db()
        assert history.sync_type_config["cdc_buffered_before"] is True

        with _mocked_side_effects():
            self._run(source, rollback=True)
        history.refresh_from_db()
        assert history.sync_type_config["cdc_buffered_before"] is True

    def test_marking_keeps_the_keys_a_run_wrote_while_the_command_waited(self):
        # The command waits out an in-flight capture run, and that run appends to the same JSON —
        # under backpressure, the only record of batches it deferred. Saving the copy loaded before
        # the wait would put the JSON back the way it was.
        source = self._source()
        schema = self._schema(source, "users")

        def run_writes_during_the_wait(*_args):
            update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_deferred_runs": [{"run": 1}]})

        with (
            _mocked_side_effects(),
            patch(f"{_CMD}.Command._wait_for_extraction_idle", side_effect=run_writes_during_the_wait),
        ):
            self._run(source)

        schema.refresh_from_db()
        assert schema.sync_type_config["cdc_deferred_runs"] == [{"run": 1}]
        assert schema.sync_type_config["cdc_buffered_before"] is True

    @parameterized.expand([("flip", None, False), ("rollback", "buffered", True)])
    def test_an_orphaned_companion_job_is_retired_instead_of_blocking(self, _name, ingest_mode, rollback):
        # A hard kill leaves the companion row Running; only a run's start retires it, and the
        # command has just paused the schedules — so waiting on it would never end.
        source = self._source(ingest_mode)
        schema = self._schema(source, "users", table_mode="both")
        if rollback:
            update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_buffered_lane": True})
        parent = ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline_id=source.id,
            schema_id=schema.id,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=0,
        )
        companion = ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline_id=source.id,
            schema_id=schema.id,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_run_id=None,
            schema_snapshot={"companion_of": str(parent.id)},
        )

        with _mocked_side_effects():
            self._run(source, rollback=rollback, drain_timeout=0)

        companion.refresh_from_db()
        source.refresh_from_db()
        assert (companion.status, companion.latest_error) == (ExternalDataJob.Status.FAILED, COMPANION_RETIRED_ERROR)
        assert source.job_inputs["cdc_ingest_mode"] == ("legacy" if rollback else "buffered")

    def test_a_stuck_sourcebatch_aborts_the_flip_with_the_source_paused(self):
        source = self._source()
        self._schema(source, "users")

        with _mocked_side_effects(oldest_batch_age=9999.0) as mocks:
            with pytest.raises(CommandError, match="still has a batch"):
                self._run(source, drain_timeout=0)

        source.refresh_from_db()
        # Flipping on top of a stuck load would let that batch land against a table the buffered
        # lane has already started writing.
        assert "cdc_ingest_mode" not in source.job_inputs
        mocks["pause"].assert_called_once()
        mocks["unpause"].assert_not_called()

    def test_the_flip_waits_out_a_running_scheduled_sync(self):
        # A sync that started legacy resolves its pipeline version before the mode changes; letting
        # it straddle the change would consume the buffer on that stale version.
        source = self._source()
        schema = self._schema(source, "users")
        ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline_id=source.id,
            schema_id=schema.id,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        with _mocked_side_effects() as mocks:
            with pytest.raises(CommandError, match="still running"):
                self._run(source, drain_timeout=0)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        mocks["pause_schema"].assert_called_once_with(str(schema.id))
        mocks["unpause"].assert_not_called()

    def test_the_flip_waits_out_an_in_flight_extraction_run(self):
        # A legacy run with the shadow lane on keeps writing buffer files after the schedule pauses;
        # one landing after the purge would be merged on top of rows legacy already delivered.
        source = self._source()
        self._schema(source, "users")

        with _mocked_side_effects(extraction_running=True) as mocks:
            with pytest.raises(CommandError, match="still executing"):
                self._run(source, drain_timeout=0)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        mocks["purge"].assert_not_called()
        mocks["unpause"].assert_not_called()

    def test_rollback_waits_out_an_in_flight_extraction_run(self):
        # Pausing the schedule does not stop a running workflow — one still executing would keep
        # writing buffer files and advancing the slot behind the drain check.
        source = self._source(ingest_mode="buffered")
        self._schema(source, "users")

        with _mocked_side_effects(extraction_running=True):
            with pytest.raises(CommandError, match="still executing"):
                self._run(source, rollback=True, drain_timeout=0)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "buffered"

    def test_a_user_disabled_schema_is_not_flipped(self):
        # Step 5 unpauses eligible schedules; flipping a disabled schema would reverse the disable.
        source = self._source()
        disabled = self._schema(source, "users")
        disabled.should_sync = False
        disabled.save(update_fields=["should_sync"])

        with _mocked_side_effects():
            with pytest.raises(CommandError, match="No schema on this source serves the buffered lane"):
                self._run(source)
