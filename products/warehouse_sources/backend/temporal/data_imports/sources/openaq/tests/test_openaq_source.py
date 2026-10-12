from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openaq import OpenAQSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source import OpenAQSource


def _config() -> OpenAQSourceConfig:
    return OpenAQSourceConfig(api_key="key")


class TestOpenAQSourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog, so the public docs may render the table list.
        assert OpenAQSource.lists_tables_without_credentials is True


class TestOpenAQSchemas:
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
    def _inputs(self, **overrides: Any) -> MagicMock:
        inputs = MagicMock()
        inputs.schema_name = overrides.get("schema_name", "measurements")
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
        inputs.db_incremental_field_last_value = overrides.get(
            "db_incremental_field_last_value", "2026-01-01T00:00:00Z"
        )
        return inputs

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
