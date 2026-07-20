from typing import Any

import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VultrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.source import VultrSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.vultr.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "instances",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestVultrSource:
    def setup_method(self) -> None:
        self.source = VultrSource()
        self.team_id = 123
        self.config = VultrSourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.VULTR

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Vultr"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/vultr.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/vultr"

        assert len(config.fields) == 1
        (api_key_field,) = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        # The single account token is confidential, so it must render as a masked, secret field.
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any(expected_key in key for key in errors)

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Vultr has no server-side timestamp filter, so nothing supports incremental sync.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["invoices"])
        assert [s.name for s in schemas] == ["invoices"]

    @pytest.mark.parametrize(
        ("mock_return", "expected"),
        [
            ((True, None), (True, None)),
            ((False, "Invalid Vultr API key."), (False, "Invalid Vultr API key.")),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_vultr_credentials")
    def test_validate_credentials_plumbing(
        self, mock_validate: mock.MagicMock, mock_return: tuple[bool, str | None], expected: tuple[bool, str | None]
    ) -> None:
        mock_validate.return_value = mock_return
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="instances")

        assert result == expected
        mock_validate.assert_called_once_with("test-key", "instances")

    @pytest.mark.parametrize("schema_name", list(ENDPOINTS))
    @mock.patch(f"{SOURCE_MODULE}.vultr_source")
    def test_source_for_pipeline_maps_primary_keys(self, mock_vultr_source: mock.MagicMock, schema_name: str) -> None:
        resource = mock.MagicMock()
        resource.name = schema_name
        resource.column_hints = None
        mock_vultr_source.return_value = resource

        response = self.source.source_for_pipeline(self.config, _make_inputs(schema_name=schema_name))

        assert response.name == schema_name
        # Every Vultr id is globally unique per account, so ["id"] is the table-wide key.
        assert response.primary_keys == ENDPOINTS[schema_name].primary_keys
        mock_vultr_source.assert_called_once_with(api_key="test-key", endpoint=schema_name, team_id=123, job_id="job-1")

    def test_documented_tables_cover_every_endpoint(self) -> None:
        # lists_tables_without_credentials is True, so the public docs catalog must render statically.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_keys_are_valid_endpoints(self) -> None:
        # A description keyed to a non-existent endpoint would silently never apply.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
