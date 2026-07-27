from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.runpod import RunPodResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.source import RunPodSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_BILLING_ENDPOINTS = ["billing_pods", "billing_endpoints", "billing_network_volumes"]
_INVENTORY_ENDPOINTS = ["pods", "endpoints", "templates", "network_volumes"]


class TestRunPodSourceConfig:
    def test_source_type(self) -> None:
        assert RunPodSource().source_type == ExternalDataSourceType.RUNPOD

    def test_config_exposes_single_secret_api_key_field(self) -> None:
        config = RunPodSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.RUN_POD
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/runpod"
        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["api_key"]
        assert fields[0].secret is True and fields[0].required is True


class TestRunPodSchemas:
    def test_all_endpoints_present(self) -> None:
        names = {s.name for s in RunPodSource().get_schemas(MagicMock(), team_id=1)}
        assert names == set(_BILLING_ENDPOINTS) | set(_INVENTORY_ENDPOINTS)

    @parameterized.expand([(name,) for name in _BILLING_ENDPOINTS])
    def test_billing_endpoints_are_incremental_on_time(self, endpoint: str) -> None:
        # Only the billing endpoints have a genuine server-side time filter (startTime).
        schema = next(s for s in RunPodSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False  # open buckets get restated; append would duplicate
        assert [f["field"] for f in schema.incremental_fields] == ["time"]
        assert schema.default_incremental_lookback_seconds == 60 * 60 * 48

    @parameterized.expand([(name,) for name in _INVENTORY_ENDPOINTS])
    def test_inventory_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # No updated-since filter exists on the resource lists, so they must not advertise incremental.
        schema = next(s for s in RunPodSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_names_filter(self) -> None:
        schemas = RunPodSource().get_schemas(MagicMock(), team_id=1, names=["billing_pods"])
        assert [s.name for s in schemas] == ["billing_pods"]


class TestRunPodResumableManager:
    def test_manager_bound_to_resume_config(self) -> None:
        manager = RunPodSource().get_resumable_source_manager(MagicMock())
        assert manager._data_class is RunPodResumeConfig


class TestRunPodSourceForPipeline:
    @parameterized.expand(
        [
            ("billing_pods", "datetime", ["time"]),
            ("billing_endpoints", "datetime", ["time"]),
            ("billing_network_volumes", "datetime", ["time"]),
            ("pods", None, None),
            ("templates", None, None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, partition_mode: str | None, partition_keys: list[str] | None
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        response = RunPodSource().source_for_pipeline(MagicMock(api_key="rpa_test"), MagicMock(), inputs)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == partition_mode
        assert response.partition_keys == partition_keys


class TestDocumentedTables:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog => the source opts into publishing its table list to public docs.
        assert RunPodSource().lists_tables_without_credentials is True
        tables = RunPodSource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert set(_BILLING_ENDPOINTS) | set(_INVENTORY_ENDPOINTS) <= names
        billing = next(t for t in tables if t["name"] == "billing_pods")
        assert "Incremental" in billing["sync_methods"]
        assert billing["description"]  # canonical description is surfaced
