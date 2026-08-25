import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.exceptions import CDCHandledExternally
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

_SCHEMA_MODEL = "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema"
_MANAGER = "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager"


def _schema(ingest_mode: str = "buffered", **overrides) -> MagicMock:
    schema = MagicMock()
    schema.name = "users"
    schema.is_cdc = overrides.get("is_cdc", True)
    schema.cdc_mode = overrides.get("cdc_mode", "streaming")
    schema.cdc_table_mode = overrides.get("cdc_table_mode", "consolidated")
    schema.initial_sync_complete = overrides.get("initial_sync_complete", True)
    schema.sync_type_config = {}
    schema.schema_metadata = {}
    schema.resolved_s3_folder_name = None
    schema.primary_key_columns = ["id"]
    schema.source.job_inputs = {"cdc_enabled": True, "cdc_ingest_mode": ingest_mode}
    return schema


def _inputs(reset_pipeline: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name="users",
        schema_id="3f7c1f4e-0000-0000-0000-000000000001",
        source_id="3f7c1f4e-0000-0000-0000-000000000002",
        team_id=7,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=reset_pipeline,
    )


def _dispatch(schema: MagicMock, inputs: SourceInputs, backlog: bool = False):
    with (
        patch(f"{_SCHEMA_MODEL}.objects") as objects,
        patch(f"{_MANAGER}.has_pending_legacy_backlog", return_value=backlog),
        patch.object(PostgresSource, "make_ssh_tunnel_func", return_value=MagicMock()),
    ):
        objects.select_related.return_value.get.return_value = schema
        return PostgresSource().source_for_pipeline(MagicMock(), inputs)


class TestBufferedDispatch:
    def test_a_flipped_schema_is_consumed_here_instead_of_by_the_extraction_workflow(self):
        response = _dispatch(_schema(), _inputs())

        assert response.name == "users"
        assert response.cdc_write_mode == "incremental_merge"

    @pytest.mark.parametrize(
        "overrides,ingest_mode",
        [
            ({}, "legacy"),
            ({"cdc_table_mode": "cdc_only"}, "buffered"),
            ({"initial_sync_complete": False}, "buffered"),
        ],
    )
    def test_a_schema_the_buffer_does_not_serve_stays_with_the_extraction_workflow(self, overrides, ingest_mode):
        with pytest.raises(CDCHandledExternally):
            _dispatch(_schema(ingest_mode, **overrides), _inputs())

    def test_a_pending_legacy_backlog_yields_an_empty_run_rather_than_pausing_the_schedule(self):
        response = _dispatch(_schema(), _inputs(), backlog=True)

        assert list(response.items()) == []

    def test_a_reset_on_a_streaming_buffered_schema_is_refused(self):
        with pytest.raises(ValueError, match="cdc_mode='snapshot'"):
            _dispatch(_schema(), _inputs(reset_pipeline=True))
