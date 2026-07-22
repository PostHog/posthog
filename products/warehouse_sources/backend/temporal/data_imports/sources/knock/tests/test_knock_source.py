from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.knock import KnockResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.source import KnockSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "sk_test") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert KnockSource().source_type == ExternalDataSourceType.KNOCK

    def test_config_is_visible_and_alpha(self) -> None:
        config = KnockSource().get_source_config
        # A finished source must not be hidden from users.
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/knock"

    def test_fields(self) -> None:
        fields = {f.name: f for f in KnockSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key"}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True


class TestGetSchemas:
    def test_only_server_side_filtered_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in KnockSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only messages (inserted_at[gte]) and workflow_recipient_runs (starting_at)
        # have a genuine server-side timestamp filter.
        assert {name for name, s in schemas.items() if s.supports_incremental} == {
            "messages",
            "workflow_recipient_runs",
        }
        assert [f["field"] for f in schemas["messages"].incremental_fields] == ["inserted_at"]
        assert [f["field"] for f in schemas["workflow_recipient_runs"].incremental_fields] == ["inserted_at"]

    def test_names_filter(self) -> None:
        schemas = KnockSource().get_schemas(_config(), team_id=1, names=["users", "tenants"])
        assert {s.name for s in schemas} == {"users", "tenants"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert KnockSource.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in KnockSource().get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["users"]["sync_methods"] == ["Full refresh"]
        assert "Incremental" in tables["messages"]["sync_methods"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "The API key you supplied is invalid")),
        ]
    )
    def test_plumbs_transport_result(self, _name: str, result: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.knock.source.validate_knock_credentials",
            return_value=result,
        ) as mocked:
            assert KnockSource().validate_credentials(_config(), team_id=1) == result
        mocked.assert_called_once_with("sk_test")


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = KnockSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is KnockResumeConfig

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
        inputs.schema_name = "messages"
        inputs.team_id = 42
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.knock.source.knock_source"
        ) as mocked:
            KnockSource().source_for_pipeline(_config(), manager, inputs)

        mocked.assert_called_once_with(
            api_key="sk_test",
            endpoint="messages",
            team_id=42,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )
