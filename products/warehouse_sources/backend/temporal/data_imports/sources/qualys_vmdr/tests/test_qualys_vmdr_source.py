import datetime

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualysvmdr import (
    QualysVmdrSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source import QualysVmdrSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source"


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

    def test_default_version_is_4_0_and_2_0_is_deprecated(self):
        # New sources start on 4.0; 2.0 carries the vendor's announced sunset date and 4.0 is clean.
        assert self.source.default_version == "4.0"
        deprecation = self.source.get_version_deprecation("2.0")
        assert deprecation is not None and deprecation.sunset_at == datetime.date(2026, 6, 30)
        assert self.source.get_version_deprecation("4.0") is None

    @pytest.mark.parametrize(
        "pin,expected_version",
        [("2.0", "2.0"), ("4.0", "4.0"), (None, "4.0")],
    )
    def test_source_for_pipeline_threads_resolved_version_and_gateway(self, pin, expected_version):
        with mock.patch(f"{_MODULE}.qualys_vmdr_source") as transport:
            self.source.source_for_pipeline(
                _config(gateway_server="gateway.qg2.apps.qualys.com"),
                mock.MagicMock(),
                _inputs(schema_name="knowledge_base", api_version=pin),
            )

        # A NULL pin resolves to default_version (4.0); a present pin is honored verbatim.
        assert transport.call_args.kwargs["api_version"] == expected_version
        assert transport.call_args.kwargs["gateway_server"] == "gateway.qg2.apps.qualys.com"
