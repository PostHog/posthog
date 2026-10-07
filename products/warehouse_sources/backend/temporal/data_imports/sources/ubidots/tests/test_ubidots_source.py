import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ubidots import (
    UbidotsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.settings import VALUES_ENDPOINT
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.source import UbidotsSource


class TestUbidotsSource:
    def setup_method(self) -> None:
        self.source = UbidotsSource()
        self.team_id = 123
        self.config = UbidotsSourceConfig(api_token="BBUS-token")

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert len(schemas) == 1
        assert schemas[0].name == "devices"

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://industrial.api.ubidots.com/api/v2.0/devices/",),
            ("403 Client Error: Forbidden for url: https://industrial.api.ubidots.com/api/v2.0/variables/",),
            ("401 Client Error: Unauthorized for url: https://things.ubidots.com/api/v1.6/variables/abc/values",),
            ("403 Client Error: Forbidden for url: https://things.ubidots.com/api/v2.0/events/",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://industrial.api.ubidots.com/api/v2.0/devices/",),
            ("429 Client Error: Too Many Requests for url: https://things.ubidots.com/api/v2.0/variables/",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_version_declarations(self) -> None:
        # v2.0 is the default new sources are stamped with; v1 stays supported so existing pins keep
        # syncing through the legacy v1.6 Data API.
        assert self.source.supported_versions == ("v1", "v2.0")
        assert self.source.default_version == "v2.0"

    @parameterized.expand(
        [
            ("no_pin_resolves_to_default", None, "v2.0"),
            ("legacy_pin_honored", "v1", "v1"),
            ("v2_pin_honored", "v2.0", "v2.0"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.source.ubidots_source")
    def test_source_for_pipeline_threads_resolved_api_version(
        self, _name: str, pin: str | None, expected: str, mock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = VALUES_ENDPOINT
        inputs.api_version = pin

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["api_version"] == expected

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Ubidots schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
