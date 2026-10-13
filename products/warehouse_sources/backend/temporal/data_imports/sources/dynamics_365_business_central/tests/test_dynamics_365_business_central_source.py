from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.settings import (
    BUSINESS_CENTRAL_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.source import (
    Dynamics365BusinessCentralSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365businesscentral import (
    Dynamics365BusinessCentralSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.source"


class TestDynamics365BusinessCentralSource:
    def setup_method(self) -> None:
        self.source = Dynamics365BusinessCentralSource()
        self.team_id = 123
        self.config = Dynamics365BusinessCentralSourceConfig(
            tenant_id="contoso.onmicrosoft.com",
            environment="production",
            client_id="client-id",
            client_secret="client-secret",
        )

    def test_connection_host_fields_force_credential_reentry(self) -> None:
        # Both feed the request path (`/{tenant_id}/{environment}/api/...`), so editing either
        # must re-require the client secret rather than retargeting the preserved credential.
        assert set(self.source.connection_host_fields) == {"tenant_id", "environment"}

    def test_api_version_matches_the_path_the_code_calls(self) -> None:
        # The version is a request path segment, so the pin must be the one the transport builds.
        assert self.source.supported_versions == ("v2.0",)
        assert self.source.default_version == "v2.0"
        assert self.source.api_docs_url.startswith("https://")
        assert self.source.resolve_api_version(None) == "v2.0"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.businesscentral.dynamics.com/v2.0/t/production/api/v2.0/companies",
            "403 Client Error: Forbidden for url: https://api.businesscentral.dynamics.com/v2.0/t/production/api/v2.0/companies(c-1)/customers",
            "HTTP 401 from the OAuth2 token endpoint: invalid_client [oauth2_token_config_error]",
        ],
    )
    def test_non_retryable_errors_match_permanent_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.businesscentral.dynamics.com/v2.0/t/production/api/v2.0/items",
            # A throttled token exchange is transient and carries no permanent marker.
            "HTTP 429 from the OAuth2 token endpoint",
        ],
    )
    def test_non_retryable_errors_leave_transient_failures_retryable(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_the_whole_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == set(INCREMENTAL_FIELDS)
        # `companies` and the document line tables have no server-side change filter.
        assert "companies" not in incremental
        assert "salesInvoiceLines" not in incremental

    def test_documented_tables_are_published_without_credentials(self) -> None:
        # `get_schemas` does no I/O, so the public docs can render the table catalog.
        assert self.source.lists_tables_without_credentials is True
        tables = {table["name"]: table for table in self.source.get_documented_tables()}

        assert set(tables) == set(ENDPOINTS)
        assert tables["customers"]["description"]

    def test_canonical_descriptions_key_off_schema_names(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions).issubset(set(ENDPOINTS))
        for name, entry in descriptions.items():
            assert entry["docs_url"].startswith("https://learn.microsoft.com/"), name
            if BUSINESS_CENTRAL_ENDPOINTS[name].company_scoped:
                # Every fan-out table's key starts with the stamped company id, so it must be documented.
                assert "company_id" in entry["columns"], name

    @mock.patch(f"{SOURCE_MODULE}.dynamics_365_business_central_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "salesInvoices"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.api_version = None
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"
        inputs.incremental_field = "lastModifiedDateTime"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs: dict[str, Any] = dict(mock_source.call_args.kwargs)
        assert kwargs["tenant_id"] == "contoso.onmicrosoft.com"
        assert kwargs["environment"] == "production"
        assert kwargs["client_id"] == "client-id"
        assert kwargs["client_secret"] == "client-secret"
        assert kwargs["endpoint"] == "salesInvoices"
        assert kwargs["resumable_source_manager"] is manager
        # An unpinned source resolves to the default version rather than passing None through.
        assert kwargs["api_version"] == "v2.0"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-06-01T00:00:00Z"
        assert kwargs["incremental_field"] == "lastModifiedDateTime"

    @mock.patch(f"{SOURCE_MODULE}.dynamics_365_business_central_source")
    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "salesInvoiceLines"
        inputs.api_version = "v2.0"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
