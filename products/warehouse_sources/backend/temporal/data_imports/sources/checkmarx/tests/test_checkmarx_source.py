from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx import CheckmarxResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.source import CheckmarxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CheckmarxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_config(**overrides: Any) -> CheckmarxSourceConfig:
    payload: dict[str, Any] = {"tenant_name": "my-tenant", "region": "eu", "api_key": "secret-key", **overrides}
    return CheckmarxSourceConfig(**payload)


class TestCheckmarxSource:
    def setup_method(self) -> None:
        self.source = CheckmarxSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CHECKMARX

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.label == "Checkmarx (Checkmarx One)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/checkmarx"
        assert [field.name for field in config.fields] == ["tenant_name", "region", "api_key"]

    def test_api_key_field_is_secret(self) -> None:
        api_key_field = next(field for field in self.source.get_source_config.fields if field.name == "api_key")
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True

    def test_region_field_covers_all_configured_hosts(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.settings import (
            CHECKMARX_REGION_HOSTS,
        )

        region_field = next(field for field in self.source.get_source_config.fields if field.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert {option.value for option in region_field.options} == set(CHECKMARX_REGION_HOSTS.keys())

    @pytest.mark.parametrize(
        ("endpoint", "supports_incremental", "supports_append"),
        [
            ("projects", False, False),
            ("applications", False, False),
            ("scans", True, True),
            ("scan_results", True, False),
            ("scan_results_summary", True, False),
        ],
    )
    def test_get_schemas_sync_modes(self, endpoint: str, supports_incremental: bool, supports_append: bool) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(_make_config(), team_id=1)}

        assert schemas[endpoint].supports_incremental == supports_incremental
        assert schemas[endpoint].supports_append == supports_append

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_make_config(), team_id=1, names=["scans", "projects"])
        assert {schema.name for schema in schemas} == {"scans", "projects"}

    @pytest.mark.parametrize(("valid", "error"), [(True, None), (False, "Checkmarx One authentication failed: nope")])
    def test_validate_credentials_delegates_to_transport(self, valid: bool, error: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.source.validate_checkmarx_credentials",
            return_value=(valid, error),
        ) as mock_validate:
            result = self.source.validate_credentials(_make_config(), team_id=1)

        assert result == (valid, error)
        mock_validate.assert_called_once_with("my-tenant", "eu", "secret-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CheckmarxResumeConfig

    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    def test_source_for_pipeline_plumbs_inputs(self, should_use_incremental_field: bool) -> None:
        inputs = MagicMock()
        inputs.schema_name = "scans"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.source.checkmarx_source"
        ) as mock_source:
            self.source.source_for_pipeline(_make_config(), manager, inputs)

        mock_source.assert_called_once_with(
            tenant_name="my-tenant",
            region="eu",
            api_key="secret-key",
            endpoint="scans",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            # The stored watermark must not leak into a full-refresh run.
            db_incremental_field_last_value="2026-01-01T00:00:00Z" if should_use_incremental_field else None,
        )

    def test_get_non_retryable_errors_covers_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert "Checkmarx One authentication failed" in errors
        assert "401 Client Error: Unauthorized for url" in errors
        assert "403 Client Error: Forbidden for url" in errors
