from typing import Any

import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.capsule_crm import (
    CapsuleCRMResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source import CapsuleCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CapsuleCRMSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCapsuleCRMSource:
    def setup_method(self) -> None:
        self.source = CapsuleCRMSource()
        self.config = CapsuleCRMSourceConfig(access_token="tok")
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CAPSULECRM

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Capsule CRM"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/capsule-crm"
        field_names = [f.name for f in config.fields]
        assert field_names == ["access_token"]
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        # The token is a secret so it must render as a password input.
        assert field.type == "password"
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs catalog can render.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(self.source.get_schemas(self.config, self.team_id))

    @pytest.mark.parametrize(
        "endpoint,expected_incremental",
        [
            ("parties", True),
            ("opportunities", True),
            ("kases", True),
            ("tasks", False),
            ("users", False),
            ("milestones", False),
            ("pipelines", False),
            ("categories", False),
            ("lost_reasons", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert endpoint in schemas
        assert schemas[endpoint].supports_incremental is expected_incremental
        if expected_incremental:
            assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["updatedAt"]
        else:
            assert schemas[endpoint].incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["parties", "tasks"])
        assert {s.name for s in schemas} == {"parties", "tasks"}

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_validate_credentials_success(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.validate_capsule_crm_credentials",
            return_value=True,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.validate_capsule_crm_credentials",
            return_value=False,
        ):
            ok, message = self.source.validate_credentials(self.config, self.team_id)
            assert ok is False
            assert message is not None

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CapsuleCRMResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "parties"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        captured: dict[str, Any] = {}

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.capsule_crm_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert captured["access_token"] == "tok"
        assert captured["endpoint"] == "parties"
        assert captured["resumable_source_manager"] is manager
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        captured: dict[str, Any] = {}

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.capsule_crm_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A non-incremental run must not pass a stale watermark through as a `since` filter.
        assert captured["db_incremental_field_last_value"] is None
