from base64 import b64encode

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.partnerize import (
    PartnerizeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.partnerize import DEFAULT_START_DATE
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source import PartnerizeSource

INCREMENTAL_ENDPOINTS = {"conversions", "clicks"}


class TestPartnerizeSource:
    def setup_method(self) -> None:
        self.source = PartnerizeSource()
        self.team_id = 123
        self.config = PartnerizeSourceConfig(
            application_key="app-key", user_api_key="api-key", publisher_id="111111l92"
        )

    @parameterized.expand(
        [
            (
                "unknown_publisher",
                "404 Client Error: Not Found for url: https://api.partnerize.com/user/publisher/111111l92/campaign/a",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_validate_credentials_delegates_with_config_values(self) -> None:
        # The status-to-message mapping lives in partnerize.validate_credentials; here we only assert
        # the source probes with the configured credentials and returns the delegate's verdict.
        with scripted_network([ScriptedResponse(status=401)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (
            False,
            "Invalid Partnerize API credentials. Check your user application key and user API key.",
        )
        assert [request.path for request in network.requests_log] == ["/user/publisher/111111l92"]
        assert network.requests_log[0].headers["authorization"] == f"Basic {b64encode(b'app-key:api-key').decode()}"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.partnerize_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "conversions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01 12:00:00"
        inputs.incremental_field = "conversion_time"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["application_key"] == "app-key"
        assert kwargs["user_api_key"] == "api-key"
        assert kwargs["publisher_id"] == "111111l92"
        assert kwargs["endpoint"] == "conversions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01 12:00:00"
        assert kwargs["incremental_field"] == "conversion_time"

    def test_source_for_pipeline_drops_watermark_for_full_refresh(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "conversions",
            [ScriptedResponse(json={"conversions": []})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2024-05-01 12:00:00",
        )

        assert result.raised is None
        assert result.params("start_date") == [DEFAULT_START_DATE]
