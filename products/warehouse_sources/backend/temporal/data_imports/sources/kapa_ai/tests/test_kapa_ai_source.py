import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kapaai import KapaAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.source import KapaAISource


def driver() -> SourceDriver:
    config = KapaAISourceConfig(api_key="test-key", project_id="00000000-0000-4000-8000-000000000001")
    return SourceDriver(KapaAISource(), config)


@pytest.mark.parametrize("status,reason", [(401, "Unauthorized"), (403, "Forbidden")])
def test_pipeline_auth_failures_match_terminal_errors(status: int, reason: str) -> None:
    source = KapaAISource()
    result = driver().run("threads", [ScriptedResponse(status=status, json={})])

    assert len(result.requests) == 1
    assert isinstance(result.raised, HTTPError)
    assert reason in str(result.raised)
    assert error_message_matches(str(result.raised), source.get_non_retryable_errors())


def test_full_refresh_ignores_a_stale_watermark() -> None:
    result = driver().run(
        "threads",
        [ScriptedResponse(json={"results": [{"id": "old-thread", "last_activity_at": None}], "next_cursor": None})],
        should_use_incremental_field=False,
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
    )

    assert result.raised is None
    assert result.items == [[{"id": "old-thread", "last_activity_at": None}]]
    assert result.requests[0].param("updated_since") is None
