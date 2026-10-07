import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sagehr import SageHRSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.source import SageHRSource


class TestSageHRSource:
    def setup_method(self) -> None:
        self.source = SageHRSource()
        self.team_id = 123
        self.config = SageHRSourceConfig(subdomain="acme", api_key="sage-key")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # The API key is sent to `<subdomain>.sage.hr`, so retargeting the subdomain must force the
        # editor to re-enter the key.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["employees"])
        assert len(schemas) == 1
        assert schemas[0].name == "employees"

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://acme.sage.hr/api/employees?page=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://other-co.sage.hr/api/teams?page=2"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://acme.sage.hr/api/employees"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://acme.sage.hr/api/teams"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.source.sage_hr_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "employees"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["api_key"] == "sage-key"
        assert kwargs["endpoint"] == "employees"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Sage HR schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
