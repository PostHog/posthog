from typing import Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpenRouterSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.openrouter import (
    OpenRouterResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.source import OpenRouterSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MANAGEMENT_ENDPOINTS = ["activity", "api_keys", "credits", "organization_members", "workspaces"]
CATALOG_ENDPOINTS = ["models", "providers"]


def _patch_key_info(info: Optional[dict]):
    return mock.patch.object(source_module, "get_key_info", return_value=info)


class TestOpenRouterSource:
    def setup_method(self):
        self.source = OpenRouterSource()
        self.team_id = 123
        self.config = OpenRouterSourceConfig(api_key="sk-or-test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OPENROUTER

    def test_source_config_fields(self):
        config = self.source.get_source_config
        assert config.label == "OpenRouter"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is not hidden.
        assert config.unreleasedSource is None or config.unreleasedSource is False
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/openrouter"

        assert len(config.fields) == 1
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — required for the public-docs table list to render.
        assert self.source.lists_tables_without_credentials is True

    def test_only_activity_is_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(MANAGEMENT_ENDPOINTS) | set(CATALOG_ENDPOINTS)
        assert schemas["activity"].supports_incremental is True
        assert [f["field"] for f in schemas["activity"].incremental_fields] == ["date"]
        for name, schema in schemas.items():
            if name != "activity":
                assert schema.supports_incremental is False, name
            # No table advertises append: activity relies on merge to dedupe re-fetched days.
            assert schema.supports_append is False, name

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["models", "activity"])
        assert {s.name for s in schemas} == {"models", "activity"}

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_validate_credentials_invalid_key(self):
        with _patch_key_info(None):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error is not None

    def test_validate_credentials_accepts_any_genuine_key_at_create(self):
        # An inference (non-management) key must still connect: the catalog tables sync, and
        # get_endpoint_permissions reports which tables need a management key.
        with _patch_key_info({"is_management_key": False}):
            ok, error = self.source.validate_credentials(self.config, self.team_id, schema_name=None)
        assert ok is True
        assert error is None

    @pytest.mark.parametrize("schema_name", MANAGEMENT_ENDPOINTS)
    def test_validate_credentials_rejects_non_management_key_for_management_table(self, schema_name):
        with _patch_key_info({"is_management_key": False}):
            ok, error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert ok is False
        assert error is not None and "management" in error.lower()

    @pytest.mark.parametrize("schema_name", CATALOG_ENDPOINTS)
    def test_validate_credentials_allows_catalog_tables_for_any_key(self, schema_name):
        with _patch_key_info({"is_management_key": False}):
            ok, error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert ok is True
        assert error is None

    def test_endpoint_permissions_flag_management_tables_for_inference_key(self):
        with _patch_key_info({"is_management_key": False}):
            result = self.source.get_endpoint_permissions(
                self.config, self.team_id, MANAGEMENT_ENDPOINTS + CATALOG_ENDPOINTS
            )
        for name in CATALOG_ENDPOINTS:
            assert result[name] is None
        for name in MANAGEMENT_ENDPOINTS:
            assert result[name] is not None

    def test_endpoint_permissions_all_reachable_with_management_key(self):
        with _patch_key_info({"is_management_key": True}):
            result = self.source.get_endpoint_permissions(
                self.config, self.team_id, MANAGEMENT_ENDPOINTS + CATALOG_ENDPOINTS
            )
        assert all(v is None for v in result.values())

    def test_resumable_manager_bound_to_resume_config(self):
        inputs = mock.Mock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is OpenRouterResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self):
        inputs = mock.Mock()
        inputs.schema_name = "activity"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01"
        manager = mock.Mock()

        with mock.patch.object(source_module, "openrouter_source") as mocked:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        assert kwargs["api_key"] == "sk-or-test"
        assert kwargs["endpoint"] == "activity"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-06-01"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        inputs = mock.Mock()
        inputs.schema_name = "models"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01"

        with mock.patch.object(source_module, "openrouter_source") as mocked:
            self.source.source_for_pipeline(self.config, mock.Mock(), inputs)

        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_documented_tables_rendered_for_public_docs(self):
        tables = self.source.get_documented_tables()
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == set(MANAGEMENT_ENDPOINTS) | set(CATALOG_ENDPOINTS)
        # Canonical descriptions flow through to the docs.
        assert by_name["activity"]["description"]
        assert "Incremental" in by_name["activity"]["sync_methods"]
        assert "Full refresh" in by_name["models"]["sync_methods"]
