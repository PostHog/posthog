import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.source import BreezometerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BreezometerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str = "air_quality_current") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestBreezometerSource:
    def setup_method(self):
        self.source = BreezometerSource()
        self.team_id = 123
        self.config = BreezometerSourceConfig(api_key="test-key", locations="51.5,-0.12,London")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BREEZOMETER

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Breezometer"
        assert config.label == "BreezoMeter"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/breezometer.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/breezometer"

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        by_name = {field.name: field for field in fields if isinstance(field, SourceFieldInputConfig)}
        assert set(by_name) == {"api_key", "locations"}

        api_key_field = by_name["api_key"]
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        locations_field = by_name["locations"]
        assert locations_field.type == SourceFieldInputConfigType.TEXTAREA
        assert locations_field.required is True
        assert locations_field.secret is False

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_supports_append_not_incremental(self, endpoint):
        # No endpoint exposes a server-side change cursor, so none is truly incremental;
        # all support append so users can accumulate snapshots over time.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is True
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["dt_iso"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["pollen_forecast"])

        assert [schema.name for schema in schemas] == ["pollen_forecast"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize("host", ["airquality.googleapis.com", "pollen.googleapis.com"])
    @pytest.mark.parametrize("status", ["400 Client Error: Bad Request", "403 Client Error: Forbidden"])
    def test_non_retryable_errors_cover_both_hosts(self, host, status):
        errors = self.source.get_non_retryable_errors()

        assert any(status in key and host in key for key in errors)

    def test_documented_tables_render_without_credentials(self):
        # Exercises the public-docs path: a credential-free placeholder config must list every table.
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid API key"), False, "Invalid API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.source.validate_breezometer_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "air_quality_current")

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.locations)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.source.breezometer_source"
    )
    def test_source_for_pipeline_plumbs_args(self, mock_breezometer_source):
        inputs = _make_inputs(schema_name="pollen_forecast")

        self.source.source_for_pipeline(self.config, inputs)

        mock_breezometer_source.assert_called_once_with(
            api_key="test-key",
            endpoint="pollen_forecast",
            locations_raw="51.5,-0.12,London",
            logger=inputs.logger,
        )
