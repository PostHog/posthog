from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    LessAnnoyingCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.less_annoying_crm import (
    LessAnnoyingCRMResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.settings import (
    ENDPOINTS,
    LESS_ANNOYING_CRM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source import (
    LessAnnoyingCRMSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source"


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "contacts")
    return inputs


class TestLessAnnoyingCRMSource:
    def setup_method(self) -> None:
        self.source = LessAnnoyingCRMSource()
        self.team_id = 123
        self.config = LessAnnoyingCRMSourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LESSANNOYINGCRM

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "LessAnnoyingCRM"
        assert config.label == "Less Annoying CRM"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/less-annoying-crm"

        assert len(config.fields) == 1
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_are_full_refresh_only(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        # LACRM has no server-side modified-since filter, so nothing is incremental.
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.detected_primary_keys == LESS_ANNOYING_CRM_ENDPOINTS[endpoint].primary_keys

    def test_get_schemas_names_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts", "tasks"])
        assert {s.name for s in schemas} == {"contacts", "tasks"}

    def test_validate_credentials_success(self) -> None:
        with mock.patch(f"{MODULE}.validate_less_annoying_crm_credentials", return_value=True):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch(f"{MODULE}.validate_less_annoying_crm_credentials", return_value=False):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error is not None

    def test_non_retryable_errors_cover_invalid_credentials(self) -> None:
        assert "Invalid credentials" in self.source.get_non_retryable_errors()

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LessAnnoyingCRMResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = _make_inputs(schema_name="tasks")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        with mock.patch(f"{MODULE}.less_annoying_crm_source") as mocked:
            self.source.source_for_pipeline(self.config, manager, inputs)
        mocked.assert_called_once_with(
            api_key="test-key",
            endpoint="tasks",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )

    def test_canonical_descriptions_key_on_endpoint_names(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "contacts" in descriptions

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)
