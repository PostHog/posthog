from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock

import responses
import structlog
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.abnormal_security import (
    AbnormalSecurityResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.source import (
    AbnormalSecuritySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.abnormalsecurity import (
    AbnormalSecuritySourceConfig,
)

BASE = "https://api.abnormalplatform.com/v1"


def inputs(table: str, incremental: bool = False, watermark: Any = None) -> SourceInputs:
    return SourceInputs(
        schema_name=table,
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        job_id="job-test",
        logger=structlog.get_logger(),
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        reset_pipeline=False,
        api_version="v1",
    )


def manager(resume: AbnormalSecurityResumeConfig | None = None) -> MagicMock:
    result = MagicMock()
    result.can_resume.return_value = resume is not None
    result.load_state.return_value = resume
    return result


def sync_items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


@pytest.mark.parametrize("terminal", [{}, {"nextPageNumber": None}])
@responses.activate
def test_cases_pagination_and_auth(terminal: dict[str, Any]) -> None:
    rows = [{"caseId": "case-a", "last_modified": "2025-01-01T00:00:00Z"}, {"caseId": "case-b"}]
    responses.get(f"{BASE}/cases", json={"cases": rows[:1], "nextPageNumber": 2})
    responses.get(f"{BASE}/cases", json={"cases": rows[1:], **terminal})
    checkpoint = manager()
    result = AbnormalSecuritySource().source_for_pipeline(
        AbnormalSecuritySourceConfig(api_key="test-token"), checkpoint, inputs("cases")
    )
    assert [row for page in sync_items(result) for row in page] == rows
    assert len(responses.calls) == 2
    for number, call in enumerate(responses.calls, start=1):
        assert call.request.headers["Authorization"] == "Bearer test-token"
        query = parse_qs(urlparse(call.request.url).query)
        assert query["pageNumber"] == [str(number)]
        assert query["pageSize"] == ["100"]
        assert query["filter"][0].startswith("lastModifiedTime gte 1970-01-01T00:00:00Z lte ")
    assert checkpoint.save_state.call_args.args[0].paginator_state == {"cursor": 2}
    assert not checkpoint.clear_state.called
    assert result.on_complete is not None
    result.on_complete()
    checkpoint.clear_state.assert_called_once()


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected"),
    [
        (False, "2025-02-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        (True, None, "1970-01-01T00:00:00Z"),
        (True, "2025-02-01T02:00:00+02:00", "2025-02-01T00:00:00Z"),
        (True, datetime(2025, 2, 1, tzinfo=UTC), "2025-02-01T00:00:00Z"),
        (True, datetime(2025, 2, 1), "2025-02-01T00:00:00Z"),
    ],
)
@pytest.mark.parametrize("table", ["cases", "vendor_cases"])
@responses.activate
def test_incremental_filter(table: str, incremental: bool, watermark: Any, expected: str) -> None:
    path, selector = ("cases", "cases") if table == "cases" else ("vendor-cases", "vendorCases")
    responses.get(f"{BASE}/{path}", json={selector: []})
    result = AbnormalSecuritySource().source_for_pipeline(
        AbnormalSecuritySourceConfig(api_key="test-token"), manager(), inputs(table, incremental, watermark)
    )
    assert list(sync_items(result)) == []
    query = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert query["filter"][0].startswith(f"lastModifiedTime gte {expected} lte ")
    assert result.sort_mode == "desc"


@pytest.mark.parametrize(
    ("table", "path", "selector", "primary_key", "details"),
    [
        (
            "threats",
            "threats",
            "threats",
            "threatId",
            {"recipientCount": 12, "messages": [{"subject": "Test message"}]},
        ),
        (
            "vendor_cases",
            "vendor-cases",
            "vendorCases",
            "vendorCaseId",
            {"vendorDomain": "example.com", "lastModifiedTime": "2025-01-01T00:00:00Z"},
        ),
    ],
)
@responses.activate
def test_detail_fanout(table: str, path: str, selector: str, primary_key: str, details: dict[str, Any]) -> None:
    responses.get(f"{BASE}/{path}", json={selector: [{primary_key: "item-a"}], "nextPageNumber": 2})
    responses.get(f"{BASE}/{path}/item-a", json={primary_key: "item-a", **details})
    responses.get(f"{BASE}/{path}", json={selector: [{primary_key: "item-b"}]})
    responses.get(f"{BASE}/{path}/item-b", json={primary_key: "item-b", **details})
    result = AbnormalSecuritySource().source_for_pipeline(
        AbnormalSecuritySourceConfig(api_key="test-token"), manager(), inputs(table)
    )
    assert [row for page in sync_items(result) for row in page] == [
        {primary_key: "item-a", **details},
        {primary_key: "item-b", **details},
    ]
    assert len(responses.calls) == 4
    assert result.primary_keys == [primary_key]
    for index in (1, 3):
        assert urlparse(responses.calls[index].request.url).query == ""


@responses.activate
def test_resume_preserves_filter_and_page() -> None:
    saved_filter = "lastModifiedTime gte 2025-01-01T00:00:00Z lte 2025-02-01T00:00:00Z"
    checkpoint = manager(AbnormalSecurityResumeConfig(filter_value=saved_filter, paginator_state={"cursor": 3}))
    responses.get(f"{BASE}/cases", json={"cases": [{"caseId": "case-c"}]})
    result = AbnormalSecuritySource().source_for_pipeline(
        AbnormalSecuritySourceConfig(api_key="test-token"), checkpoint, inputs("cases", True, "2025-01-15T00:00:00Z")
    )
    assert list(sync_items(result)) == [[{"caseId": "case-c"}]]
    query = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert query["pageNumber"] == ["3"]
    assert query["filter"] == [saved_filter]


@responses.activate
def test_fanout_resume_skips_completed_details() -> None:
    checkpoint = manager(
        AbnormalSecurityResumeConfig(
            filter_value="receivedTime gte 1970-01-01T00:00:00Z lte 2025-02-01T00:00:00Z",
            paginator_state={"completed": ["threats/item-a"], "current": None, "child_state": None},
        )
    )
    responses.get(f"{BASE}/threats", json={"threats": [{"threatId": "item-a"}, {"threatId": "item-b"}]})
    responses.get(f"{BASE}/threats/item-b", json={"threatId": "item-b", "messages": []})
    result = AbnormalSecuritySource().source_for_pipeline(
        AbnormalSecuritySourceConfig(api_key="test-token"), checkpoint, inputs("threats")
    )
    assert list(sync_items(result)) == [[{"threatId": "item-b", "messages": []}]]
    assert len(responses.calls) == 2


@pytest.mark.parametrize("status", [401, 403])
@responses.activate
def test_sync_auth_errors_match_user_messages(status: int) -> None:
    responses.get(f"{BASE}/cases", status=status, json={"detail": "denied"})
    source = AbnormalSecuritySource()
    result = source.source_for_pipeline(AbnormalSecuritySourceConfig(api_key="test-token"), manager(), inputs("cases"))
    with pytest.raises(HTTPError) as error:
        list(sync_items(result))
    matches = [message for pattern, message in source.get_non_retryable_errors().items() if pattern in str(error.value)]
    assert len(matches) == 1
    assert "test-token" not in str(error.value)
    assert len(responses.calls) == 1


@pytest.mark.parametrize("watermark", ["not-a-date", 123])
@responses.activate
def test_invalid_watermark_fails_before_request(watermark: Any) -> None:
    with pytest.raises(ValueError, match="Invalid Abnormal incremental timestamp"):
        AbnormalSecuritySource().source_for_pipeline(
            AbnormalSecuritySourceConfig(api_key="test-token"), manager(), inputs("cases", True, watermark)
        )
    assert len(responses.calls) == 0


@pytest.mark.parametrize("body", [{}, {"error": "invalid_request"}])
@responses.activate
def test_missing_collection_does_not_erase_table(body: dict[str, Any]) -> None:
    responses.get(f"{BASE}/cases", json=body)
    result = AbnormalSecuritySource().source_for_pipeline(
        AbnormalSecuritySourceConfig(api_key="test-token"), manager(), inputs("cases")
    )
    with pytest.raises(ValueError):
        list(sync_items(result))
