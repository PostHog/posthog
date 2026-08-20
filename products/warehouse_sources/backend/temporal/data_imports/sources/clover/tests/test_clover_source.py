from typing import Literal

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldOauthConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.clover.clover import CloverResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.settings import (
    CLOVER_ENDPOINTS,
    CLOVER_REGION_INTEGRATION_KINDS,
    ENDPOINTS,
    FILTERABLE_TIME_FIELDS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.source import CloverSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clover import (
    CloverAuthTypeConfig,
    CloverSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType

CloverOauthSelection = Literal["oauth_na", "oauth_eu", "oauth_latam", "oauth_sandbox"]

MERCHANT_ID = "6MRDFDQMRSSTZ"
SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.clover.source"


def _token_config() -> CloverSourceConfig:
    return CloverSourceConfig(
        auth_type=CloverAuthTypeConfig(selection="api_token", region="na", merchant_id=MERCHANT_ID, api_token="tok")
    )


def _oauth_config(selection: CloverOauthSelection = "oauth_eu") -> CloverSourceConfig:
    return CloverSourceConfig(auth_type=CloverAuthTypeConfig(selection=selection, clover_integration_id=7))


def _integration(kind: str = "clover-eu", merchant_id: str | None = MERCHANT_ID) -> mock.MagicMock:
    integration = mock.MagicMock()
    integration.kind = kind
    integration.config = {"merchant_id": merchant_id} if merchant_id else {}
    return integration


class TestCloverSource:
    def setup_method(self) -> None:
        self.source = CloverSource()
        self.team_id = 123
        self.config = _token_config()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CLOVER

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Clover"
        assert config.label == "Clover"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/clover.png"

    def _auth_field(self) -> SourceFieldSelectConfig:
        return next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldSelectConfig) and f.name == "auth_type"
        )

    def test_every_region_offers_its_own_oauth_app(self) -> None:
        # A Clover app can only authorize merchants in the region it was registered in, so each
        # region's Connect button must be bound to that region's integration kind.
        auth = self._auth_field()
        oauth_kinds = {
            field.kind
            for option in auth.options
            for field in option.fields or []
            if isinstance(field, SourceFieldOauthConfig)
        }
        assert oauth_kinds == set(CLOVER_REGION_INTEGRATION_KINDS.values())
        assert auth.defaultValue == "oauth_na"

    def test_api_token_option_keeps_region_merchant_and_secret_token(self) -> None:
        option = next(o for o in self._auth_field().options if o.value == "api_token")
        assert option.fields is not None

        region = next(f for f in option.fields if isinstance(f, SourceFieldSelectConfig))
        assert [o.value for o in region.options] == list(CLOVER_REGION_INTEGRATION_KINDS)

        secrets = {f.name for f in option.fields if isinstance(f, SourceFieldInputConfig) and f.secret}
        assert secrets == {"api_token"}

    def test_credential_sub_fields_are_optional_so_either_option_validates(self) -> None:
        # The generator flattens every option's sub-fields into one config class, so marking any
        # credential required would make the other option's credentials mandatory too.
        for option in self._auth_field().options:
            for field in option.fields or []:
                if isinstance(field, SourceFieldInputConfig | SourceFieldOauthConfig):
                    assert field.required is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.clover.com/v3/merchants/M/orders",
            "403 Client Error: Forbidden for url: https://api.eu.clover.com/v3/merchants/M/items",
            "Missing Clover integration ID",
            "Integration not found: 7",
            "Clover access token not found",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.clover.com/v3/merchants/M/orders",
            "500 Server Error for url: https://api.clover.com/v3/merchants/M/orders",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the entities carrying a timestamp Clover will filter on server-side.
        assert incremental == {"orders", "payments", "refunds", "credits", "items"}
        # Resume replays the checkpointed page and windows share their boundary millisecond, so
        # append would duplicate rows.
        assert all(schema.supports_append is False for schema in schemas)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_advertised_cursors_are_server_filterable_integers(self, endpoint: str) -> None:
        for field in INCREMENTAL_FIELDS[endpoint]:
            assert field["field"] in FILTERABLE_TIME_FIELDS
            # Clover returns epoch milliseconds, so the stored column is an integer.
            assert field["field_type"] == IncrementalFieldType.Integer

    def test_orders_prefer_modified_time(self) -> None:
        # `_select_incremental_field` picks the update-tracking cursor, which must be the one
        # listed for orders so late edits aren't missed.
        assert INCREMENTAL_FIELDS["orders"][0]["field"] == "modifiedTime"

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_are_globally_unique_ids(self, endpoint: str) -> None:
        # Every endpoint is a top-level merchant collection (no fan-out), so Clover's own id is
        # unique across the table.
        assert CLOVER_ENDPOINTS[endpoint].primary_keys == ["id"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert [schema.name for schema in schemas] == ["orders"]

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()
        assert {table["name"] for table in tables} == set(ENDPOINTS)
        assert all(table["description"] for table in tables)

    @mock.patch(f"{SOURCE_MODULE}.validate_clover_credentials", return_value=(True, None))
    def test_validate_credentials_uses_the_pasted_api_token(self, mock_validate: mock.MagicMock) -> None:
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        kwargs = mock_validate.call_args.kwargs
        assert kwargs["region"] == "na"
        assert kwargs["merchant_id"] == MERCHANT_ID
        assert kwargs["auth"].token == "tok"

    @pytest.mark.parametrize(
        "integration_kind, expected_region",
        [("clover", "na"), ("clover-eu", "eu"), ("clover-latam", "latam"), ("clover-sandbox", "sandbox")],
    )
    @mock.patch(f"{SOURCE_MODULE}.resolve_clover_oauth_token", return_value="access")
    @mock.patch(f"{SOURCE_MODULE}.validate_clover_credentials", return_value=(True, None))
    def test_oauth_path_takes_region_and_merchant_from_the_integration(
        self,
        mock_validate: mock.MagicMock,
        mock_resolve: mock.MagicMock,
        integration_kind: str,
        expected_region: str,
    ) -> None:
        # The stored region selection is not trusted: the integration's kind is what pins the Clover
        # app and host the token was issued against, and the merchant is recorded on the callback.
        with mock.patch.object(CloverSource, "get_oauth_integration", return_value=_integration(integration_kind)):
            assert self.source.validate_credentials(_oauth_config(), self.team_id) == (True, None)

        kwargs = mock_validate.call_args.kwargs
        assert kwargs["region"] == expected_region
        assert kwargs["merchant_id"] == MERCHANT_ID
        assert kwargs["auth"].token == "access"

    @pytest.mark.parametrize(
        "integration_id, integration, expected_message",
        [
            (None, _integration(), "Clover is not connected"),
            (7, _integration(merchant_id=None), "did not record a merchant"),
        ],
    )
    def test_validate_credentials_reports_a_broken_connection(
        self, integration_id: int | None, integration: mock.MagicMock, expected_message: str
    ) -> None:
        config = CloverSourceConfig(
            auth_type=CloverAuthTypeConfig(selection="oauth_eu", clover_integration_id=integration_id)
        )
        with mock.patch.object(CloverSource, "get_oauth_integration", return_value=integration):
            valid, message = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        assert message is not None and expected_message in message

    @pytest.mark.parametrize(
        "schema_name, expected_accept_forbidden",
        [(None, True), ("orders", False)],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_clover_credentials", return_value=(True, None))
    def test_forbidden_only_blocks_a_per_schema_check(
        self, mock_validate: mock.MagicMock, schema_name: str | None, expected_accept_forbidden: bool
    ) -> None:
        self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert mock_validate.call_args.kwargs["accept_forbidden"] is expected_accept_forbidden

    @mock.patch(f"{SOURCE_MODULE}.clover_endpoint_permissions", return_value={"orders": None})
    def test_get_endpoint_permissions_plumbs_credentials(self, mock_permissions: mock.MagicMock) -> None:
        assert self.source.get_endpoint_permissions(self.config, self.team_id, ["orders"]) == {"orders": None}

        kwargs = mock_permissions.call_args.kwargs
        assert kwargs["endpoints"] == ["orders"]
        assert kwargs["auth"].token == "tok"

    def test_get_endpoint_permissions_never_blocks_the_picker(self) -> None:
        # A broken connection is reported by validate_credentials; the schema picker must not fail.
        config = CloverSourceConfig(auth_type=CloverAuthTypeConfig(selection="oauth_na"))
        assert self.source.get_endpoint_permissions(config, self.team_id, ["orders"]) == {"orders": None}

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CloverResumeConfig

    @mock.patch(f"{SOURCE_MODULE}.clover_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.incremental_field = "modifiedTime"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1_700_000_000_000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "na"
        assert kwargs["merchant_id"] == MERCHANT_ID
        assert kwargs["endpoint"] == "orders"
        assert kwargs["auth"].token == "tok"
        assert kwargs["resumable_source_manager"] is manager
        # The user's chosen cursor must reach the transport, not a per-endpoint default.
        assert kwargs["incremental_field"] == "modifiedTime"
        assert kwargs["db_incremental_field_last_value"] == 1_700_000_000_000

    @mock.patch(f"{SOURCE_MODULE}.resolve_clover_oauth_token", return_value="access")
    @mock.patch(f"{SOURCE_MODULE}.clover_source")
    def test_source_for_pipeline_syncs_with_the_integration_access_token(
        self, mock_source: mock.MagicMock, mock_resolve: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = False

        with mock.patch.object(CloverSource, "get_oauth_integration", return_value=_integration()):
            self.source.source_for_pipeline(_oauth_config(), mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["merchant_id"] == MERCHANT_ID
        assert kwargs["auth"].token == "access"

    @mock.patch(f"{SOURCE_MODULE}.clover_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "employees"
        inputs.incremental_field = None
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1_700_000_000_000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
