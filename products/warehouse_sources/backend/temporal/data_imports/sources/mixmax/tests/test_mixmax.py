from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mixmax import MixMaxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.mixmax import (
    MixmaxResumeConfig,
    _build_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import MIXMAX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.source import MixMaxSource


def _driver() -> SourceDriver:
    return SourceDriver(MixMaxSource(), MixMaxSourceConfig(api_key="tok"))


class TestBuildUrl:
    def test_single_object_url_has_no_pagination_params(self) -> None:
        assert _build_url("/users/me", single_object=True) == "https://api.mixmax.com/v1/users/me"


class TestExtractionShapes:
    """The old `_extract_page` heuristic (now `_reshape_row` + the cursor paginator), asserted end to
    end: each body shape produces the same rows and terminates after a single request."""

    @parameterized.expand(
        [
            # Wrapped collection on its last page: hasNext False stops even though `next` echoes a value.
            (
                "wrapped_last_page",
                "sequences",
                {"results": [{"_id": "1"}], "next": "cur2", "hasNext": False},
                [{"_id": "1"}],
            ),
            # `hasNext` missing is treated as no more pages.
            ("wrapped_no_flag", "sequences", {"results": [{"_id": "1"}]}, [{"_id": "1"}]),
            # Empty wrapped page yields no rows.
            ("wrapped_empty", "sequences", {"results": [], "hasNext": False}, []),
            # `/…/me` single-object endpoints return the object directly — one record, no pagination.
            ("single_object", "users", {"_id": "u1", "email": "a@b.com"}, [{"_id": "u1", "email": "a@b.com"}]),
            # A dict-without-results on a defensive collection endpoint maps to one record.
            ("dict_without_results", "appointment_links", {"_id": "x"}, [{"_id": "x"}]),
            # A bare array (defensive) is treated as a full, unpaginated page.
            ("bare_list", "appointment_links", [{"_id": "1"}, {"_id": "2"}], [{"_id": "1"}, {"_id": "2"}]),
        ]
    )
    def test_shape(self, _name: str, endpoint: str, body: Any, expected: list[dict[str, Any]]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == expected
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestPagination:
    def test_walks_cursor_pages_and_checkpoints_after_each_yield(self) -> None:
        next_url = "https://api.mixmax.com/v1/sequences?limit=100&next=cur2"
        result = _driver().run(
            "sequences",
            [
                ScriptedResponse(json={"results": [{"_id": "1"}], "next": "cur2", "hasNext": True}),
                ScriptedResponse(json={"results": [{"_id": "2"}], "hasNext": False}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"_id": "1"}, {"_id": "2"}]
        # The first request starts at the collection. The second carries the next-page cursor.
        assert result.paths == ["/v1/sequences", "/v1/sequences"]
        assert result.params("limit") == ["100", "100"]
        assert result.params("next") == [None, "cur2"]
        assert result.urls[1] == next_url
        # Checkpoint saved only when another page follows, pointing at that next page — so a crash
        # re-yields the last page rather than skipping it.
        assert result.saved_states == [MixmaxResumeConfig(next_url=next_url)]
        assert result.committed_states == [MixmaxResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_cursor(self) -> None:
        resume_url = "https://api.mixmax.com/v1/sequences?limit=100&next=cur2"
        result = _driver().run(
            "sequences",
            [ScriptedResponse(json={"results": [{"_id": "2"}], "hasNext": False})],
            resume_state=MixmaxResumeConfig(next_url=resume_url),
        )

        # The first page is skipped entirely — only the saved cursor's page is fetched.
        assert result.raised is None
        assert result.rows == [{"_id": "2"}]
        assert result.urls == [resume_url]
        assert result.saved_states == []


class TestLiveFeedEventsFanout:
    def test_fetches_events_per_live_feed_message_and_skips_missing_messages(self) -> None:
        result = _driver().run(
            "live_feed_events",
            [
                ScriptedResponse(json={"results": [{"_id": "m1"}], "next": "cur2", "hasNext": True}),
                ScriptedResponse(json={"results": [{"_id": "e1", "type": "opened"}, {"_id": "e2", "type": "replied"}]}),
                ScriptedResponse(json={"results": [{"_id": "m2&limit=1"}], "hasNext": False}),
                ScriptedResponse(status=404, json={}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"_id": "e1", "type": "opened", "message_id": "m1"},
            {"_id": "e2", "type": "replied", "message_id": "m1"},
        ]
        assert result.paths == ["/v1/livefeed", "/v1/livefeed/events", "/v1/livefeed", "/v1/livefeed/events"]
        assert [dict(request.query) for request in result.requests] == [
            {"limit": ("100",)},
            {"messageId": ("m1",), "wasSentViaMixmax": ("true",)},
            {"limit": ("100",), "next": ("cur2",)},
            {"messageId": ("m2&limit=1",), "wasSentViaMixmax": ("true",)},
        ]


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _driver().run(
            "sequences",
            [ScriptedResponse(status=status, json={}), ScriptedResponse(json={"results": [], "hasNext": False})],
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/v1/sequences", "/v1/sequences"]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("sequences", ["_id"]),
            ("messages", ["_id"]),
            ("live_feed", ["uid"]),
            ("appointment_links", ["_id"]),
        ]
    )
    def test_source_response_carries_endpoint_primary_keys(self, endpoint: str, expected_pks: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"results": [], "hasNext": False})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        # Collections arrive newest-first; declared honestly so full-refresh ordering isn't misread.
        assert response.sort_mode == "desc"

    def test_every_endpoint_declares_a_unique_primary_key(self) -> None:
        # A non-unique/empty primary key seeds duplicate rows and makes every merge multi-match (OOM risk).
        for config in MIXMAX_ENDPOINTS.values():
            assert config.primary_keys, f"{config.name} has no primary key"
