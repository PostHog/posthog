from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smaily import SmailySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source import SmailySource


class TestSmailySource:
    def setup_method(self) -> None:
        self.source = SmailySource()
        self.team_id = 123
        self.config = SmailySourceConfig(subdomain="acme", username="user", password="pass")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # The stored password is sent to `{subdomain}.sendsmaily.net`; retargeting the subdomain
        # without re-entering the password would let an editor replay the credential elsewhere.
        assert self.source.connection_host_fields == ["subdomain"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source.validate_credentials")
    def test_validate_credentials_delegates_with_config_values(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in smaily.validate_credentials; here we only assert
        # the source probes with the configured credentials and returns the verdict unchanged.
        mock_validate.return_value = (False, "Invalid Smaily credentials")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("acme", "user", "pass")
        assert result == (False, "Invalid Smaily credentials")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source.smaily_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["username"] == "user"
        assert kwargs["password"] == "pass"
        assert kwargs["endpoint"] == "campaigns"
        assert kwargs["resumable_source_manager"] is manager
