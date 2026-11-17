from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.writesonic._config import WritesonicSourceConfig
from products.warehouse_sources.sources.writesonic.settings import WRITESONIC_ENDPOINTS
from products.warehouse_sources.sources.writesonic.source import WritesonicSource
from products.warehouse_sources.sources.writesonic.writesonic import (
    WritesonicResumeConfig,
    WritesonicRetryableError,
    _check_response,
    _to_date,
    get_rows,
    validate_credentials,
)


def _api(
    daily_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
    config_pages: list[list[dict[str, Any]]] | None = None,
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Canned paginated Writesonic responses, chosen by the request's `date` and `page`."""
    daily = daily_pages or {}
    config = config_pages or []

    def respond(request: RecordedRequest) -> ScriptedResponse:
        day = request.param("date")
        pages = daily.get(day, []) if day is not None else config
        page = int(request.param("page") or 0)
        items = pages[page - 1] if 1 <= page <= len(pages) else []
        return ScriptedResponse(
            json={
                "items": items,
                "page": page,
                "size": int(request.param("size") or 0),
                "total": sum(len(p) for p in pages),
                "count": len(items),
                "total_pages": len(pages),
            }
        )

    return respond


def _driver(project_id: str | None = None) -> SourceDriver:
    return SourceDriver(
        WritesonicSource(),
        WritesonicSourceConfig(api_key="key", site_url="https://example.com", project_id=project_id),
    )


class TestToDate:
    @parameterized.expand(
        [
            ("date_value", date(2026, 7, 1), date(2026, 7, 1)),
            ("aware_datetime", datetime(2026, 7, 1, 12, 30, tzinfo=UTC), date(2026, 7, 1)),
            ("date_string", "2026-07-01", date(2026, 7, 1)),
            ("iso_string", "2026-07-01T12:30:00Z", date(2026, 7, 1)),
            ("epoch_int", 1782950400, date(2026, 7, 2)),
            ("bad_string", "not-a-date", None),
            ("none", None, None),
            ("bool", True, None),
        ]
    )
    def test_to_date(self, _name, value, expected):
        assert _to_date(value) == expected


class TestConfigEndpoints:
    def test_paginates_until_total_pages(self) -> None:
        result = _driver().run("topics", _api(config_pages=[[{"topic_id": "t1"}], [{"topic_id": "t2"}]]))

        assert [r["topic_id"] for r in result.rows] == ["t1", "t2"]
        assert result.params("page") == ["1", "2"]

    def test_sends_project_id_when_configured(self) -> None:
        result = _driver(project_id="proj-1").run("topics", _api(config_pages=[[{"topic_id": "t1"}]]))

        assert result.requests[0].param("project_id") == "proj-1"

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "topics",
            _api(config_pages=[[{"topic_id": "t1"}], [{"topic_id": "t2"}]]),
            resume_state=WritesonicResumeConfig(page=2),
        )

        # Page 1 was already yielded before the crash; only page 2 is re-fetched.
        assert [r["topic_id"] for r in result.rows] == ["t2"]
        assert result.params("page") == ["2"]

    def test_unknown_endpoint_raises(self) -> None:
        result = _driver().run("nonexistent", _api())

        assert isinstance(result.raised, KeyError)
        assert result.requests == []

    def test_get_rows_rejects_unknown_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Unknown Writesonic endpoint"):
            list(
                get_rows(
                    api_key="key",
                    site_url="https://example.com",
                    project_id=None,
                    endpoint="nonexistent",
                    logger=mock.MagicMock(),
                    manager=mock.MagicMock(),
                )
            )


class TestDailyEndpoints:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-07-09T12:00:00Z", tick=False):
            yield

    def test_future_cursor_clamped_to_today(self) -> None:
        result = _driver().run(
            "performance_summary",
            _api(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2027, 1, 1),
        )

        assert result.params("date") == ["2026-07-09"]

    def test_injects_date_into_content_rows(self) -> None:
        # Content export rows don't carry the export date, but it's part of the primary key,
        # the partition key, and the incremental cursor — a missing column breaks all three.
        result = _driver().run(
            "content_citations",
            _api(daily_pages={"2026-07-09": [[{"citation_id": "c1"}]]}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 9),
        )

        assert result.rows == [{"citation_id": "c1", "date": "2026-07-09"}]

    def test_resumes_from_saved_day_and_page(self) -> None:
        result = _driver().run(
            "performance_summary",
            _api(
                daily_pages={
                    "2026-07-07": [[{"date": "2026-07-07", "website_id": "w1"}]],
                    "2026-07-08": [
                        [{"date": "2026-07-08", "website_id": "w1"}],
                        [{"date": "2026-07-08", "website_id": "w2"}],
                    ],
                }
            ),
            resume_state=WritesonicResumeConfig(date="2026-07-08", page=2),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 7),
        )

        # Completed days and pages are skipped; the resume day continues at its saved page.
        assert list(zip(result.params("date"), result.params("page"), strict=True)) == [
            ("2026-07-08", "2"),
            ("2026-07-09", "1"),
        ]
        assert [r["website_id"] for r in result.rows] == ["w2"]


_CO = "/v2/geo/presence/business/export/actionable/content-optimize"

_LISTING = [
    [
        {"optimization_page_id": "p1", "source_url": "https://example.com/a"},
        {"optimization_page_id": "p2", "source_url": "https://example.com/b"},
    ],
    [{"optimization_page_id": "p3", "source_url": "https://example.com/c"}],
]


def _content_optimize_api(
    children: dict[str, dict[str, Any]],
    missing: frozenset[str] = frozenset(),
    listing: list[list[dict[str, Any]]] = _LISTING,
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """The pages listing (page count under `pages`), plus per-page child responses keyed by `page_url`."""

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == f"{_CO}/pages":
            page = int(request.param("page") or 0)
            items = listing[page - 1] if 1 <= page <= len(listing) else []
            return ScriptedResponse(json={"items": items, "page": page, "size": 100, "pages": len(listing), "total": 3})
        page_url = request.param("page_url") or ""
        if page_url in missing:
            return ScriptedResponse(status=404, json={"detail": "Not found"})
        return ScriptedResponse(json=children.get(page_url, {}))

    return respond


class TestContentOptimizeEndpoints:
    @parameterized.expand(
        [
            (
                "issues",
                "content_optimize_issues",
                f"{_CO}/issues",
                {
                    "https://example.com/a": {
                        "issues": [{"issue_id": "i1", "issue_type": "TITLE"}, {"issue_id": "i2", "issue_type": "FAQ"}]
                    },
                    "https://example.com/c": {"issues": [{"issue_id": "i3", "issue_type": "TITLE"}]},
                },
                "issue_id",
                [
                    ("p1", "https://example.com/a", "i1", "TITLE"),
                    ("p1", "https://example.com/a", "i2", "FAQ"),
                    ("p3", "https://example.com/c", "i3", "TITLE"),
                ],
            ),
            (
                "recommendations_across_issue_types",
                "content_optimize_recommendations",
                f"{_CO}/recommendations/all",
                {
                    "https://example.com/b": {
                        "recommendations": [
                            {"issue_type": "TITLE", "fixes": [{"id": "f1"}]},
                            {"issue_type": "FAQ", "status": "FAILED", "fixes": None},
                            {
                                "issue_type": "META_DESCRIPTION",
                                "fixes": [{"id": "f2", "issue_type": "META_DESCRIPTION"}],
                            },
                        ]
                    },
                },
                "id",
                [
                    ("p2", "https://example.com/b", "f1", "TITLE"),
                    ("p2", "https://example.com/b", "f2", "META_DESCRIPTION"),
                ],
            ),
        ]
    )
    def test_fans_out_over_every_listed_page(self, _name, endpoint, child_path, children, row_id, expected):
        result = _driver().run(endpoint, _content_optimize_api(children))

        assert [(r["optimization_page_id"], r["page_url"], r[row_id], r["issue_type"]) for r in result.rows] == expected
        # The listing stops at its `pages` count, without a request for an empty page.
        assert [r.param("page") for r in result.requests if r.path == f"{_CO}/pages"] == ["1", "2"]
        assert [r.param("page_url") for r in result.requests if r.path == child_path] == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_skips_page_removed_since_listing(self) -> None:
        result = _driver().run(
            "content_optimize_issues",
            _content_optimize_api(
                {"https://example.com/c": {"issues": [{"issue_id": "i3"}]}},
                missing=frozenset({"https://example.com/a", "https://example.com/b"}),
            ),
        )

        assert result.raised is None
        assert [r["issue_id"] for r in result.rows] == ["i3"]

    @parameterized.expand(
        [
            ("listing_unchanged", _LISTING),
            ("finished_parent_removed", [[_LISTING[0][1]], _LISTING[1]]),
        ]
    )
    def test_resumes_after_last_finished_page(self, _name, listing) -> None:
        result = _driver().run(
            "content_optimize_issues",
            _content_optimize_api(
                {
                    "https://example.com/a": {"issues": [{"issue_id": "i1"}]},
                    "https://example.com/b": {"issues": [{"issue_id": "i2"}]},
                    "https://example.com/c": {"issues": [{"issue_id": "i3"}]},
                },
                listing=listing,
            ),
            resume_state=WritesonicResumeConfig(page=1, parent_id="p1"),
        )

        assert [r["issue_id"] for r in result.rows] == ["i2", "i3"]
        assert [r.param("page_url") for r in result.requests if r.path == f"{_CO}/issues"] == [
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_issues_summary_rows_carry_scan_date(self) -> None:
        summary: dict[str, Any] = {
            "issues": [
                {"issue_type": "TITLE", "sub_issue_type": "TITLE_MISSING", "impacted_urls": 2, "urls": [{"url": "u"}]},
                {"issue_type": "FAQ", "sub_issue_type": "FAQ_MISSING", "impacted_urls": 1, "urls": []},
            ],
            "last_scan_date": "2026-07-01T08:00:00Z",
        }
        result = _driver(project_id="proj-1").run(
            "content_optimize_issues_summary", always(ScriptedResponse(json=summary))
        )

        assert result.rows == [{**row, "last_scan_date": "2026-07-01T08:00:00Z"} for row in summary["issues"]]
        assert len(result.requests) == 1
        assert result.requests[0].param("project_id") == "proj-1"


class TestCheckResponse:
    def _response(self, status_code: int, headers: dict[str, str] | None = None) -> Any:
        response = mock.MagicMock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 300
        response.headers = headers or {}
        response.text = "body"
        if not response.ok:
            response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error", response=response)
        return response

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502), ("unavailable", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name, status):
        with pytest.raises(WritesonicRetryableError):
            _check_response(self._response(status), "https://api.writesonic.com/x", mock.MagicMock())

    def test_retry_after_header_is_carried(self):
        with pytest.raises(WritesonicRetryableError) as exc_info:
            _check_response(
                self._response(429, headers={"Retry-After": "30"}),
                "https://api.writesonic.com/x",
                mock.MagicMock(),
            )
        assert exc_info.value.retry_after == 30.0

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404), ("unprocessable", 422)])
    def test_terminal_statuses_raise_http_error(self, _name, status):
        with pytest.raises(requests.HTTPError):
            _check_response(self._response(status), "https://api.writesonic.com/x", mock.MagicMock())

    def test_ok_returns_response(self):
        response = self._response(200)
        assert _check_response(response, "https://api.writesonic.com/x", mock.MagicMock()) is response


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("not_found", 404, False),
            ("unprocessable", 422, False),
        ]
    )
    def test_status_mapping(self, _name, status, expected_ok):
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            ok, message = validate_credentials(api_key="key", site_url="https://example.com")
            assert ok is expected_ok
            if not expected_ok:
                assert message


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in WRITESONIC_ENDPOINTS])
    def test_source_response_matches_endpoint_config(self, endpoint):
        config = WRITESONIC_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
