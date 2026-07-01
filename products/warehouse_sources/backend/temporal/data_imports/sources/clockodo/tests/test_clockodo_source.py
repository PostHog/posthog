from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo import ClockodoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.source import ClockodoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClockodoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> ClockodoSourceConfig:
    return ClockodoSourceConfig(api_user="me@example.com", api_key="secret")


class TestClockodoSource:
    def test_source_type(self) -> None:
        assert ClockodoSource().source_type == ExternalDataSourceType.CLOCKODO

    def test_source_config_shape(self) -> None:
        config = ClockodoSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/clockodo"
        field_names = {f.name for f in config.fields}
        assert field_names == {"api_user", "api_key"}

    def test_api_key_field_is_secret(self) -> None:
        config = ClockodoSource().get_source_config
        api_key = next(f for f in config.fields if f.name == "api_key")
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.secret is True
        assert api_key.required is True

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

    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = ClockodoSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = ClockodoSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ClockodoResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.logger = MagicMock()
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
