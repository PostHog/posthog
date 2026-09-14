from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.bigeye import BigeyeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.source import BigeyeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigeye import BigeyeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Workspaces",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestBigeyeSource:
    def setup_method(self) -> None:
        self.source = BigeyeSource()
        self.team_id = 123
        self.config = BigeyeSourceConfig(api_key="test-key", host=None, workspace_id=None)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BIGEYE

    def test_host_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to the configured host, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["host"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Bigeye"
        assert config.label == "Bigeye"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/bigeye.png"

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["api_key", "host", "workspace_id"]

        by_name = {f.name: f for f in fields}
        assert by_name["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert by_name["api_key"].secret is True
        assert by_name["api_key"].required is True
        assert by_name["host"].type == SourceFieldInputConfigType.TEXT
        assert by_name["host"].required is False
        assert by_name["workspace_id"].type == SourceFieldInputConfigType.NUMBER
        assert by_name["workspace_id"].required is False

    def test_no_unreleased_source_flag(self) -> None:
        # A finished source ships visible; unreleasedSource hides it from the wizard entirely.
        assert self.source.get_source_config.unreleasedSource is None

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(expected_key in k for k in keys)

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No Bigeye list endpoint exposes a server-side updated-since filter.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Issues"])
        assert len(schemas) == 1
        assert schemas[0].name == "Issues"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            (
                (False, "Invalid Bigeye API key. Please check your key and try again."),
                False,
                "Invalid Bigeye API key. Please check your key and try again.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.source.validate_bigeye_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key", None, None, self.team_id)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BigeyeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.source.bigeye_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        config = BigeyeSourceConfig(api_key="test-key", host="bigeye.internal.example.com", workspace_id=7)
        inputs = _make_inputs(schema_name="Issues", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            host="bigeye.internal.example.com",
            workspace_id=7,
            endpoint="Issues",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
        )

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        described = self.source.get_canonical_descriptions()
        assert set(described.keys()) == set(ENDPOINTS)
