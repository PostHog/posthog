from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.baseten import BasetenResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.source import BasetenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BasetenSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.baseten.source"


def _inputs(schema_name: str = "models") -> SourceInputs:
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


class TestBasetenSourceConfig:
    def test_source_type(self) -> None:
        assert BasetenSource().source_type == ExternalDataSourceType.BASETEN

    def test_config_exposes_secret_api_key_field(self) -> None:
        config = BasetenSource().get_source_config
        fields = cast(list[SourceFieldInputConfig], config.fields)
        assert len(fields) == 1
        api_key = fields[0]
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

    def test_config_metadata(self) -> None:
        config = BasetenSource().get_source_config
        # Alpha + unreleased per the task's staged-rollout requirement.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/baseten"


class TestBasetenSchemas:
    def test_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = BasetenSource().get_schemas(BasetenSourceConfig(api_key="k"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No Baseten list endpoint exposes a server-side timestamp filter, so nothing is incremental.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)

    def test_names_filter(self) -> None:
        schemas = BasetenSource().get_schemas(BasetenSourceConfig(api_key="k"), team_id=1, names=["models", "chains"])
        assert {s.name for s in schemas} == {"models", "chains"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static catalog -> public docs render the table list.
        assert BasetenSource.lists_tables_without_credentials is True
        tables = BasetenSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)


class TestBasetenCredentials:
    @pytest.mark.parametrize(("valid", "expected_ok"), [(True, True), (False, False)])
    def test_validate_credentials(self, valid: bool, expected_ok: bool) -> None:
        with patch(f"{MODULE}.validate_baseten_credentials", return_value=valid):
            ok, error = BasetenSource().validate_credentials(BasetenSourceConfig(api_key="k"), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_non_retryable_errors_cover_403(self) -> None:
        errors = BasetenSource().get_non_retryable_errors()
        # Baseten answers a bad key with 403, not 401 — the 403 entry is the one that matters.
        assert any("403 Client Error" in key and "https://api.baseten.co" in key for key in errors)


class TestBasetenPipelineWiring:
    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = BasetenSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BasetenResumeConfig

    def test_source_for_pipeline_plumbs_args(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _inputs(schema_name="deployments")
        with patch(f"{MODULE}.baseten_source") as mock_source:
            BasetenSource().source_for_pipeline(BasetenSourceConfig(api_key="secret"), manager, inputs)
        mock_source.assert_called_once_with(
            api_key="secret",
            endpoint="deployments",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
