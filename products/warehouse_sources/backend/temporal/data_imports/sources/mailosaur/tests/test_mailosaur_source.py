from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source import MailosaurSource


def _config(api_key: str = "key") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestResumableWiring:
    def test_source_for_pipeline_drops_incremental_value_when_disabled(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "servers"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = datetime(2026, 1, 1, tzinfo=UTC)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source.mailosaur_source"
        ) as mocked:
            MailosaurSource().source_for_pipeline(_config(), MagicMock(), inputs)
        # A full-refresh table must not carry a stale cursor into the request.
        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None


class TestCanonicalDescriptions:
    def test_keys_are_known_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
