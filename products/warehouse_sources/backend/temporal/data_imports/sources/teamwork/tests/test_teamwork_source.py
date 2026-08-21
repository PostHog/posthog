from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamwork import (
    TeamworkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.source import TeamworkSource

INCREMENTAL_ENDPOINTS = {"tasks", "tasklists", "milestones", "timelogs"}
FULL_REFRESH_ENDPOINTS = {"projects", "people", "companies", "tags", "comments"}


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_teamwork_credentials", lambda host, api_key: True)
        ok, error = TeamworkSource().validate_credentials(
            TeamworkSourceConfig(site="mycompany", api_key="key"), team_id=1
        )
        assert ok is True
        assert error is None

    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_teamwork_credentials", lambda host, api_key: False)
        ok, error = TeamworkSource().validate_credentials(
            TeamworkSourceConfig(site="mycompany", api_key="bad"), team_id=1
        )
        assert ok is False
        assert error is not None

    def test_normalizes_host_before_validating(self, monkeypatch: Any) -> None:
        captured: dict[str, str] = {}

        def fake_validate(host: str, api_key: str) -> bool:
            captured["host"] = host
            return True

        monkeypatch.setattr(source_module, "validate_teamwork_credentials", fake_validate)
        TeamworkSource().validate_credentials(
            TeamworkSourceConfig(site="https://mycompany.teamwork.com/", api_key="key"), team_id=1
        )
        assert captured["host"] == "mycompany.teamwork.com"


class TestSourceForPipeline:
    def _response(self, endpoint: str, **input_overrides: Any) -> Any:
        inputs = SimpleNamespace(
            schema_name=endpoint,
            team_id=1,
            job_id="job-1",
            logger=MagicMock(),
            should_use_incremental_field=input_overrides.get("should_use_incremental_field", False),
            db_incremental_field_last_value=input_overrides.get("db_incremental_field_last_value", None),
        )
        return TeamworkSource().source_for_pipeline(
            TeamworkSourceConfig(site="mycompany", api_key="key"),
            MagicMock(),
            inputs,  # type: ignore[arg-type]
        )

    def test_unsafe_host_blocks_sync(self, monkeypatch: Any) -> None:
        # An internal/private host must be rejected at sync time, not just at source creation —
        # otherwise an edited `site` could redirect the stored API key (SSRF).
        monkeypatch.setattr(source_module, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        with pytest.raises(ValueError):
            self._response("tasks")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
