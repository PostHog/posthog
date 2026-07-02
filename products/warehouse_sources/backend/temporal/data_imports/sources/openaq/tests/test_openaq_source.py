from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpenAQSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.openaq import OpenAQResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.settings import OPENAQ_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source import OpenAQSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> OpenAQSourceConfig:
    return OpenAQSourceConfig(api_key="key")


class TestOpenAQSourceConfig:
    def test_source_type(self) -> None:
        assert OpenAQSource().source_type == ExternalDataSourceType.OPENAQ

    def test_api_key_field_is_secret_password(self) -> None:
        fields = OpenAQSource().get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert api_key.name == "api_key"
        assert api_key.type.value == "password"
        assert api_key.required is True
        assert api_key.secret is True

    def test_docs_url_matches_slug(self) -> None:
        # The website derives the doc slug from this URL; a mismatch 404s the Supported tables section.
        assert OpenAQSource().get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/openaq"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog, so the public docs may render the table list.
        assert OpenAQSource.lists_tables_without_credentials is True


class TestOpenAQSchemas:
    def test_all_endpoints_exposed(self) -> None:
        names = {s.name for s in OpenAQSource().get_schemas(_config(), team_id=1)}
        assert names == set(OPENAQ_ENDPOINTS.keys())

    @parameterized.expand(
        [
            ("measurements", True, False),
            ("measurements_hourly", True, False),
            ("measurements_daily", True, False),
            ("locations", False, True),
            ("parameters", False, True),
            ("sensors", False, True),
        ]
    )
    def test_incremental_and_default_sync_flags(
        self, endpoint: str, expected_incremental: bool, expected_default_sync: bool
    ) -> None:
        # Only the per-sensor measurement streams have a server-side datetime filter, so only they are
        # incremental; and because they're request-heavy they must be off by default.
        schema = {s.name: s for s in OpenAQSource().get_schemas(_config(), team_id=1)}[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.should_sync_default is expected_default_sync

    def test_measurement_primary_key_is_sensor_and_period(self) -> None:
        # A non-unique key seeds duplicate rows that every later merge multi-matches; measurements have
        # no id of their own, so the key must be (sensor_id, datetime_from).
        schema = {s.name: s for s in OpenAQSource().get_schemas(_config(), team_id=1)}["measurements"]
        assert schema.detected_primary_keys == ["sensor_id", "datetime_from"]

    def test_names_filter_narrows_schemas(self) -> None:
        schemas = OpenAQSource().get_schemas(_config(), team_id=1, names=["parameters"])
        assert [s.name for s in schemas] == ["parameters"]


class TestOpenAQNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.openaq.org/v3/locations?page=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.openaq.org/v3/sensors/1/measurements"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        non_retryable = OpenAQSource().get_non_retryable_errors()
        assert any(key in observed for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.openaq.org/v3/locations"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.openaq.org/v3/locations"),
            ("timeout", "HTTPSConnectionPool(host='api.openaq.org', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        non_retryable = OpenAQSource().get_non_retryable_errors()
        assert not any(key in observed for key in non_retryable)


class TestOpenAQValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_validate_credentials(self, _name: str, upstream_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source.validate_openaq_credentials",
            return_value=upstream_ok,
        ):
            valid, message = OpenAQSource().validate_credentials(_config(), team_id=1)
        assert valid is upstream_ok
        assert (message is None) is upstream_ok


class TestOpenAQPipelineWiring:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = OpenAQSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OpenAQResumeConfig

    def _inputs(self, **overrides: Any) -> MagicMock:
        inputs = MagicMock()
        inputs.schema_name = overrides.get("schema_name", "measurements")
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
        inputs.db_incremental_field_last_value = overrides.get(
            "db_incremental_field_last_value", "2026-01-01T00:00:00Z"
        )
        return inputs

    def test_source_for_pipeline_passes_incremental_value_when_enabled(self) -> None:
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source.openaq_source"
        ) as mock_source:
            OpenAQSource().source_for_pipeline(_config(), manager, self._inputs())
        _, kwargs = mock_source.call_args
        assert kwargs["endpoint"] == "measurements"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_incremental_value_when_disabled(self) -> None:
        # When the schema isn't synced incrementally, the last value must not leak into a filter.
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source.openaq_source"
        ) as mock_source:
            OpenAQSource().source_for_pipeline(
                _config(),
                manager,
                self._inputs(should_use_incremental_field=False),
            )
        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None


class TestOpenAQDocumentedTables:
    def test_documented_tables_include_curated_descriptions(self) -> None:
        # lists_tables_without_credentials + canonical descriptions feed the public Supported tables docs.
        tables = {t["name"]: t for t in OpenAQSource().get_documented_tables()}
        assert set(tables) == set(OPENAQ_ENDPOINTS.keys())
        # locations has no schema-level description, so the curated canonical one is surfaced.
        assert tables["locations"]["description"].startswith("Monitoring locations")
        assert "Incremental" in tables["measurements"]["sync_methods"]
        assert "Full refresh" in tables["locations"]["sync_methods"]
