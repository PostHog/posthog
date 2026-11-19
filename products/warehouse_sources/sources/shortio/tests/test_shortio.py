from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, SourceDriver, always
from products.warehouse_sources.sources.shortio._config import ShortioSourceConfig
from products.warehouse_sources.sources.shortio.shortio import SHORTIO_BASE_URL, ShortioResumeConfig
from products.warehouse_sources.sources.shortio.source import ShortioSource

DOMAINS_URL = f"{SHORTIO_BASE_URL}/api/domains"


def _driver() -> SourceDriver:
    return SourceDriver(ShortioSource(), ShortioSourceConfig(api_key="sk-key"))


class TestShortioSource:
    def test_non_list_body_fails_fast(self) -> None:
        # A non-list 200 means the schema changed under us — fail loud, never sync the object as a row.
        result = _driver().run("domains", [ScriptedResponse(json={"error": "nope"})])

        assert isinstance(result.raised, ValueError)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error_with_url(self, _name: str, status: int) -> None:
        result = _driver().run("domains", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, HTTPError)
        # The raised message carries the status + endpoint URL so get_non_retryable_errors can match it.
        assert f"{status}" in str(result.raised)
        assert DOMAINS_URL in str(result.raised)
        # A 4xx is permanent — it must not be retried.
        assert len(result.requests) == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("domains", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        # The client exhausts its full retry budget on a persistently-erroring endpoint.
        assert len(result.requests) == 5

    def test_links_paginate_each_domain(self) -> None:
        result = _driver().run(
            "links",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(
                    json={"links": [{"idString": "lnk_a", "password": "fake-link-password"}], "nextPageToken": "page-2"}
                ),
                ScriptedResponse(json={"links": [{"idString": "lnk_b"}], "nextPageToken": None}),
                ScriptedResponse(json={"links": [{"idString": "lnk_c"}], "nextPageToken": None}),
            ],
        )

        assert result.raised is None
        assert [(row["idString"], row["domain_id"]) for row in result.rows] == [
            ("lnk_a", 1),
            ("lnk_b", 1),
            ("lnk_c", 2),
        ]
        assert result.params("domain_id") == [None, "1", "1", "2"]
        assert all("password" not in row for row in result.rows)
        assert result.params("pageToken") == [None, None, "page-2", None]
        assert all(request.headers["authorization"] == "sk-key" for request in result.requests)
        assert result.committed_states
        assert result.completed_state is None

    def test_links_resume_child_page(self) -> None:
        result = _driver().run(
            "links",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(json={"links": [{"idString": "lnk_c"}], "nextPageToken": None}),
            ],
            resume_state=ShortioResumeConfig(
                paginator_state={
                    "completed": ["/api/links?domain_id=1"],
                    "current": "/api/links?domain_id=2",
                    "child_state": {"cursor": "page-2"},
                }
            ),
        )

        assert result.raised is None
        assert result.params("domain_id") == [None, "2"]
        assert result.params("pageToken") == [None, "page-2"]
        assert result.rows[0]["idString"] == "lnk_c"

    @parameterized.expand([("link_clicks",), ("link_by_interval",)])
    def test_link_statistics_walk_all_links(self, endpoint: str) -> None:
        statistics = (
            [{"lnk_a": 0, "lnk_z": 3}, {"lnk_b": 12}]
            if endpoint == "link_clicks"
            else [{"clickStatistics": []}, {"clickStatistics": [{"x": "2026-01-01T00:00:00Z", "y": 12}]}]
        )
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(
                    json={
                        "links": [{"idString": "lnk_a"}, {"idString": "lnk_z"}]
                        if endpoint == "link_clicks"
                        else [{"idString": "lnk_a"}],
                        "nextPageToken": "page-2",
                    }
                ),
                ScriptedResponse(json=statistics[0]),
                ScriptedResponse(json={"links": [{"idString": "lnk_b"}], "nextPageToken": None}),
                ScriptedResponse(json=statistics[1]),
            ],
        )

        assert result.raised is None
        assert result.params("pageToken") == [None, None, None, "page-2", None]
        stats_requests = [request for request in result.requests if request.origin == "https://statistics.short.io"]
        assert len(stats_requests) == 2
        if endpoint == "link_clicks":
            assert [request.param("ids") for request in stats_requests] == ["lnk_a,lnk_z", "lnk_b"]
            assert all(request.path == "/statistics/domain/1/link_clicks" for request in stats_requests)
            assert result.rows == [
                {"domain_id": 1, "link_id": "lnk_a", "clicks": 0},
                {"domain_id": 1, "link_id": "lnk_z", "clicks": 3},
                {"domain_id": 1, "link_id": "lnk_b", "clicks": 12},
            ]
        else:
            assert [request.path for request in stats_requests] == [
                "/statistics/link/lnk_a/by_interval",
                "/statistics/link/lnk_b/by_interval",
            ]
            assert all(request.method == "POST" for request in stats_requests)
            assert all(
                request.json() == {"period": "total", "tz": "UTC", "clicksChartInterval": "day"}
                for request in stats_requests
            )
            assert result.rows == [{"domain_id": 1, "link_id": "lnk_b", "x": "2026-01-01T00:00:00Z", "y": 12}]

    def test_last_clicks_paginate_and_reset_for_each_domain(self) -> None:
        result = _driver().run(
            "last_clicks",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(json=[{"dt": "2026-01-02T00:00:00Z", "path": "/a"}]),
                ScriptedResponse(json=[{"dt": "2026-01-01T00:00:00Z", "path": "/a"}]),
                ScriptedResponse(json=[]),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert [row["domain_id"] for row in result.rows] == [1, 1]
        assert [request.json() for request in result.requests[1:]] == [
            {"period": "total", "tz": "UTC", "limit": 30},
            {"period": "total", "tz": "UTC", "limit": 30, "beforeDate": "2026-01-02T00:00:00Z"},
            {"period": "total", "tz": "UTC", "limit": 30, "beforeDate": "2026-01-01T00:00:00Z"},
            {"period": "total", "tz": "UTC", "limit": 30},
        ]
        assert result.committed_states
        assert result.completed_state is None

    @parameterized.expand([(30,), (60,)])
    def test_last_clicks_resume_before_date(self, limit: int) -> None:
        result = _driver().run(
            "last_clicks",
            [ScriptedResponse(json=[{"id": 1}]), ScriptedResponse(json=[])],
            resume_state=ShortioResumeConfig(
                paginator_state={
                    "current": "https://statistics.short.io/statistics/domain/1/last_clicks",
                    "child_state": {"before_date": "2026-01-01T00:00:00Z", "limit": limit},
                }
            ),
        )

        assert result.raised is None
        assert result.requests[1].json()["beforeDate"] == "2026-01-01T00:00:00Z"
        assert result.requests[1].json()["limit"] == limit

    @parameterized.expand([(0, False), (10, False), (0, True), (10, True)])
    def test_last_clicks_preserve_clicks_sharing_page_boundary(self, newer_count: int, inclusive: bool) -> None:
        newer = [{"dt": "2026-01-02T00:00:00Z", "path": "/newer"} for _ in range(newer_count)]
        boundary = [{"dt": "2026-01-01T00:00:00Z", "path": "/same"} for _ in range(31)]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/domains":
                return ScriptedResponse(json=[{"id": 1}])
            body = request.json()
            before_date = body.get("beforeDate")
            rows = [
                row
                for row in newer + boundary
                if before_date is None or row["dt"] < before_date or (inclusive and row["dt"] == before_date)
            ]
            return ScriptedResponse(json=rows[: body["limit"]])

        result = _driver().run(
            "last_clicks",
            respond,
        )

        assert result.raised is None
        assert result.rows == [{**row, "domain_id": 1} for row in newer + boundary]
        assert any(request.json()["limit"] == 60 for request in result.requests[1:])

    @parameterized.expand([(False,), (True,)])
    def test_last_clicks_reject_unsafe_pagination(self, oversized_group: bool) -> None:
        click = {"dt": "2026-01-01T00:00:00Z", "path": "/a"}
        result = _driver().run(
            "last_clicks",
            [
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(json=[click] * (10000 if oversized_group else 1)),
                ScriptedResponse(json=[{**click, "dt": "2026-01-02T00:00:00Z"}]),
            ],
            resume_state=ShortioResumeConfig(
                paginator_state={
                    "current": "https://statistics.short.io/statistics/domain/1/last_clicks",
                    "child_state": {"limit": 10000},
                }
            )
            if oversized_group
            else None,
        )

        assert isinstance(result.raised, ValueError)
        assert ("too many clicks" if oversized_group else "did not advance") in str(result.raised)

    @parameterized.expand([({}, False), ({"message": "Invalid request"}, True), ({"lnk_a": None}, True)])
    def test_link_clicks_handle_empty_and_invalid_counts(self, counts: dict[str, object], invalid: bool) -> None:
        result = _driver().run(
            "link_clicks",
            [
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(json={"links": [{"idString": "lnk_a"}], "nextPageToken": None}),
                ScriptedResponse(json=counts),
            ],
        )

        if invalid:
            assert isinstance(result.raised, ValueError)
            assert "invalid link click count" in str(result.raised)
        else:
            assert result.raised is None
        assert result.rows == []
