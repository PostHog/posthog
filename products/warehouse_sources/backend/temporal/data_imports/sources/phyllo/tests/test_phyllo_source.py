import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.phyllo import PhylloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.source import PhylloSource


class TestPhylloSource:
    def setup_method(self) -> None:
        self.source = PhylloSource()
        self.team_id = 123
        self.config = PhylloSourceConfig(client_id="cid", client_secret="cs-secret", environment="production")

    def test_no_connection_host_fields(self) -> None:
        # The environment select only chooses between two Phyllo-controlled hosts, so an editor
        # can't retarget the preserved secret at a server they control.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.getphyllo.com/v1/users?limit=100&offset=0",),
            ("401 Client Error: Unauthorized for url: https://api.sandbox.getphyllo.com/v1/accounts",),
            ("403 Client Error: Forbidden for url: https://api.getphyllo.com/v1/social/contents",),
            ("403 Client Error: Forbidden for url: https://api.sandbox.getphyllo.com/v1/income/payouts",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.getphyllo.com/v1/users",),
            ("429 Client Error: Too Many Requests for url: https://api.getphyllo.com/v1/social/contents",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        # The source method forwards the credentials and environment to the shared validator and
        # returns its result verbatim.
        mock_validate.return_value = (False, "Invalid Phyllo client ID or secret for the selected environment")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Phyllo client ID or secret for the selected environment")
        mock_validate.assert_called_once_with("cid", "cs-secret", "production")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.source.phyllo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "social_contents"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "cs-secret"
        assert kwargs["environment"] == "production"
        assert kwargs["endpoint"] == "social_contents"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Phyllo schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
