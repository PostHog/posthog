from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest.mock import patch

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium import BuildiumResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.source import BuildiumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildium import (
    BuildiumSourceConfig,
)

CONFIG = BuildiumSourceConfig(client_id="example-client", client_secret="example-secret")


def driver() -> SourceDriver:
    return SourceDriver(BuildiumSource(), CONFIG)


@pytest.mark.parametrize(
    ("pages", "total", "expected_offsets", "expected_ids"),
    [
        ([[{"Id": 1}, {"Id": 2}], [{"Id": 3}]], 3, ["0", "2"], [1, 2, 3]),
        ([[{"Id": 1}, {"Id": 2}]], 2, ["0"], [1, 2]),
        ([[{"Id": 1}, {"Id": 2}], []], None, ["0", "2"], [1, 2]),
        ([[]], 0, ["0"], []),
    ],
)
def test_pagination(
    pages: list[list[dict[str, object]]],
    total: int | None,
    expected_offsets: list[str],
    expected_ids: list[int],
) -> None:
    script = [
        ScriptedResponse(json=page, headers={"X-Total-Count": str(total)} if total is not None else {})
        for page in pages
    ]
    with patch("products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium.PAGE_SIZE", 2):
        result = driver().run("leases", script)

    assert result.raised is None
    assert [row["Id"] for row in result.rows] == expected_ids
    assert result.params("offset") == expected_offsets
    assert result.saved_states == ([BuildiumResumeConfig(offset=2)] if len(expected_offsets) > 1 else [])


@pytest.mark.parametrize("endpoint", ["leases", "applicants"])
@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_filter"),
    [
        (True, None, None),
        (False, "2026-01-02T03:04:05Z", None),
        (True, "2026-01-02T03:04:05.999Z", "2026-01-02T03:04:05Z"),
        (True, datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
        (True, datetime(2026, 1, 2, 5, 4, 5, tzinfo=timezone(timedelta(hours=2))), "2026-01-02T03:04:05Z"),
    ],
)
def test_incremental_filter_and_timestamp(
    endpoint: str, incremental: bool, watermark: datetime | str | None, expected_filter: str | None
) -> None:
    data: list[dict[str, Any]] = [
        {"Id": 1, "LastUpdatedDateTime": "2026-01-03T00:00:00Z"},
        {"Id": 2, "LastUpdatedDateTime": None},
    ]
    result = driver().run(
        endpoint,
        [ScriptedResponse(json=data)],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.requests[0].param("lastupdatedfrom") == expected_filter
    assert result.requests[0].param("orderby") == "Id asc"
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.rows == [
        {"Id": 1, "LastUpdatedDateTime": datetime(2026, 1, 3, tzinfo=UTC)},
        {"Id": 2, "LastUpdatedDateTime": None},
    ]


@pytest.mark.parametrize("original_filter", [None, "2026-01-01T00:00:00Z"])
def test_resume_keeps_filter_and_offset(original_filter: str | None) -> None:
    result = driver().run(
        "leases",
        [ScriptedResponse(json=[{"Id": 1001}])],
        resume_state=BuildiumResumeConfig(offset=1000, updated_from=original_filter),
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-05T00:00:00Z",
    )

    assert result.raised is None
    assert result.rows == [{"Id": 1001}]
    assert result.requests[0].param("offset") == "1000"
    assert result.requests[0].param("lastupdatedfrom") == original_filter


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_mapping(status: int, message: str) -> None:
    result = driver().run("leases", [ScriptedResponse(status=status, json=[])])

    assert isinstance(result.raised, HTTPError)
    errors = BuildiumSource().get_non_retryable_errors()
    assert next(value for key, value in errors.items() if key in str(result.raised)) == message
