from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import CLOCKIFY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.source import ClockifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clockify import (
    ClockifySourceConfig,
)


class TestClockifySource:
    def setup_method(self) -> None:
        self.source = ClockifySource()
        self.team_id = 123

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
