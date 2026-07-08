from typing import Any

import pytest
from unittest.mock import MagicMock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.clockify import ClockifyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import (
    CLOCKIFY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.source import ClockifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClockifySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestClockifySource:
    def setup_method(self) -> None:
        self.source = ClockifySource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CLOCKIFY

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Clockify"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True

    def test_source_config_has_secret_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_time_entries_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        for name, schema in schemas.items():
            expected = name == "time_entries"
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected

    def test_time_entries_incremental_field(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        fields = schemas["time_entries"].incremental_fields
        assert [f["field"] for f in fields] == ["time_interval_start"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["clients", "time_entries"])
        assert {s.name for s in schemas} == {"clients", "time_entries"}

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_non_retryable_error_keys_match_clockify_host(self) -> None:
        # The observed HTTPError message embeds the request URL; the key must match the base host.
        observed = "401 Client Error: Unauthorized for url: https://api.clockify.me/api/v1/user"
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    def test_validate_credentials_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clockify.source.validate_clockify_credentials",
            lambda api_key: True,
        )
        config = ClockifySourceConfig(api_key="key")
        assert self.source.validate_credentials(config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clockify.source.validate_clockify_credentials",
            lambda api_key: False,
        )
        config = ClockifySourceConfig(api_key="bad")
        valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert error is not None

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ClockifyResumeConfig

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    def test_source_for_pipeline_plumbs_endpoint_and_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clockify.source.clockify_source",
            fake_source,
        )

        inputs = MagicMock()
        inputs.schema_name = "time_entries"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-04T00:00:00Z"
        inputs.incremental_field = "time_interval_start"
        manager = MagicMock()

        self.source.source_for_pipeline(ClockifySourceConfig(api_key="key"), manager, inputs)
        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "time_entries"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-03-04T00:00:00Z"

    def test_source_for_pipeline_drops_incremental_value_when_full_refresh(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clockify.source.clockify_source",
            lambda **kwargs: captured.update(kwargs),
        )

        inputs = MagicMock()
        inputs.schema_name = "clients"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(ClockifySourceConfig(api_key="key"), MagicMock(), inputs)
        assert captured["db_incremental_field_last_value"] is None


class TestEndpointConfig:
    def test_fan_out_children_include_parent_ids_in_primary_key(self) -> None:
        # Fan-out child ids are unique only within their parent, so the parent id(s) must be part
        # of the primary key or merges would collapse rows across parents.
        assert CLOCKIFY_ENDPOINTS["tasks"].primary_keys == ["workspace_id", "project_id", "id"]
        assert CLOCKIFY_ENDPOINTS["time_entries"].primary_keys == ["workspace_id", "user_id", "id"]

    def test_only_time_entries_has_a_server_side_filter(self) -> None:
        with_filter = [name for name, cfg in CLOCKIFY_ENDPOINTS.items() if cfg.incremental_param]
        assert with_filter == ["time_entries"]
        assert CLOCKIFY_ENDPOINTS["time_entries"].incremental_param == "start"

    def test_partition_keys_are_creation_style_not_updated(self) -> None:
        for cfg in CLOCKIFY_ENDPOINTS.values():
            if cfg.partition_key:
                assert "updated" not in cfg.partition_key
                assert "last" not in cfg.partition_key.lower()
