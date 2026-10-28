from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plain import PlainSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plain.plain import (
    _datetime_to_plain_iso8601,
    _fetch_paginated_endpoint,
    _fetch_thread_timeline_entries,
    _fetch_timeline_entries,
    _flatten_node,
    _flatten_timeline_entry,
    _parse_plain_datetime,
    plain_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plain.queries import VIEWER_QUERY
from products.warehouse_sources.backend.temporal.data_imports.sources.plain.source import PlainSource


class TestFlattenNode:
    def test_flattens_customer_node(self):
        node = {
            "id": "c_1",
            "fullName": "Alice",
            "email": {"email": "alice@example.com", "isVerified": True},
            "createdAt": {"iso8601": "2024-01-01T00:00:00Z"},
            "updatedAt": {"iso8601": "2024-02-01T00:00:00Z"},
            "assignedToUser": {"user": {"id": "u_1", "fullName": "Bob", "email": "bob@example.com"}},
            "createdBy": {"actorType": "UserActor", "userId": "u_2"},
            "company": {"id": "co_1", "name": "Acme"},
        }
        result = _flatten_node(node)

        assert result["id"] == "c_1"
        assert result["email"] == "alice@example.com"
        assert result["emailIsVerified"] is True
        assert result["createdAt"] == "2024-01-01T00:00:00Z"
        assert result["updatedAt"] == "2024-02-01T00:00:00Z"
        assert result["assignedToUserId"] == "u_1"
        assert result["assignedToUserName"] == "Bob"
        assert result["createdByType"] == "UserActor"
        assert result["createdById"] == "u_2"
        assert result["companyId"] == "co_1"
        assert result["companyName"] == "Acme"

    def test_flattens_thread_assignee_resolved_directly(self):
        # Thread.assignedTo (aliased to assignedToUser) resolves to the assignee object directly,
        # unlike Customer.assignedToUser which wraps a nested `user`.
        node = {"id": "t_1", "assignedToUser": {"id": "u_1", "fullName": "Bob", "email": "bob@example.com"}}
        result = _flatten_node(node)

        assert result["assignedToUserId"] == "u_1"
        assert result["assignedToUserName"] == "Bob"
        assert result["assignedToUserEmail"] == "bob@example.com"

    def test_flattens_thread_with_labels_and_message_info(self):
        node = {
            "id": "t_1",
            "customer": {"id": "c_1", "fullName": "Alice", "email": {"email": "alice@example.com"}},
            "labels": [
                {"id": "l_1", "labelType": {"name": "bug"}},
                {"id": "l_2", "labelType": {"name": "urgent"}},
            ],
            "firstInboundMessageInfo": {"timestamp": {"iso8601": "2024-01-01T01:00:00Z"}},
            "lastOutboundMessageInfo": None,
        }
        result = _flatten_node(node)

        assert result["customerId"] == "c_1"
        assert result["customerEmail"] == "alice@example.com"
        assert result["labelIds"] == ["l_1", "l_2"]
        assert result["labelNames"] == ["bug", "urgent"]
        assert result["firstInboundMessageAt"] == "2024-01-01T01:00:00Z"
        assert result["lastOutboundMessageAt"] is None

    @pytest.mark.parametrize(
        "node,expected",
        [
            (
                {"id": "co_1", "accountOwner": {"id": "u_1"}, "deletedBy": None, "deletedAt": None},
                {"accountOwnerId": "u_1", "deletedByType": None, "deletedById": None, "deletedAt": None},
            ),
            (
                {
                    "id": "co_2",
                    "accountOwner": None,
                    "deletedBy": {"actorType": "MachineUserActor", "machineUserId": "mu_1"},
                },
                {"accountOwnerId": None, "deletedByType": "MachineUserActor", "deletedById": "mu_1"},
            ),
            (
                {"id": "lt_1", "parentLabelType": None, "archivedBy": None},
                {"parentLabelTypeId": None, "archivedByType": None, "archivedById": None},
            ),
            (
                {
                    "id": "lt_2",
                    "parentLabelType": {"id": "lt_1"},
                    "archivedBy": {"actorType": "UserActor", "userId": "u_1"},
                },
                {"parentLabelTypeId": "lt_1", "archivedByType": "UserActor", "archivedById": "u_1"},
            ),
        ],
    )
    def test_flattens_nullable_references_into_stable_columns(self, node, expected):
        result = _flatten_node(node)

        assert {key: result[key] for key in expected} == expected
        assert not {"accountOwner", "parentLabelType", "deletedBy", "archivedBy"} & result.keys()


class TestFlattenTimelineEntry:
    def test_email_entry(self):
        entry = {
            "id": "te_2",
            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
            "actor": {"actorType": "user", "userId": "u_1"},
            "entry": {
                "__typename": "EmailEntry",
                "emailId": "email_1",
                "subject": "hi",
                "textContent": "body",
                "to": {"email": "to@example.com", "name": "To"},
                "from": {"email": "from@example.com", "name": "From"},
            },
        }
        result = _flatten_timeline_entry(entry, thread_id="t_1")

        assert result["entryType"] == "EmailEntry"
        assert result["emailId"] == "email_1"
        assert result["subject"] == "hi"
        assert result["text"] == "body"
        assert result["toEmail"] == "to@example.com"
        assert result["fromEmail"] == "from@example.com"

    def test_note_entry(self):
        entry = {
            "id": "te_3",
            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
            "actor": {"actorType": "user", "userId": "u_1"},
            "entry": {"__typename": "NoteEntry", "noteId": "note_1", "noteText": "internal"},
        }
        result = _flatten_timeline_entry(entry, thread_id="t_1")

        assert result["entryType"] == "NoteEntry"
        assert result["noteId"] == "note_1"
        assert result["text"] == "internal"

    def test_custom_entry(self):
        entry = {
            "id": "te_4",
            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
            "actor": {"actorType": "user", "userId": "u_1"},
            "entry": {"__typename": "CustomEntry", "title": "Order placed", "externalId": "ext_1"},
        }
        result = _flatten_timeline_entry(entry, thread_id="t_1")

        assert result["entryType"] == "CustomEntry"
        assert result["title"] == "Order placed"
        assert result["externalId"] == "ext_1"


class TestPlainSourcePipeline:
    def test_returns_source_response_with_partition_metadata(self):
        response = plain_source(api_key="k", endpoint_name="customers", logger=mock.MagicMock())

        assert response.name == "customers"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["createdAt"]


class TestValidateCredentials:
    def test_success(self) -> None:
        with scripted_network(
            [ScriptedResponse(json={"data": {"myWorkspace": {"id": "w_1", "name": "Acme"}}})]
        ) as network:
            is_valid, error = validate_credentials("valid_key")

        assert is_valid is True
        assert error is None
        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.method == "POST"
        assert request.path == "/graphql/v1"
        assert request.headers["authorization"] == "Bearer valid_key"
        assert request.json() == {"query": VIEWER_QUERY}

    def test_returns_error_from_graphql_errors(self) -> None:
        with scripted_network([ScriptedResponse(json={"errors": [{"message": "Unauthorized"}]})]) as network:
            is_valid, error = validate_credentials("bad_key")

        assert is_valid is False
        assert error is not None
        assert "Unauthorized" in error
        assert network.requests_log[0].headers["authorization"] == "Bearer bad_key"

    def test_handles_request_exception(self) -> None:
        with scripted_network(always(requests.ConnectionError("down"))) as network:
            is_valid, error = validate_credentials("any_key")

        assert is_valid is False
        assert error is not None
        assert "down" in error
        assert {request.path for request in network.requests_log} == {"/graphql/v1"}


class TestDatetimeHelpers:
    def test_datetime_to_plain_iso8601_assumes_utc_for_naive(self):
        assert _datetime_to_plain_iso8601(datetime(2024, 1, 15, 10, 30, 0)) == "2024-01-15T10:30:00Z"

    def test_datetime_to_plain_iso8601_caps_microseconds_at_milliseconds(self):
        # Plain rejects 6-digit microsecond precision with "There was a validation error.";
        # incremental watermarks carry microseconds, so we must emit millisecond precision.
        assert (
            _datetime_to_plain_iso8601(datetime(2026, 6, 7, 18, 3, 36, 624000, tzinfo=UTC))
            == "2026-06-07T18:03:36.624Z"
        )
        assert _datetime_to_plain_iso8601(datetime(2024, 1, 15, 10, 30, 0, 1, tzinfo=UTC)) == "2024-01-15T10:30:00.000Z"

    def test_parse_plain_datetime_passthrough_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        assert _parse_plain_datetime(dt) is dt

    def test_parse_plain_datetime_none(self):
        assert _parse_plain_datetime(None) is None


class TestTimelineEntryIncrementalFilter:
    """Verify incremental filtering compares datetimes, not ISO-8601 strings."""

    def _make_execute(self, pages):
        calls = iter(pages)

        def execute(_query, _variables):
            return next(calls)

        return execute

    def test_filters_older_entries_by_datetime(self):
        execute = self._make_execute(
            [
                {
                    "data": {
                        "thread": {
                            "timelineEntries": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "te_old",
                                            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
                                            "actor": {"actorType": "customer", "customerId": "c_1"},
                                            "entry": {"__typename": "ChatEntry", "chatId": "c", "text": "old"},
                                        }
                                    },
                                    {
                                        "node": {
                                            "id": "te_new",
                                            "timestamp": {"iso8601": "2024-02-01T00:00:00Z"},
                                            "actor": {"actorType": "customer", "customerId": "c_1"},
                                            "entry": {"__typename": "ChatEntry", "chatId": "c", "text": "new"},
                                        }
                                    },
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            ]
        )

        pages = list(
            _fetch_thread_timeline_entries(
                execute,
                thread_id="t_1",
                logger=mock.MagicMock(),
                created_at_gte=datetime(2024, 1, 15, tzinfo=UTC),
            )
        )

        assert len(pages) == 1
        assert [e["id"] for e in pages[0]] == ["te_new"]


class TestFetchPaginatedEndpointIncrementalFilter:
    def test_sends_after_filter_when_incremental(self):
        recorded = []

        def execute(query, variables):
            recorded.append((query, dict(variables)))
            return {"data": {"customers": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}

        list(
            _fetch_paginated_endpoint(
                execute,
                endpoint_name="customers",
                query="query PaginatedCustomers { customers { edges { node { id } } } }",
                logger=mock.MagicMock(),
                updated_at_gte=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            )
        )

        assert recorded, "expected customers query to be issued"
        _, variables = recorded[0]
        # Plain's DatetimeFilter uses `after` (>=), not `gte` — sending `gte` is rejected with a 400.
        assert variables["filter"] == {"updatedAt": {"after": "2024-01-15T10:30:00Z"}}


class TestFetchTimelineEntriesStreaming:
    def test_sends_updatedat_filter_when_incremental(self):
        recorded = []

        def execute(query, variables):
            recorded.append((query, dict(variables)))
            if "ThreadIdsList" in query or "threads" in query:
                return {"data": {"threads": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            raise AssertionError("unexpected query")

        list(
            _fetch_timeline_entries(
                execute,
                logger=mock.MagicMock(),
                created_at_gte=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            )
        )

        assert recorded, "expected threads query to be issued"
        _, variables = recorded[0]
        # Plain's DatetimeFilter uses `after` (>=), not `gte` — sending `gte` is rejected with a 400.
        assert variables["filter"] == {"updatedAt": {"after": "2024-01-15T10:30:00Z"}}

    def test_streams_thread_pages_without_buffering_all_ids(self):
        executed_queries: list[str] = []

        def execute(query, _variables):
            executed_queries.append(query)
            # First threads page: returns one thread id then no next page.
            if "ThreadIdsList" in query:
                return {
                    "data": {
                        "threads": {
                            "edges": [{"node": {"id": "t_1"}}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            # Timeline entries for t_1.
            return {
                "data": {
                    "thread": {
                        "timelineEntries": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "te_1",
                                        "timestamp": {"iso8601": "2024-02-01T00:00:00Z"},
                                        "actor": {"actorType": "customer", "customerId": "c_1"},
                                        "entry": {"__typename": "ChatEntry", "chatId": "c", "text": "x"},
                                    }
                                }
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }

        pages = list(_fetch_timeline_entries(execute, logger=mock.MagicMock()))

        assert len(pages) == 1
        assert [e["id"] for e in pages[0]] == ["te_1"]
        # Threads query first, then TIMELINE_ENTRIES_QUERY after we've seen the first edge — no second threads page expected.
        assert "ThreadIdsList" in executed_queries[0]


def _connection_page(endpoint: str, ids: list[str], end_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {
                endpoint: {
                    "edges": [
                        {"node": {"id": node_id, "createdAt": {"iso8601": "2024-01-01T00:00:00Z"}}} for node_id in ids
                    ],
                    "pageInfo": {"hasNextPage": end_cursor is not None, "endCursor": end_cursor},
                }
            }
        }
    )


def _run(endpoint: str, script: list[ScriptedResponse], **inputs: Any):
    return SourceDriver(PlainSource(), PlainSourceConfig(api_key="plainApiKey_test")).run(endpoint, script, **inputs)


class TestLookupEndpoints:
    @pytest.mark.parametrize(
        "endpoint,operation",
        [
            ("companies", "PaginatedCompanies"),
            ("tenants", "PaginatedTenants"),
            ("users", "PaginatedUsers"),
            ("label_types", "PaginatedLabelTypes"),
        ],
    )
    def test_walks_pages_until_has_next_page_is_false(self, endpoint, operation):
        result = _run(
            endpoint,
            [_connection_page(endpoint, ["a", "b"], "cursor_1"), _connection_page(endpoint, ["c"], None)],
        )

        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert result.rows[0]["createdAt"] == "2024-01-01T00:00:00Z"
        bodies = [request.json() for request in result.requests]
        assert all(f"query {operation}(" in body["query"] for body in bodies)
        assert [body["variables"].get("after") for body in bodies] == [None, "cursor_1"]

    @pytest.mark.parametrize(
        "endpoint,incremental,expected_filter",
        [
            ("companies", True, {"updatedAt": {"after": "2024-03-01T12:00:00Z"}}),
            ("tenants", True, {"updatedAt": {"after": "2024-03-01T12:00:00Z"}}),
            ("companies", False, None),
            ("tenants", False, None),
        ],
    )
    def test_incremental_sync_sends_updated_at_filter(self, endpoint, incremental, expected_filter):
        inputs: dict[str, Any] = (
            {"incremental_field": "updatedAt", "db_incremental_field_last_value": datetime(2024, 3, 1, 12, tzinfo=UTC)}
            if incremental
            else {}
        )

        result = _run(endpoint, [_connection_page(endpoint, ["a"], None)], **inputs)

        body = result.requests[0].json()
        assert body["variables"].get("filter") == expected_filter
        assert "$filter" in body["query"]

    @pytest.mark.parametrize(
        "endpoint,expected_sort_mode",
        [
            ("customers", None),
            ("threads", None),
            ("timeline_entries", None),
            ("companies", "desc"),
            ("tenants", "desc"),
            ("users", None),
            ("label_types", None),
        ],
    )
    def test_source_for_pipeline_sets_sort_mode(self, endpoint, expected_sort_mode):
        result = _run(endpoint, [_connection_page(endpoint, ["a"], None)])

        assert result.response is not None
        assert result.response.sort_mode == expected_sort_mode
