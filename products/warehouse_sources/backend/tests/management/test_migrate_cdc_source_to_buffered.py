import io
from contextlib import contextmanager

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_CMD = "products.warehouse_sources.backend.management.commands.migrate_cdc_source_to_buffered"


@contextmanager
def _mocked_side_effects(oldest_batch_age: float | None = None, write_resolution: bool = True):
    """Stub every outside effect: Temporal schedules, the sourcebatch probe, the flag, and S3."""
    with (
        patch(f"{_CMD}.psycopg.Connection.connect") as mock_connect,
        patch(f"{_CMD}.BatchQueue.get_oldest_non_terminal_batch_age_seconds", return_value=oldest_batch_age),
        patch(f"{_CMD}.is_cdc_write_resolution_enabled", return_value=write_resolution),
        patch(f"{_CMD}.purge_buffer_prefix") as mock_purge,
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

    def test_rollback_restores_legacy_and_keeps_buffer_files(self):
        source = self._source(ingest_mode="buffered")
        schema = self._schema(source, "users")

        with _mocked_side_effects() as mocks:
            self._run(source, rollback=True)

        source.refresh_from_db()
        assert source.job_inputs["cdc_ingest_mode"] == "legacy"
        # Leftover files are harmless — the position guard no-ops a stale replay and the TTL clears
        # them — and purging would throw away changes the legacy lane has not delivered yet.
        mocks["purge"].assert_not_called()
        mocks["pause_schema"].assert_called_once_with(str(schema.id))

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

    def test_dry_run_changes_nothing(self):
        source = self._source()
        self._schema(source, "users")

        with _mocked_side_effects() as mocks:
            output = self._run(source, dry_run=True)

        source.refresh_from_db()
        assert "cdc_ingest_mode" not in source.job_inputs
        assert "Dry run" in output
        mocks["pause"].assert_not_called()
        mocks["purge"].assert_not_called()

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
