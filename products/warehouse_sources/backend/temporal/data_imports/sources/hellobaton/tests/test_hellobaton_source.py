import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hellobaton import (
    HellobatonSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.source import HellobatonSource


class TestHellobatonSource:
    def setup_method(self):
        self.source = HellobatonSource()
        self.team_id = 123
        self.config = HellobatonSourceConfig(company="acme", api_key="key")

    def test_company_listed_as_connection_host_field(self):
        # The API key is sent to <company>.hellobaton.com, so retargeting the company must re-require it.
        assert self.source.connection_host_fields == ["company"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.hellobaton.com/api/projects/?api_key=key&page_size=100&page=1",
            "403 Client Error: Forbidden for url: https://acme.hellobaton.com/api/tasks/?api_key=key&page_size=100&page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.hellobaton.com/api/projects/",
            "500 Server Error: Internal Server Error for url: https://acme.hellobaton.com/api/projects/",
            "HTTPSConnectionPool(host='acme.hellobaton.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_all_full_refresh(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            # Baton exposes no server-side time filter, so nothing supports incremental/append.
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["projects"])
        assert len(schemas) == 1
        assert schemas[0].name == "projects"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Baton API key"),
            ((False, 403), False, "Could not connect to Baton with the provided company instance and API key"),
            ((False, None), False, "Could not connect to Baton with the provided company instance and API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.source.validate_hellobaton_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("acme", "key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.source.validate_hellobaton_credentials"
    )
    def test_validate_credentials_surfaces_bad_company(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Baton company: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Baton company" in (error_message or "")
