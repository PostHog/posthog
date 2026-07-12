from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HarveySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.harvey import HarveyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source import HarveySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "audit_logs",
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


class TestHarveySource:
    def setup_method(self) -> None:
        self.source = HarveySource()
        self.team_id = 123
        self.config = HarveySourceConfig(api_key="test-token", region="us")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HARVEY

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Harvey"
        assert config.label == "Harvey"
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/harvey.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/harvey"

        api_key_field, region_field = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.name == "region"
        assert region_field.required is True
        assert region_field.defaultValue == "us"
        assert [option.value for option in region_field.options] == ["us", "eu", "au"]

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error: Unauthorized for url", "403 Client Error: Forbidden for url"],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("endpoint", "supports_incremental", "supports_append", "incremental_field"),
        [
            # Audit logs are immutable, so only append is offered.
            ("audit_logs", False, True, "timestamp"),
            ("usage_history", True, True, "utc_time"),
            ("query_history", True, True, "utc_time"),
            ("client_matters", False, False, None),
            ("vault_projects", False, False, None),
        ],
    )
    def test_get_schemas_sync_modes(
        self,
        endpoint: str,
        supports_incremental: bool,
        supports_append: bool,
        incremental_field: str | None,
    ) -> None:
        (schema,) = self.source.get_schemas(self.config, self.team_id, names=[endpoint])

        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_append
        if incremental_field is None:
            assert schema.incremental_fields == []
        else:
            assert [f["field"] for f in schema.incremental_fields] == [incremental_field]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.validate_harvey_credentials"
    )
    def test_validate_credentials_success(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with("test-token", "us")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.validate_harvey_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Harvey API token"

    @pytest.mark.parametrize(
        ("access_reason", "expected_valid"),
        [
            (None, True),
            ("Your API token does not have permission for this endpoint.", False),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.check_endpoint_access")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.validate_harvey_credentials"
    )
    def test_validate_credentials_with_schema_name_checks_endpoint_access(
        self,
        mock_validate: mock.MagicMock,
        mock_access: mock.MagicMock,
        access_reason: str | None,
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = True
        mock_access.return_value = access_reason

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name="audit_logs")

        assert is_valid is expected_valid
        assert error_message == access_reason
        mock_access.assert_called_once_with("test-token", "us", "audit_logs")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.check_endpoint_access")
    def test_get_endpoint_permissions(self, mock_access: mock.MagicMock) -> None:
        mock_access.side_effect = lambda api_key, region, endpoint: (
            "missing permission" if endpoint == "vault_projects" else None
        )

        permissions = self.source.get_endpoint_permissions(
            self.config, self.team_id, ["audit_logs", "vault_projects", "unknown_endpoint"]
        )

        assert permissions == {
            "audit_logs": None,
            "vault_projects": "missing permission",
            "unknown_endpoint": None,
        }

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HarveyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.harvey_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="usage_history")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-token",
            region="us",
            endpoint="usage_history",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.harvey_source")
    def test_source_for_pipeline_strips_last_value_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_known_endpoints(self) -> None:
        assert set(self.source.get_canonical_descriptions().keys()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
