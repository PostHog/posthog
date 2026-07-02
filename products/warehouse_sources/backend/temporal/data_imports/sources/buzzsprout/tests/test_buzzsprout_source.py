import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.source import BuzzsproutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BuzzsproutSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str = "episodes") -> SourceInputs:
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


class TestBuzzsproutSource:
    def setup_method(self):
        self.source = BuzzsproutSource()
        self.team_id = 123
        self.config = BuzzsproutSourceConfig(api_token="test-token", podcast_id="123456")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BUZZSPROUT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Buzzsprout"
        assert config.label == "Buzzsprout"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/buzzsprout.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/buzzsprout"

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        by_name = {field.name: field for field in fields if isinstance(field, SourceFieldInputConfig)}
        assert set(by_name) == {"api_token", "podcast_id"}

        token_field = by_name["api_token"]
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

        podcast_field = by_name["podcast_id"]
        assert podcast_field.type == SourceFieldInputConfigType.TEXT
        assert podcast_field.required is True
        # The podcast ID is not a secret — it scopes the URL but grants no access on its own.
        assert podcast_field.secret is False

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_full_refresh_only(self, endpoint):
        # Buzzsprout has no server-side timestamp filter, so every endpoint is full refresh only.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["episodes"])

        assert [schema.name for schema in schemas] == ["episodes"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_non_retryable_errors_include_auth_failures(self):
        errors = self.source.get_non_retryable_errors()

        assert any("401 Client Error: Unauthorized" in key for key in errors)
        assert any("403 Client Error: Forbidden" in key for key in errors)
        # The match must be anchored to the Buzzsprout host so unrelated 401s don't trip it.
        assert all("https://www.buzzsprout.com" in key for key in errors)

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)

    def test_lists_tables_without_credentials(self):
        # The static endpoint catalog has no I/O, so the public docs table list opts in.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Buzzsprout API token"), False, "Invalid Buzzsprout API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.source.validate_buzzsprout_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "episodes")

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token, self.config.podcast_id)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.source.buzzsprout_source")
    def test_source_for_pipeline_plumbs_args(self, mock_buzzsprout_source):
        inputs = _make_inputs(schema_name="podcasts")

        self.source.source_for_pipeline(self.config, inputs)

        mock_buzzsprout_source.assert_called_once_with(
            api_token="test-token",
            podcast_id="123456",
            endpoint="podcasts",
            logger=inputs.logger,
        )
