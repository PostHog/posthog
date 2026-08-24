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

    @pytest.mark.parametrize(
        "raw_error,is_non_retryable",
        [
            # Real raise_for_status() strings carry the offset/limit query the org endpoints page with;
            # the keys must still match them as a substring the way external_data_job.py classifies.
            (
                "404 Client Error: Not Found for url: https://openrouter.ai/api/v1/organization/members?offset=0&limit=100",
                True,
            ),
            (
                "404 Client Error: Not Found for url: https://openrouter.ai/api/v1/workspaces?offset=0&limit=100",
                True,
            ),
            # A 404 on a catalog endpoint would be a real path bug, not a missing organization — it must
            # stay retryable rather than be silently disabled.
            ("404 Client Error: Not Found for url: https://openrouter.ai/api/v1/models", False),
        ],
    )
    def test_404_classification(self, raw_error, is_non_retryable):
        errors = self.source.get_non_retryable_errors()
        matches = [msg for key, msg in errors.items() if key in raw_error]
        assert bool(matches) is is_non_retryable
        if is_non_retryable:
            assert "organization" in (matches[0] or "").lower()

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

    def test_documented_tables_rendered_for_public_docs(self):
        tables = self.source.get_documented_tables()
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == set(MANAGEMENT_ENDPOINTS) | set(CATALOG_ENDPOINTS)
        # Canonical descriptions flow through to the docs.
        assert by_name["activity"]["description"]
        assert "Incremental" in by_name["activity"]["sync_methods"]
        assert "Full refresh" in by_name["models"]["sync_methods"]
