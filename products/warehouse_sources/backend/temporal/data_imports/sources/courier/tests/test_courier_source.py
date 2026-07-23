from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.courier import CourierResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.source import CourierSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "sk_test") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert CourierSource().source_type == ExternalDataSourceType.COURIER

    def test_config_is_visible_and_alpha(self) -> None:
        config = CourierSource().get_source_config
        # A finished source must not be hidden from users.
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.COMMUNICATION
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/courier"

    def test_fields(self) -> None:
        fields = {f.name: f for f in CourierSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key"}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True

    def test_non_retryable_errors_cover_auth_failure(self) -> None:
        errors = CourierSource().get_non_retryable_errors()
        assert any("403" in key for key in errors)


class TestGetSchemas:
    def test_only_server_side_filtered_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in CourierSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only Messages (enqueued_after) has a genuine server-side timestamp filter.
        assert {name for name, s in schemas.items() if s.supports_incremental} == {"Messages"}
        assert [f["field"] for f in schemas["Messages"].incremental_fields] == ["enqueued"]

    def test_names_filter(self) -> None:
        schemas = CourierSource().get_schemas(_config(), team_id=1, names=["Brands", "Tenants"])
        assert {s.name for s in schemas} == {"Brands", "Tenants"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert CourierSource.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in CourierSource().get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["Brands"]["sync_methods"] == ["Full refresh"]
        assert "Incremental" in tables["Messages"]["sync_methods"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Courier authentication failed: Invalid or missing authentication credentials.")),
        ]
    )
    def test_plumbs_transport_result(self, _name: str, result: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.courier.source.validate_courier_credentials",
            return_value=result,
        ) as mocked:
            assert CourierSource().validate_credentials(_config(), team_id=1) == result
        mocked.assert_called_once_with("sk_test")


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = CourierSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CourierResumeConfig

    @parameterized.expand(
        [
            ("incremental", True, "2026-01-01"),
            # A stale watermark must not leak into a full-refresh run.
            ("full_refresh", False, None),
        ]
    )
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, should_use_incremental_field: bool, expected_last_value: Any
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = "Messages"
        inputs.team_id = 42
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.courier.source.courier_source"
        ) as mocked:
            CourierSource().source_for_pipeline(_config(), manager, inputs)

        mocked.assert_called_once_with(
            api_key="sk_test",
            endpoint="Messages",
            team_id=42,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )
