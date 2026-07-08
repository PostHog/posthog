from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SendGridSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import SendGridResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source import SendGridSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_ENDPOINTS = {
    "bounces",
    "blocks",
    "invalid_emails",
    "spam_reports",
    "global_unsubscribes",
    "unsubscribe_groups",
    "marketing_lists",
    "templates",
}
INCREMENTAL_ENDPOINTS = {"bounces", "blocks", "invalid_emails", "spam_reports", "global_unsubscribes"}


def _config() -> SendGridSourceConfig:
    return SendGridSourceConfig(api_key="SG.test-key")


def _source_inputs(schema_name: str = "bounces", **overrides: Any) -> SourceInputs:
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
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSendGridSource:
    def test_source_type(self) -> None:
        assert SendGridSource().source_type == ExternalDataSourceType.SENDGRID

    def test_source_config_basics(self) -> None:
        config = SendGridSource().get_source_config
        assert config.label == "SendGrid"
        assert config.releaseStatus == "alpha"
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/sendgrid.png"

    def test_source_config_has_api_key_password_field(self) -> None:
        fields = SendGridSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = SendGridSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == ALL_ENDPOINTS

    def test_only_suppression_endpoints_support_incremental(self) -> None:
        schemas = {s.name: s for s in SendGridSource().get_schemas(_config(), team_id=1)}
        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert {f["field"] for f in schemas[name].incremental_fields} == {"created"}
        for name in ALL_ENDPOINTS - INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = SendGridSource().get_schemas(_config(), team_id=1, names=["bounces", "templates"])
        assert {s.name for s in schemas} == {"bounces", "templates"}

    @pytest.mark.parametrize(
        ("status", "schema_name", "expected_ok", "expected_has_msg"),
        [
            (200, None, True, False),
            (200, "bounces", True, False),
            (401, None, False, True),
            (401, "bounces", False, True),
            # 403 = valid token, missing scope: accepted at source-create, rejected per-schema.
            (403, None, True, False),
            (403, "bounces", False, True),
            (None, None, False, True),
        ],
    )
    def test_validate_credentials(
        self, status: int | None, schema_name: str | None, expected_ok: bool, expected_has_msg: bool
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source.get_status_code",
            return_value=status,
        ):
            ok, msg = SendGridSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert (msg is not None) is expected_has_msg

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = SendGridSource().get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SendGridResumeConfig

    def test_get_non_retryable_errors_covers_auth(self) -> None:
        errors = SendGridSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs(
            schema_name="bounces",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="created",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source.sendgrid_source"
        ) as mock_source:
            mock_source.return_value = MagicMock(spec=SourceResponse)
            SendGridSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "SG.test-key"
        assert kwargs["endpoint"] == "bounces"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["incremental_field"] == "created"

    def test_source_for_pipeline_drops_cursor_when_not_incremental(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs(
            schema_name="bounces",
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source.sendgrid_source"
        ) as mock_source:
            mock_source.return_value = MagicMock(spec=SourceResponse)
            SendGridSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
