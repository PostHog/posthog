from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loopreturns import (
    LoopReturnsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns import (
    LoopReturnsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.source import LoopReturnsSource

VALIDATE_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.source."
    "validate_loop_returns_credentials"
)


class FakeResumableSourceManager(ResumableSourceManager[LoopReturnsResumeConfig]):
    def __init__(self) -> None:
        pass

    def can_resume(self) -> bool:
        return False

    def load_state(self) -> Optional[LoopReturnsResumeConfig]:
        return None


def _source_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "returns",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    return SourceInputs(**{**defaults, **overrides})


class TestLoopReturnsSource:
    def setup_method(self) -> None:
        self.source = LoopReturnsSource()
        self.team_id = 1
        self.config = LoopReturnsSourceConfig(api_key="loop_test_key")

    @pytest.mark.parametrize("start_date", ["not-a-date", "2024-13-01", "1000-01-01"])
    @mock.patch(VALIDATE_PATH)
    def test_a_bad_start_date_is_rejected_before_calling_loop(
        self, mock_validate: mock.MagicMock, start_date: str
    ) -> None:
        config = LoopReturnsSourceConfig(api_key="loop_test_key", start_date=start_date)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None and "Start date" in error
        mock_validate.assert_not_called()

    @mock.patch(VALIDATE_PATH)
    def test_a_valid_start_date_is_accepted(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = LoopReturnsSourceConfig(api_key="loop_test_key", start_date="2024-01-01")

        assert self.source.validate_credentials(config, self.team_id) == (True, None)

    def test_source_for_pipeline_builds_the_requested_table(self) -> None:
        source_response = self.source.source_for_pipeline(
            self.config, FakeResumableSourceManager(), _source_inputs(schema_name="advanced_shipping_notices")
        )

        assert source_response.name == "advanced_shipping_notices"
        assert source_response.primary_keys == ["id", "return_line_item_id"]
