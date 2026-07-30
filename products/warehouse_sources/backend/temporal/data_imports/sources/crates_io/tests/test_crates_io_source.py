import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.source import CratesIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CratesIOSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str = "crates") -> SourceInputs:
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


class TestCratesIOSource:
    def setup_method(self):
        self.source = CratesIOSource()
        self.team_id = 123
        self.config = CratesIOSourceConfig(crates="serde\ntokio")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CRATESIO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "CratesIO"
        assert config.label == "crates.io"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/crates-io"
        # A finished source ships visible; re-adding the flag would hide it from every user.
        assert not config.unreleasedSource

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        by_name = {field.name: field for field in fields if isinstance(field, SourceFieldInputConfig)}
        assert set(by_name) == {"crates"}

        crates_field = by_name["crates"]
        assert crates_field.type == SourceFieldInputConfigType.TEXTAREA
        assert crates_field.required is True
        # No auth, so the field carries no secret.
        assert crates_field.secret is False

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_full_refresh_only(self, endpoint):
        # crates.io exposes no server-side timestamp filter, so no stream is incremental or append.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["versions"])

        assert [schema.name for schema in schemas] == ["versions"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Crate 'x' was not found on crates.io."), False, "Crate 'x' was not found on crates.io."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.source.validate_crates_io_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "crates")

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.crates)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.source.crates_io_source")
    def test_source_for_pipeline_plumbs_args(self, mock_crates_io_source):
        inputs = _make_inputs(schema_name="downloads")

        self.source.source_for_pipeline(self.config, inputs)

        mock_crates_io_source.assert_called_once_with(
            endpoint="downloads",
            crates_raw="serde\ntokio",
            logger=inputs.logger,
        )
