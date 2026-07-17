import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.settings import (
    CODECOV_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source import CodecovSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodecovSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"commits", "coverage_trend"}
_FULL_REFRESH_ENDPOINTS = {"repos", "branches", "pulls", "flags", "components"}


def _make_inputs(**overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": "commits",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestCodecovSource:
    def setup_method(self):
        self.source = CodecovSource()
        self.team_id = 123
        self.config = CodecovSourceConfig(owner_username="acme", api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CODECOV

    def test_get_source_config_is_released(self):
        config = self.source.get_source_config

        assert config.name.value == "Codecov"
        assert config.label == "Codecov (Sentry)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/codecov"

        field_names = [f.name for f in config.fields]
        assert field_names == ["service", "owner_username", "api_token", "repositories"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        api_token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token"
        )
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.secret is True
        assert api_token_field.required is True

    def test_service_select_defaults_to_github(self):
        config = self.source.get_source_config
        service_field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))
        assert service_field.defaultValue == "github"
        assert {option.value for option in service_field.options} == {
            "github",
            "gitlab",
            "bitbucket",
            "github_enterprise",
            "gitlab_enterprise",
            "bitbucket_server",
        }

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["timestamp"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []
        # Incremental syncs re-pull boundary rows that only merge dedupes, so append stays off.
        for schema in schemas.values():
            assert schema.supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["commits"])
        assert [s.name for s in schemas] == ["commits"]

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(CODECOV_ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.codecov.io/api/v2/github/acme/repos?page_size=500",
            "403 Client Error: Forbidden for url: https://api.codecov.io/api/v2/github/acme/repos/r1/commits",
            "404 Client Error: Not Found for url: https://api.codecov.io/api/v2/github/acme/repos?page_size=500",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.codecov.io/api/v2/github/acme/repos",
            "500 Server Error: Internal Server Error for url: https://api.codecov.io/api/v2/github/acme/repos",
            "HTTPSConnectionPool(host='api.codecov.io', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Codecov API token"),
            ((False, 404), False, "Owner 'acme' not found on Codecov for the selected git provider"),
            ((False, None), False, "Could not connect to Codecov with the provided credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source.validate_codecov_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source.codecov_source")
    def test_source_for_pipeline_gates_incremental_value(self, mock_codecov_source):
        # A stale watermark must not leak into a full-refresh run.
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_codecov_source.call_args.kwargs
        assert kwargs["endpoint"] == "commits"
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
