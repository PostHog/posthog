from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HubplannerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.hubplanner import (
    HubPlannerResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.source import HubplannerSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHubplannerSource:
    def setup_method(self) -> None:
        self.source = HubplannerSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HUBPLANNER

    def test_source_config_shape(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Hub Planner"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hubplanner"

    def test_source_config_has_single_secret_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so the public docs table list can render.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("bookings", True),
            ("time_entries", True),
            ("projects", False),
            ("resources", False),
            ("milestones", False),
            ("vacations", False),
        ]
    )
    def test_incremental_support_only_where_server_side_filter_exists(self, endpoint: str, expected: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected
        assert schema.supports_append is expected
        if expected:
            assert [f["field"] for f in schema.incremental_fields] == ["updatedDate"]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_names_filter(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["bookings", "projects"])
        assert {s.name for s in schemas} == {"bookings", "projects"}

    @parameterized.expand([("forbidden", "403 Client Error"), ("unauthorized", "401 Client Error")])
    def test_auth_errors_are_non_retryable(self, _name: str, prefix: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(key.startswith(prefix) for key in keys)

    def test_validate_credentials_success(self) -> None:
        config = HubplannerSourceConfig(api_key="good")
        with patch.object(source_module, "validate_hubplanner_credentials", return_value=True):
            assert self.source.validate_credentials(config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        config = HubplannerSourceConfig(api_key="bad")
        with patch.object(source_module, "validate_hubplanner_credentials", return_value=False):
            valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert error is not None

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is HubPlannerResumeConfig

    def test_source_for_pipeline_plumbs_inputs(self) -> None:
        config = HubplannerSourceConfig(api_key="k")
        manager = MagicMock()
        inputs = MagicMock()
        inputs.schema_name = "bookings"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = "updatedDate"

        with patch.object(source_module, "hubplanner_source") as mock_source:
            self.source.source_for_pipeline(config, manager, inputs)

        _args, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "k"
        assert kwargs["endpoint"] == "bookings"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        config = HubplannerSourceConfig(api_key="k")
        inputs = MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        with patch.object(source_module, "hubplanner_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)

        _args, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        descriptions: dict[str, Any] = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        # The high-value core tables should be documented.
        assert {"projects", "resources", "bookings", "time_entries"}.issubset(set(descriptions))
