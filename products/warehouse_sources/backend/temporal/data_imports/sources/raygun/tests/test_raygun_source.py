from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RaygunSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.raygun import RaygunResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.source import RaygunSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.raygun.source"


def _config() -> RaygunSourceConfig:
    return RaygunSourceConfig(personal_access_token="tok")


class TestRaygunSourceConfig:
    def test_source_type(self) -> None:
        assert RaygunSource().source_type == ExternalDataSourceType.RAYGUN

    def test_get_source_config_shape(self) -> None:
        config = RaygunSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        # A finished source ships visible with a soft ALPHA label, never hidden.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert len(fields) == 1
        token_field = fields[0]
        assert token_field.name == "personal_access_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    def test_get_schemas_full_refresh_only(self) -> None:
        schemas = RaygunSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint has a server-side timestamp filter, so none support incremental sync.
        assert all(s.supports_incremental is False for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = RaygunSource().get_schemas(_config(), team_id=1, names=["applications", "sessions"])
        assert {s.name for s in schemas} == {"applications", "sessions"}

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = RaygunSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas does no I/O, so the public docs catalog can render.
        assert RaygunSource.lists_tables_without_credentials is True

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = RaygunSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RaygunResumeConfig


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("token_result", "schema_name", "expected_valid"),
        [
            ((True, 200), None, True),
            # A valid token missing a scope is accepted at source-create (no schema)...
            ((False, 403), None, True),
            # ...but rejected when probing a specific table's scope.
            ((False, 403), "sessions", False),
            ((False, 401), None, False),
            ((False, None), None, False),
        ],
    )
    @patch(f"{MODULE}.validate_token")
    def test_status_to_result(
        self,
        mock_validate: MagicMock,
        token_result: tuple[bool, int | None],
        schema_name: str | None,
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = token_result
        is_valid, _ = RaygunSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert is_valid is expected_valid


class TestSourceForPipeline:
    @patch(f"{MODULE}.raygun_source")
    def test_plumbs_token_and_endpoint(self, mock_raygun_source: MagicMock) -> None:
        sentinel = object()
        mock_raygun_source.return_value = sentinel

        inputs = MagicMock()
        inputs.schema_name = "error_groups"
        logger: Any = MagicMock()
        inputs.logger = logger
        manager = MagicMock(spec=ResumableSourceManager)

        result = RaygunSource().source_for_pipeline(_config(), manager, inputs)

        assert result is sentinel
        _, kwargs = mock_raygun_source.call_args
        assert kwargs["personal_access_token"] == "tok"
        assert kwargs["endpoint"] == "error_groups"
        assert kwargs["resumable_source_manager"] is manager
