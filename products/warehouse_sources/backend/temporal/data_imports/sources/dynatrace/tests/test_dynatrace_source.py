from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.dynatrace import DynatraceResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.source import DynatraceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DynatraceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"problems", "events", "audit_logs"}


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "problems",
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


class TestDynatraceSource:
    def setup_method(self) -> None:
        self.source = DynatraceSource()
        self.team_id = 123
        self.config = DynatraceSourceConfig(
            environment_url="https://abc12345.live.dynatrace.com", api_token="dt0c01.token"
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DYNATRACE

    def test_environment_url_is_a_connection_host_field(self) -> None:
        # Changing the environment URL must force the token to be re-entered so it's never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["environment_url"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Dynatrace"
        assert config.label == "Dynatrace"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

        url_field, token_field = config.fields

        assert isinstance(url_field, SourceFieldInputConfig)
        assert url_field.name == "environment_url"
        assert url_field.type == SourceFieldInputConfigType.TEXT
        assert url_field.required is True
        assert url_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert len(schemas[name].incremental_fields) == 1
            assert schemas[name].incremental_fields[0]["field_type"] == "integer"

        for name in set(ENDPOINTS) - INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["problems", "nonexistent"])
        assert [s.name for s in schemas] == ["problems"]

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [
            ((True, None), True),
            ((False, "Invalid Dynatrace API token."), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.source.validate_dynatrace_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: tuple[bool, str | None], expected_valid: bool
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name="problems")

        assert is_valid is expected_valid
        assert error_message == mock_return[1]
        mock_validate.assert_called_once_with(
            "https://abc12345.live.dynatrace.com", "dt0c01.token", self.team_id, "problems"
        )

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DynatraceResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.source.dynatrace_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="metrics", team_id=99)
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            environment_url="https://abc12345.live.dynatrace.com",
            api_token="dt0c01.token",
            endpoint="metrics",
            team_id=99,
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.source.dynatrace_source")
    def test_source_for_pipeline_gates_incremental_value(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark must not leak into a full-refresh run.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value=1735689600000)
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
