import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.membrain import (
    MembrainSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain import source as source_module
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
        with mock.patch.object(source_module, "validate_credentials") as mock_validate:
            valid, message = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert message == "Membrain account subdomain is invalid"
        mock_validate.assert_not_called()

    def test_validate_credentials_delegates_to_probe(self) -> None:
        # The status and body mapping is covered by the membrain.validate_credentials unit
        # tests; here we only guard that the source extracts the credentials and returns the
        # probe result unchanged.
        with mock.patch.object(source_module, "validate_credentials", return_value=(True, None)) as mock_validate:
            result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (True, None)
        mock_validate.assert_called_once_with("mb-key", "acme")

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
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Membrain schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
