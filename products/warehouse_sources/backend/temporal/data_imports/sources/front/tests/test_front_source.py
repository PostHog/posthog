from typing import Any, Optional

from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.front import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.front.front import FrontResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.front.source import FrontSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger()


def _config(api_token: str = "tok") -> Any:
    return FrontSource().parse_config({"api_token": api_token})


def _inputs(schema_name: str = "events", **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": logger,
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestFrontSource:
    def test_source_type(self) -> None:
        assert FrontSource().source_type == ExternalDataSourceType.FRONT

    def test_source_config(self) -> None:
        config = FrontSource().get_source_config
        assert config.label == "Front"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_token"]
        api_token_field = config.fields[0]
        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.type == "password"
        assert api_token_field.required is True

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = FrontSource().get_schemas(_config(), team_id=1)
        names = {s.name for s in schemas}
        assert {
            "events",
            "contacts",
            "conversations",
            "accounts",
            "tags",
            "teammates",
            "inboxes",
            "channels",
            "teams",
        } == names

    def test_only_events_supports_incremental(self) -> None:
        schemas = {s.name: s for s in FrontSource().get_schemas(_config(), team_id=1)}
        assert schemas["events"].supports_incremental is True
        assert schemas["events"].incremental_fields[0]["field"] == "emitted_at"
        for name in ("contacts", "conversations", "accounts", "tags", "teammates"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = FrontSource().get_schemas(_config(), team_id=1, names=["tags"])
        assert [s.name for s in schemas] == ["tags"]

    def test_non_retryable_errors(self) -> None:
        errors = FrontSource().get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors

    @parameterized.expand(
        [
            # (status_at_create, expected_ok) — source-create probe accepts everything but 401
            ("valid", True, None),
            ("invalid", False, "Invalid Front API token. Please reconnect with a valid token."),
        ]
    )
    def test_validate_credentials_at_source_create(self, _name: str, ok: bool, msg: Optional[str]) -> None:
        with patch.object(source_module, "validate_front_credentials", return_value=(ok, msg)) as mock_validate:
            result = FrontSource().validate_credentials(_config(), team_id=1, schema_name=None)
        assert result == (ok, msg)
        # source-create probes /teammates with require_scope=False
        mock_validate.assert_called_once_with("tok", "/teammates", require_scope=False)

    def test_validate_credentials_for_schema_requires_scope(self) -> None:
        with patch.object(source_module, "validate_front_credentials", return_value=(True, None)) as mock_validate:
            FrontSource().validate_credentials(_config(), team_id=1, schema_name="tags")
        mock_validate.assert_called_once_with("tok", "/tags", require_scope=True)

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = FrontSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FrontResumeConfig

    def test_source_for_pipeline_passes_arguments(self) -> None:
        manager = MagicMock()
        inputs = _inputs(
            schema_name="events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="emitted_at",
        )
        sentinel = MagicMock()
        with patch.object(source_module, "front_source", return_value=sentinel) as mock_source:
            result = FrontSource().source_for_pipeline(_config(), manager, inputs)

        assert result is sentinel
        _args, kwargs = mock_source.call_args
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "events"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        manager = MagicMock()
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value=1700000000)
        with patch.object(source_module, "front_source", return_value="response") as mock_source:
            FrontSource().source_for_pipeline(_config(), manager, inputs)
        _args, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
