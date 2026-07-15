import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import QualysVmdrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.qualys_vmdr import (
    QualysVmdrResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source import QualysVmdrSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source"


def _config() -> QualysVmdrSourceConfig:
    return QualysVmdrSourceConfig(api_server="qualysapi.qualys.com", username="user", password="pass")


def _inputs(**overrides) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "hosts")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    return inputs


class TestQualysVmdrSource:
    def setup_method(self):
        self.source = QualysVmdrSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.QUALYSVMDR

    def test_source_is_released(self):
        config = self.source.get_source_config
        assert not config.unreleasedSource

    def test_api_server_is_a_connection_host_field(self):
        # Retargeting `api_server` must force re-entry of the stored credentials
        assert "api_server" in self.source.connection_host_fields

    def test_get_schemas(self):
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}

        assert set(schemas.keys()) == {"hosts", "host_list_detection", "scans", "knowledge_base"}
        assert all(s.supports_incremental for s in schemas.values())
        # Every endpoint re-pulls updated rows, so append mode would materialize duplicates
        assert all(not s.supports_append for s in schemas.values())
        # KnowledgeBase needs a subscription add-on, so it must not be on by default
        assert not schemas["knowledge_base"].should_sync_default

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(_config(), team_id=1, names=["scans"])
        assert [s.name for s in schemas] == ["scans"]

    @pytest.mark.parametrize(
        "transport_result",
        [(True, None), (False, "Invalid Qualys credentials or API server URL")],
    )
    def test_validate_credentials(self, transport_result):
        with mock.patch(f"{_MODULE}.validate_qualys_vmdr_credentials", return_value=transport_result) as validate:
            result = self.source.validate_credentials(_config(), team_id=1)

        assert result == transport_result
        validate.assert_called_once_with("qualysapi.qualys.com", "user", "pass")

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is QualysVmdrResumeConfig

    @pytest.mark.parametrize(
        "endpoint,expected_primary_keys,expected_partition_keys",
        [
            ("hosts", ["id"], None),
            ("host_list_detection", ["unique_vuln_id"], ["first_found_datetime"]),
            ("scans", ["ref"], ["launch_datetime"]),
            ("knowledge_base", ["qid"], None),
        ],
    )
    def test_source_for_pipeline_response_shape(self, endpoint, expected_primary_keys, expected_partition_keys):
        manager = mock.MagicMock()
        response = self.source.source_for_pipeline(_config(), manager, _inputs(schema_name=endpoint))

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys == expected_partition_keys
        # Rows arrive in record-id order, not incremental-field order — the watermark must only
        # persist at successful job end
        assert response.sort_mode == "desc"

    def test_source_for_pipeline_ignores_watermark_when_incremental_disabled(self):
        with mock.patch(f"{_MODULE}.qualys_vmdr_source") as transport:
            inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01")
            self.source.source_for_pipeline(_config(), mock.MagicMock(), inputs)

        assert transport.call_args.kwargs["db_incremental_field_last_value"] is None

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "Unauthorized for url"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()
