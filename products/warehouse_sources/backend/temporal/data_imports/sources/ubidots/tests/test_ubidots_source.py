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

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://things.ubidots.com/api/v1.6/variables/abc/values",),
            ("403 Client Error: Forbidden for url: https://things.ubidots.com/api/v2.0/events/",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

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
