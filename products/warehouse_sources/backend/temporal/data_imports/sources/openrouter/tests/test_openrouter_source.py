from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openrouter import (
    OpenRouterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.source import OpenRouterSource

MANAGEMENT_ENDPOINTS = ["activity", "api_keys", "credits", "organization_members", "workspaces"]
CATALOG_ENDPOINTS = ["models", "providers"]


def _patch_key_info(info: Optional[dict]):
    return mock.patch.object(source_module, "get_key_info", return_value=info)


class TestOpenRouterSource:
    def setup_method(self):
        self.source = OpenRouterSource()
        self.team_id = 123
        self.config = OpenRouterSourceConfig(api_key="sk-or-test")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — required for the public-docs table list to render.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["models", "activity"])
        assert {s.name for s in schemas} == {"models", "activity"}

    def test_validate_credentials_invalid_key(self):
        with _patch_key_info(None):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error is not None

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
