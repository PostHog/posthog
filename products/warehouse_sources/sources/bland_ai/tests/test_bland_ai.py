import json
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.bland_ai._config import BlandAISourceConfig
from products.warehouse_sources.sources.bland_ai.bland_ai import (
    ALARM_EVENTS_LIMIT,
    BASE_URL,
    CONTACTS_PAGE_SIZE,
    EVALS_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PAGE_SIZE,
    SMS_PAGE_SIZE,
    BlandAIResumeConfig,
    _format_start_date,
    validate_credentials,
)
from products.warehouse_sources.sources.bland_ai.source import BlandAISource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(BlandAISource(), BlandAISourceConfig(api_key="key"))


def _wrap(selector: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    body: Any = rows
    for key in reversed(selector.split(".")):
        body = {key: body}
    return body


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

    @parameterized.expand(
        [
            ("bare_list", lambda events: events),
            ("wrapped_events", lambda events: {"events": events}),
            ("wrapped_data", lambda events: {"data": events, "errors": None}),
        ]
    )
    def test_call_events_hydrates_each_call_and_numbers_events(self, _name: str, wrap: Any) -> None:
        events = [
            {"level": "queue", "message": "Call queued", "category": "info", "timestamp": "2026-01-01T00:00:00Z"},
            {"level": "call", "message": "LLM 420ms", "category": "performance", "timestamp": "2026-01-01T00:00:02Z"},
        ]
        result = _driver().run(
            "call_events",
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
                ScriptedResponse(json=wrap(events)),
                ScriptedResponse(json=wrap([])),
            ],
        )

        assert result.raised is None
        # Events carry no id; the position in the stream completes the composite key.
        assert [(row["call_id"], row["event_index"]) for row in result.rows] == [("c1", 0), ("c1", 1)]
        assert [row["category"] for row in result.rows] == ["info", "performance"]
        assert all(row["call_created_at"] == "2026-01-01T00:00:00+00:00" for row in result.rows)
        assert result.paths == ["/v1/calls", "/v1/event_stream/c1", "/v1/event_stream/c2"]

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
            ("inbound_numbers", "v1/inbound", "inbound_numbers", {"phone_number": "+15550001111"}, "phone_number"),
            ("voices", "v1/voices", "voices", {"id": "voice-1", "name": "Karen"}, "id"),
            ("web_agents", "v1/agents", "agents", {"agent_id": "agent-1", "voice": "Karen"}, "agent_id"),
            (
                "agent_test_scenarios",
                "v1/agent-testing/scenarios",
                "scenarios",
                {"id": "scn-1", "name": "Booking flow"},
                "id",
            ),
            ("alarms", "v1/alarms", "data.alarms", {"id": "alarm-1", "metric_type": "latency"}, "id"),
            # The endpoint returns 50 events unless asked for its maximum.
            (
                "alarm_events",
                "v1/alarms/history",
                "data.events",
                {"id": "evt-1", "new_state": "NORMAL"},
                "id",
                str(ALARM_EVENTS_LIMIT),
            ),
        ]
    )
    def test_single_page_lookup_selects_rows(
        self,
        endpoint: str,
        path: str,
        selector: str,
        row: dict[str, Any],
        key: str,
        expected_limit: str | None = None,
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=_wrap(selector, [row]))])

        assert result.raised is None
        assert len(result.rows) == 1
        assert result.rows[0][key] == row[key]
        assert result.paths == [f"/{path}"]
        assert result.params("limit") == [expected_limit]


class TestPaginatedLists:
    @parameterized.expand(
        [
            # Offset pagination stops once `total_count` rows are read, without an extra request.
            (
                "agent_test_runs",
                [
                    ScriptedResponse(
                        json={
                            "runs": [{"id": f"run{i}"} for i in range(MAX_PAGE_SIZE)],
                            "total_count": MAX_PAGE_SIZE + 1,
                        }
                    ),
                    ScriptedResponse(json={"runs": [{"id": "runlast"}], "total_count": MAX_PAGE_SIZE + 1}),
                ],
                MAX_PAGE_SIZE + 1,
                "offset",
                ["0", str(MAX_PAGE_SIZE)],
                "/v1/agent-testing/runs",
            ),
            # The total sits under `pagination`, not at the root of the body. A full last page
            # ends the walk only through the total.
            (
                "contacts",
                [
                    ScriptedResponse(
                        json={
                            "data": [{"id": f"ct{page}-{i}"} for i in range(CONTACTS_PAGE_SIZE)],
                            "pagination": {"total": 2 * CONTACTS_PAGE_SIZE},
                            "errors": None,
                        }
                    )
                    for page in range(2)
                ],
                2 * CONTACTS_PAGE_SIZE,
                "offset",
                ["0", str(CONTACTS_PAGE_SIZE)],
                "/v1/contacts",
                CONTACTS_PAGE_SIZE,
            ),
            # `data.pagination.total_pages` ends the walk without an extra empty page.
            (
                "outcomes",
                [
                    ScriptedResponse(
                        json={"data": {"dispositions": [{"id": "o1"}], "pagination": {"page": 1, "total_pages": 2}}}
                    ),
                    ScriptedResponse(
                        json={"data": {"dispositions": [{"id": "o2"}], "pagination": {"page": 2, "total_pages": 2}}}
                    ),
                ],
                2,
                "page",
                ["1", "2"],
                "/v1/dispositions",
            ),
            # `data.total` counts items, not pages, so the walk ends on the first empty page.
            (
                "knowledge_bases",
                [
                    ScriptedResponse(json={"data": {"kbs": [{"id": "kb1"}, {"id": "kb2"}], "total": 3}}),
                    ScriptedResponse(json={"data": {"kbs": [{"id": "kb3"}], "total": 3}}),
                    ScriptedResponse(json={"data": {"kbs": [], "total": 3}}),
                ],
                3,
                "page",
                ["1", "2", "3"],
                "/v1/knowledge",
            ),
        ]
    )
    def test_walks_pages_to_the_end(
        self,
        endpoint: str,
        responses: list[ScriptedResponse],
        expected_rows: int,
        page_param: str,
        expected_pages: list[str],
        path: str,
        page_size: int = MAX_PAGE_SIZE,
    ) -> None:
        result = _driver().run(endpoint, responses)

        assert result.raised is None
        assert len(result.rows) == expected_rows
        assert result.params(page_param) == expected_pages
        assert result.params("limit") == [str(page_size)] * len(expected_pages)
        assert set(result.paths) == {path}

    def test_contacts_resume_from_saved_offset(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json={"data": [{"id": "ct401"}], "pagination": {"total": 401}})],
            resume_state=BlandAIResumeConfig(offset=400),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ct401"]
        assert result.params("offset") == ["400"]


def _triage_page(ids: list[str], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": {"items": [{"id": i} for i in ids], "next_cursor": next_cursor}, "errors": None}
    )


class TestTriageIssues:
    @parameterized.expand(
        [
            ("fresh", None, [None, "i2"]),
            ("resumed", BlandAIResumeConfig(cursor="i0"), ["i0", "i2"]),
        ]
    )
    def test_walks_keyset_pages_in_creation_order(
        self, _name: str, resume_state: BlandAIResumeConfig | None, expected_cursors: list[str | None]
    ) -> None:
        result = _driver().run(
            "triage_issues",
            [_triage_page(["i1", "i2"], "i2"), _triage_page(["i3"], None)],
            resume_state=resume_state,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["i1", "i2", "i3"]
        assert result.paths == ["/v1/triage/issues", "/v1/triage/issues"]
        assert result.params("cursor") == expected_cursors
        # The default sort is last_activity_at, which moves while the walk pages.
        assert result.params("sort") == ["created_at"] * 2
        assert result.params("order") == ["asc"] * 2


class TestWidgetThreads:
    def test_fans_out_over_widgets_and_pages_each_one(self) -> None:
        result = _driver().run(
            "widget_threads",
            [
                ScriptedResponse(json={"status": 200, "data": [{"id": "w1"}, {"id": "w2"}], "errors": None}),
                ScriptedResponse(
                    json={
                        "data": {
                            "threads": [
                                {"id": "t1", "created_at": "2026-01-01T00:00:00Z", "messages": [{"id": "m1"}]},
                            ],
                            "total": 1,
                        }
                    }
                ),
                ScriptedResponse(json={"data": {"threads": [], "total": 1}}),
                # A widget with no threads yet must not break the batch.
                ScriptedResponse(json={"data": {"threads": [], "total": 0}}),
            ],
        )

        assert result.raised is None
        # Thread ids aren't documented as globally unique, so the parent id must reach every row.
        assert [(row["widget_id"], row["id"]) for row in result.rows] == [("w1", "t1")]
        assert result.rows[0]["messages"] == [{"id": "m1"}]
        assert result.paths == [
            "/v1/widgets",
            "/v1/widget/w1/threads",
            "/v1/widget/w1/threads",
            "/v1/widget/w2/threads",
        ]
        # The second widget starts again at page 1.
        assert result.params("page") == [None, "1", "2", "1"]


def _audit_page(ids: list[str], total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {
                "events": [{"id": i, "created_at": "2026-01-01T00:00:00.000Z"} for i in ids],
                "total_pages": total_pages,
            },
            "errors": None,
        }
    )


class TestAuditLogs:
    @parameterized.expand(
        [
            ("full_refresh", False, None, None),
            ("incremental", True, datetime(2026, 1, 5, tzinfo=UTC), "2026-01-05T00:00:00+00:00"),
            # The first incremental run has no watermark yet, so it reads the whole log.
            ("incremental_first_run", True, None, None),
        ]
    )
    def test_filters_on_watermark_and_stops_at_total_pages(
        self, _name: str, incremental: bool, last_value: datetime | None, expected_filter: str | None
    ) -> None:
        result = _driver().run(
            "audit_logs",
            [_audit_page(["e1"], 2), _audit_page(["e2"], 2)],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e1", "e2"]
        assert result.paths == ["/v1/audit-logs", "/v1/audit-logs"]
        assert result.params("page") == ["1", "2"]
        assert result.params("page_size") == [str(MAX_PAGE_SIZE)] * 2
        assert result.params("created_after") == [expected_filter] * 2

    def test_resumes_from_saved_page_and_filter(self) -> None:
        saved_filter = "2026-01-05T00:00:00+00:00"
        result = _driver().run(
            "audit_logs",
            [_audit_page(["e3"], 3)],
            resume_state=BlandAIResumeConfig(page=3, start_date=saved_filter),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 7, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e3"]
        assert result.requests[0].param("page") == "3"
        assert result.requests[0].param("created_after") == saved_filter


class TestPathwayVersions:
    def test_fans_out_over_pathways_and_injects_pathway_id(self) -> None:
        result = _driver().run(
            "pathway_versions",
            [
                ScriptedResponse(json=[{"id": "p1"}, {"id": "p2"}]),
                ScriptedResponse(
                    json=[
                        {"id": "v1", "version_number": 1, "created_at": "2026-01-01T00:00:00Z", "is_latest": False},
                        {"id": "v2", "version_number": 2, "created_at": "2026-01-02T00:00:00Z", "is_latest": True},
                    ]
                ),
                # A single version still parses as one row, not as a list of keys.
                ScriptedResponse(json=[{"id": "v1", "version_number": 1, "created_at": "2026-01-03T00:00:00Z"}]),
            ],
        )

        assert result.raised is None
        # Version ids repeat across pathways, so the parent id must reach every row.
        assert [(row["pathway_id"], row["id"]) for row in result.rows] == [("p1", "v1"), ("p1", "v2"), ("p2", "v1")]
        assert result.paths == ["/v1/pathway", "/v1/pathway/p1/versions", "/v1/pathway/p2/versions"]


def _evals_page(rows: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {"object": "list", "data": rows, "has_more": next_cursor is not None, "next_cursor": next_cursor},
            "errors": None,
        }
    )


class TestEvals:
    @parameterized.expand(
        [
            ("fresh", None, [None, "r2"]),
            ("resumed", BlandAIResumeConfig(cursor="r0"), ["r0", "r2"]),
        ]
    )
    def test_eval_runs_walk_cursor_pages(
        self, _name: str, resume_state: BlandAIResumeConfig | None, expected_cursors: list[str | None]
    ) -> None:
        result = _driver().run(
            "eval_runs",
            [_evals_page([{"id": "r1"}, {"id": "r2"}], "r2"), _evals_page([{"id": "r3"}], None)],
            resume_state=resume_state,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["r1", "r2", "r3"]
        # A null next_cursor ends the walk without a third request.
        assert result.paths == ["/v1/evals/runs", "/v1/evals/runs"]
        assert result.params("starting_after") == expected_cursors
        assert result.params("limit") == [str(EVALS_PAGE_SIZE)] * 2

    def test_eval_call_results_paginate_per_run(self) -> None:
        result = _driver().run(
            "eval_call_results",
            [
                _evals_page([{"id": "r1"}, {"id": "r2"}], None),
                _evals_page([{"id": "cr1", "eval_run_id": "r1", "overall_score_normalized_0_100": 88.0}], "cr1"),
                _evals_page([{"id": "cr2", "eval_run_id": "r1"}], None),
                _evals_page([{"id": "cr3", "eval_run_id": "r2"}], None),
            ],
        )

        assert result.raised is None
        assert [(row["eval_run_id"], row["id"]) for row in result.rows] == [("r1", "cr1"), ("r1", "cr2"), ("r2", "cr3")]
        assert result.paths == [
            "/v1/evals/runs",
            "/v1/evals/runs/r1/call-results",
            "/v1/evals/runs/r1/call-results",
            "/v1/evals/runs/r2/call-results",
        ]
        # The first run's cursor must not leak into the second run's first request.
        assert result.params("starting_after") == [None, None, "cr1", None]


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
            # Audit events always arrive newest first, so the table must not claim ascending order.
            ("audit_logs", ["id"], ["created_at"], None),
        ]
    )
    def test_source_response_shape(
        self,
        endpoint: str,
        primary_keys: list[str],
        partition_keys: list[str] | None,
        sort_mode: str | None = "asc",
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
            "audit_logs": {"data": {"events": [], "total_pages": 0}},
        }
        result = _driver().run(endpoint, [ScriptedResponse(json=empty_responses[endpoint])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        assert response.sort_mode == sort_mode
