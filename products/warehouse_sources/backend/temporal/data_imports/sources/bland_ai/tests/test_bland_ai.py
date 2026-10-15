import json
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.bland_ai import (
    BASE_URL,
    PAGE_SIZE,
    SMS_PAGE_SIZE,
    BlandAIResumeConfig,
    _format_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.source import BlandAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blandai import (
    BlandAISourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(BlandAISource(), BlandAISourceConfig(api_key="key"))


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("none", None, None),
            # A naive watermark is stamped UTC so the server-side filter is unambiguous.
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05+00:00"),
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05+00:00"),
            ("date", date(2026, 1, 2), "2026-01-02"),
            ("iso_string", "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00"),
        ]
    )
    def test_format_start_date(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False), ("error", 500, False)]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].url == f"{BASE_URL}/v1/calls?limit=1"
        assert network.requests_log[0].headers["authorization"] == "key"
        assert network.session_options[0]["redact_values"] == ("key",)


class TestCallsPagination:
    def test_paginates_by_offset_until_total_count(self) -> None:
        page_one = [{"call_id": f"c{i}", "created_at": "2026-01-01T00:00:00+00:00"} for i in range(PAGE_SIZE)]
        page_two = [{"call_id": "clast", "created_at": "2026-01-02T00:00:00+00:00"}]
        result = _driver().run(
            "calls",
            [
                ScriptedResponse(json={"total_count": PAGE_SIZE + 1, "count": PAGE_SIZE, "calls": page_one}),
                ScriptedResponse(json={"total_count": PAGE_SIZE + 1, "count": 1, "calls": page_two}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1]["call_id"] == "clast"
        # Reaching total_count terminates without requesting a third page.
        assert len(result.requests) == 2
        assert result.requests[0].path == "/v1/calls"
        assert result.params("from") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Ascending creation order so index offsets stay stable while new calls append.
        assert result.requests[0].param("ascending") == "true"
        assert result.requests[0].param("sort_by") == "created_at"


class TestCallTranscripts:
    def test_hydrates_each_call_and_injects_parent_keys(self) -> None:
        result = _driver().run(
            "call_transcripts",
            [
                ScriptedResponse(
                    json={
                        "total_count": 2,
                        "count": 2,
                        "calls": [
                            {"call_id": "c1", "created_at": "2026-01-01T00:00:00+00:00"},
                            {"call_id": "c2", "created_at": "2026-01-02T00:00:00+00:00"},
                        ],
                    }
                ),
                ScriptedResponse(
                    json={
                        "call_id": "c1",
                        "transcripts": [
                            {"id": 1, "text": "hello", "user": "assistant", "created_at": "2026-01-01T00:00:01+00:00"},
                            {"id": 2, "text": "hi", "user": "user", "created_at": "2026-01-01T00:00:05+00:00"},
                        ],
                    }
                ),
                # A call with no transcripts (e.g. unanswered) must not break the batch.
                ScriptedResponse(json={"call_id": "c2", "transcripts": None}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        # Rows carry the parent call id (composite primary key) and the parent's creation time
        # (the incremental/partition field — utterance timestamps aren't monotonic across calls).
        assert all(row["call_id"] == "c1" for row in result.rows)
        assert all(row["call_created_at"] == "2026-01-01T00:00:00+00:00" for row in result.rows)
        assert result.rows[0]["text"] == "hello"
        # One list request plus one hydration request per listed call.
        assert result.paths == ["/v1/calls", "/v1/calls/c1", "/v1/calls/c2"]

    def test_old_format_resume_state_restarts_fanout_under_saved_filter(self) -> None:
        saved_filter = "2026-01-05T00:00:00+00:00"
        # State saved before fanout_state existed (offset-only): the fan-out restarts from the top
        # but keeps the frozen filter so it walks the same result set (merge dedupes re-yields).
        result = _driver().run(
            "call_transcripts",
            [
                ScriptedResponse(
                    json={
                        "total_count": 1,
                        "count": 1,
                        "calls": [{"call_id": "c1", "created_at": "2026-01-05T00:00:00+00:00"}],
                    }
                ),
                ScriptedResponse(json={"call_id": "c1", "transcripts": [{"id": 1}]}),
            ],
            resume_state=BlandAIResumeConfig(offset=5, start_date=saved_filter),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 7, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.requests[0].param("from") == "0"
        assert result.requests[0].param("start_date") == saved_filter


class TestPathways:
    @parameterized.expand(
        [
            # Bare list of pathway objects.
            ("bare_list", [{"id": "p1"}, {"id": "p2"}], ["p1", "p2"]),
            # Wrapped list variants.
            ("wrapped_pathways", {"pathways": [{"id": "p1"}]}, ["p1"]),
            ("wrapped_data", {"data": [{"id": "p1"}]}, ["p1"]),
            # A single bare object (the shape the docs' response example shows).
            ("single_object", {"id": "p1", "name": "Demo", "nodes": []}, ["p1"]),
        ]
    )
    def test_normalizes_response_shapes(self, _name: str, api_response: Any, expected_ids: list[str]) -> None:
        result = _driver().run("pathways", [ScriptedResponse(json=api_response)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        # A single unordered page on a full-refresh-only endpoint.
        assert result.paths == ["/v1/pathway"]


def _conversations_page(
    ids: list[str], total_pages: int, created_at: str = "2026-01-01T00:00:00.000Z"
) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": [{"id": i, "created_at": created_at} for i in ids],
            "errors": None,
            "extra": {"pagination": {"totalItems": 0, "totalPages": total_pages, "currentPage": 1, "pageSize": 100}},
        }
    )


class TestSmsConversations:
    def test_paginates_by_page_number_until_total_pages(self) -> None:
        result = _driver().run("sms_conversations", [_conversations_page(["v1"], 2), _conversations_page(["v2"], 2)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["v1", "v2"]
        # Reaching totalPages terminates without paying for an extra empty page.
        assert len(result.requests) == 2
        assert result.requests[0].path == "/v1/sms/conversations"
        assert result.params("page") == ["1", "2"]
        assert result.params("pageSize") == [str(SMS_PAGE_SIZE), str(SMS_PAGE_SIZE)]
        # The endpoint defaults to newest-first; the watermark needs ascending creation order.
        assert result.requests[0].param("sortBy") == "created_at"
        assert result.requests[0].param("sortDir") == "asc"

    def test_resumes_from_saved_page_and_filter(self) -> None:
        saved_filter = "2026-01-05T00:00:00+00:00"
        result = _driver().run(
            "sms_conversations",
            [_conversations_page(["v3"], 3)],
            resume_state=BlandAIResumeConfig(page=3, start_date=saved_filter),
            should_use_incremental_field=True,
            # The checkpointed watermark has advanced past the interrupted run's filter; the
            # resumed run must reuse the saved filter or the saved page points at other rows.
            db_incremental_field_last_value=datetime(2026, 1, 7, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["v3"]
        assert result.requests[0].param("page") == "3"
        assert json.loads(result.requests[0].param("filters") or "null")[0]["value"] == saved_filter


class TestSmsMessages:
    def test_hydrates_each_conversation_and_injects_parent_keys(self) -> None:
        result = _driver().run(
            "sms_messages",
            [
                ScriptedResponse(
                    json={
                        "data": [
                            {"id": "v1", "created_at": "2026-01-01T00:00:00.000Z"},
                            {"id": "v2", "created_at": "2026-01-02T00:00:00.000Z"},
                        ],
                        "extra": {"pagination": {"totalPages": 1}},
                    }
                ),
                ScriptedResponse(
                    json={
                        "data": {
                            "id": "v1",
                            "messages": [
                                {"id": 100001, "message": "hey", "sender": "USER", "status": "delivered"},
                                {"id": 100002, "message": "hi", "sender": "AGENT", "status": "sent"},
                            ],
                        }
                    }
                ),
                # A conversation with no messages yet must not break the batch.
                ScriptedResponse(json={"data": {"id": "v2", "messages": None}}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [100001, 100002]
        # Rows carry the parent conversation id (composite primary key) and the parent's creation
        # time (the incremental/partition field — message timestamps aren't monotonic across
        # conversations).
        assert all(row["conversation_id"] == "v1" for row in result.rows)
        assert all(row["conversation_created_at"] == "2026-01-01T00:00:00.000Z" for row in result.rows)
        assert result.rows[0]["message"] == "hey"
        # One list request plus one hydration request per listed conversation.
        assert result.paths == [
            "/v1/sms/conversations",
            "/v1/sms/conversations/v1",
            "/v1/sms/conversations/v2",
        ]

    def test_checkpoints_fanout_state_with_filter(self) -> None:
        result = _driver().run(
            "sms_messages",
            [
                _conversations_page(["v1"], 1, created_at="2026-01-05T00:00:00.000Z"),
                ScriptedResponse(json={"data": {"id": "v1", "messages": [{"id": 1}]}}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.saved_states
        saved = result.saved_states[-1]
        assert saved.fanout_state["completed"] == ["v1/sms/conversations/v1"]
        assert saved.fanout_state["current"] is None
        assert saved.start_date == "2026-01-05T00:00:00+00:00"


class TestLookupEndpoints:
    @parameterized.expand(
        [
            # The response wrapper key differs per endpoint; a wrong selector silently yields
            # zero rows instead of failing.
            ("inbound_numbers", "v1/inbound", {"inbound_numbers": [{"phone_number": "+15550001111"}]}, "phone_number"),
            ("voices", "v1/voices", {"voices": [{"id": "voice-1", "name": "Karen"}]}, "id"),
        ]
    )
    def test_single_page_lookup_selects_rows(
        self, endpoint: str, path: str, api_response: dict[str, Any], key: str
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=api_response)])

        assert result.raised is None
        assert len(result.rows) == 1
        assert result.rows[0][key] == api_response[endpoint][0][key]
        assert result.paths == [f"/{path}"]


class TestBlandAISourceResponse:
    @parameterized.expand(
        [
            ("calls", ["call_id"], ["created_at"]),
            # The composite key keeps utterances unique table-wide; partitioning uses the parent
            # call's stable creation time.
            ("call_transcripts", ["call_id", "id"], ["call_created_at"]),
            ("pathways", ["id"], None),
            ("sms_conversations", ["id"], ["created_at"]),
            # The composite key keeps messages unique table-wide; partitioning uses the parent
            # conversation's stable creation time.
            ("sms_messages", ["conversation_id", "id"], ["conversation_created_at"]),
            # Small account-level lookups — no partitioning.
            ("inbound_numbers", ["phone_number"], None),
            ("personas", ["id"], None),
            ("voices", ["id"], None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        empty_responses: dict[str, Any] = {
            "calls": {"total_count": 0, "count": 0, "calls": []},
            "call_transcripts": {"total_count": 0, "count": 0, "calls": []},
            "pathways": [],
            "sms_conversations": {"data": [], "extra": {"pagination": {"totalPages": 1}}},
            "sms_messages": {"data": [], "extra": {"pagination": {"totalPages": 1}}},
            "inbound_numbers": {"inbound_numbers": []},
            "personas": {"data": []},
            "voices": {"voices": []},
        }
        result = _driver().run(endpoint, [ScriptedResponse(json=empty_responses[endpoint])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        # Call listings request ascending=true&sort_by=created_at.
        assert response.sort_mode == "asc"
