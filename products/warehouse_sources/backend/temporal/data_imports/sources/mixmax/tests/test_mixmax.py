import dataclasses
from typing import Any

from unittest import mock

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


class TestFanout:
    @parameterized.expand(
        [
            (
                "live_feed_events",
                [
                    ScriptedResponse(json={"results": [{"_id": "m1"}], "next": "cur2", "hasNext": True}),
                    ScriptedResponse(
                        json={"results": [{"_id": "e1", "type": "opened"}, {"_id": "e2", "type": "replied"}]}
                    ),
                    ScriptedResponse(json={"results": [{"_id": "m2&limit=1"}], "hasNext": False}),
                    ScriptedResponse(status=404, json={}),
                ],
                [
                    {"_id": "e1", "type": "opened", "message_id": "m1"},
                    {"_id": "e2", "type": "replied", "message_id": "m1"},
                ],
                ["/v1/livefeed", "/v1/livefeed/events", "/v1/livefeed", "/v1/livefeed/events"],
                [
                    {"limit": ("100",)},
                    {"messageId": ("m1",), "wasSentViaMixmax": ("true",)},
                    {"limit": ("100",), "next": ("cur2",)},
                    {"messageId": ("m2&limit=1",), "wasSentViaMixmax": ("true",)},
                ],
            ),
            (
                "team_members",
                [
                    ScriptedResponse(json={"results": [{"_id": "t1"}, {"_id": "t/2"}], "hasNext": False}),
                    ScriptedResponse(
                        json={
                            "results": [
                                {"memberId": "mb1", "userId": "u1", "role": "admin", "name": "Jane Roe"},
                                {"memberId": "mb2", "email": "invitee@example.com", "role": "member"},
                            ]
                        }
                    ),
                    ScriptedResponse(status=404, json={}),
                ],
                [
                    {"memberId": "mb1", "userId": "u1", "role": "admin", "name": "Jane Roe", "team_id": "t1"},
                    {"memberId": "mb2", "email": "invitee@example.com", "role": "member", "team_id": "t1"},
                ],
                ["/v1/teams", "/v1/teams/t1/members", "/v1/teams/t%2F2/members"],
                [
                    {"limit": ("100",)},
                    {"expand": ("members.userId",)},
                    {"expand": ("members.userId",)},
                ],
            ),
        ]
    )
    def test_fetches_children_per_parent_and_skips_missing_parents(
        self,
        endpoint: str,
        responses: list[ScriptedResponse],
        expected_rows: list[dict[str, Any]],
        expected_paths: list[str],
        expected_queries: list[dict[str, tuple[str, ...]]],
    ) -> None:
        result = _driver().run(endpoint, responses)

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.paths == expected_paths
        assert [dict(request.query) for request in result.requests] == expected_queries


def _recipients(prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"_id": f"{prefix}{i}", "state": "active"} for i in range(count)]


class TestSequenceRecipients:
    @parameterized.expand(
        [
            # A short page ends the first sequence before the offset ceiling.
            ("short_last_page", [2, 1], ["0", "2"]),
            # Two full pages reach `offset + limit == 4`; asking for more would return 400.
            ("stops_at_offset_ceiling", [2, 2], ["0", "2"]),
            ("empty_sequence", [0], ["0"]),
        ]
    )
    def test_pages_each_sequence_by_offset(
        self, _name: str, first_sequence_pages: list[int], expected_first_offsets: list[str]
    ) -> None:
        config = dataclasses.replace(MIXMAX_ENDPOINTS["sequence_recipients"], child_page_size=2, child_max_offset=4)
        first_sequence = [_recipients(f"p{page}r", size) for page, size in enumerate(first_sequence_pages)]
        responses = [
            ScriptedResponse(json={"results": [{"_id": "s1"}, {"_id": "s2"}], "hasNext": False}),
            *(ScriptedResponse(json=page) for page in first_sequence),
            ScriptedResponse(json=[{"_id": "only", "state": "completed"}]),
        ]

        with mock.patch.dict(MIXMAX_ENDPOINTS, {"sequence_recipients": config}):
            result = _driver().run("sequence_recipients", responses)

        assert result.raised is None
        assert result.rows == [
            *({**row, "sequence_id": "s1"} for page in first_sequence for row in page),
            {"_id": "only", "state": "completed", "sequence_id": "s2"},
        ]
        assert result.paths == [
            "/v1/sequences",
            *["/v1/sequences/s1/recipients/"] * len(first_sequence_pages),
            "/v1/sequences/s2/recipients/",
        ]
        # The offset starts again at 0 for the next sequence.
        assert result.params("offset") == [None, *expected_first_offsets, "0"]
        assert set(result.params("limit")[1:]) == {"2"}
        assert set(result.params("sortBy")[1:]) == {"email"}
        assert set(result.params("sortDesc")[1:]) == {"false"}

    def test_skips_sequence_deleted_after_listing(self) -> None:
        result = _driver().run(
            "sequence_recipients",
            [
                ScriptedResponse(json={"results": [{"_id": "gone"}], "hasNext": False}),
                ScriptedResponse(status=404, json={"message": "Sequence not found"}),
            ],
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/v1/sequences", "/v1/sequences/gone/recipients/"]


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
