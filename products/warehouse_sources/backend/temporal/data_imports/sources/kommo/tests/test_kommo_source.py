import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kommo import KommoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.settings import (
    ENDPOINT_CONFIG,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.source import KommoSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kommo.source"

INCREMENTAL_ENDPOINTS = {"Leads", "Contacts", "Companies", "LeadNotes", "ContactNotes", "CompanyNotes"}


class TestKommoSource:
    def setup_method(self) -> None:
        self.source = KommoSource()
        self.team_id = 123
        self.config = KommoSourceConfig(subdomain="acme", api_key="test-token")

    def test_subdomain_is_declared_as_a_connection_host_field(self) -> None:
        # The token is sent to https://<subdomain>.kommo.com, so editing the subdomain must
        # force the token to be re-entered instead of reusing the stored one.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_api_version_is_pinned_to_the_path_the_source_calls(self) -> None:
        assert self.source.supported_versions == ("v4",)
        assert self.source.default_version == "v4"
        assert self.source.resolve_api_version(None) == "v4"
        assert all(endpoint.path.startswith("/api/v4/") for endpoint in ENDPOINT_CONFIG.values())

    def test_get_schemas_marks_only_ordered_endpoints_incremental(self) -> None:
        # Tasks and Events expose a timestamp filter but no ordering parameter for it, so they
        # must stay full refresh rather than advertising a watermark we cannot trust.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        assert {name for name, schema in schemas.items() if schema.supports_incremental} == INCREMENTAL_ENDPOINTS
        assert all(
            [f["field"] for f in schemas[name].incremental_fields] == ["updated_at"] for name in INCREMENTAL_ENDPOINTS
        )

    def test_incremental_fields_only_declared_where_a_server_side_filter_exists(self) -> None:
        assert set(INCREMENTAL_FIELDS) == {
            name for name, endpoint in ENDPOINT_CONFIG.items() if endpoint.incremental_param is not None
        }

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.kommo.com/api/v4/leads",
            "403 Client Error: Forbidden for url: https://acme.kommo.com/api/v4/users",
            "402 Client Error: Payment Required for url: https://acme.kommo.com/api/v4/events",
            "404 Client Error: Not Found for url: https://acme.kommo.com/api/v4/leads",
        ],
    )
    def test_non_retryable_errors_match_auth_and_billing_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.kommo.com/api/v4/leads",
            "500 Server Error for url: https://acme.kommo.com/api/v4/leads",
        ],
    )
    def test_non_retryable_errors_leave_transient_failures_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize("subdomain", ["acme.amocrm.ru", "evil.example.com/acme", "", "acme_corp"])
    @mock.patch(f"{_MODULE}.validate_kommo_credentials")
    def test_validate_credentials_rejects_a_bad_subdomain_without_calling_kommo(
        self, mock_validate: mock.MagicMock, subdomain: str
    ) -> None:
        config = KommoSourceConfig(subdomain=subdomain, api_key="test-token")

        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message is not None and "subdomain" in message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize("raw_subdomain", ["acme", "https://acme.kommo.com/"])
    @mock.patch(f"{_MODULE}.validate_kommo_credentials")
    def test_validate_credentials_probes_the_normalized_account(
        self, mock_validate: mock.MagicMock, raw_subdomain: str
    ) -> None:
        mock_validate.return_value = (True, None)
        config = KommoSourceConfig(subdomain=raw_subdomain, api_key="test-token")

        assert self.source.validate_credentials(config, self.team_id) == (True, None)
        mock_validate.assert_called_once_with("test-token", "acme")

    @mock.patch(f"{_MODULE}.kommo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Leads"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()
        config = KommoSourceConfig(subdomain="https://acme.kommo.com", api_key="test-token")

        response = self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "test-token"
        assert kwargs["subdomain"] == "acme"
        assert kwargs["endpoint"] == "Leads"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["resumable_source_manager"] is manager
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("schema_name", ["Tasks", "Events", "Pipelines"])
    @mock.patch(f"{_MODULE}.kommo_source")
    def test_source_for_pipeline_forces_full_refresh_on_unordered_endpoints(
        self, mock_source: mock.MagicMock, schema_name: str
    ) -> None:
        # A schema row can carry should_use_incremental_field from an older config; the source
        # must not honour it for an endpoint with no server-side filter.
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    @mock.patch(f"{_MODULE}.kommo_source")
    def test_source_for_pipeline_rejects_a_bad_subdomain(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Leads"
        config = KommoSourceConfig(subdomain="evil.example.com", api_key="test-token")

        with pytest.raises(ValueError):
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        mock_source.assert_not_called()
