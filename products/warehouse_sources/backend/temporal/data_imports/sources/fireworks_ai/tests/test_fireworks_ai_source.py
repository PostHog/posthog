import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FireworksAIResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.source import FireworksAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FireworksAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFireworksAISource:
    def setup_method(self):
        self.source = FireworksAISource()
        self.config = FireworksAISourceConfig(account_id="acme", api_key="fw_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.FIREWORKSAI

    def test_source_config_fields(self):
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields}
        assert set(fields) == {"account_id", "api_key"}
        assert fields["account_id"].required and not fields["account_id"].secret
        # The API key is confidential and must be stored as a secret password field.
        assert fields["api_key"].required and fields["api_key"].secret
        assert fields["api_key"].type.value == "password"

    def test_docs_url_matches_doc_filename(self):
        assert self.source.get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/fireworks-ai"

    def test_get_schemas_lists_every_endpoint_as_full_refresh(self):
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No confirmed server-side timestamp filter, so every table ships full refresh only.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, team_id=1, names=["models"])
        assert [s.name for s in schemas] == ["models"]

    def test_lists_tables_without_credentials(self):
        # get_schemas does no I/O, so the public docs table catalog can render without a connection.
        assert self.source.lists_tables_without_credentials is True
        assert {t["name"] for t in self.source.get_documented_tables()} == set(ENDPOINTS)

    def test_canonical_descriptions_key_on_endpoint_names(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical).issubset(set(ENDPOINTS))
        assert "models" in canonical

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is FireworksAIResumeConfig

    @pytest.mark.parametrize(
        "ok,status,schema_name,expected_valid",
        [
            (True, 200, None, True),
            (False, 401, None, False),
            # 403 at source-create means a valid token missing scope for some resource — allow it.
            (False, 403, None, True),
            # 403 while probing a specific schema is a real permission failure for that table.
            (False, 403, "models", False),
            (False, None, None, False),
        ],
    )
    def test_validate_credentials(self, ok, status, schema_name, expected_valid):
        with mock.patch.object(source_module, "validate_fireworks_ai_credentials", return_value=(ok, status)):
            valid, error = self.source.validate_credentials(self.config, team_id=1, schema_name=schema_name)
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_source_for_pipeline_plumbs_config_and_endpoint(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "datasets"
        manager = mock.MagicMock()
        with mock.patch.object(source_module, "fireworks_ai_source") as mocked:
            self.source.source_for_pipeline(self.config, manager, inputs)
        mocked.assert_called_once_with(
            api_key="fw_test",
            account_id="acme",
            endpoint="datasets",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
