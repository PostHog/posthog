from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.browser_use import (
    BROWSER_USE_BASE_URL,
    BrowserUseResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import (
    BROWSER_USE_API_VERSION_V3,
    BROWSER_USE_API_VERSION_V4,
    BROWSER_USE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.source import BrowserUseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browseruse import (
    BrowserUseSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(BrowserUseSource(), BrowserUseSourceConfig(api_key="bu_test"))


class TestPagination:
    @parameterized.expand(
        [
            ("sessions", "sessions", "page", "page_size"),
            ("browser_sessions", "items", "pageNumber", "pageSize"),
            ("profiles", "items", "pageNumber", "pageSize"),
            ("workspaces", "items", "pageNumber", "pageSize"),
        ]
    )
    def test_all_pages_aggregated_and_terminates(
        self, endpoint: str, data_key: str, page_param: str, size_param: str
    ) -> None:
        # Two full pages then a short page: guards that every page is collected, that the endpoint's
        # own page/pageSize param names are sent (the wrong name would silently return page 1
        # forever), and that a short page terminates the loop instead of paging forever.
        size = BROWSER_USE_ENDPOINTS[endpoint].page_size
        pages = [
            [{"id": f"a{i}"} for i in range(size)],
            [{"id": f"b{i}"} for i in range(size)],
            [{"id": "c0"}, {"id": "c1"}],
        ]
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={data_key: page}) for page in pages],
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert result.raised is None
        assert len(result.rows) == size * 2 + 2
        assert result.params(page_param) == ["1", "2", "3"]
        assert result.params(size_param) == [str(size)] * 3

    def test_total_stops_before_an_empty_page(self) -> None:
        # A full final page whose count equals `total` must not trigger one more (empty) request.
        size = BROWSER_USE_ENDPOINTS["sessions"].page_size
        full_page = [{"id": f"a{i}"} for i in range(size)]
        result = _driver().run(
            "sessions",
            [ScriptedResponse(json={"sessions": full_page, "total": size})],
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert result.raised is None
        assert len(result.rows) == size
        assert len(result.requests) == 1

    def test_missing_data_key_is_empty_page(self) -> None:
        # The API envelopes zero rows as a missing/empty array — treat it as the end, not an error.
        result = _driver().run("sessions", [ScriptedResponse(json={})], api_version=BROWSER_USE_API_VERSION_V3)

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_state_saved_after_each_yield(self) -> None:
        # Resume state must advance to the NEXT page and only be saved when more pages remain, so a
        # crash re-yields the last page rather than skipping it.
        size = BROWSER_USE_ENDPOINTS["sessions"].page_size
        pages = [[{"id": f"a{i}"} for i in range(size)], [{"id": "b0"}]]
        result = _driver().run(
            "sessions",
            [ScriptedResponse(json={"sessions": page}) for page in pages],
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert result.raised is None
        # Only the first (full) page has a successor, so exactly one save advancing to page 2.
        assert result.saved_states == [BrowserUseResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "sessions",
            [ScriptedResponse(json={"sessions": [{"id": "p3"}]})],
            resume_state=BrowserUseResumeConfig(page=3),
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert result.raised is None
        assert result.rows == [{"id": "p3"}]
        assert result.params("page") == ["3"]


class TestSessionMessagesFanOut:
    def test_checkpoints_track_fanout_progress(self) -> None:
        result = _driver().run(
            "session_messages",
            [
                ScriptedResponse(json={"sessions": [{"id": "s1"}, {"id": "s2"}]}),
                ScriptedResponse(json={"messages": [{"id": "m1"}, {"id": "m2"}], "hasMore": True}),
                ScriptedResponse(json={"messages": [{"id": "m3"}], "hasMore": False}),
                ScriptedResponse(json={"messages": [{"id": "m9"}], "hasMore": False}),
            ],
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert result.raised is None
        saved = [state.fanout_state for state in result.saved_states]
        # Mid-s1 the checkpoint carries the in-progress cursor so a crash resumes from m2.
        assert {
            "completed": [],
            "current": "/sessions/s1/messages",
            "child_state": {"after": "m2"},
        } in saved
        # The final checkpoint marks both sessions completed.
        assert saved[-1] == {
            "completed": ["/sessions/s1/messages", "/sessions/s2/messages"],
            "current": None,
            "child_state": None,
        }

    def test_resumes_cursor_within_bookmarked_session(self) -> None:
        # A crash mid-s2 leaves completed=[s1] plus s2's `after` cursor; on resume s2 must continue
        # from m8 (not restart) while the already-completed s1 is skipped.
        result = _driver().run(
            "session_messages",
            [
                ScriptedResponse(json={"sessions": [{"id": "s1"}, {"id": "s2"}]}),
                ScriptedResponse(json={"messages": [{"id": "m9"}], "hasMore": False}),
            ],
            resume_state=BrowserUseResumeConfig(
                fanout_state={
                    "completed": ["/sessions/s1/messages"],
                    "current": "/sessions/s2/messages",
                    "child_state": {"after": "m8"},
                }
            ),
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert result.raised is None
        assert [(row["id"], row["sessionId"]) for row in result.rows] == [("m9", "s2")]
        assert result.urls[1].startswith(f"{BROWSER_USE_BASE_URL}/sessions/s2/messages")
        assert result.requests[1].param("after") == "m8"

    def test_legacy_resume_state_restarts_fanout(self) -> None:
        # State saved before the framework migration bookmarked a session id + `after` cursor.
        # It still parses (the dataclass keeps the fields) but restarts the fan-out fresh —
        # merge dedupes the re-pulled rows.
        result = _driver().run(
            "session_messages",
            [
                ScriptedResponse(json={"sessions": [{"id": "s1"}]}),
                ScriptedResponse(json={"messages": [{"id": "m1"}], "hasMore": False}),
            ],
            resume_state=BrowserUseResumeConfig(session_id="s1", after="m0"),
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m1"]
        assert result.requests[1].param("after") is None


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_retries_then_raises(self, _name: str, status: int) -> None:
        result = _driver().run(
            "sessions",
            always(ScriptedResponse(status=status, json={})),
            api_version=BROWSER_USE_API_VERSION_V3,
        )

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1
        assert set(result.paths) == {"/api/v3/sessions"}

    def test_client_error_raises_for_status(self) -> None:
        # A credential error is terminal — no retry, and the message carries the stable
        # "401 Client Error: Unauthorized for url: <base host>" prefix the source's
        # get_non_retryable_errors classifier matches on.
        result = _driver().run(
            "sessions", [ScriptedResponse(status=401, json={})], api_version=BROWSER_USE_API_VERSION_V3
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized for url: https://api.browser-use.com" in str(result.raised)
        assert len(result.requests) == 1


class TestSessionHardening:
    # Every Browser Use endpoint returns free-form agent content — session titles and
    # session_messages.data hold whatever a user's agent typed or browsed, which the name-based
    # scrubbers can't recognise — so both the export path and the credential probe must build
    # their tracked session with capture=False. And the API key rides in the custom
    # X-Browser-Use-API-Key header, which requests preserves across a cross-host 3xx (it only
    # strips Authorization), so both must also pin allow_redirects=False. A regression that drops
    # either flag re-opens the corresponding leak.
    def test_source_session_disables_capture_and_redirects(self) -> None:
        result = _driver().run(
            "sessions", [ScriptedResponse(json={"sessions": []})], api_version=BROWSER_USE_API_VERSION_V3
        )

        assert result.raised is None
        kwargs = result.session_options[0]
        assert kwargs["capture"] is False
        assert kwargs["allow_redirects"] is False
        assert kwargs["redact_values"] == ("bu_test",)

    def test_validate_credentials_disables_capture_and_redirects(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("bu_test", BROWSER_USE_API_VERSION_V3)

        kwargs = network.session_options[0]
        assert kwargs["capture"] is False
        assert kwargs["allow_redirects"] is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("sessions", ["id"], "createdAt"),
            ("browser_sessions", ["id"], "startedAt"),
            ("profiles", ["id"], "createdAt"),
            ("workspaces", ["id"], "createdAt"),
            ("session_messages", ["sessionId", "id"], "createdAt"),
        ]
    )
    def test_primary_keys_and_partition(self, endpoint: str, primary_keys: list[str], partition_key: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={})], api_version=BROWSER_USE_API_VERSION_V3)

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"


class TestVersionRouting:
    @parameterized.expand(
        [
            (BROWSER_USE_API_VERSION_V3, "sessions", "sessions", {"total": 1}),
            (BROWSER_USE_API_VERSION_V3, "browser_sessions", "items", {"totalItems": 1}),
            (BROWSER_USE_API_VERSION_V4, "sessions", "sessions", {"hasMore": False}),
            (BROWSER_USE_API_VERSION_V4, "runs", "runs", {"hasMore": False}),
            (BROWSER_USE_API_VERSION_V4, "browser_sessions", "items", {"totalItems": 1}),
            (BROWSER_USE_API_VERSION_V4, "profiles", "items", {"totalItems": 1}),
        ]
    )
    def test_request_hits_versioned_base_url(
        self, version: str, endpoint: str, data_key: str, extra: dict[str, Any]
    ) -> None:
        # The pinned version is the URL path segment, so each version's request must go to
        # /api/<version>/... — the whole point of pinning. A v4 endpoint left on the v3 base (or
        # vice versa) would silently hit the wrong API.
        result = _driver().run(
            endpoint, [ScriptedResponse(json={data_key: [{"id": "a"}], **extra})], api_version=version
        )

        assert result.raised is None
        assert result.urls[0].startswith(f"https://api.browser-use.com/api/{version}/")


class TestV4KeysetPagination:
    @parameterized.expand([("sessions", "sessions"), ("runs", "runs")])
    def test_keyset_pages_aggregated_and_terminates(self, endpoint: str, data_key: str) -> None:
        # v4 sessions/runs use keyset paging: `limit` + a `cursor` echoed back as `nextCursor`, with
        # `hasMore` as the stop signal. Guards that the cursor advances from the body (not the row
        # id), that `limit` is sent, and that hasMore=false terminates.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={data_key: [{"id": "a"}], "nextCursor": "c1", "hasMore": True}),
                ScriptedResponse(json={data_key: [{"id": "b"}], "nextCursor": "c2", "hasMore": True}),
                ScriptedResponse(json={data_key: [{"id": "c"}], "nextCursor": None, "hasMore": False}),
            ],
            api_version=BROWSER_USE_API_VERSION_V4,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert result.params("limit") == ["100"] * 3
        assert result.params("cursor") == [None, "c1", "c2"]

    def test_keyset_saves_next_cursor_only_while_more_remain(self) -> None:
        # The checkpoint advances to the body's nextCursor and saves only when a page follows, so a
        # crash re-yields the last page (merge dedupes) rather than skipping it.
        result = _driver().run(
            "sessions",
            [
                ScriptedResponse(json={"sessions": [{"id": "a"}], "nextCursor": "c1", "hasMore": True}),
                ScriptedResponse(json={"sessions": [{"id": "b"}], "hasMore": False}),
            ],
            api_version=BROWSER_USE_API_VERSION_V4,
        )

        assert result.raised is None
        assert result.saved_states == [BrowserUseResumeConfig(cursor="c1")]

    def test_keyset_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "sessions",
            [ScriptedResponse(json={"sessions": [{"id": "x"}], "hasMore": False})],
            resume_state=BrowserUseResumeConfig(cursor="c9"),
            api_version=BROWSER_USE_API_VERSION_V4,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["x"]
        assert result.params("cursor") == ["c9"]


class TestV4SourceResponse:
    @parameterized.expand(
        [
            ("sessions", ["sessionId"], "createdAt"),
            ("runs", ["id"], "createdAt"),
            ("browser_sessions", ["id"], "startedAt"),
            ("profiles", ["id"], "createdAt"),
        ]
    )
    def test_primary_keys_and_partition(self, endpoint: str, primary_keys: list[str], partition_key: str) -> None:
        # v4 sessions key on `sessionId` (not `id`) — merge would collapse rows if this regressed.
        result = _driver().run(endpoint, [ScriptedResponse(json={})], api_version=BROWSER_USE_API_VERSION_V4)

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
