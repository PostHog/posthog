from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.source import FactorialSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.factorial import (
    FactorialSourceConfig,
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "employees",
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


class TestFactorialSource:
    def setup_method(self) -> None:
        self.source = FactorialSource()
        self.team_id = 123
        self.config = FactorialSourceConfig(api_key="test-key")

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O in get_schemas), so the public docs can render the
        # Supported tables section.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message"),
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(
        self,
        status_code: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        # No row pin at creation time, so the probe runs under the default (newest) version.
        assert network.requests_log[0].path == "/api/2026-07-01/resources/employees/employees"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["x-api-key"] == "test-key"

    @pytest.mark.parametrize(
        ("pin", "resolved"),
        [
            # None pin resolves to the default (the newest supported version) — new sources land here.
            (None, "2026-07-01"),
            ("2025-04-01", "2025-04-01"),
            ("2026-04-01", "2026-04-01"),
            ("2026-07-01", "2026-07-01"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.factorial.source.factorial_source")
    def test_source_for_pipeline_resolves_and_threads_version(
        self, mock_factorial_source: mock.MagicMock, pin: str | None, resolved: str
    ) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs(schema_name="leaves", team_id=99, job_id="job-xyz", api_version=pin)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_factorial_source.assert_called_once_with(
            api_key="test-key",
            endpoint="leaves",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
            api_version=resolved,
        )
