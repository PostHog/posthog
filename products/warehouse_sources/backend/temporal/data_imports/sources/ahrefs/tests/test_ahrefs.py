import json
from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from requests import Response, Session
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.ahrefs import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.settings import (
    BACKLINK_FIELDS,
    ENDPOINTS,
    ORGANIC_KEYWORD_FIELDS,
    RANK_TRACKER_FIELDS,
    REFDOMAIN_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.source import AhrefsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahrefs import AhrefsSourceConfig

CLIENT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.ahrefs"


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = "OK" if status == 200 else "Error"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    result.url = "https://api.ahrefs.com/v3/site-audit/issues"
    return result


@pytest.fixture
def send() -> Iterator[MagicMock]:
    with Session() as session:
        with (
            patch(f"{CLIENT_MODULE}.make_tracked_session", return_value=session),
            patch.object(session, "send") as mock,
        ):
            yield mock


@pytest.mark.parametrize(
    ("table", "path", "selector", "row", "expected_params"),
    [
        (
            "site_audit_health_scores",
            "site-audit/projects",
            "healthscores",
            {"project_id": "123", "health_score": 95, "date": None},
            {"project_id": ["123"]},
        ),
        (
            "site_audit_issues",
            "site-audit/issues",
            "issues",
            {"issue_id": "missing_title", "crawled": 3},
            {"project_id": ["123"]},
        ),
        (
            "site_audit_pages",
            "site-audit/page-explorer",
            "pages",
            {"url": "https://example.com/", "http_code": 200, "title": ["Example"]},
            {
                "project_id": ["123"],
                "limit": ["100"],
                "select": ["url,http_code,title,depth,is_html"],
                "order_by": ["url:asc"],
            },
        ),
        (
            "projects",
            "management/projects",
            "projects",
            {"project_id": "999", "project_name": "Other site", "url": "https://example.org/"},
            {},
        ),
    ],
)
@pytest.mark.parametrize("empty", [False, True])
def test_snapshot_request_and_terminal_page(
    send: MagicMock,
    table: str,
    path: str,
    selector: str,
    row: dict[str, object],
    expected_params: dict[str, list[str]],
    empty: bool,
) -> None:
    send.return_value = response({selector: [] if empty else [row], "next": "https://example.com/ignored"})
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = table
    inputs.team_id = 1
    inputs.job_id = "test-job"
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = "2026-01-01"
    result = AhrefsSource().source_for_pipeline(AhrefsSourceConfig(api_key="test-key", project_id="00123"), inputs)

    expected_row = {**row, "project_id": "123"} if "project_id" in expected_params else row
    assert list(cast(Iterable[Any], result.items())) == ([] if empty else [[expected_row]])
    send.assert_called_once()
    assert send.call_args.kwargs["timeout"] == (10, 60)
    request = send.call_args.args[0]
    assert request.method == "GET"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert urlparse(request.url).path == f"/v3/{path}"
    assert parse_qs(urlparse(request.url).query) == {"output": ["json"], **expected_params}


TARGET = {
    "project_id": "123",
    "target_url": "https://example.com/",
    "target_mode": "domain",
    "target_protocol": "https",
}


@pytest.mark.parametrize(
    ("table", "selector", "rows", "expected_rows", "expected_params"),
    [
        (
            "domain_rating_history",
            "domain_ratings",
            [{"date": "2026-09-01", "domain_rating": 51.0}, {"date": "2026-08-01", "domain_rating": 50.5}],
            [{"date": "2026-08-01", "domain_rating": 50.5}, {"date": "2026-09-01", "domain_rating": 51.0}],
            {"history_grouping": ["monthly"]},
        ),
        (
            "metrics_history",
            "metrics",
            [{"date": "2026-09-01", "org_traffic": 20}, {"date": "2026-08-01", "org_traffic": 10}],
            [{"date": "2026-08-01", "org_traffic": 10}, {"date": "2026-09-01", "org_traffic": 20}],
            {
                "select": ["date,org_traffic,org_cost,paid_traffic,paid_cost"],
                "history_grouping": ["monthly"],
                "mode": ["domain"],
                "protocol": ["https"],
            },
        ),
        (
            "backlinks",
            "backlinks",
            [
                {"url_from": "https://a.example/", "url_to": "https://example.com/", "anchor": "first"},
                {"url_from": "https://a.example/", "url_to": "https://example.com/", "anchor": "second"},
                {"url_from": "https://b.example/", "url_to": "https://example.com/", "anchor": "other"},
            ],
            [
                {"url_from": "https://a.example/", "url_to": "https://example.com/", "anchor": "first"},
                {"url_from": "https://b.example/", "url_to": "https://example.com/", "anchor": "other"},
            ],
            {
                "select": [",".join(BACKLINK_FIELDS)],
                "limit": ["1000"],
                "order_by": ["domain_rating_source:desc"],
                "history": ["live"],
                "aggregation": ["similar_links"],
                "mode": ["domain"],
                "protocol": ["https"],
            },
        ),
        (
            "organic_keywords",
            "keywords",
            [
                {"keyword": "posthog", "keyword_country": "us", "sum_traffic": 50},
                {"keyword": "posthog", "keyword_country": "gb", "sum_traffic": 10},
            ],
            [
                {"keyword": "posthog", "keyword_country": "us", "sum_traffic": 50},
                {"keyword": "posthog", "keyword_country": "gb", "sum_traffic": 10},
            ],
            {
                "select": [",".join(ORGANIC_KEYWORD_FIELDS)],
                "limit": ["1000"],
                "order_by": ["sum_traffic:desc"],
                "date": ["2026-10-13"],
                "mode": ["domain"],
                "protocol": ["https"],
            },
        ),
        (
            "referring_domains",
            "refdomains",
            [{"domain": "a.example", "domain_rating": 80}, {"domain": "b.example", "domain_rating": 40}],
            [{"domain": "a.example", "domain_rating": 80}, {"domain": "b.example", "domain_rating": 40}],
            {
                "select": [",".join(REFDOMAIN_FIELDS)],
                "limit": ["1000"],
                "order_by": ["domain_rating:desc"],
                "history": ["live"],
                "mode": ["domain"],
                "protocol": ["https"],
            },
        ),
    ],
)
@pytest.mark.parametrize(
    ("last_value", "expected_date_from"),
    [(None, "2026-04-16"), ("2026-08-01", "2026-08-01")],
)
@time_machine.travel("2026-10-13T12:00:00Z", tick=False)
def test_target_report_resolves_site_audit_target(
    table: str,
    selector: str,
    rows: list[dict[str, object]],
    expected_rows: list[dict[str, object]],
    expected_params: dict[str, list[str]],
    last_value: str | None,
    expected_date_from: str,
) -> None:
    result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="00123")).run(
        table,
        [ScriptedResponse(json={"healthscores": [TARGET]}), ScriptedResponse(json={selector: rows})],
        incremental_field="date" if last_value else None,
        db_incremental_field_last_value=last_value,
    )

    assert result.raised is None
    assert result.rows == [{**row, "project_id": "123"} for row in expected_rows]
    target_request, report_request = result.requests
    assert target_request.path == "/v3/site-audit/projects"
    assert target_request.query["project_id"] == ("123",)
    assert report_request.path == f"/v3/{ENDPOINTS[table]['path']}"
    query = {name: list(values) for name, values in report_request.query.items()}
    history_params = {"date_from": [expected_date_from]} if ENDPOINTS[table].get("history") else {}
    assert query == {"output": ["json"], "target": ["https://example.com/"], **expected_params, **history_params}


@time_machine.travel("2026-10-13T12:00:00Z", tick=False)
def test_rank_tracker_reads_each_device() -> None:
    row = {"keyword": "posthog", "country": "us", "location": "United States", "language": "en", "position": 1}
    result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="00123")).run(
        "rank_tracker_overview",
        [
            ScriptedResponse(json={"overviews": [row]}),
            ScriptedResponse(json={"overviews": [{**row, "position": 3}]}),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {**row, "project_id": "123", "device": "desktop"},
        {**row, "position": 3, "project_id": "123", "device": "mobile"},
    ]
    for request, device in zip(result.requests, ["desktop", "mobile"], strict=True):
        assert request.path == "/v3/rank-tracker/overview"
        assert {name: list(values) for name, values in request.query.items()} == {
            "output": ["json"],
            "select": [",".join(RANK_TRACKER_FIELDS)],
            "limit": ["10000"],
            "order_by": ["keyword:asc"],
            "project_id": ["123"],
            "date": ["2026-10-13"],
            "device": [device],
        }


SITE_METRICS_PATHS = [
    "/v3/site-explorer/domain-rating",
    "/v3/site-explorer/backlinks-stats",
    "/v3/site-explorer/metrics",
]


def site_metrics_answer(request: RecordedRequest) -> ScriptedResponse:
    if request.path == "/v3/site-audit/projects":
        return ScriptedResponse(json={"healthscores": [TARGET]})
    day = int((request.param("date") or "")[-2:])
    if request.path == "/v3/site-explorer/domain-rating":
        return ScriptedResponse(json={"domain_rating": {"domain_rating": 50.0 + day, "ahrefs_rank": None}})
    if request.path == "/v3/site-explorer/backlinks-stats":
        return ScriptedResponse(
            json={"metrics": {"all_time": 900, "all_time_refdomains": 90, "live": 500 + day, "live_refdomains": 40}}
        )
    return ScriptedResponse(
        json={
            "metrics": {
                "org_keywords": 300 + day,
                "org_keywords_1_3": 20,
                "org_traffic": 1000,
                "org_cost": None,
                "paid_traffic": 7,
            }
        }
    )


def iso_days(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]


@pytest.mark.parametrize(
    ("last_value", "incremental", "expected_days"),
    [
        (None, True, iso_days("2026-10-07", "2026-10-13")),
        ("2026-10-11", False, iso_days("2026-10-07", "2026-10-13")),
        ("2026-10-11", True, ["2026-10-12", "2026-10-13"]),
        (date(2026, 10, 12), True, ["2026-10-13"]),
        ("2026-10-13", True, []),
        ("2026-05-01", True, iso_days("2026-09-13", "2026-10-13")),
    ],
)
@time_machine.travel("2026-10-13T12:00:00Z", tick=False)
def test_site_metrics_daily_reads_each_day_once(
    last_value: object, incremental: bool, expected_days: list[str]
) -> None:
    result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
        "site_metrics_daily",
        site_metrics_answer,
        incremental_field="date",
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=last_value,
    )

    assert result.raised is None
    assert result.response is not None and result.response.sort_mode == "asc"
    assert [row["date"] for row in result.rows] == expected_days
    expected_requests: list[tuple[str, str | None]] = [("/v3/site-audit/projects", None)] if expected_days else []
    expected_requests += [(path, day) for day in expected_days for path in SITE_METRICS_PATHS]
    assert [(request.path, request.param("date")) for request in result.requests] == expected_requests


@time_machine.travel("2026-10-13T12:00:00Z", tick=False)
def test_site_metrics_daily_merges_reports_into_one_row_per_day() -> None:
    result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="00123")).run(
        "site_metrics_daily",
        site_metrics_answer,
        incremental_field="date",
        db_incremental_field_last_value="2026-10-11",
    )

    assert result.raised is None
    assert result.rows == [
        {
            "project_id": "123",
            "target": "https://example.com/",
            "date": day,
            "domain_rating": 50.0 + int(day[-2:]),
            "ahrefs_rank": None,
            "live_backlinks": 500 + int(day[-2:]),
            "live_refdomains": 40,
            "org_keywords": 300 + int(day[-2:]),
            "org_keywords_1_3": 20,
            "org_traffic": 1000,
            "org_cost": None,
        }
        for day in ["2026-10-12", "2026-10-13"]
    ]
    target_query = {"target": ["https://example.com/"], "mode": ["domain"], "protocol": ["https"]}
    expected_queries = {
        "/v3/site-explorer/domain-rating": {"target": ["https://example.com/"]},
        "/v3/site-explorer/backlinks-stats": target_query,
        "/v3/site-explorer/metrics": target_query,
    }
    for request in result.requests[1:]:
        assert {name: list(values) for name, values in request.query.items()} == {
            "output": ["json"],
            "date": [request.param("date")],
            **expected_queries[request.path],
        }


@pytest.mark.parametrize("healthscores", [[], [{"project_id": "123", "target_url": None}]])
def test_target_report_without_site_audit_target_fails_permanently(healthscores: list[dict[str, object]]) -> None:
    source = AhrefsSource()
    result = SourceDriver(source, AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
        "backlinks", [ScriptedResponse(json={"healthscores": healthscores})]
    )
    assert isinstance(result.raised, ValueError)
    mapped = source.get_non_retryable_errors()[str(result.raised)]
    assert mapped is not None and "project ID" in mapped
    assert len(result.requests) == 1


@pytest.mark.parametrize("count", [99, 100, 101])
def test_page_sample_cap(count: int) -> None:
    rows = [{"url": f"https://example.com/{i}"} for i in range(count)]
    with patch(f"{SOURCE_MODULE}.logger") as logger:
        result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
            "site_audit_pages", [ScriptedResponse(json={"pages": rows})]
        )
    assert result.raised is None
    assert result.rows == [{**row, "project_id": "123"} for row in rows[:100]]
    assert logger.info.call_count == int(count >= 100)
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (400, {"error": "API units limit exceeded"}),
        (402, {"error": "Payment required"}),
    ],
)
def test_exhausted_units_keep_the_schema_enabled(status: int, body: object) -> None:
    answer = ScriptedResponse(status=status, json=body)
    with scripted_network([answer]) as network:
        valid, error = validate_credentials("test-key")
    assert valid is False
    assert error is not None and "API units are exhausted" in error
    assert len(network.requests_log) == 1

    source = AhrefsSource()
    result = SourceDriver(source, AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
        "site_audit_issues", [answer]
    )
    assert isinstance(result.raised, ValueError)
    raised = str(result.raised)
    assert error_message_matches(raised, source.get_retryable_errors())
    assert not error_message_matches(raised, source.get_non_retryable_errors())
    exhausted = [m for key, m in source.get_retry_exhausted_errors().items() if error_message_matches(raised, [key])]
    assert exhausted and "tries again on its own" in exhausted[0]
    assert len(result.requests) == 1


def test_free_credential_probe(send: MagicMock) -> None:
    send.return_value = response({"limits_and_usage": {"subscription": "Lite", "units_usage_api_key": 0}})
    assert validate_credentials("test-key") == (True, None)
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.url == "https://api.ahrefs.com/v3/subscription-info/limits-and-usage?output=json"
    assert send.call_args.kwargs["timeout"] == (10, 60)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_failure_is_not_invalid_credentials(status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"error": "Try later"}))) as network:
        with pytest.raises(RESTClientRetryableError):
            validate_credentials("test-key")
    assert network.requests_log
    assert all(request.path == "/v3/subscription-info/limits-and-usage" for request in network.requests_log)


def test_unrecognized_probe_error_propagates() -> None:
    with scripted_network([ScriptedResponse(status=400, json={"error": "Invalid request"})]) as network:
        with pytest.raises(HTTPError):
            validate_credentials("test-key")
    assert len(network.requests_log) == 1


@pytest.mark.parametrize("probe", [False, True])
def test_missing_response_envelope_fails(probe: bool) -> None:
    answer = ScriptedResponse(json={"unexpected": []})
    if probe:
        with scripted_network([answer]) as network:
            with pytest.raises(ValueError, match="matched nothing"):
                validate_credentials("test-key")
        assert len(network.requests_log) == 1
    else:
        result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
            "site_audit_issues", [answer]
        )
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)
        assert len(result.requests) == 1


@pytest.mark.parametrize(
    ("table", "selector", "row", "base_select"),
    [
        (
            "link_intersect_refdomains",
            "referring-domains",
            {"domain": "a.example", "intersect": 2},
            ["domain", "domain_rating", "intersect", "links_to_target"],
        ),
        (
            "link_intersect_refpages",
            "referring-pages",
            {"url": "https://a.example/post", "intersect": 1},
            ["url", "title", "domain_rating", "url_rating", "intersect", "links_to_target"],
        ),
    ],
)
@pytest.mark.parametrize("has_competitors", [True, False])
def test_link_intersect_compares_target_with_project_competitors(
    table: str, selector: str, row: dict[str, object], base_select: list[str], has_competitors: bool
) -> None:
    competitors = (
        [{"url": "rival.example", "mode": "domain"}, {"url": "https://other.example/blog/", "mode": None}]
        if has_competitors
        else []
    )
    result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="00123")).run(
        table,
        [
            ScriptedResponse(json={"competitors": competitors}),
            ScriptedResponse(json={"healthscores": [TARGET]}),
            ScriptedResponse(json={selector: [row]}),
        ],
    )

    assert result.raised is None
    competitors_request = result.requests[0]
    assert competitors_request.path == "/v3/management/project-competitors"
    assert competitors_request.query["project_id"] == ("123",)
    if not has_competitors:
        assert result.rows == []
        assert len(result.requests) == 1
        return
    competitor_urls = ["rival.example", "https://other.example/blog/"]
    assert result.rows == [{**row, "project_id": "123", "competitors": competitor_urls}]
    _, target_request, report_request = result.requests
    assert target_request.path == "/v3/site-audit/projects"
    assert report_request.method == "POST"
    assert report_request.path == f"/v3/{ENDPOINTS[table]['path']}"
    assert json.loads(report_request.body or b"") == {
        "output": "json",
        "select": [*base_select, "links_to_competitor_1", "links_to_competitor_2"],
        "order_by": ["intersect:desc", "domain_rating:desc"],
        "limit": 1000,
        "target": {"url": "https://example.com/", "mode": "domain", "protocol": "https"},
        "competitors": [
            {"url": "rival.example", "mode": "domain", "protocol": "both"},
            {"url": "https://other.example/blog/", "mode": "subdomains", "protocol": "both"},
        ],
    }


def test_brand_radar_web_pages_read_each_report_linked_to_the_project() -> None:
    reports = [
        {"report_id": "r-1", "project_id": 123},
        {"report_id": "r-other", "project_id": 999},
        {"report_id": "r-unlinked", "project_id": None},
        {"report_id": "r-2", "project_id": 123},
    ]
    result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
        "brand_radar_web_pages",
        [
            ScriptedResponse(json={"reports": reports}),
            ScriptedResponse(json={"pages": [{"url": "https://news.example/a"}]}),
            ScriptedResponse(json={"pages": [{"url": "https://news.example/a"}, {"url": "https://blog.example/b"}]}),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {"url": "https://news.example/a", "project_id": "123", "report_id": "r-1"},
        {"url": "https://news.example/a", "project_id": "123", "report_id": "r-2"},
        {"url": "https://blog.example/b", "project_id": "123", "report_id": "r-2"},
    ]
    reports_request, *page_requests = result.requests
    assert reports_request.path == "/v3/management/brand-radar-reports"
    assert [request.method for request in page_requests] == ["POST", "POST"]
    assert [json.loads(request.body or b"")["report_id"] for request in page_requests] == ["r-1", "r-2"]


@pytest.mark.parametrize(
    ("max_rank", "page_sizes", "expected_ranges"),
    [
        (5, [2, 2, 1], [("1", "2"), ("3", "4"), ("5", "5")]),
        (10, [2, 1], [("1", "2"), ("3", "4")]),
        (10, [2, 0], [("1", "2"), ("3", "4")]),
    ],
)
def test_top_domains_walk_rank_ranges_to_terminal_page(
    max_rank: int, page_sizes: list[int], expected_ranges: list[tuple[str, str]]
) -> None:
    ranks = iter(range(1, 100))
    pages: list[list[dict[str, object]]] = [
        [{"domain": f"d{rank}.example", "rank": rank} for rank in [next(ranks) for _ in range(size)]]
        for size in page_sizes
    ]
    with patch(f"{SOURCE_MODULE}.TOP_DOMAINS_PAGE_ROWS", 2), patch(f"{SOURCE_MODULE}.TOP_DOMAINS_COUNT", max_rank):
        result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
            "domain_rating_top_domains", [ScriptedResponse(json={"domains": page}) for page in pages]
        )

    assert result.raised is None
    assert result.rows == [row for page in pages for row in page]
    assert [(request.param("from"), request.param("to")) for request in result.requests] == expected_ranges
    assert all(request.path == "/v3/public/domain-rating-top-domains" for request in result.requests)
