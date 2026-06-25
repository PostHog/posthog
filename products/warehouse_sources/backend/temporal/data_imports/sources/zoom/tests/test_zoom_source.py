import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZoomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.source import ZoomSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.zoom import ZoomResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zoom.source"


def _config() -> ZoomSourceConfig:
    return ZoomSourceConfig(account_id="acc", client_id="cid", client_secret="secret")


def _inputs(schema_name: str = "users") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestZoomSource:
    def test_source_type(self) -> None:
        assert ZoomSource().source_type == ExternalDataSourceType.ZOOM

    def test_source_config_fields(self) -> None:
        config = ZoomSource().get_source_config
        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"account_id", "client_id", "client_secret"}
        assert fields["client_secret"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["client_secret"].secret is True
        assert fields["account_id"].secret is False
        assert fields["client_id"].secret is False

    def test_source_config_is_alpha(self) -> None:
        config = ZoomSource().get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource

    def test_get_schemas_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = ZoomSource().get_schemas(_config(), team_id=1)
        names = {s.name for s in schemas}
        assert names == {"users", "meetings", "webinars"}
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    @pytest.mark.parametrize("names", [["users"], ["meetings", "webinars"]])
    def test_get_schemas_filters_by_names(self, names: list[str]) -> None:
        schemas = ZoomSource().get_schemas(_config(), team_id=1, names=names)
        assert {s.name for s in schemas} == set(names)

    def test_validate_credentials_delegates(self) -> None:
        with patch(f"{MODULE}.validate_zoom_credentials", return_value=(True, None)) as mock_validate:
            result = ZoomSource().validate_credentials(_config(), team_id=1, schema_name="users")
        assert result == (True, None)
        mock_validate.assert_called_once_with(
            account_id="acc", client_id="cid", client_secret="secret", schema_name="users"
        )

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = ZoomSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZoomResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _inputs(schema_name="meetings")
        with patch(f"{MODULE}.zoom_source") as mock_source:
            ZoomSource().source_for_pipeline(_config(), manager, inputs)
        mock_source.assert_called_once_with(
            account_id="acc",
            client_id="cid",
            client_secret="secret",
            endpoint="meetings",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = ZoomSource().get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors
        assert "Invalid access token" in errors
