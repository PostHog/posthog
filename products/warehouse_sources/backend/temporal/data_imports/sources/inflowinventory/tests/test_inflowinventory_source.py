import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.inflowinventory import (
    InflowinventorySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.source import (
    InflowinventorySource,
)


class TestInflowinventorySource:
    def setup_method(self) -> None:
        self.source = InflowinventorySource()
        self.team_id = 123
        self.config = InflowinventorySourceConfig(company_id="co-123", api_key="inflow-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Inflowinventory"
        assert config.label == "Inflowinventory"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/inflowinventory"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["company_id", "api_key"]

    def test_connection_host_fields_pins_company_id(self) -> None:
        # The secret key is sent to a host/path derived from company_id, so retargeting it must
        # re-require the key.
        assert self.source.connection_host_fields == ["company_id"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://cloudapi.inflowinventory.com/co-123/products?count=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://cloudapi.inflowinventory.com/co-123/customers?count=100",
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
                "500 Server Error: Internal Server Error for url: https://cloudapi.inflowinventory.com/co-123/products",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://cloudapi.inflowinventory.com/co-123/customers",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_version_declaration(self) -> None:
        # New sources default to the current stable version; the legacy pin stays supported so
        # existing sources keep syncing under their own version.
        assert self.source.default_version == "2026-07-10"
        assert set(self.source.supported_versions) == {"2023-04-01", "2026-07-10"}

    @parameterized.expand(
        [
            ("pinned_legacy", "2023-04-01", "2023-04-01"),
            ("pinned_current", "2026-07-10", "2026-07-10"),
            ("unpinned_resolves_to_default", None, "2026-07-10"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.source.inflowinventory_source"
    )
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, pinned: str | None, expected_version: str, mock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "products"
        inputs.api_version = pinned
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "inflow-key"
        assert kwargs["company_id"] == "co-123"
        assert kwargs["endpoint"] == "products"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["api_version"] == expected_version

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown inFlow Inventory schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
