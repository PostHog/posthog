from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldOauthConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercadopago import (
    MercadoPagoAuthMethodConfig,
    MercadoPagoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.mercado_pago import (
    MercadoPagoResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.source import (
    INTEGRATION_TOKEN_MISSING_ERROR,
    MISSING_ACCESS_TOKEN_ERROR,
    MISSING_INTEGRATION_ERROR,
    REQUIRED_SCOPES,
    MercadoPagoSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

INTEGRATION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.source."
    "MercadoPagoSource.get_oauth_integration"
)


def _config(
    selection: str = "access_token",
    access_token: Optional[str] = "APP_USR-secret-token",
    mercado_pago_integration_id: Optional[int] = None,
) -> MercadoPagoSourceConfig:
    return MercadoPagoSourceConfig(
        auth_method=MercadoPagoAuthMethodConfig(
            selection=selection,  # type: ignore[arg-type]
            access_token=access_token,
            mercado_pago_integration_id=mercado_pago_integration_id,
        )
    )


def _oauth_config(integration_id: Optional[int] = 42) -> MercadoPagoSourceConfig:
    return _config(selection="oauth", access_token=None, mercado_pago_integration_id=integration_id)


class TestMercadoPagoSource:
    def setup_method(self) -> None:
        self.source = MercadoPagoSource()
        self.team_id = 123
        self.config = _config()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.MERCADOPAGO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "MercadoPago"
        assert config.label == "Mercado Pago (Mercado Libre)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/mercado-pago"
        assert config.iconPath == "/static/services/mercado_pago.png"

    def test_config_has_no_unreleased_flag(self) -> None:
        # A finished source must not carry `unreleasedSource` — it hides the connector entirely.
        assert self.source.get_source_config.unreleasedSource is None

    def test_auth_defaults_to_connecting_through_posthogs_oauth_app(self) -> None:
        select = next(f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldSelectConfig))
        assert select.name == "auth_method"
        assert select.defaultValue == "oauth"
        assert [option.value for option in select.options] == ["oauth", "access_token"]

    def test_oauth_option_offers_the_connect_field(self) -> None:
        select = next(f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldSelectConfig))
        option = next(o for o in select.options if o.value == "oauth")
        oauth_field = next(f for f in (option.fields or []) if isinstance(f, SourceFieldOauthConfig))
        assert oauth_field.name == "mercado_pago_integration_id"
        assert oauth_field.kind == "mercado-pago"
        # `offline_access` is what makes Mercado Pago issue a refresh token, so a connection without
        # it silently stops syncing after the access token expires.
        assert oauth_field.requiredScopes == REQUIRED_SCOPES

    def test_access_token_option_stays_available_and_secret(self) -> None:
        select = next(f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldSelectConfig))
        option = next(o for o in select.options if o.value == "access_token")
        field = next(f for f in (option.fields or []) if isinstance(f, SourceFieldInputConfig))
        assert field.name == "access_token"
        assert field.secret is True
        assert field.type.value == "password"

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url.startswith("https://")

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_payments_supports_incremental(self) -> None:
        # `/v1/payments/search` is the only endpoint with a documented server-side date window;
        # advertising incremental elsewhere would re-fetch everything on every sync.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["payments"].supports_incremental is True
        assert [f["field"] for f in schemas["payments"].incremental_fields] == [
            "date_last_updated",
            "date_created",
        ]
        for name, schema in schemas.items():
            if name != "payments":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["subscriptions"])
        assert [s.name for s in schemas] == ["subscriptions"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.mercadopago.com/v1/payments/search",),
            ("403 Client Error: Forbidden for url: https://api.mercadopago.com/preapproval/search",),
            (MISSING_ACCESS_TOKEN_ERROR,),
            (MISSING_INTEGRATION_ERROR,),
            (INTEGRATION_TOKEN_MISSING_ERROR,),
            ("Integration not found: 42",),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://api.mercadopago.com/v1/payments/search",),
            ("500 Server Error: Internal Server Error for url: https://api.mercadopago.com/v1/payments/search",),
        ]
    )
    def test_non_retryable_errors_ignore_transient_failures(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_pasted_access_token_is_used_as_is(self) -> None:
        assert self.source._resolve_access_token(self.config, self.team_id) == "APP_USR-secret-token"

    @mock.patch(INTEGRATION_PATCH)
    def test_connected_account_uses_the_integrations_access_token(self, mock_integration: mock.MagicMock) -> None:
        mock_integration.return_value = mock.MagicMock(kind="mercado-pago", access_token="APP_USR-from-integration")
        assert self.source._resolve_access_token(_oauth_config(), self.team_id) == "APP_USR-from-integration"
        mock_integration.assert_called_once_with(42, self.team_id)

    @mock.patch(INTEGRATION_PATCH)
    def test_an_integration_of_another_kind_is_refused(self, mock_integration: mock.MagicMock) -> None:
        # The lookup is only scoped to the team, so a hand-crafted config could otherwise point at
        # any of the team's integrations and have its token sent to api.mercadopago.com.
        mock_integration.return_value = mock.MagicMock(kind="stripe", access_token="sk_live-not-ours")
        with pytest.raises(ValueError, match="Integration not found"):
            self.source._resolve_access_token(_oauth_config(), self.team_id)

    @parameterized.expand(
        [
            ("no_access_token", _config(access_token=None), MISSING_ACCESS_TOKEN_ERROR),
            ("no_integration", _oauth_config(integration_id=None), MISSING_INTEGRATION_ERROR),
        ]
    )
    def test_incomplete_credentials_are_rejected_with_a_curated_message(
        self, _name: str, config: MercadoPagoSourceConfig, expected_key: str
    ) -> None:
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message == self.source.get_non_retryable_errors()[expected_key]

    @mock.patch(INTEGRATION_PATCH)
    def test_deleted_integration_is_reported_without_leaking_the_id(self, mock_integration: mock.MagicMock) -> None:
        mock_integration.side_effect = ValueError("Integration not found: 42")
        is_valid, message = self.source.validate_credentials(_oauth_config(), self.team_id)
        assert is_valid is False
        assert message == self.source.get_non_retryable_errors()["Integration not found"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.source.validate_mercado_pago_credentials"
    )
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Your Mercado Pago credentials are invalid or expired")
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="payments")
        assert result == (False, "Your Mercado Pago credentials are invalid or expired")
        mock_validate.assert_called_once_with("APP_USR-secret-token", "payments")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MercadoPagoResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.source.mercado_pago_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.team_id = self.team_id
        inputs.job_id = "job-123"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "date_last_updated"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "APP_USR-secret-token"
        assert kwargs["endpoint"] == "payments"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-123"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "date_last_updated"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.source.mercado_pago_source"
    )
    @mock.patch(INTEGRATION_PATCH)
    def test_source_for_pipeline_syncs_with_the_connected_accounts_token(
        self, mock_integration: mock.MagicMock, mock_source: mock.MagicMock
    ) -> None:
        mock_integration.return_value = mock.MagicMock(kind="mercado-pago", access_token="APP_USR-from-integration")
        inputs = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.team_id = self.team_id

        self.source.source_for_pipeline(_oauth_config(), mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["access_token"] == "APP_USR-from-integration"

    @mock.patch(INTEGRATION_PATCH)
    def test_source_for_pipeline_fails_when_the_integration_has_no_token(
        self, mock_integration: mock.MagicMock
    ) -> None:
        mock_integration.return_value = mock.MagicMock(kind="mercado-pago", access_token=None)
        inputs: Any = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.team_id = self.team_id
        with pytest.raises(ValueError, match=INTEGRATION_TOKEN_MISSING_ERROR):
            self.source.source_for_pipeline(_oauth_config(), mock.MagicMock(), inputs)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.source.mercado_pago_source"
    )
    def test_full_refresh_run_passes_no_watermark(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "merchant_orders"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs: Any = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Mercado Pago schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
