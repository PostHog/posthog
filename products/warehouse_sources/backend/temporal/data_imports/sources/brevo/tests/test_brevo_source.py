from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo import BrevoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source import BrevoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrevoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> BrevoSourceConfig:
    return BrevoSourceConfig(api_key="test-key")


def _source_inputs(schema_name: str = "contacts", **overrides: Any) -> SourceInputs:
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


class TestBrevoSource:
    def test_source_type(self) -> None:
        assert BrevoSource().source_type == ExternalDataSourceType.BREVO

    def test_source_config_basics(self) -> None:
        config = BrevoSource().get_source_config
        assert config.label == "Brevo"
        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.iconPath == "/static/services/brevo.png"

    def test_source_config_has_api_key_password_field(self) -> None:
        fields = BrevoSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = BrevoSource().get_schemas(_config(), team_id=1)
        names = {s.name for s in schemas}
        assert names == {
            "contacts",
            "contact_lists",
            "contact_folders",
            "contact_segments",
            "email_campaigns",
            "sms_campaigns",
            "email_templates",
            "senders",
        }

    def test_only_contacts_supports_incremental(self) -> None:
        schemas = {s.name: s for s in BrevoSource().get_schemas(_config(), team_id=1)}
        assert schemas["contacts"].supports_incremental is True
        assert {f["field"] for f in schemas["contacts"].incremental_fields} == {"createdAt", "modifiedAt"}
        for name in ["contact_lists", "email_campaigns", "sms_campaigns", "senders"]:
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = BrevoSource().get_schemas(_config(), team_id=1, names=["contacts", "senders"])
        assert {s.name for s in schemas} == {"contacts", "senders"}

    @pytest.mark.parametrize(
        ("valid", "expected_ok", "expected_msg"),
        [(True, True, None), (False, False, "Invalid Brevo API key")],
    )
    def test_validate_credentials(self, valid: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source.validate_brevo_credentials",
            return_value=valid,
        ):
            ok, msg = BrevoSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = BrevoSource().get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BrevoResumeConfig

    def test_get_non_retryable_errors_covers_auth(self) -> None:
        errors = BrevoSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs(
            schema_name="contacts",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
            incremental_field="modifiedAt",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source.brevo_source"
        ) as mock_brevo_source:
            mock_brevo_source.return_value = MagicMock(spec=SourceResponse)
            BrevoSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_brevo_source.call_args
        assert kwargs["api_key"] == "test-key"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "modifiedAt"

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs(
            schema_name="contacts",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source.brevo_source"
        ) as mock_brevo_source:
            mock_brevo_source.return_value = MagicMock(spec=SourceResponse)
            BrevoSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_brevo_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
