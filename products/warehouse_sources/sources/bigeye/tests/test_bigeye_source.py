from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.bigeye import BigeyeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.source import BigeyeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigeye import BigeyeSourceConfig


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

    def test_host_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to the configured host, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["host"]

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
