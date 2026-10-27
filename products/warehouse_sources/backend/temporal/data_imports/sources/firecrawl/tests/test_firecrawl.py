from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.firecrawl import (
    FirecrawlResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.source import FirecrawlSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firecrawl import (
    FirecrawlSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FirecrawlSource(), FirecrawlSourceConfig(api_key="fc-test"))


def _response(selector: str, items: list[dict[str, Any]], *, extra: dict[str, Any] | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={selector: items, **(extra or {})})


class TestCursorPagination:
    def test_follows_cursor_until_cursor_empty(self) -> None:
        result = _driver().run(
            "team_activity",
            [
                _response("data", [{"id": "a"}], extra={"cursor": "c1", "has_more": True}),
                _response("data", [{"id": "b"}], extra={"cursor": "c2", "has_more": True}),
                _response("data", [{"id": "c"}], extra={"cursor": None, "has_more": False}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        # limit is sent on every page; the cursor is injected only from the second page on.
        assert result.params("limit") == ["100", "100", "100"]
        assert result.params("cursor") == [None, "c1", "c2"]
        # Checkpoint is saved only while a next cursor remains, and it points at the NEXT page.
        assert result.saved_states == [FirecrawlResumeConfig(cursor="c1"), FirecrawlResumeConfig(cursor="c2")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "team_activity",
            [_response("data", [{"id": "b"}], extra={"cursor": None, "has_more": False})],
            resume_state=FirecrawlResumeConfig(cursor="c1"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["b"]
        # The resumed cursor is applied to the very first request; the earlier page is never re-fetched.
        assert result.params("cursor") == ["c1"]
        assert len(result.requests) == 1


class TestOffsetPagination:
    def test_pages_until_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(100)]
        result = _driver().run("monitors", [_response("data", full_page), _response("data", [{"id": "last"}])])

        assert result.raised is None
        assert len(result.rows) == 101
        assert result.params("offset") == ["0", "100"]
        assert result.requests[0].param("limit") == "100"
        # One checkpoint after the first full page (points at the next offset); the short page ends it.
        assert result.saved_states == [FirecrawlResumeConfig(offset=100)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "monitors",
            [_response("data", [{"id": "m_201"}])],
            resume_state=FirecrawlResumeConfig(offset=200),
        )

        assert result.raised is None
        assert result.params("offset") == ["200"]


class TestUnpaginated:
    @parameterized.expand(
        [
            ("credit_usage_historical", "periods"),
            ("token_usage_historical", "periods"),
            ("active_crawls", "crawls"),
        ]
    )
    def test_single_request_reads_the_endpoint_selector(self, endpoint: str, selector: str) -> None:
        result = _driver().run(endpoint, [_response(selector, [{"id": "1"}, {"id": "2"}])])

        assert result.raised is None
        assert result.rows == [{"id": "1"}, {"id": "2"}]
        assert len(result.requests) == 1  # unpaginated: exactly one request

    def test_missing_selector_raises_loudly(self) -> None:
        # A 200 body without the expected selector means the response shape changed — fail loud rather
        # than silently replacing warehouse data with zero rows on a full refresh.
        result = _driver().run("active_crawls", [_response("something_else", [{"id": "1"}])])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestMonitorChecksFanOut:
    def test_resumes_past_completed_monitor(self) -> None:
        # m1's checks are already checkpointed as complete, so the resume skips straight to m2.
        result = _driver().run(
            "monitor_checks",
            route(
                {
                    "/v2/monitor": [_response("data", [{"id": "m1"}, {"id": "m2"}])],
                    "/v2/monitor/m2/checks": [_response("data", [{"id": "chk2", "monitorId": "m2"}])],
                }
            ),
            resume_state=FirecrawlResumeConfig(fanout_state={"completed": ["/v2/monitor/m1/checks"], "current": None}),
        )

        assert result.raised is None
        assert result.rows == [{"id": "chk2", "monitorId": "m2"}]
        assert result.paths == ["/v2/monitor", "/v2/monitor/m2/checks"]


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_retry_then_succeed(self, _name: str, status_code: int) -> None:
        # 429 (plan rate/concurrency limit) and 5xx must retry rather than fail the sync outright.
        result = _driver().run(
            "team_activity",
            [ScriptedResponse(status=status_code, json={}), _response("data", [{"id": "a"}])],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a"]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_client_errors_surface_immediately(self, _name: str, status_code: int, reason: str) -> None:
        # A 4xx credential/permission error can never be fixed by retrying, so it must surface at once
        # (and carries the status text get_non_retryable_errors matches on).
        result = _driver().run("team_activity", [ScriptedResponse(status=status_code, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert str(status_code) in str(result.raised)
        assert reason in str(result.raised)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            assert validate_credentials("fc-test") is expected

        assert {request.path for request in network.requests_log} == {"/v2/team/credit-usage"}
        assert network.requests_log[0].headers["authorization"] == "Bearer fc-test"


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("team_activity", ["id"], "created_at", "week"),
            ("credit_usage_historical", ["startDate"], None, None),
            ("token_usage_historical", ["startDate"], None, None),
            ("active_crawls", ["id"], None, None),
            ("monitors", ["id"], "createdAt", "week"),
            ("monitor_checks", ["id"], "createdAt", "week"),
        ]
    )
    def test_primary_keys_and_partitioning(
        self,
        endpoint: str,
        expected_pk: list[str],
        partition_key: str | None,
        partition_format: str | None,
    ) -> None:
        # Locks the primary key + a STABLE (creation-time) partition field per endpoint. A non-unique
        # key or an updated_at partition would rewrite partitions every sync and accumulate duplicates.
        selector = {
            "credit_usage_historical": "periods",
            "token_usage_historical": "periods",
            "active_crawls": "crawls",
        }.get(endpoint, "data")
        result = _driver().run(endpoint, [_response(selector, [])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == partition_format
