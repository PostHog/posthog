import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShippoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.shippo import ShippoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source import ShippoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestShippoSource:
    def setup_method(self) -> None:
        self.source = ShippoSource()
        self.team_id = 123
        self.config = ShippoSourceConfig(api_key="shippo_test_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SHIPPO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Shippo"
        assert config.label == "Shippo"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/shippo"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API token; the base URL is hardcoded, so there is no
        # non-secret field an editor could retarget to reuse a preserved token elsewhere.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_only_shipments_is_incremental(self) -> None:
        # Only /shipments honors the server-side object_created filters; advertising incremental
        # on any other endpoint would silently sync unfiltered data.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["shipments"].supports_incremental is True
        assert [f["field"] for f in schemas["shipments"].incremental_fields] == ["object_created"]
        for name, schema in schemas.items():
            if name != "shipments":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["transactions"])
        assert len(schemas) == 1
        assert schemas[0].name == "transactions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Keys must match schema names exactly or the enrichment silently falls back to the LLM.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.goshippo.com/shipments/?results=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.goshippo.com/transactions/?results=100",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.goshippo.com/shipments/"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.goshippo.com/shipments/"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source.validate_shippo_credentials"
    )
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Shippo API token")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("shippo_test_key")
        assert result == (False, "Invalid Shippo API token")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ShippoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source.shippo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "shipments"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "shippo_test_key"
        assert kwargs["endpoint"] == "shipments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source.shippo_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left on the schema must not leak into a full-refresh run.
        inputs = mock.MagicMock()
        inputs.schema_name = "shipments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Shippo schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
