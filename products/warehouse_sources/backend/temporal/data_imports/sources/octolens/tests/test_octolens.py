import json
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.octolens import (
    OctolensSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.octolens import (
    OCTOLENS_BASE_URL,
    PAGE_SIZE,
    OctolensResumeConfig,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.source import OctolensSource


def _driver() -> SourceDriver:
    return SourceDriver(OctolensSource(), OctolensSourceConfig(api_key="dummy-key"))


def _mentions_page(items: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "pagination": {"nextCursor": next_cursor}})


class TestMentionsPagination:
    def test_cursor_rides_in_the_post_body_until_exhausted(self) -> None:
        result = _driver().run(
            "mentions",
            [
                _mentions_page([{"sourceId": "reddit_1"}], next_cursor="c1"),
                _mentions_page([{"sourceId": "reddit_2"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"sourceId": "reddit_1"}, {"sourceId": "reddit_2"}]
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.requests[0].url == f"{OCTOLENS_BASE_URL}/api/v2/mentions"
        assert "cursor" not in result.requests[0].json()
        assert result.requests[1].json()["cursor"] == "c1"
        # The cursor must not leak into the query string — the API only reads it from the body.
        assert result.requests[1].query == {}
        assert result.requests[0].json()["limit"] == PAGE_SIZE


class TestMentionsFullRefresh:
    def test_never_sends_a_date_filter(self) -> None:
        """`filters.startDate` filters on post time, which is not an update-aware cursor.

        Mention rows mutate after they are posted (`sentiment` fills in once scoring finishes,
        `engaged`/`feedbackRelevant` change as people act on them) and Octolens backfills historical
        mentions, so a post-time watermark would permanently drop both. The feed resyncs in full.
        """
        result = _driver().run("mentions", [_mentions_page([])])

        assert result.raised is None
        assert "filters" not in result.requests[0].json()
        assert "startDate" not in json.dumps(result.requests[0].json())


class TestResume:
    def test_resumes_from_the_saved_cursor(self) -> None:
        result = _driver().run(
            "mentions",
            [_mentions_page([{"sourceId": "z"}])],
            resume_state=OctolensResumeConfig(cursor="resume-cursor"),
        )

        assert result.raised is None
        assert result.rows == [{"sourceId": "z"}]
        assert result.requests[0].json()["cursor"] == "resume-cursor"

    def test_unpaginated_endpoints_never_checkpoint(self) -> None:
        result = _driver().run(
            "keywords",
            [ScriptedResponse(json={"data": [{"id": 1}]})],
            resume_state=OctolensResumeConfig(cursor="stale-mentions-cursor"),
        )

        assert result.raised is None
        assert result.saved_states == []
        assert result.requests[0].body is None
        assert result.requests[0].query == {}


class TestDimensionEndpoints:
    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("keywords", "/api/v2/keywords"),
            ("feeds", "/api/v2/feeds"),
            ("notifications", "/api/v2/notifications"),
            ("org_members", "/api/v2/org/members"),
        ],
    )
    def test_single_get_request_per_endpoint(self, endpoint: str, path: str) -> None:
        # A stray cursor in the body must not make these endpoints page — they are not paginated.
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"data": [{"id": 1}], "pagination": {"nextCursor": "c1"}})],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 1
        assert result.requests[0].method == "GET"
        assert result.requests[0].url == f"{OCTOLENS_BASE_URL}{path}"
        assert result.requests[0].body is None


class TestSearches:
    def test_cursor_rides_in_the_query_string_until_exhausted(self) -> None:
        result = _driver().run(
            "searches",
            [
                _mentions_page([{"searchId": "s1"}], next_cursor="c1"),
                _mentions_page([{"searchId": "s2"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"searchId": "s1"}, {"searchId": "s2"}]
        assert [request.method for request in result.requests] == ["GET", "GET"]
        assert [request.path for request in result.requests] == ["/api/v2/search", "/api/v2/search"]
        assert result.requests[0].query == {"limit": (str(PAGE_SIZE),)}
        assert result.requests[1].query == {"limit": (str(PAGE_SIZE),), "cursor": ("c1",)}
        assert result.requests[1].body is None


class TestFanOut:
    def test_search_results_fetch_each_search_and_carry_its_id(self) -> None:
        result = _driver().run(
            "search_results",
            [
                _mentions_page([{"searchId": "s1"}], next_cursor="c1"),
                ScriptedResponse(json={"searchId": "s1", "mentions": [{"sourceId": "reddit_1"}]}),
                _mentions_page([{"searchId": "s2"}]),
                ScriptedResponse(json={"searchId": "s2", "mentions": [{"sourceId": "reddit_1"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"sourceId": "reddit_1", "searchId": "s1"},
            {"sourceId": "reddit_1", "searchId": "s2"},
        ]
        assert [request.path for request in result.requests] == [
            "/api/v2/search",
            "/api/v2/search/s1",
            "/api/v2/search",
            "/api/v2/search/s2",
        ]
        assert result.requests[2].query["cursor"] == ("c1",)
        # The single-search endpoint takes no page size.
        assert result.requests[1].query == {}

    def test_search_results_resume_skips_completed_searches(self) -> None:
        searches = _mentions_page([{"searchId": "s1"}, {"searchId": "s2"}])
        first = _driver().run(
            "search_results",
            [
                searches,
                ScriptedResponse(json={"mentions": [{"sourceId": "reddit_1"}]}),
                ScriptedResponse(json={"mentions": [{"sourceId": "reddit_2"}]}),
            ],
        )
        after_first_search = first.saved_states[0]
        assert after_first_search.fanout_state is not None

        resumed = _driver().run(
            "search_results",
            [searches, ScriptedResponse(json={"mentions": [{"sourceId": "reddit_2"}]})],
            resume_state=after_first_search,
        )

        assert resumed.raised is None
        assert resumed.rows == [{"sourceId": "reddit_2", "searchId": "s2"}]
        assert [request.path for request in resumed.requests] == ["/api/v2/search", "/api/v2/search/s2"]


class TestUsage:
    def test_the_response_object_is_one_row(self) -> None:
        usage = {"plan": "Pro_v3", "mentions": {"count": 5, "limit": 100, "resetAt": None}}
        result = _driver().run("usage", [ScriptedResponse(json=usage)])

        assert result.raised is None
        assert result.rows == [usage]
        assert result.requests[0].path == "/api/v2/org/usage"


class TestHttpErrors:
    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_failures_raise_a_matchable_error(self, status_code: int) -> None:
        result = _driver().run(
            "mentions", [ScriptedResponse(status=status_code, json={"error": {"code": "UNAUTHORIZED"}})]
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status_code} Client Error" in str(result.raised)


class TestCheckAccess:
    @pytest.mark.parametrize(
        "response, expected_status",
        [
            (ScriptedResponse(json={"organizationId": "org_1", "scopes": ["read"]}), 200),
            (ScriptedResponse(status=401, json={"error": {"message": "Invalid key"}}), 401),
            (ScriptedResponse(status=403, json={"error": {"message": "Insufficient scope"}}), 403),
            (ScriptedResponse(status=500), 500),
            # A 200 that isn't JSON, or one without a workspace, is not a validated key.
            (ScriptedResponse(body=b"not json"), 0),
            (ScriptedResponse(json={"scopes": ["read"]}), 0),
        ],
    )
    def test_status_mapping(self, response: ScriptedResponse, expected_status: int) -> None:
        with scripted_network(always(response)) as network:
            status, _message = check_access("k", "v2")

        assert status == expected_status
        assert network.requests_log
        assert all(request.path == "/api/v2/auth" for request in network.requests_log)

    @pytest.mark.parametrize(
        "response",
        [
            # Not JSON at all (a proxy or maintenance page fronting the error).
            ScriptedResponse(status=500, body=b"not json"),
            # JSON, but not the documented error envelope.
            ScriptedResponse(status=500, json=["unexpected"]),
            ScriptedResponse(status=500, json={"error": "just a string"}),
            ScriptedResponse(status=500, json={"error": {"code": "boom"}}),
        ],
    )
    def test_falls_back_to_the_status_code_when_there_is_no_envelope_message(self, response: ScriptedResponse) -> None:
        with scripted_network(always(response)):
            status, message = check_access("k", "v2")

        assert status == 500
        assert message == "Octolens returned HTTP 500"

    def test_connection_error_reports_unvalidated(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            status, message = check_access("k", "v2")

        assert status == 0
        assert message is not None
