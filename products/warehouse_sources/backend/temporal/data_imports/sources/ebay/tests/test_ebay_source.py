from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldOauthConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.ebay import EbayResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.settings import EBAY_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ebay.source import EbaySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ebay import EbaySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

VALIDATE_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.source.validate_ebay_credentials"
SOURCE_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.source.ebay_source"
RESOLVE_TOKEN_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.source.resolve_ebay_oauth_token"
)


def _config(marketplace_id: str = "EBAY_US") -> EbaySourceConfig:
    return EbaySourceConfig.from_dict({"ebay_integration_id": "7", "marketplace_id": marketplace_id})


@contextmanager
def _connected(token: str = "tok-1") -> Iterator[None]:
    """Stand in for a linked eBay integration that currently holds `token`."""
    with (
        patch.object(EbaySource, "get_oauth_integration", return_value=MagicMock()),
        patch(RESOLVE_TOKEN_PATH, return_value=token),
    ):
        yield


def _inputs(
    schema_name: str = "orders",
    should_use_incremental_field: bool = False,
    last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=incremental_field,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestEbaySource:
    def test_source_type(self) -> None:
        assert EbaySource().source_type == ExternalDataSourceType.EBAY

    def test_source_config_shape(self) -> None:
        config = EbaySource().get_source_config
        # A finished source must be visible: unreleasedSource hides the connector entirely.
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/ebay"
        # The seller connects through PostHog's eBay app; no keyset or refresh token is asked for.
        assert [f.name for f in config.fields] == ["ebay_integration_id", "marketplace_id"]

    def test_oauth_field_requests_every_scope_the_source_calls(self) -> None:
        # A scope the source calls but doesn't declare leaves the user with a table that 403s
        # and no reconnect prompt, since the frontend diffs this against the granted scopes.
        field = next(f for f in EbaySource().get_source_config.fields if f.name == "ebay_integration_id")
        assert isinstance(field, SourceFieldOauthConfig)
        assert field.kind == "ebay"
        assert set((field.requiredScopes or "").split()) == {
            "https://api.ebay.com/oauth/api_scope",
            "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.finances",
            "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
        }

    def test_marketplace_stays_selectable(self) -> None:
        field = next(f for f in EbaySource().get_source_config.fields if f.name == "marketplace_id")
        assert isinstance(field, SourceFieldSelectConfig)
        assert field.defaultValue == "EBAY_US"

    def test_get_schemas_lists_every_endpoint_with_its_incremental_support(self) -> None:
        schemas = EbaySource().get_schemas(_config(), team_id=1)
        assert [s.name for s in schemas] == list(ENDPOINTS)
        assert {s.name for s in schemas if s.supports_incremental} == {"orders", "transactions", "payouts"}
        orders = next(s for s in schemas if s.name == "orders")
        assert [f["field"] for f in orders.incremental_fields] == ["lastModifiedDate", "creationDate"]

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = EbaySource().get_schemas(_config(), team_id=1, names=["payouts"])
        assert [s.name for s in schemas] == ["payouts"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # Public docs call get_schemas with a placeholder config, so discovery must do no I/O.
        tables = EbaySource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all(t["description"] for t in tables)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = EbaySource().get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            columns = entry.get("columns") or {}
            # Every primary key must be documented, since it anchors the table's grain.
            assert set(EBAY_ENDPOINTS[endpoint].primary_keys) <= set(columns)

    @parameterized.expand(
        [
            ("valid", (True, False), None, True),
            # A seller who only granted some scopes must still be able to create the source.
            ("forbidden_at_create", (False, True), None, True),
            ("forbidden_for_schema", (False, True), "transactions", False),
            ("invalid", (False, False), None, False),
            ("invalid_for_schema", (False, False), "orders", False),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        probe_result: tuple[bool, bool],
        schema_name: Optional[str],
        expected_valid: bool,
    ) -> None:
        with _connected(), patch(VALIDATE_PATH, return_value=probe_result) as probe:
            is_valid, message = EbaySource().validate_credentials(_config(), team_id=1, schema_name=schema_name)

        assert probe.call_args.kwargs["access_token"] == "tok-1"
        assert is_valid is expected_valid
        assert message is None if is_valid else bool(message)

    def test_validate_credentials_without_a_linked_integration(self) -> None:
        with patch.object(EbaySource, "get_oauth_integration", side_effect=ValueError("Missing integration ID")):
            is_valid, message = EbaySource().validate_credentials(_config(), team_id=1)

        assert is_valid is False
        assert message == "Connect an eBay account to continue"

    def test_get_endpoint_permissions_delegates_to_the_shared_probe(self) -> None:
        with (
            _connected(),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.ebay.source"
                ".check_ebay_endpoint_permissions",
                return_value={"orders": None},
            ) as probe,
        ):
            assert EbaySource().get_endpoint_permissions(_config(), team_id=1, endpoints=["orders"]) == {"orders": None}

        assert probe.call_args.kwargs["endpoints"] == ["orders"]
        assert probe.call_args.kwargs["access_token"] == "tok-1"

    def test_get_endpoint_permissions_never_blocks_the_picker_on_a_broken_connection(self) -> None:
        # The schema picker is reached before the connection is proven; reporting every table as
        # permission-denied here would push the user to deselect tables that are actually fine.
        with patch.object(EbaySource, "get_oauth_integration", side_effect=ValueError("Integration not found: 7")):
            assert EbaySource().get_endpoint_permissions(_config(), team_id=1, endpoints=["orders"]) == {"orders": None}

    def test_resumable_manager_is_bound_to_the_resume_config_and_namespaced(self) -> None:
        # Windowed endpoints and the offers fan-out store incompatible cursors, so a shared
        # slot would let one endpoint load the other's state after a retry.
        manager = EbaySource().get_resumable_source_manager(_inputs("offers"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is EbayResumeConfig
        assert manager._namespace == "offers"

    def test_non_retryable_errors_cover_auth_scope_and_connection_failures(self) -> None:
        errors = EbaySource().get_non_retryable_errors()
        # The deterministic ValueErrors the OAuth path raises can never be fixed by a retry.
        assert {"Missing integration ID", "Integration not found", "eBay access token not found"} <= set(errors)
        assert all(message for message in errors.values())

    def test_source_for_pipeline_passes_the_users_cursor_through(self) -> None:
        inputs = _inputs(
            "orders", should_use_incremental_field=True, last_value="2026-01-01", incremental_field="creationDate"
        )
        with _connected(), patch(SOURCE_PATH) as mock_source:
            EbaySource().source_for_pipeline(_config(), MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "orders"
        assert kwargs["incremental_field"] == "creationDate"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"
        assert kwargs["marketplace_id"] == "EBAY_US"

    def test_source_for_pipeline_syncs_with_the_integrations_token(self) -> None:
        inputs = _inputs("orders")
        with _connected("tok-live"), patch(SOURCE_PATH) as mock_source:
            EbaySource().source_for_pipeline(_config(), MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "tok-live"
        # eBay tokens last two hours, so a backfill has to be able to re-mint mid-sync.
        assert kwargs["token_refresher"] is not None
        assert kwargs["token_refresher"]("tok-live") == "tok-live"

    def test_source_for_pipeline_drops_the_watermark_on_a_full_refresh(self) -> None:
        # Passing a stale watermark on a full refresh would filter rows out of a run the
        # user asked to be complete.
        inputs = _inputs("orders", should_use_incremental_field=False, last_value="2026-01-01")
        with _connected(), patch(SOURCE_PATH) as mock_source:
            EbaySource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
