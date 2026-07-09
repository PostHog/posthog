from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KatanaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.katana import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.katana import KatanaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.settings import ENDPOINTS, KATANA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.source import KatanaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = [name for name, cfg in KATANA_ENDPOINTS.items() if cfg.incremental_fields]
_FULL_REFRESH_ENDPOINTS = [name for name, cfg in KATANA_ENDPOINTS.items() if not cfg.incremental_fields]


class TestKatanaSourceClass:
    def test_source_type(self) -> None:
        assert KatanaSource().source_type == ExternalDataSourceType.KATANA

    def test_source_config(self) -> None:
        config = KatanaSource().get_source_config
        assert config.label == "Katana"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/katana"
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key"]

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list must render.
        assert KatanaSource.lists_tables_without_credentials is True

    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = KatanaSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = KatanaSource().get_schemas(KatanaSourceConfig(api_key="k"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand([(name,) for name in _INCREMENTAL_ENDPOINTS])
    def test_incremental_endpoints_support_incremental(self, endpoint: str) -> None:
        schemas = KatanaSource().get_schemas(KatanaSourceConfig(api_key="k"), team_id=1, names=[endpoint])
        assert schemas[0].supports_incremental is True
        assert len(schemas[0].incremental_fields) >= 1

    @parameterized.expand([(name,) for name in _FULL_REFRESH_ENDPOINTS])
    def test_full_refresh_endpoints_do_not_support_incremental(self, endpoint: str) -> None:
        schemas = KatanaSource().get_schemas(KatanaSourceConfig(api_key="k"), team_id=1, names=[endpoint])
        assert schemas[0].supports_incremental is False
        assert schemas[0].incremental_fields == []

    def test_get_schemas_name_filter(self) -> None:
        schemas = KatanaSource().get_schemas(KatanaSourceConfig(api_key="k"), team_id=1, names=["products"])
        assert [s.name for s in schemas] == ["products"]

    @patch.object(source_module, "validate_katana_credentials")
    def test_validate_credentials_success(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = True
        ok, error = KatanaSource().validate_credentials(KatanaSourceConfig(api_key="k"), team_id=1)
        assert ok is True
        assert error is None

    @patch.object(source_module, "validate_katana_credentials")
    def test_validate_credentials_failure(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = False
        ok, error = KatanaSource().validate_credentials(KatanaSourceConfig(api_key="bad"), team_id=1)
        assert ok is False
        assert error is not None

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = KatanaSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is KatanaResumeConfig

    @patch.object(source_module, "katana_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_katana_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "sales_orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = "updated_at"
        manager = MagicMock()

        KatanaSource().source_for_pipeline(KatanaSourceConfig(api_key="key"), manager, inputs)

        mock_katana_source.assert_called_once()
        kwargs = mock_katana_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "sales_orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"
        assert kwargs["incremental_field"] == "updated_at"

    @patch.object(source_module, "katana_source")
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_katana_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "inventory"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = None

        KatanaSource().source_for_pipeline(KatanaSourceConfig(api_key="key"), MagicMock(), inputs)

        assert mock_katana_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keys_match_endpoints(self) -> None:
        descriptions = KatanaSource().get_canonical_descriptions()
        assert descriptions is CANONICAL_DESCRIPTIONS
        # Every documented table must be a real endpoint (no stale keys).
        assert set(descriptions).issubset(set(ENDPOINTS))
