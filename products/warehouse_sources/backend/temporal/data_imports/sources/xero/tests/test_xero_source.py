import datetime
from typing import Any, Optional

import pytest
from unittest import mock

from django.test import override_settings

import requests

from posthog.schema import ReleaseStatus, SourceFieldOauthAccountSelectConfig, SourceFieldOauthConfig

from posthog.models.integration import OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xero import XeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    XERO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.source import XeroSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.xero import XeroAuthError, XeroResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.xero.source"


def _inputs(schema_name: str = "invoices", **overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = schema_name
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value")
    return inputs


class TestXeroSource:
    def setup_method(self) -> None:
        self.source = XeroSource()
        self.team_id = 123
        self.config = XeroSourceConfig(xero_integration_id=456, tenant_id="tenant-a")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.XERO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Xero"
        assert config.label == "Xero"
        assert config.iconPath == "/static/services/xero.png"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource

        oauth_field, account_field = config.fields
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert (oauth_field.name, oauth_field.kind, oauth_field.required) == ("xero_integration_id", "xero", True)

        assert isinstance(account_field, SourceFieldOauthAccountSelectConfig)
        assert account_field.name == "tenant_id"
        assert account_field.required is True
        assert account_field.integrationField == "xero_integration_id"
        assert account_field.integrationKind == "xero"

    @override_settings(XERO_APP_CLIENT_ID="client-id", XERO_APP_CLIENT_SECRET="client-secret")
    def test_required_scopes_match_the_posthog_xero_app(self) -> None:
        # A mismatch either warns about a scope the app never asks for, or stays silent when a
        # connection really is missing one.
        oauth_field = self.source.get_source_config.fields[0]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.requiredScopes is not None
        assert set(oauth_field.requiredScopes.split()) == set(
            OauthIntegration.oauth_config_for_kind("xero").scope.split()
        )

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint_name", sorted(ENDPOINTS))
    def test_incremental_support_matches_the_endpoint_catalog(self, endpoint_name: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint_name)
        expected_field = XERO_ENDPOINTS[endpoint_name].incremental_field

        assert schema.supports_incremental is (expected_field is not None)
        assert [f["field"] for f in schema.incremental_fields] == ([expected_field] if expected_field else [])

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["invoices", "nope"])
        assert [s.name for s in schemas] == ["invoices"]

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all(t["description"] for t in tables)

    def test_canonical_descriptions_only_key_real_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) <= set(ENDPOINTS)
        for endpoint_name, entry in descriptions.items():
            incremental = XERO_ENDPOINTS[endpoint_name].incremental_field
            if incremental is not None:
                assert incremental in entry["columns"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.xero.com/api.xro/2.0/Invoices",
            "403 Client Error: Forbidden for url: https://api.xero.com/api.xro/2.0/Journals",
            "Xero organization tenant-z is not connected to this app",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.xero.com/api.xro/2.0/Invoices",
            "503 Server Error: Service Unavailable for url: https://api.xero.com/api.xro/2.0/Invoices",
            "Read timed out",
        ],
    )
    def test_non_retryable_errors_leave_transient_failures_alone(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "config",
        [
            XeroSourceConfig(xero_integration_id=0, tenant_id="tenant-a"),
            XeroSourceConfig(xero_integration_id=456, tenant_id=""),
        ],
    )
    def test_validate_credentials_requires_a_connection_and_an_organization(self, config: XeroSourceConfig) -> None:
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "required" in message

    @mock.patch(f"{SOURCE_MODULE}.validate_xero_credentials")
    @mock.patch.object(XeroSource, "_access_token", return_value="access-1")
    def test_validate_credentials_probes_with_the_integration_token(
        self, _mock_access_token: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = (True, None)

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.kwargs == {"access_token": "access-1", "tenant_id": "tenant-a"}

    @pytest.mark.parametrize(
        "failure, expected_message",
        [
            (ValueError("Integration not found: 456"), "Integration not found: 456"),
            (XeroAuthError("Could not refresh the Xero credentials."), "Could not refresh the Xero credentials."),
            (requests.ConnectionError("connection reset"), "Could not reach Xero"),
        ],
    )
    @mock.patch.object(XeroSource, "_access_token")
    def test_validate_credentials_surfaces_connection_failures(
        self, mock_access_token: mock.MagicMock, failure: Exception, expected_message: str
    ) -> None:
        mock_access_token.side_effect = failure

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None and expected_message in message

    @mock.patch(f"{SOURCE_MODULE}.XeroClient")
    @mock.patch.object(XeroSource, "_access_token", return_value="access-1")
    def test_get_oauth_accounts_lists_connected_organizations(
        self, _mock_access_token: mock.MagicMock, mock_client: mock.MagicMock
    ) -> None:
        mock_client.return_value.list_organisations.return_value = [
            {"tenantId": "tenant-a", "tenantName": "Acme"},
            {"tenantId": "tenant-b"},
        ]

        accounts = self.source.get_oauth_accounts(456, self.team_id)

        assert [(a.value, a.display_name) for a in accounts] == [("tenant-a", "Acme"), ("tenant-b", "tenant-b")]

    @pytest.mark.parametrize(
        "failure, expected_message",
        [
            (ValueError("Integration not found: 456"), "could not be found"),
            (XeroAuthError("Could not refresh the Xero credentials."), "Could not refresh the Xero credentials."),
            (requests.ConnectionError("connection reset"), "Could not reach Xero"),
        ],
    )
    @mock.patch.object(XeroSource, "_access_token")
    def test_get_oauth_accounts_maps_token_failures_to_listing_errors(
        self, mock_access_token: mock.MagicMock, failure: Exception, expected_message: str
    ) -> None:
        mock_access_token.side_effect = failure

        with pytest.raises(IntegrationAccountListingError, match=expected_message):
            self.source.get_oauth_accounts(456, self.team_id)

    @pytest.mark.parametrize(
        "status_code, expected_message",
        [
            (401, "Xero rejected this connection"),
            (429, "rate limiting"),
            (503, "trouble responding"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.XeroClient")
    @mock.patch.object(XeroSource, "_access_token", return_value="access-1")
    def test_get_oauth_accounts_maps_api_failures_to_listing_errors(
        self,
        _mock_access_token: mock.MagicMock,
        mock_client: mock.MagicMock,
        status_code: int,
        expected_message: str,
    ) -> None:
        response = requests.Response()
        response.status_code = status_code
        mock_client.return_value.list_organisations.side_effect = requests.HTTPError(response=response)

        with pytest.raises(IntegrationAccountListingError, match=expected_message):
            self.source.get_oauth_accounts(456, self.team_id)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is XeroResumeConfig

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, expected",
        [
            (True, datetime.datetime(2024, 3, 1), datetime.datetime(2024, 3, 1)),
            # A stored watermark must not leak into a full-refresh run.
            (False, datetime.datetime(2024, 3, 1), None),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.xero_source")
    @mock.patch.object(XeroSource, "get_oauth_integration")
    def test_source_for_pipeline_plumbs_arguments(
        self,
        mock_get_oauth_integration: mock.MagicMock,
        mock_xero_source: mock.MagicMock,
        should_use_incremental_field: bool,
        last_value: datetime.datetime,
        expected: Optional[datetime.datetime],
    ) -> None:
        mock_get_oauth_integration.return_value = mock.MagicMock(access_token="access-1")
        manager = mock.MagicMock()
        inputs = _inputs(
            "contacts",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_xero_source.call_args.kwargs
        assert kwargs["access_token"] == "access-1"
        assert kwargs["tenant_id"] == "tenant-a"
        assert kwargs["endpoint_name"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == expected

    @mock.patch.object(XeroSource, "get_oauth_integration")
    def test_source_for_pipeline_without_an_access_token(self, mock_get_oauth_integration: mock.MagicMock) -> None:
        mock_get_oauth_integration.return_value = mock.MagicMock(access_token=None)

        with pytest.raises(ValueError, match="Xero access token not found"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), _inputs())


class TestXeroSettings:
    @pytest.mark.parametrize("endpoint_name", sorted(ENDPOINTS))
    def test_endpoint_catalog_is_internally_consistent(self, endpoint_name: str) -> None:
        endpoint = XERO_ENDPOINTS[endpoint_name]
        assert endpoint.name == endpoint_name
        assert endpoint.primary_key
        # A partition key must be a creation timestamp — partitioning on a mutable field
        # rewrites every partition on each sync.
        assert endpoint.partition_key in (None, "CreatedDateUTC")
        assert (endpoint_name in INCREMENTAL_FIELDS) is (endpoint.incremental_field is not None)

    def test_only_journals_uses_offset_pagination(self) -> None:
        offset_endpoints = [name for name, e in XERO_ENDPOINTS.items() if e.pagination == "offset"]
        assert offset_endpoints == ["journals"]
