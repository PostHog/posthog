from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.membrain import (
    MembrainSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.source import MembrainSource


class TestMembrainSource:
    def setup_method(self) -> None:
        self.source = MembrainSource()
        self.team_id = 123
        self.config = MembrainSourceConfig(api_key="mb-key", subdomain="acme")

    def test_connection_host_fields_include_subdomain(self) -> None:
        # The API key is sent to the customer-controlled `{subdomain}.membrain.com` host, so
        # editing the subdomain must force re-entering the key.
        assert self.source.connection_host_fields == ["subdomain"]

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://acme.membrain.com/API/v2/companies/",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://acme.membrain.com/API/v2/contacts/",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://acme.membrain.com/API/v2/tickets/",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://acme.membrain.com/API/v2/activities/",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("path_traversal", "acme.membrain.com/evil"),
            ("dotted_host", "evil.example"),
            ("empty", ""),
            ("whitespace", "acme corp"),
            ("leading_hyphen", "-acme"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_validate_credentials_rejects_invalid_subdomain_without_probe(self, _name: str, subdomain: str) -> None:
        config = MembrainSourceConfig(api_key="mb-key", subdomain=subdomain)
        with scripted_network([]) as network:
            valid, message = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert message == "Membrain account subdomain is invalid"
        assert network.requests_log == []

    def test_validate_credentials_delegates_to_probe(self) -> None:
        with scripted_network([ScriptedResponse(json=[])]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (True, None)
        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == "https://acme.membrain.com/API/v2/users/"
        assert network.requests_log[0].headers["apikey"] == "mb-key"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.membrain.source.membrain_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "companies"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "mb-key"
        assert kwargs["subdomain"] == "acme"
        assert kwargs["endpoint"] == "companies"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        result = SourceDriver(self.source, self.config).run("not_a_table", [])

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == "Unknown Membrain schema 'not_a_table'"
