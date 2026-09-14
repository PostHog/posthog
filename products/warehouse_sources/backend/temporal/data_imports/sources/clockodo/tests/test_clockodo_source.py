from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.source import ClockodoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clockodo import (
    ClockodoSourceConfig,
)


def _config() -> ClockodoSourceConfig:
    return ClockodoSourceConfig(api_user="me@example.com", api_key="secret")


class TestClockodoSource:
    def test_get_schemas_lists_all_endpoints_full_refresh_only(self) -> None:
        schemas = ClockodoSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # The Clockodo API has no server-side modified-since filter, so nothing is incremental.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = ClockodoSource().get_schemas(_config(), team_id=1, names=["entries"])
        assert [s.name for s in schemas] == ["entries"]

    def test_lists_tables_without_credentials_renders_docs(self) -> None:
        # Static catalog → public docs Supported tables section renders without a live connection.
        assert ClockodoSource.lists_tables_without_credentials is True
        tables = ClockodoSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all(t["sync_methods"] == ["Full refresh"] for t in tables)

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.source.validate_clockodo_credentials",
            return_value=probe_result,
        ):
            ok, error = ClockodoSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    @parameterized.expand([("unpinned", None, "v3"), ("legacy_pin", "v2", "v2"), ("new_pin", "v3", "v3")])
    def test_source_for_pipeline_threads_resolved_api_version(
        self, _name: str, pin: str | None, expected_version: str
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.logger = MagicMock()
        inputs.api_version = pin
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.source.clockodo_source"
        ) as mock_source:
            ClockodoSource().source_for_pipeline(_config(), manager, inputs)
        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_user"] == "me@example.com"
        assert kwargs["api_key"] == "secret"
        assert kwargs["endpoint"] == "customers"
        assert kwargs["resumable_source_manager"] is manager
        # An unpinned source resolves to the default (v3); a pin is honored verbatim.
        assert kwargs["api_version"] == expected_version
