import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualysvmdr import (
    QualysVmdrSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source import QualysVmdrSource


def _config(gateway_server: str | None = None) -> QualysVmdrSourceConfig:
    return QualysVmdrSourceConfig(
        api_server="qualysapi.qualys.com", username="user", password="pass", gateway_server=gateway_server
    )


def _inputs(**overrides) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "hosts")
    inputs.api_version = overrides.get("api_version", None)
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    return inputs


class TestQualysVmdrSource:
    def setup_method(self):
        self.source = QualysVmdrSource()

    def test_api_server_is_a_connection_host_field(self):
        # Retargeting `api_server` must force re-entry of the stored credentials
        assert "api_server" in self.source.connection_host_fields

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(_config(), team_id=1, names=["scans"])
        assert [s.name for s in schemas] == ["scans"]

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
