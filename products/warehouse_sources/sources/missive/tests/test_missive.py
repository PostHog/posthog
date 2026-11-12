from datetime import UTC, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.sources.missive._config import MissiveSourceConfig
from products.warehouse_sources.sources.missive.missive import MissiveResumeConfig
from products.warehouse_sources.sources.missive.source import MissiveSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)

TOKEN = "missive_pat-test-token"


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # The proxy env vars of a sandbox rewrite the recorded request host.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)


def _run(schema: str, script: Any, **inputs: Any) -> DriveResult:
    return SourceDriver(MissiveSource(), MissiveSourceConfig(api_token=TOKEN)).run(schema, script, **inputs)


def _rows(key: str, field: str, stamps: list[int], prefix: str = "r") -> ScriptedResponse:
    return ScriptedResponse(
        json={key: [{"id": f"{prefix}{stamp}-{i}", field: stamp} for i, stamp in enumerate(stamps)]}
    )


def _conversations(stamps: list[tuple[str, int]]) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "conversations": [{"id": conversation_id, "last_activity_at": stamp} for conversation_id, stamp in stamps]
        }
    )


class TestUntilPagination:
    def test_walks_pages_backwards_and_drops_rows_repeated_at_the_boundary(self) -> None:
        # `until` is inclusive, so the second page repeats the two rows at the oldest timestamp of the first.
        first = [{"id": f"a{i}", "last_activity_at": 1000 - i} for i in range(48)] + [
            {"id": "b1", "last_activity_at": 900},
            {"id": "b2", "last_activity_at": 900},
        ]
        second = [
            {"id": "b1", "last_activity_at": 900},
            {"id": "b2", "last_activity_at": 900},
            {"id": "c1", "last_activity_at": 800},
        ]
        result = _run(
            "conversations",
            [ScriptedResponse(json={"conversations": first}), ScriptedResponse(json={"conversations": second})],
        )

        assert result.raised is None
        assert result.params("until") == [None, "900"]
        assert result.params("all") == ["true", "true"]
        assert result.params("limit") == ["50", "50"]
        ids = [row["id"] for row in result.rows]
        assert len(ids) == len(set(ids)) == 51
        assert ids[-1] == "c1"
        assert result.final_state == MissiveResumeConfig(finished=True)
        assert {TOKEN} <= set(result.session_options[0]["redact_values"])

    @parameterized.expand(
        [
            ("conversations_end", "conversations", [None]),
            ("tasks_continue", "tasks", [None, "499"]),
        ]
    )
    def test_full_page_that_shares_one_timestamp(
        self, _name: str, schema: str, expected_until: list[str | None]
    ) -> None:
        result = _run(
            schema,
            [_rows(schema, "last_activity_at", [500] * 50), _rows(schema, "last_activity_at", [400], prefix="old")],
        )

        assert result.raised is None
        assert result.params("until") == expected_until

    @parameterized.expand(
        [
            ("incremental_stops_at_watermark", True, 1, "desc"),
            ("full_refresh_reads_every_page", False, 2, None),
        ]
    )
    def test_incremental_walk_stops_after_the_page_that_reaches_the_watermark(
        self, _name: str, incremental: bool, expected_requests: int, expected_sort: str | None
    ) -> None:
        result = _run(
            "conversations",
            [
                _rows("conversations", "last_activity_at", list(range(1049, 999, -1))),
                _rows("conversations", "last_activity_at", [999]),
            ],
            incremental_field="last_activity_at",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=1020,
        )

        assert result.raised is None
        assert len(result.requests) == expected_requests
        assert result.response is not None and result.response.sort_mode == expected_sort

    def test_resume_starts_at_the_saved_until_and_skips_rows_already_read(self) -> None:
        result = _run(
            "conversations",
            [_conversations([("seen", 700), ("new", 700), ("older", 650)])],
            resume_state=MissiveResumeConfig(until=700, seen_ids=["seen"]),
        )

        assert result.params("until") == ["700"]
        assert [row["id"] for row in result.rows] == ["new", "older"]


class TestConversationFanOut:
    def test_reads_every_conversation_and_tags_rows_with_the_conversation(self) -> None:
        result = _run(
            "messages",
            route(
                {
                    "/conversations/c1/messages": [
                        _rows("messages", "delivered_at", list(range(110, 100, -1)), prefix="m"),
                        _rows("messages", "delivered_at", [101, 90], prefix="m"),
                    ],
                    # A conversation merged or deleted after it was listed.
                    "/conversations/c2/messages": [ScriptedResponse(status=404, json={"error": "Not found"})],
                    "/conversations": [_conversations([("c1", 200), ("c2", 150)])],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/conversations",
            "/v1/conversations/c1/messages",
            "/v1/conversations/c1/messages",
            "/v1/conversations/c2/messages",
        ]
        assert result.params("until") == [None, None, "101", None]
        assert len(result.rows) == 12
        assert {row["conversation_id"] for row in result.rows} == {"c1"}
        assert result.response is not None and result.response.sort_mode is None
        assert result.final_state == MissiveResumeConfig(finished=True)

    def test_incremental_skips_quiet_conversations_and_stops_each_walk_at_the_watermark(self) -> None:
        result = _run(
            "comments",
            route(
                {
                    "/conversations/active/comments": [
                        _rows("comments", "created_at", list(range(320, 310, -1)), prefix="new"),
                    ],
                    "/conversations": [_conversations([("active", 400), ("quiet", 250)])],
                }
            ),
            incremental_field="created_at",
            db_incremental_field_last_value=315,
        )

        assert result.raised is None
        assert result.paths == ["/v1/conversations", "/v1/conversations/active/comments"]

    def test_resume_finishes_the_open_conversation_before_listing_the_rest(self) -> None:
        result = _run(
            "posts",
            route(
                {
                    "/conversations/c2/posts": [_rows("posts", "created_at", [40], prefix="p")],
                    "/conversations/c3/posts": [_rows("posts", "created_at", [30], prefix="q")],
                    "/conversations": [_conversations([("c1", 200), ("c3", 150)])],
                }
            ),
            resume_state=MissiveResumeConfig(
                until=300, seen_ids=["c0"], done_parent_ids=["c1"], child_parent_id="c2", child_until=50
            ),
        )

        assert result.raised is None
        assert result.paths == ["/v1/conversations/c2/posts", "/v1/conversations", "/v1/conversations/c3/posts"]
        assert result.params("until") == ["50", "300", None]
        assert [row["conversation_id"] for row in result.rows] == ["c2", "c3"]
        assert result.final_state == MissiveResumeConfig(finished=True)

    def test_stages_the_position_inside_a_conversation_before_its_page_is_handed_over(self) -> None:
        result = _run(
            "messages",
            route(
                {
                    "/conversations/c1/messages": [
                        _rows("messages", "delivered_at", list(range(110, 100, -1)), prefix="m"),
                        _rows("messages", "delivered_at", [95], prefix="m"),
                    ],
                    "/conversations": [_conversations([("c1", 200)])],
                }
            ),
        )

        assert result.committed_states[0] == MissiveResumeConfig(
            child_parent_id="c1", child_until=101, child_seen_ids=["m101-9"]
        )
        assert result.committed_states[1] == MissiveResumeConfig(done_parent_ids=["c1"])


class TestContactBookFanOut:
    @parameterized.expand(
        [
            ("full_refresh", False, None, [None, None]),
            ("incremental_int_watermark", True, 1700000000, ["1700000000", "1700000000"]),
            (
                "incremental_datetime_watermark",
                True,
                datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
                ["1700000000", "1700000000"],
            ),
        ]
    )
    def test_contacts_walk_each_book_and_filter_on_modification_time(
        self, _name: str, incremental: bool, watermark: Any, expected_since: list[str | None]
    ) -> None:
        full_page = {"contacts": [{"id": f"k{i}", "contact_book": "book1"} for i in range(200)]}
        result = _run(
            "contacts",
            route(
                {
                    "/contact_books": [ScriptedResponse(json={"contact_books": [{"id": "book1"}]})],
                    "/contacts": [
                        ScriptedResponse(json=full_page),
                        ScriptedResponse(json={"contacts": [{"id": "gone", "deleted": True}]}),
                    ],
                }
            ),
            incremental_field="modified_at",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        contact_requests = [request for request in result.requests if request.path == "/v1/contacts"]
        assert [request.param("offset") for request in contact_requests] == ["0", "200"]
        assert [request.param("contact_book") for request in contact_requests] == ["book1", "book1"]
        assert [request.param("modified_since") for request in contact_requests] == expected_since
        assert [request.param("include_deleted") for request in contact_requests] == (
            ["true", "true"] if incremental else [None, None]
        )
        # A deleted contact comes back with only its id, so the book is filled in from the parent.
        assert result.rows[-1] == {"id": "gone", "deleted": True, "modified_at": None, "contact_book": "book1"}

    def test_contact_groups_read_each_kind_and_record_it_on_the_row(self) -> None:
        result = _run(
            "contact_groups",
            route(
                {
                    "/contact_books": [ScriptedResponse(json={"contact_books": [{"id": "book1"}]})],
                    "/contact_groups": [
                        ScriptedResponse(json={"contact_groups": [{"id": "g1", "name": "VIPs"}]}),
                        ScriptedResponse(json={"contact_groups": [{"id": "o1", "name": "Acme"}]}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "g1", "name": "VIPs", "kind": "group", "contact_book": "book1"},
            {"id": "o1", "name": "Acme", "kind": "organization", "contact_book": "book1"},
        ]


class TestOffsetPagination:
    def test_walks_offsets_to_the_short_page(self) -> None:
        result = _run(
            "users",
            [
                ScriptedResponse(json={"users": [{"id": f"u{i}"} for i in range(200)]}),
                ScriptedResponse(json={"users": [{"id": "last"}]}),
            ],
        )

        assert result.raised is None
        assert result.params("offset") == ["0", "200"]
        assert result.params("limit") == ["200", "200"]
        assert len(result.rows) == 201
        assert result.requests[0].headers["authorization"] == f"Bearer {TOKEN}"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {"organizations": []}, True, None),
            ("bad_token", 401, {"error": "Unauthorized"}, False, "rejected"),
            ("no_api_plan", 403, {"error": "Forbidden"}, False, "Productive plan"),
            ("server_error", 500, {"error": "Oops"}, False, "unexpected status: 500"),
        ]
    )
    def test_maps_the_probe_status_to_a_message(
        self, _name: str, status: int, body: dict[str, Any], expected_valid: bool, expected_message: str | None
    ) -> None:
        responses = [ScriptedResponse(status=status, json=body)] * (4 if status >= 500 else 1)
        with scripted_network(responses) as network:
            valid, message = MissiveSource().validate_credentials(MissiveSourceConfig(api_token=TOKEN), team_id=1)

        assert valid is expected_valid
        if expected_message is None:
            assert message is None
        else:
            assert message is not None and expected_message in message
        assert network.requests_log[0].url == "https://public.missiveapp.com/v1/organizations?limit=1"
