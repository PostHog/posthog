import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.exceptions import CDCHandledExternally
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

_SCHEMA_MODEL = "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema"
_JOB_MODEL = "products.warehouse_sources.backend.models.external_data_job.ExternalDataJob"
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


def _dispatch(
    schema: MagicMock,
    inputs: SourceInputs,
    in_flight: bool = False,
    job_version: str | None = ExternalDataJob.PipelineVersion.V3,
):
    job = None if job_version is None else MagicMock(pipeline_version=job_version)
    with (
        patch(f"{_SCHEMA_MODEL}.objects") as objects,
        patch(f"{_JOB_MODEL}.objects") as job_objects,
        patch(f"{_MANAGER}.has_batches_in_flight", return_value=in_flight),
        patch.object(PostgresSource, "make_ssh_tunnel_func", return_value=MagicMock()),
    ):
        objects.select_related.return_value.get.return_value = schema
        job_objects.filter.return_value.first.return_value = job
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
            ({"cdc_table_mode": "something_new"}, "buffered"),
            ({"initial_sync_complete": False}, "buffered"),
        ],
    )
    def test_a_schema_the_buffer_does_not_serve_stays_with_the_extraction_workflow(self, overrides, ingest_mode):
        with pytest.raises(CDCHandledExternally):
            _dispatch(_schema(ingest_mode, **overrides), _inputs())

    def test_a_cdc_only_schema_is_consumed_into_its_companion_table(self):
        response = _dispatch(_schema(cdc_table_mode="cdc_only"), _inputs())

        assert response.name == "users_cdc"
        assert response.cdc_write_mode == "scd2_append"

    def test_both_alternates_so_each_table_is_served_by_a_run_of_its_own(self):
        # A pipeline run writes one table, so serving both at once is not expressible. Each run
        # takes the lane the last one did not.
        schema = _schema(cdc_table_mode="both")
        assert _dispatch(schema, _inputs()).name == "users"

        schema.sync_type_config = {"cdc_buffer_listing": {"users": {"listed_at": "2026-08-28T12:00:00+00:00"}}}
        assert _dispatch(schema, _inputs()).name == "users_cdc"

    def test_a_v2_run_reaching_the_buffered_lane_fails_loudly(self):
        # The forcing keeps this unreachable; if a race or deploy skew gets past it, the run must
        # fail rather than consume without recording a load position.
        with pytest.raises(ValueError, match="requires v3"):
            _dispatch(_schema(), _inputs(), job_version="v2-non-dlt")

    def test_a_missing_job_row_does_not_block_buffered_consumption(self):
        response = _dispatch(_schema(), _inputs(), job_version=None)

        assert response.name == "users"

    def test_a_delivery_still_in_flight_fails_the_run_rather_than_completing_it(self):
        # An empty response completes the job, and a listing stamp matures into a deletion proof on
        # its job completing — so standing down would prove files a crashed attempt never drained.
        with pytest.raises(ValueError, match="deliveries in flight"):
            _dispatch(_schema(), _inputs(), in_flight=True)

    def test_a_reset_on_a_streaming_buffered_schema_is_refused(self):
        with pytest.raises(ValueError, match="cdc_mode='snapshot'"):
            _dispatch(_schema(), _inputs(reset_pipeline=True))
