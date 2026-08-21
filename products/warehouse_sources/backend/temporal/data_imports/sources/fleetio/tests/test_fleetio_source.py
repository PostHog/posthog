from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.source import FleetioSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fleetio import (
    FleetioSourceConfig,
)


class TestFleetioSource:
    def setup_method(self) -> None:
        self.source = FleetioSource()
        self.team_id = 123

    def test_version_declarations(self) -> None:
        # New sources start on the newest stable version; the legacy pin stays supported so existing
        # rows keep syncing unchanged.
        assert self.source.default_version == "2025-05-05"
        assert set(self.source.supported_versions) == {"v1", "2025-05-05"}

    @pytest.mark.parametrize("probe_result,expected_valid", [(True, True), (False, False)])
    def test_validate_credentials(self, probe_result: bool, expected_valid: bool, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            source_module, "validate_fleetio_credentials", lambda api_key, account_token, api_version: probe_result
        )
        config = FleetioSourceConfig(api_key="k", account_token="a")
        valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is expected_valid
        assert (error is None) is expected_valid

    @pytest.mark.parametrize("pin,expected", [(None, "2025-05-05"), ("v1", "v1"), ("2025-05-05", "2025-05-05")])
    def test_validate_credentials_probes_resolved_version(
        self, pin: str | None, expected: str, monkeypatch: Any
    ) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            source_module,
            "validate_fleetio_credentials",
            lambda api_key, account_token, api_version: captured.update(api_version=api_version) or True,
        )
        config = FleetioSourceConfig(api_key="k", account_token="a")
        self.source.validate_credentials(config, self.team_id, api_version=pin)
        assert captured["api_version"] == expected

    def test_source_for_pipeline_plumbs_args(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_fleetio_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(source_module, "fleetio_source", fake_fleetio_source)

        config = FleetioSourceConfig(api_key="my-key", account_token="my-acct")
        manager = MagicMock()
        inputs = MagicMock()
        inputs.schema_name = "vehicles"
        inputs.api_version = "v1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = "updated_at"

        result: Any = self.source.source_for_pipeline(config, manager, inputs)

        assert result == "response"
        assert captured["api_key"] == "my-key"
        assert captured["account_token"] == "my-acct"
        assert captured["endpoint"] == "vehicles"
        assert captured["api_version"] == "v1"
        assert captured["resumable_source_manager"] is manager
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01"
        assert captured["incremental_field"] == "updated_at"

    @pytest.mark.parametrize("pin,expected", [(None, "2025-05-05"), ("v1", "v1"), ("2025-05-05", "2025-05-05")])
    def test_source_for_pipeline_resolves_api_version(self, pin: str | None, expected: str, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(source_module, "fleetio_source", lambda **kwargs: captured.update(kwargs))

        config = FleetioSourceConfig(api_key="k", account_token="a")
        inputs = MagicMock()
        inputs.schema_name = "vehicles"
        inputs.api_version = pin
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None

        self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert captured["api_version"] == expected

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(source_module, "fleetio_source", lambda **kwargs: captured.update(kwargs))

        config = FleetioSourceConfig(api_key="k", account_token="a")
        inputs = MagicMock()
        inputs.schema_name = "vehicles"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = None

        self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert captured["db_incremental_field_last_value"] is None
