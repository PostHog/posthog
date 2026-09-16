from typing import cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.source import BigMailerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigmailer import (
    BigMailerSourceConfig,
)


def _config(api_key: str = "key") -> BigMailerSourceConfig:
    return cast(BigMailerSourceConfig, BigMailerSource()._config_class(api_key=api_key))


def _inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestGetSchemas:
    def test_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = BigMailerSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # BigMailer has no server-side time filter, so no table may advertise incremental or append
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_users_is_not_synced_by_default(self) -> None:
        # account-level admin data shouldn't be pulled unless the user opts in; the marketing tables should
        by_name = {s.name: s for s in BigMailerSource().get_schemas(_config(), team_id=1)}
        assert by_name["users"].should_sync_default is False
        assert by_name["contacts"].should_sync_default is True


class TestDocumentedTables:
    def test_renders_table_catalog_without_credentials(self) -> None:
        # lists_tables_without_credentials must stay on so posthog.com renders the Supported tables section
        assert BigMailerSource().lists_tables_without_credentials is True
        tables = BigMailerSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        brands = next(t for t in tables if t["name"] == "brands")
        assert brands["sync_methods"] == ["Full refresh"]
        assert brands["description"]  # canonical description is wired up


class TestCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials_plumbing(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        with patch.object(source_module, "validate_bigmailer_credentials", return_value=probe_result):
            ok, error = BigMailerSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestPipelineHandoff:
    @parameterized.expand([("contacts", ["brand_id", "id"]), ("brands", ["id"])])
    def test_source_for_pipeline_builds_response(self, endpoint: str, expected_keys: list[str]) -> None:
        src = BigMailerSource()
        inputs = _inputs(endpoint)
        # the transport reads resume state while building the resource, so a Redis-free stand-in is used
        manager = MagicMock()
        manager.can_resume.return_value = False
        response = src.source_for_pipeline(_config(), manager, inputs)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
