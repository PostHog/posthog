import re
import json
from collections.abc import Callable, Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import patch

from requests import PreparedRequest, RequestException, Response, Session

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.semrush.semrush import (
    DOMAIN_REPORT_ROW_ERROR,
    semrush_source,
    validate_credentials,
)
from products.warehouse_sources.sources.semrush.settings import (
    ACCESS_ERROR,
    AUTH_ERROR,
    DATABASE_ACCESS_ERROR,
    DOMAIN_ERROR,
    DOMAIN_REPORT_ERROR,
    PROJECT_ERROR,
    PROJECT_ID_ERROR,
    QUOTA_ERROR,
    REQUEST_ERROR,
    UNAVAILABLE_ERROR,
)
from products.warehouse_sources.sources.semrush.source import SemrushSource


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.mark.parametrize(
    "status,body,message",
    [
        (401, "Unauthorized", AUTH_ERROR),
        (403, "Forbidden", ACCESS_ERROR),
        (400, {"code": 70, "message": "API key hash failure"}, AUTH_ERROR),
        (400, {"code": 120, "message": "Wrong key-ID pair"}, AUTH_ERROR),
        (400, {"code": 121, "message": "Wrong format or empty hash"}, AUTH_ERROR),
        (400, {"code": 122, "message": "Wrong format or empty key"}, AUTH_ERROR),
        (400, {"code": 130, "message": "API disabled"}, ACCESS_ERROR),
        (400, {"code": 131, "message": "Limit exceeded"}, QUOTA_ERROR),
        (400, {"code": 132, "message": "API units balance is zero"}, QUOTA_ERROR),
        (400, {"code": 134, "message": "Total limit exceeded"}, QUOTA_ERROR),
        (400, {"code": 512, "message": "Can't find project with project_id 123"}, PROJECT_ERROR),
        (200, {"code": "132", "message": "API units balance is zero"}, QUOTA_ERROR),
        (400, {"code": 519, "message": "Missing mandatory URL parameter"}, REQUEST_ERROR),
        (404, {"message": "Not found"}, REQUEST_ERROR),
    ],
)
def test_errors_stop_sync_and_explain_validation_failure(status: int, body: object, message: str) -> None:
    with patch.object(Session, "send", return_value=response(body, status)) as send:
        with pytest.raises(ValueError, match=message):
            list(cast(Iterable[Any], semrush_source("fake-api-key", "123", "site_audit", 1, "job").items()))
        assert send.call_count == 1
        assert validate_credentials("fake-api-key", "123", 1) == (False, message)
        assert send.call_count == 2
    assert message in SemrushSource().get_non_retryable_errors()


@pytest.mark.parametrize(
    "status,body", [(429, {}), (500, {}), (503, {}), (200, {"code": 511, "message": "Unknown error"})]
)
def test_transient_errors_retry(status: int, body: object) -> None:
    failed = response(body, status)
    failed.headers["Retry-After"] = "0"
    with (
        patch.object(Session, "send", side_effect=[failed, response({"id": 123})]) as send,
        patch("tenacity.nap.time.sleep"),
    ):
        assert validate_credentials("fake-api-key", "123", 1) == (True, None)
    assert send.call_count == 2


def test_connection_failure_reports_unavailable() -> None:
    with patch.object(Session, "send", side_effect=RequestException("boom")):
        assert validate_credentials("fake-api-key", "123", 1) == (False, UNAVAILABLE_ERROR)


@pytest.mark.parametrize("project_id", ["", "../456", "123?key=other", "https://example.com", "１２３", "123/456"])
def test_invalid_project_id_never_makes_a_request(project_id: str) -> None:
    with patch.object(Session, "send") as send:
        assert validate_credentials("fake-api-key", project_id, 1) == (False, PROJECT_ID_ERROR)
        with pytest.raises(ValueError, match=PROJECT_ID_ERROR):
            semrush_source("fake-api-key", project_id, "site_audit", 1, "job")
    send.assert_not_called()


@pytest.mark.parametrize(
    "endpoint,body,message",
    [
        ("site_audit_snapshots", {"message": "Unexpected response"}, "Required data_selector"),
        ("site_audit", {"code": 999, "message": "Unexpected error"}, "record without its ID"),
        ("site_audit_snapshots", {"snapshots": [{"finish_date": 1700000000000}]}, "record without its ID"),
    ],
)
def test_malformed_records_fail_instead_of_erasing_rows(endpoint: str, body: object, message: str) -> None:
    with patch.object(Session, "send", return_value=response(body)):
        with pytest.raises(ValueError, match=message):
            list(cast(Iterable[Any], semrush_source("fake-api-key", "123", endpoint, 1, "job").items()))


def text_response(body: str, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result._content = body.encode()
    result.headers["Content-Type"] = "text/plain"
    return result


def routed(routes: dict[str, Callable[[dict[str, list[str]]], Response]], seen: list[str]) -> Callable[..., Response]:
    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        url = urlparse(request.url or "")
        seen.append(f"{url.path}?{url.query}")
        query = parse_qs(url.query)
        for prefix, handler in routes.items():
            if url.path == prefix:
                return handler(query)
        raise AssertionError(f"unexpected request {url.path}")

    return send


def rows_of(endpoint: str, **kwargs: Any) -> list[dict[str, Any]]:
    response = semrush_source("fake-api-key", "123", endpoint, 1, "job", **kwargs)
    return [row for page in cast(Iterable[Any], response.items()) for row in page]


SNAPSHOTS = {
    "snapshots": [
        {"snapshot_id": "aaa111", "finish_date": 1000},
        {"snapshot_id": "bbb222", "finish_date": 3000},
        {"snapshot_id": "ccc333", "finish_date": 2000},
    ]
}


def snapshot_details(query: dict[str, list[str]]) -> Response:
    snapshot_id = query["snapshot_id"][0]
    return response({"snapshot_id": snapshot_id, "quality": {"value": 90, "delta": 1}, "pages_crawled": 10})


@pytest.mark.parametrize(
    "incremental,last_value,expected",
    [
        (False, None, ["aaa111", "bbb222", "ccc333"]),
        (False, 2500, ["aaa111", "bbb222", "ccc333"]),
        (True, None, ["aaa111", "bbb222", "ccc333"]),
        (True, 1000, ["bbb222", "ccc333"]),
        (True, 3000, []),
    ],
)
def test_history_fetches_details_only_for_snapshots_past_the_watermark(
    incremental: bool, last_value: int | None, expected: list[str]
) -> None:
    seen: list[str] = []
    routes = {
        "/reports/v1/projects/123/siteaudit/snapshots": lambda _: response(SNAPSHOTS),
        "/reports/v1/projects/123/siteaudit/snapshot": snapshot_details,
    }
    with patch.object(Session, "send", side_effect=routed(routes, seen)):
        rows = rows_of(
            "site_audit_history", should_use_incremental_field=incremental, db_incremental_field_last_value=last_value
        )

    assert sorted(row["snapshot_id"] for row in rows) == expected
    assert len(seen) == 1 + len(expected)
    finish_dates = {item["snapshot_id"]: item["finish_date"] for item in SNAPSHOTS["snapshots"]}
    for row in rows:
        assert row["project_id"] == "123"
        assert row["finish_date"] == finish_dates[row["snapshot_id"]]
        assert row["quality"] == {"value": 90, "delta": 1}
        assert not any(key.startswith("_site_audit_snapshots") for key in row)


@pytest.mark.parametrize("snapshot_id", [None, "../456", "abc?key=x"])
def test_history_rejects_snapshot_ids_that_would_change_the_request(snapshot_id: str | None) -> None:
    seen: list[str] = []
    routes = {
        "/reports/v1/projects/123/siteaudit/snapshots": lambda _: response(
            {"snapshots": [{"snapshot_id": snapshot_id, "finish_date": 1}]}
        ),
    }
    with patch.object(Session, "send", side_effect=routed(routes, seen)):
        with pytest.raises(ValueError, match="record without its ID"):
            rows_of("site_audit_history")
    assert len(seen) == 1


def issue_pages(query: dict[str, list[str]], total: int, page_size: int) -> Response:
    page = int(query["page"][0])
    start = (page - 1) * page_size
    count = max(0, min(page_size, total - start))
    data = [
        {"source_url": f"https://example.com/{start + i}", "target_url": None, "page_id": f"p{start + i}"}
        for i in range(count)
    ]
    return response({"limit": page_size, "page": page, "total": total, "data": data})


def test_issue_details_walks_pages_of_detected_issues_in_the_latest_snapshot() -> None:
    seen: list[str] = []
    base = "/reports/v1/projects/123/siteaudit"
    routes = {
        f"{base}/snapshots": lambda _: response(SNAPSHOTS),
        f"{base}/info": lambda _: response({"id": 123, "defects": {"8": 150, "109": 2, "110": 0}}),
        f"{base}/snapshot/bbb222/issue/8": lambda query: issue_pages(query, total=150, page_size=100),
        f"{base}/snapshot/bbb222/issue/109": lambda query: issue_pages(query, total=2, page_size=100),
    }
    with patch.object(Session, "send", side_effect=routed(routes, seen)):
        rows = rows_of("site_audit_issue_details")

    assert sum(row["issue_id"] == 8 for row in rows) == 150
    assert sum(row["issue_id"] == 109 for row in rows) == 2
    assert all(row["snapshot_id"] == "bbb222" and row["project_id"] == "123" for row in rows)
    issue_requests = [request for request in seen if "/issue/" in request]
    assert len(issue_requests) == 3
    assert all("limit=100" in request for request in issue_requests)


def test_issue_details_skips_an_issue_that_is_gone() -> None:
    seen: list[str] = []
    base = "/reports/v1/projects/123/siteaudit"
    routes = {
        f"{base}/snapshots": lambda _: response(SNAPSHOTS),
        f"{base}/info": lambda _: response({"id": 123, "defects": {"8": 1, "9": 1}}),
        f"{base}/snapshot/bbb222/issue/8": lambda _: response({"message": "Not found"}, 404),
        f"{base}/snapshot/bbb222/issue/9": lambda query: issue_pages(query, total=1, page_size=100),
    }
    with patch.object(Session, "send", side_effect=routed(routes, seen)):
        rows = rows_of("site_audit_issue_details")

    assert [row["issue_id"] for row in rows] == [9]


def test_issue_details_without_audits_reads_nothing_else() -> None:
    seen: list[str] = []
    routes = {"/reports/v1/projects/123/siteaudit/snapshots": lambda _: response({"snapshots": []})}
    with patch.object(Session, "send", side_effect=routed(routes, seen)):
        assert rows_of("site_audit_issue_details") == []
    assert len(seen) == 1


KEYWORDS_CSV = (
    "Keyword;Position;Previous Position;Position Difference;Search Volume;CPC;Url;Traffic (%);"
    "Traffic Cost (%);Competition;Number of Results;Trends;Keyword Difficulty Index;Timestamp\r\n"
    '"seo; tools";"6";"7";"1";"8100";"10.54";"http://example.com/";"2.15";"3.87";"0.54";"321000000";'
    '"0.67,0.82";"71";"1700000000"\r\n'
    '"seo";"9";"";"0";"110000";"14.82";"http://example.com/a";"17.53";"44.40";"0.50";"0";"0.81";"";"1700000000"\r\n'
)


@pytest.mark.parametrize(
    "domain,database,expected_domain,expected_database,info_requests",
    [
        ("example.com", "UK", "example.com", "uk", 0),
        ("https://www.example.com/blog", None, "www.example.com", "us", 0),
        (None, "", "example.org", "us", 1),
        ("  ", "de", "example.org", "de", 1),
    ],
)
def test_domain_organic_keywords_request_and_rows(
    domain: str | None, database: str | None, expected_domain: str, expected_database: str, info_requests: int
) -> None:
    seen: list[str] = []
    queries: list[dict[str, list[str]]] = []

    def report(query: dict[str, list[str]]) -> Response:
        queries.append(query)
        return text_response(KEYWORDS_CSV)

    routes = {
        "/reports/v1/projects/123/siteaudit/info": lambda _: response({"id": 123, "url": "https://example.org/"}),
        "/": report,
    }
    with patch.object(Session, "send", side_effect=routed(routes, seen)):
        rows = rows_of("domain_organic_keywords", domain=domain, database=database)

    assert len(seen) == 1 + info_requests
    (query,) = queries
    assert query["type"] == ["domain_organic"]
    assert query["domain"] == [expected_domain]
    assert query["database"] == [expected_database]
    assert query["display_limit"] == ["10000"]
    assert query["export_columns"] == ["Ph,Po,Pp,Pd,Nq,Cp,Ur,Tr,Tc,Co,Nr,Td,Kd,Ts"]
    assert rows[0] == {
        "domain": expected_domain,
        "database": expected_database,
        "keyword": "seo; tools",
        "position": 6,
        "previous_position": 7,
        "position_difference": 1,
        "search_volume": 8100,
        "cpc": 10.54,
        "url": "http://example.com/",
        "traffic_percent": 2.15,
        "traffic_cost_percent": 3.87,
        "competition": 0.54,
        "number_of_results": 321000000,
        "trends": "0.67,0.82",
        "keyword_difficulty": 71.0,
        "timestamp": 1700000000,
    }
    assert rows[1]["previous_position"] is None
    assert rows[1]["keyword_difficulty"] is None


def test_domain_organic_competitors_rows() -> None:
    body = (
        "Domain;Competitor Relevance;Common Keywords;Organic Keywords;Organic Traffic;Organic Cost;Adwords Keywords\n"
        "rival.example.com;0.13;338;11021;5640;9690;0\n"
    )
    seen: list[str] = []
    with patch.object(Session, "send", side_effect=routed({"/": lambda _: text_response(body)}, seen)):
        rows = rows_of("domain_organic_competitors", domain="example.com")

    assert "type=domain_organic_organic" in seen[0]
    assert rows == [
        {
            "domain": "example.com",
            "database": "us",
            "competitor_domain": "rival.example.com",
            "competitor_relevance": 0.13,
            "common_keywords": 338,
            "organic_keywords": 11021,
            "organic_traffic": 5640,
            "organic_cost": 9690.0,
            "adwords_keywords": 0,
        }
    ]


@pytest.mark.parametrize(
    "status,body,error,message",
    [
        (200, "ERROR 50 :: NOTHING FOUND", None, None),
        (400, "ERROR 120 :: WRONG KEY - ID PAIR", ValueError, AUTH_ERROR),
        (200, "ERROR 132 :: API UNITS BALANCE IS ZERO", ValueError, QUOTA_ERROR),
        (200, "ERROR 133 :: DB ACCESS DENIED", ValueError, DATABASE_ACCESS_ERROR),
        (400, "ERROR 10000 :: Wrong parameter 'database'.", ValueError, DOMAIN_REPORT_ERROR),
        (200, "ERROR 500 :: Internal Error", RESTClientRetryableError, UNAVAILABLE_ERROR),
        (403, "Forbidden", ValueError, ACCESS_ERROR),
        (200, "Domain;Competitor Relevance\nrival.example.com;0.13\n", ValueError, DOMAIN_REPORT_ROW_ERROR),
    ],
)
def test_domain_report_errors(status: int, body: str, error: type[Exception] | None, message: str | None) -> None:
    seen: list[str] = []
    with patch.object(Session, "send", side_effect=routed({"/": lambda _: text_response(body, status)}, seen)):
        if error is None:
            assert rows_of("domain_organic_competitors", domain="example.com") == []
        else:
            with pytest.raises(error, match=re.escape(message or "")):
                rows_of("domain_organic_competitors", domain="example.com")
    if message in {DATABASE_ACCESS_ERROR, DOMAIN_REPORT_ERROR}:
        assert message in SemrushSource().get_non_retryable_errors()


def test_domain_report_without_a_project_url_asks_for_a_domain() -> None:
    seen: list[str] = []
    routes = {"/reports/v1/projects/123/siteaudit/info": lambda _: response({"id": 123, "url": ""})}
    with patch.object(Session, "send", side_effect=routed(routes, seen)):
        with pytest.raises(ValueError, match=DOMAIN_ERROR):
            rows_of("domain_organic_keywords")
    assert len(seen) == 1
