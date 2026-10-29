from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onehundredms import (
    OneHundredMsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.onehundredms import (
    OneHundredMsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.source import OneHundredMsSource


@pytest.fixture
def config() -> OneHundredMsSourceConfig:
    return OneHundredMsSourceConfig(
        app_access_key="example-access-key", app_secret="example-secret-for-tests-only-12345"
    )


@pytest.mark.parametrize(
    "endpoint,incremental,watermark,expected",
    [
        ("sessions", True, None, None),
        ("sessions", False, "2026-01-01T00:00:00Z", None),
        ("sessions", True, "2026-01-01T00:00:00.123456Z", "2026-01-01T00:00:00.123Z"),
        ("sessions", True, "2026-01-01T02:00:00+02:00", "2026-01-01T00:00:00.000Z"),
        ("sessions", True, datetime(2026, 1, 1), "2026-01-01T00:00:00.000Z"),
        ("sessions", True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00.000Z"),
        ("recordings", True, "2026-01-01T00:00:00Z", None),
        ("live_streams", False, "2026-01-01T00:00:00Z", None),
    ],
)
def test_incremental_filter_is_retained_on_every_page(
    config: OneHundredMsSourceConfig,
    endpoint: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    result = SourceDriver(OneHundredMsSource(), config).run(
        endpoint,
        [
            ScriptedResponse(json={"data": [{"id": "example-row"}], "last": "next-cursor"}),
            ScriptedResponse(json={"data": [], "last": None}),
        ],
        incremental_field="created_at" if incremental else None,
        db_incremental_field_last_value=watermark,
    )
    assert result.raised is None
    assert result.rows == [{"id": "example-row"}]
    assert result.paths == [f"/v2/{endpoint.replace('_', '-')}"] * 2
    assert result.params("start") == [None, "next-cursor"]
    assert result.params("after") == [expected, expected]
    if endpoint == "sessions" and incremental:
        assert result.response is not None
        assert result.response.sort_mode == "desc"


@pytest.mark.parametrize("body", [{"data": [{"id": "row-1"}], "last": "saved-cursor"}, {"unexpected": []}])
def test_invalid_pagination_fails_instead_of_silently_losing_data(
    config: OneHundredMsSourceConfig, body: dict[str, Any]
) -> None:
    result = SourceDriver(OneHundredMsSource(), config).run(
        "recordings",
        [ScriptedResponse(json=body)],
        resume_state=OneHundredMsResumeConfig(cursor="saved-cursor"),
    )
    assert isinstance(result.raised, ValueError)
    assert result.paths == ["/v2/recordings"]
    assert result.params("start") == ["saved-cursor"]
    assert result.saved_states == []
    assert result.final_state == OneHundredMsResumeConfig(cursor="saved-cursor")
