import time

import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldOauthConfig, SourceFieldSelectConfig

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.quickbooks import (
    QuickBooksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.quickbooks import (
    QuickBooksResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    QUICKBOOKS_ENTITIES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.source import QuickBooksSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.source"

_INTEGRATION_ID = 42
_REALM_ID = "9130347"


def _integration(
    realm_id: str | None = _REALM_ID,
    access_token: str | None = "access-token",
    integration_id: str | None = _REALM_ID,
    expired: bool = False,
    kind: str = "quickbooks",
) -> Integration:
    """An unsaved integration row shaped like one the QuickBooks OAuth callback writes."""
    return Integration(
        id=_INTEGRATION_ID,
        team_id=123,
        kind=kind,
        integration_id=integration_id,
        config={
            **({"quickbooks_realm_id": realm_id} if realm_id else {}),
            "expires_in": 3600,
            "refreshed_at": int(time.time()) - (3600 if expired else 0),
        },
        sensitive_config={"refresh_token": "rt", **({"access_token": access_token} if access_token else {})},
    )


class TestQuickBooksSource:
    def setup_method(self) -> None:
        self.source = QuickBooksSource()
        self.team_id = 123
        self.config = QuickBooksSourceConfig(
            quickbooks_integration_id=_INTEGRATION_ID,
            environment="production",
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.QUICKBOOKS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "QuickBooks"
        assert config.label == "QuickBooks"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/quickbooks.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/quickbooks"

    def test_config_asks_only_for_a_connection_and_an_environment(self) -> None:
        config = self.source.get_source_config

        # The user connects through PostHog's Intuit app; nothing is pasted in by hand.
        oauth = next(f for f in config.fields if isinstance(f, SourceFieldOauthConfig))
        assert oauth.name == "quickbooks_integration_id"
        assert oauth.kind == "quickbooks"
        assert oauth.required is True
        assert oauth.requiredScopes == "com.intuit.quickbooks.accounting"

        environment = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))
        assert environment.name == "environment"
        assert [option.value for option in environment.options] == ["production", "sandbox"]
        assert environment.defaultValue == "production"

        assert [f.name for f in config.fields] == ["quickbooks_integration_id", "environment"]

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static entity catalog with no I/O, so public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://quickbooks.api.intuit.com/v3/company/1/query",
            "401 Client Error: Unauthorized for url: https://sandbox-quickbooks.api.intuit.com/v3/company/1/query",
            "403 Client Error: Forbidden for url: https://quickbooks.api.intuit.com/v3/company/1/query",
            "403 Client Error: Forbidden for url: https://sandbox-quickbooks.api.intuit.com/v3/company/1/query",
            # Reconnect signals from the OAuth layer can never be fixed by retrying.
            "Integration not found: 42",
            "QuickBooks app not configured",
            "QuickBooks access token could not be refreshed",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "429 Client Error: Too Many Requests for url: https://quickbooks.api.intuit.com/v3/company/1/query",
            "500 Server Error for url: https://quickbooks.api.intuit.com/v3/company/1/query",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert len(schemas) == len(ENDPOINTS)

    def test_singletons_are_full_refresh_only(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # One row per company, so a Metadata.LastUpdatedTime cursor buys nothing.
        for name in ("CompanyInfo", "Preferences"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    @pytest.mark.parametrize("entity_name", [name for name, e in QUICKBOOKS_ENTITIES.items() if not e.singleton])
    def test_regular_entities_advertise_the_last_updated_cursor(self, entity_name: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == entity_name)

        assert schema.supports_incremental is True
        assert schema.incremental_fields == INCREMENTAL_FIELDS[entity_name]
        assert [f["field"] for f in schema.incremental_fields] == ["LastUpdatedTime"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Invoice"])

        assert [schema.name for schema in schemas] == ["Invoice"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["Nope"]) == []

    def test_canonical_descriptions_cover_every_entity(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        assert all(entry.get("description") for entry in descriptions.values())

    @pytest.mark.parametrize(
        "credentials_valid, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Your QuickBooks connection is invalid or expired. Please reconnect it."),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_validate_credentials(
        self,
        mock_get_integration: mock.MagicMock,
        mock_validate: mock.MagicMock,
        credentials_valid: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_get_integration.return_value = _integration()
        mock_validate.return_value = credentials_valid

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_get_integration.assert_called_once_with(_INTEGRATION_ID, self.team_id)
        assert mock_validate.call_args.kwargs["realm_id"] == _REALM_ID
        assert mock_validate.call_args.kwargs["access_token"] == "access-token"
        assert mock_validate.call_args.kwargs["api_version"] == "v3"

    @pytest.mark.parametrize(
        "integration_error, expected_message",
        [
            (
                ValueError("Integration not found: 42"),
                "The linked QuickBooks connection no longer exists. Please reconnect your QuickBooks company.",
            ),
            (
                ValueError("Missing integration ID"),
                "QuickBooks is not connected. Please connect your QuickBooks company.",
            ),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_validate_credentials_maps_connection_errors(
        self,
        mock_get_integration: mock.MagicMock,
        mock_validate: mock.MagicMock,
        integration_error: ValueError,
        expected_message: str,
    ) -> None:
        mock_get_integration.side_effect = integration_error

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        # The raw message can carry the integration ID, so the wizard gets the curated wording.
        assert error_message == expected_message
        assert "42" not in (error_message or "")
        mock_validate.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_validate_credentials_rejects_an_integration_of_another_kind(
        self, mock_get_integration: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        # The lookup only scopes by ID and team, so a same-team integration of another kind is
        # reachable by ID. Its bearer token must never be handed to Intuit.
        mock_get_integration.return_value = _integration(kind="salesforce")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == (
            "The linked QuickBooks connection no longer exists. Please reconnect your QuickBooks company."
        )
        mock_validate.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.quickbooks_source")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_source_for_pipeline_rejects_an_integration_of_another_kind(
        self, mock_get_integration: mock.MagicMock, mock_quickbooks_source: mock.MagicMock
    ) -> None:
        mock_get_integration.return_value = _integration(kind="salesforce")
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match=f"Integration not found: {_INTEGRATION_ID}"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        mock_quickbooks_source.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_validate_credentials_without_a_realm_id(
        self, mock_get_integration: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        mock_get_integration.return_value = _integration(realm_id=None, integration_id=None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == (
            "This QuickBooks connection is missing its company ID. Please reconnect your QuickBooks company."
        )
        mock_validate.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_realm_id_falls_back_to_the_integration_id(
        self, mock_get_integration: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        mock_get_integration.return_value = _integration(realm_id=None)
        mock_validate.return_value = True

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.kwargs["realm_id"] == _REALM_ID

    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_an_expired_token_is_refreshed_before_use(
        self, mock_get_integration: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        integration = _integration(expired=True)
        mock_get_integration.return_value = integration
        mock_validate.return_value = True

        def _refresh(self_: object) -> None:
            integration.sensitive_config["access_token"] = "refreshed-token"

        with mock.patch(f"{_SOURCE_MODULE}.OauthIntegration.refresh_access_token", _refresh):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        assert mock_validate.call_args.kwargs["access_token"] == "refreshed-token"

    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_a_failed_refresh_asks_the_user_to_reconnect(
        self, mock_get_integration: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        integration = _integration(expired=True)
        mock_get_integration.return_value = integration

        def _refresh(self_: object) -> None:
            integration.errors = ERROR_TOKEN_REFRESH_FAILED

        with mock.patch(f"{_SOURCE_MODULE}.OauthIntegration.refresh_access_token", _refresh):
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == (
            "QuickBooks could not refresh the connection. Please reconnect your QuickBooks company."
        )
        mock_validate.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_validate_credentials_without_an_access_token(
        self, mock_get_integration: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        # An unexpired row whose token was never stored (or was stripped): nothing to refresh, so
        # this has to be caught before a bare `Authorization: Bearer None` reaches Intuit.
        mock_get_integration.return_value = _integration(access_token=None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == (
            "The QuickBooks connection has no access token. Please reconnect your QuickBooks company."
        )
        mock_validate.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.validate_quickbooks_credentials")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_validate_credentials_passes_through_an_unmapped_error(
        self, mock_get_integration: mock.MagicMock, mock_validate: mock.MagicMock
    ) -> None:
        # Nothing in get_non_retryable_errors matches, so the raw message is surfaced rather than
        # swallowed into a generic failure.
        mock_get_integration.side_effect = ValueError("Something else went wrong")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Something else went wrong"
        mock_validate.assert_not_called()

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is QuickBooksResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.quickbooks_source")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_get_integration: mock.MagicMock, mock_quickbooks_source: mock.MagicMock
    ) -> None:
        mock_get_integration.return_value = _integration()
        inputs = mock.MagicMock()
        inputs.schema_name = "Invoice"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_quickbooks_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["realm_id"] == _REALM_ID
        assert kwargs["access_token"] == "access-token"
        assert kwargs["entity_name"] == "Invoice"
        # An unpinned source falls back to the source class's default version.
        assert kwargs["api_version"] == "v3"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch(f"{_SOURCE_MODULE}.quickbooks_source")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_source_for_pipeline_can_renew_the_token_mid_sync(
        self, mock_get_integration: mock.MagicMock, mock_quickbooks_source: mock.MagicMock
    ) -> None:
        integration = _integration()
        mock_get_integration.return_value = integration
        inputs = mock.MagicMock()
        inputs.schema_name = "Invoice"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        def _refresh(self_: object) -> None:
            integration.sensitive_config["access_token"] = "renewed-token"

        # Intuit access tokens last an hour, so a long sync has to be able to mint a new one.
        with mock.patch(f"{_SOURCE_MODULE}.OauthIntegration.refresh_access_token", _refresh):
            assert mock_quickbooks_source.call_args.kwargs["refresh_access_token"]() == "renewed-token"

    @mock.patch(f"{_SOURCE_MODULE}.quickbooks_source")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(
        self, mock_get_integration: mock.MagicMock, mock_quickbooks_source: mock.MagicMock
    ) -> None:
        mock_get_integration.return_value = _integration()
        inputs = mock.MagicMock()
        inputs.schema_name = "CompanyInfo"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_quickbooks_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch(f"{_SOURCE_MODULE}.quickbooks_source")
    @mock.patch.object(QuickBooksSource, "get_oauth_integration")
    def test_source_for_pipeline_honors_a_pinned_api_version(
        self, mock_get_integration: mock.MagicMock, mock_quickbooks_source: mock.MagicMock
    ) -> None:
        mock_get_integration.return_value = _integration()
        inputs = mock.MagicMock()
        inputs.schema_name = "Invoice"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.api_version = "v3"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_quickbooks_source.call_args.kwargs["api_version"] == "v3"
