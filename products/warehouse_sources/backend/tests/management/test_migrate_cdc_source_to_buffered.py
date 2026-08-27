import io
from contextlib import contextmanager

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import build_buffer_file_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import consolidated_resource_name

_CMD = "products.warehouse_sources.backend.management.commands.migrate_cdc_source_to_buffered"


@contextmanager
def _mocked_side_effects(
    oldest_batch_age: float | None = None,
    write_resolution: bool = True,
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
        patch(f"{_CMD}.is_cdc_write_resolution_enabled", return_value=write_resolution),
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

    def test_flip_aborts_when_a_buffer_file_survives_the_purge(self):
        # The purge itself is best-effort; a surviving file would replay legacy-delivered rows
        # against a lane with no watermark, silently. Abort with the mode unchanged.
        source = self._source()
        self._schema(source, "users")
        leftover = f"bucket/cdc_producer/x/{build_buffer_file_name(1, 2, 0)}"

        with _mocked_side_effects(buffer_keys=[leftover]) as mocks:
            with pytest.raises(CommandError, match="survived the purge"):
                self._run(source)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        mocks["unpause"].assert_not_called()

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

    def _record_load_position(self, schema: ExternalDataSchema, position: int) -> None:
        schema.sync_type_config = {
            **schema.sync_type_config,
            "cdc_load_position": {consolidated_resource_name(schema): position},
        }
        schema.save(update_fields=["sync_type_config"])

    def test_rollback_ignores_prefixes_the_buffered_lane_never_served(self):
        # A legacy schema's prefix holds shadow copies no consumer ever reads, so scanning it would
        # wedge every rollback of a hybrid source with capture left paused.
        source = self._source(ingest_mode="buffered")
        self._schema(source, "users")
        companion = self._schema(source, "events", table_mode="cdc_only")
        shadow = f"bucket/cdc_producer/x/{build_buffer_file_name(100, 200, 0)}"

        with _mocked_side_effects(buffer_keys_by_schema={str(companion.id): [shadow]}):
            self._run(source, rollback=True, drain_timeout=0)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "legacy"

    @parameterized.expand([("at_the_position", 200, True), ("below_the_position", 199, False)])
    def test_rollback_waits_for_the_consumer_to_delete_the_file_at_the_position(
        self, _name, end_seq: int, blocks: bool
    ):
        # One transaction shares a commit position across its events, so a file ending AT the
        # position can still be an unread tail. Only the consumer's deletion proves it landed.
        source = self._source(ingest_mode="buffered")
        schema = self._schema(source, "users")
        self._record_load_position(schema, 200)
        remaining = f"bucket/cdc_producer/x/{build_buffer_file_name(100, end_seq, 0)}"

        with _mocked_side_effects(buffer_keys=[remaining]):
            if blocks:
                with pytest.raises(CommandError, match="not yet proven applied"):
                    self._run(source, rollback=True, drain_timeout=0)
            else:
                self._run(source, rollback=True, drain_timeout=0)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == ("buffered" if blocks else "legacy")

    def test_a_reflip_is_allowed_once_the_reserved_column_is_ours(self):
        # The buffered lane writes `_ph_cdc_seq` into the warehouse table, so after a rollback the
        # column is there for our own reasons — a recorded position proves capture never collided.
        source = self._source()
        table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="users",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/users/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField"}, CDC_SEQ_COLUMN: {"hogql": "IntegerDatabaseField"}},
        )
        schema = self._schema(source, "users", table=table)
        self._record_load_position(schema, 42)

        with _mocked_side_effects():
            self._run(source)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "buffered"

    def test_a_hybrid_source_flips_only_its_consolidated_schemas(self):
        source = self._source()
        consolidated = self._schema(source, "users")
        companion = self._schema(source, "events", table_mode="cdc_only")

        with _mocked_side_effects() as mocks:
            output = self._run(source)

        assert "staying on legacy" in output
        assert "events [cdc_only]" in output
        purged = [call.args[1] for call in mocks["purge"].call_args_list]
        assert purged == [str(consolidated.id)]
        mocks["unpause_schema"].assert_called_once_with(str(consolidated.id))
        assert str(companion.id) not in str(mocks["unpause_schema"].call_args_list)

    def test_a_source_with_no_eligible_schema_is_refused(self):
        source = self._source()
        self._schema(source, "events", table_mode="both")

        with _mocked_side_effects():
            with pytest.raises(CommandError, match="No schema on this source serves the buffered lane"):
                self._run(source)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs

    def test_a_still_snapshotting_schema_is_not_eligible(self):
        source = self._source()
        self._schema(source, "users", cdc_mode="snapshot")

        with _mocked_side_effects():
            with pytest.raises(CommandError, match="No schema on this source serves the buffered lane"):
                self._run(source)

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

    def test_flipping_without_write_resolution_is_refused(self):
        # No load position means no file is ever proven consumed, so the buffer fills until the S3
        # TTL expires it — with the slot long advanced, that is unrecoverable loss, not a stall.
        source = self._source()
        self._schema(source, "users")

        with _mocked_side_effects(write_resolution=False) as mocks:
            with pytest.raises(CommandError, match="dwh-cdc-write-resolution is off"):
                self._run(source)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        mocks["pause"].assert_not_called()

    def test_rollback_does_not_need_write_resolution(self):
        source = self._source(ingest_mode="buffered")
        self._schema(source, "users")

        with _mocked_side_effects(write_resolution=False):
            self._run(source, rollback=True)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "legacy"

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
