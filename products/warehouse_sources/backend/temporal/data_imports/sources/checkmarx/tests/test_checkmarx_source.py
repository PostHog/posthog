from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.source import CheckmarxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkmarx import (
    CheckmarxSourceConfig,
)


def _make_config(**overrides: Any) -> CheckmarxSourceConfig:
    payload: dict[str, Any] = {"tenant_name": "my-tenant", "region": "eu", "api_key": "secret-key", **overrides}
    return CheckmarxSourceConfig(**payload)


class TestCheckmarxSource:
    def setup_method(self) -> None:
        self.source = CheckmarxSource()

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
