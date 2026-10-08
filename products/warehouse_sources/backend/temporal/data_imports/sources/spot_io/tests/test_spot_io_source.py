from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotio import SpotIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source import SpotIoSource


class TestSpotIoSource:
    def setup_method(self) -> None:
        self.source = SpotIoSource()
        self.team_id = 123
        self.config = SpotIoSourceConfig(api_token="spot-token")

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.spotinst.io/aws/ec2/group",
            "403 Client Error: Forbidden for url: https://api.spotinst.io/aws/ec2/group",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source.spot_io_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_spot_io_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "elastigroups"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_spot_io_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
