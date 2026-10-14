from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.appcues.source import AppcuesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appcues import (
    AppcuesSourceConfig,
)


@pytest.mark.parametrize(
    ("table", "path", "region"),
    [
        ("flows", "flows", "us"),
        ("flows_v2", "flows-v2", "eu"),
        ("segments", "segments", "eu"),
        ("tags", "tags", "us"),
        ("pins", "pins", "us"),
        ("mobile", "mobile", "eu"),
        ("launchpads", "launchpads", "us"),
        ("banners", "banners", "eu"),
        ("embeds", "embeds", "us"),
        ("nps", "nps", "eu"),
        ("checklists", "checklists", "us"),
    ],
)
def test_full_refresh_reads_complete_account_array(table: str, path: str, region: Literal["us", "eu"]) -> None:
    rows = [
        {"id": "experience-a", "steps": [{"id": "step-a", "children": []}], "tags": {"tag-a": True}},
        {"id": "experience-b", "steps": [], "tags": {}, "published_at": None},
    ]
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region=region)
    result = SourceDriver(AppcuesSource(), config).run(table, [ScriptedResponse(json=rows)])

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [f"/v2/accounts/12345/{path}"]
    assert result.requests[0].origin == ("https://api.eu.appcues.com" if region == "eu" else "https://api.appcues.com")
    assert result.requests[0].headers["authorization"] == "Basic dGVzdC1rZXk6dGVzdC1zZWNyZXQ="
    assert result.queries == [{}]


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        (1704164645123, datetime(2024, 1, 2, 3, 4, 5, 123000, tzinfo=UTC)),
        (1704164645123.5, datetime(2024, 1, 2, 3, 4, 5, 123500, tzinfo=UTC)),
        (0, datetime(1970, 1, 1, tzinfo=UTC)),
        ("2024-01-02T03:04:05Z", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
        (
            "2024-01-02T03:04:05+02:00",
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2))),
        ),
        (None, None),
    ],
)
def test_creation_timestamp_supports_both_appcues_formats(created_at: Any, expected: datetime | None) -> None:
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="us")
    result = SourceDriver(AppcuesSource(), config).run(
        "pins", [ScriptedResponse(json=[{"id": "pin-a", "created_at": created_at}])]
    )

    assert result.raised is None
    assert result.rows == [{"id": "pin-a", "created_at": expected}]


@pytest.mark.parametrize("body", [[], {"error": True, "status": 200, "title": "Unexpected response"}])
def test_empty_array_is_valid_but_an_error_object_cannot_replace_a_table(body: Any) -> None:
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="us")
    result = SourceDriver(AppcuesSource(), config).run("flows", [ScriptedResponse(json=body)])

    assert result.rows == []
    if isinstance(body, list):
        assert result.raised is None
    else:
        assert isinstance(result.raised, ValueError)
        assert "Required a list response body" in str(result.raised)
