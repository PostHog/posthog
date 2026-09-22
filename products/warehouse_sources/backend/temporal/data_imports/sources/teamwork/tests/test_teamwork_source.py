from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamwork import (
    TeamworkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.source import TeamworkSource

INCREMENTAL_ENDPOINTS = {"tasks", "tasklists", "milestones", "timelogs"}
FULL_REFRESH_ENDPOINTS = {"projects", "people", "companies", "tags", "comments"}


class TestSourceConfig:
    def test_site_is_a_connection_host_field(self) -> None:
        # The API key is sent to the host derived from `site`, so retargeting it must re-require the key.
        assert TeamworkSource().connection_host_fields == ["site"]


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


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://x.teamwork.com/projects/api/v3/tasks.json",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://x.teamwork.com/projects/api/v3/tasks.json"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = TeamworkSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)


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

    def test_plumbs_endpoint_and_primary_key(self) -> None:
        response = self._response("tasks")
        assert response.name == "tasks"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    def test_partitioned_endpoint_sets_datetime_partitioning(self) -> None:
        response = self._response("timelogs")
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["dateCreated"]

    def test_unpartitioned_endpoint_has_no_partitioning(self) -> None:
        response = self._response("tasks")
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_unsafe_host_blocks_sync(self, monkeypatch: Any) -> None:
        # An internal/private host must be rejected at sync time, not just at source creation —
        # otherwise an edited `site` could redirect the stored API key (SSRF).
        monkeypatch.setattr(source_module, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        with pytest.raises(ValueError):
            self._response("tasks")


class TestCanonicalDescriptions:
    def test_keys_are_known_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))

    def test_every_entry_has_a_table_description(self) -> None:
        for entry in CANONICAL_DESCRIPTIONS.values():
            assert entry.get("description")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
