from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.source import RunPodSource

_BILLING_ENDPOINTS = ["billing_pods", "billing_endpoints", "billing_network_volumes"]
_INVENTORY_ENDPOINTS = ["pods", "endpoints", "templates", "network_volumes"]


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
