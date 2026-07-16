from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram import DeepgramResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.source import DeepgramSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeepgramSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "requests",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestDeepgramSourceClass:
    def setup_method(self) -> None:
        self.source = DeepgramSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DEEPGRAM

    def test_config_has_required_password_api_key(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True

    def test_config_stays_unreleased_alpha_with_docs(self) -> None:
        config = self.source.get_source_config
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/deepgram"

    @parameterized.expand(
        [
            ("requests_incremental", "requests", True),
            ("members_full_refresh", "members", False),
            ("balances_full_refresh", "balances", False),
            ("projects_full_refresh", "projects", False),
        ]
    )
    def test_only_requests_supports_incremental(self, _name: str, endpoint: str, incremental: bool) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is incremental

    def test_schemas_expose_composite_primary_keys(self) -> None:
        # Fan-out children must key on [project_id, ...] to stay unique table-wide; a regression to a
        # bare id would seed duplicate rows across projects.
        schemas = {s.name: s.detected_primary_keys for s in self.source.get_schemas(MagicMock(), team_id=1)}
        assert schemas["members"] == ["project_id", "member_id"]
        assert schemas["requests"] == ["project_id", "request_id"]

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["requests"])
        assert [s.name for s in schemas] == ["requests"]

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, api_ok: bool, expected: bool) -> None:
        with patch.object(source_module, "validate_deepgram_credentials", return_value=api_ok):
            ok, _error = self.source.validate_credentials(DeepgramSourceConfig(api_key="k"), team_id=1)
        assert ok is expected

    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DeepgramResumeConfig

    @parameterized.expand([("incremental_on", True), ("incremental_off", False)])
    def test_source_for_pipeline_gates_last_value_on_incremental(self, _name: str, use_incremental: bool) -> None:
        config = DeepgramSourceConfig(api_key="k")
        inputs = _inputs(should_use_incremental_field=use_incremental, db_incremental_field_last_value="2026-01-01")
        with patch.object(source_module, "deepgram_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "k"
        assert kwargs["should_use_incremental_field"] is use_incremental
        # The last value is only forwarded when the sync is actually incremental.
        assert kwargs["db_incremental_field_last_value"] == ("2026-01-01" if use_incremental else None)
