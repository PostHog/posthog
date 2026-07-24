import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.codemagic import CodemagicResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source import CodemagicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codemagic import (
    CodemagicSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCodemagicSource:
    def setup_method(self) -> None:
        self.source = CodemagicSource()
        self.team_id = 123
        self.config = CodemagicSourceConfig(api_token="test-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CODEMAGIC

    def test_get_source_config_has_no_unreleased_flag(self) -> None:
        # A finished source ships visible — this is the one thing that must never regress.
        assert self.source.get_source_config.unreleasedSource is None

    def test_get_source_config_fields(self) -> None:
        fields = self.source.get_source_config.fields
        assert [f.name for f in fields] == ["api_token"]
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.required is True
        assert field.secret is True

    def test_get_source_config_category(self) -> None:
        from posthog.schema import DataWarehouseSourceCategory

        assert self.source.get_source_config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING

    def test_get_schemas_returns_applications_and_builds(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == {"Applications", "Builds"}

    def test_get_schemas_are_full_refresh_only(self) -> None:
        # Codemagic has no documented server-side timestamp filter on any endpoint.
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Builds"])
        assert [s.name for s in schemas] == ["Builds"]

    def test_get_canonical_descriptions_covers_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == {"Applications", "Builds"}

    @pytest.mark.parametrize(
        ("error_message", "expected_substring"),
        [
            ("401 Client Error: Unauthorized for url: https://api.codemagic.io/apps", "Invalid Codemagic API token"),
            ("Unauthorized for url: https://api.codemagic.io/builds", "Invalid Codemagic API token"),
        ],
    )
    def test_get_non_retryable_errors_matches_auth_failures(self, error_message: str, expected_substring: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        matched = next((msg for key, msg in non_retryable.items() if key in error_message), None)
        assert matched is not None
        assert expected_substring in matched

    def test_validate_credentials_delegates_to_transport(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source.validate_codemagic_credentials"
        ) as mock_validate:
            mock_validate.return_value = (True, None)
            result = self.source.validate_credentials(self.config, self.team_id)

        mock_validate.assert_called_once_with("test-token")
        assert result == (True, None)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock(spec=SourceInputs)
        inputs.logger = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CodemagicResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = "Builds"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source.codemagic_source"
        ) as mock_codemagic_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_codemagic_source.assert_called_once_with(
            api_token="test-token",
            endpoint="Builds",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
        )
