from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    error_message_matches,
    scripted_network,
)
from products.warehouse_sources.sources.skio._config import SkioSourceConfig
from products.warehouse_sources.sources.skio.skio import (
    SkioAPIError,
    SkioResumeConfig,
    _build_where,
    _format_timestamp,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.sources.skio.source import SkioSource

# Verbatim message shape `requests`/urllib3 raise for a read timeout or a dropped connection
# against the live host; both are the transient failures `_post_query` retries.
READ_TIMEOUT = requests.ReadTimeout(
    "HTTPSConnectionPool(host='graphql.skio.com', port=443): Read timed out. (read timeout=60.0)"
)
CONNECTION_ERROR = requests.ConnectionError(
    "HTTPSConnectionPool(host='graphql.skio.com', port=443): Max retries exceeded with url: /v1/graphql"
)

TOKEN = "test-token"

# Verbatim message from the live API for an invalid or revoked token (Hasura returns it with
# HTTP 200 in the GraphQL errors body).
INVALID_TOKEN_BODY = {"errors": [{"message": "Invalid response from authorization hook"}]}


def _response(payload: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=payload)


def _rows(start: int, count: int, field: str = "updatedAt") -> list[dict[str, Any]]:
    return [
        {"id": f"id-{index:04d}", field: f"2026-01-01T00:00:{index % 60:02d}+00:00", "status": "ACTIVE"}
        for index in range(start, start + count)
    ]


def _page(rows: list[dict[str, Any]], query_name: str = "Subscriptions") -> dict[str, Any]:
    return {"data": {query_name: rows}}


def _manager(resume: SkioResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _run(script: Script, endpoint: str = "subscriptions", **kwargs: Any) -> DriveResult:
    return SourceDriver(SkioSource(), SkioSourceConfig(api_token=TOKEN)).run(endpoint, script, **kwargs)


class TestSkioTransport:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T02:58:14+00:00", "2026-03-04T02:58:14+00:00"),
        ],
    )
    def test_format_timestamp(self, value: Any, expected: str) -> None:
        assert _format_timestamp(value) == expected

    @pytest.mark.parametrize(
        ("_name", "incremental_field", "last_value", "cursor", "expected"),
        [
            ("full_refresh_first_page", None, None, None, None),
            ("full_refresh_next_page", None, None, SkioResumeConfig(last_id="id-0099"), {"id": {"_gt": "id-0099"}}),
            (
                "incremental_first_page",
                "updatedAt",
                datetime(2026, 1, 1, tzinfo=UTC),
                None,
                {"updatedAt": {"_gte": "2026-01-01T00:00:00+00:00"}},
            ),
            (
                "incremental_next_page",
                "updatedAt",
                datetime(2026, 1, 1, tzinfo=UTC),
                SkioResumeConfig(last_id="id-0099", last_value="2026-01-02T00:00:00+00:00"),
                {
                    "_and": [
                        {"updatedAt": {"_gte": "2026-01-01T00:00:00+00:00"}},
                        {
                            "_or": [
                                {"updatedAt": {"_gt": "2026-01-02T00:00:00+00:00"}},
                                {
                                    "_and": [
                                        {"updatedAt": {"_eq": "2026-01-02T00:00:00+00:00"}},
                                        {"id": {"_gt": "id-0099"}},
                                    ]
                                },
                            ]
                        },
                    ]
                },
            ),
        ],
    )
    def test_build_where(
        self,
        _name: str,
        incremental_field: str | None,
        last_value: Any,
        cursor: SkioResumeConfig | None,
        expected: dict[str, Any] | None,
    ) -> None:
        assert _build_where(incremental_field, last_value, cursor) == expected

    def test_incremental_request_filters_and_orders_on_cursor_field(self) -> None:
        result = _run(
            [_response(_page(_rows(0, 3)))],
            incremental_field="updatedAt",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        variables = result.requests[0].json()["variables"]
        assert variables["where"] == {"updatedAt": {"_gte": "2026-01-01T00:00:00+00:00"}}
        assert variables["orderBy"] == [{"updatedAt": "asc"}, {"id": "asc"}]

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _run([_response(_page([]))])

        assert result.items == []
        assert result.saved_states == []

    def test_graphql_errors_raise_with_verbatim_api_message(self) -> None:
        result = _run([_response(INVALID_TOKEN_BODY)])

        assert isinstance(result.raised, SkioAPIError)
        assert "Invalid response from authorization hook" in str(result.raised)

    def test_http_error_propagates_for_transport_retry_classification(self) -> None:
        result = _run([_response({}, status_code=403)])

        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand([("read_timeout", READ_TIMEOUT), ("connection_error", CONNECTION_ERROR)])
    def test_transient_network_error_is_retried_then_succeeds(self, _name: str, error: BaseException) -> None:
        # The GraphQL endpoint is queried over POST, which the tracked session's transport-level
        # retry does not cover (it only retries idempotent methods), so a read timeout or dropped
        # connection must be retried by the source itself or it fails the whole import attempt on
        # the first blip.
        result = _run([error, _response(_page(_rows(0, 1)))])

        assert result.raised is None
        assert result.rows == _rows(0, 1)

    @parameterized.expand([("read_timeout", READ_TIMEOUT), ("connection_error", CONNECTION_ERROR)])
    def test_transient_network_error_that_keeps_failing_matches_retryable_errors(
        self, _name: str, error: BaseException
    ) -> None:
        result = _run(always(error))

        assert isinstance(result.raised, type(error))
        assert error_message_matches(str(result.raised), SkioSource().get_retryable_errors())


def _child(row_id: str, field: str = "updatedAt") -> dict[str, Any]:
    return {"id": row_id, field: "2026-01-01T00:00:00+00:00"}


def _parents(
    parents: list[tuple[str, list[dict[str, Any]]]],
    relationship: str = "AuditLogs",
    parent_query: str = "Subscriptions",
) -> ScriptedResponse:
    return _response({"data": {parent_query: [{"id": pid, relationship: rows} for pid, rows in parents]}})


HAS_AUDIT_LOGS = {"AuditLogs": {"id": {"_is_null": False}}}


class TestSkioNestedTransport:
    @pytest.fixture(autouse=True)
    def small_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("products.warehouse_sources.sources.skio.skio.SKIO_PAGE_SIZE", 2)
        monkeypatch.setattr("products.warehouse_sources.sources.skio.skio.SKIO_PARENT_PAGE_SIZE", 2)

    def test_walks_parent_pages_and_reads_on_a_parent_past_its_row_cap(self) -> None:
        result = _run(
            [
                _parents([("sub-1", [_child("log-1"), _child("log-2")]), ("sub-2", [_child("log-3")])]),
                _parents([("sub-1", [_child("log-4")])]),
                _parents([("sub-3", [_child("log-5")])]),
            ],
            endpoint="audit_logs",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["log-1", "log-2", "log-4", "log-3", "log-5"]
        variables = [request.json()["variables"] for request in result.requests]
        assert [v["parentWhere"] for v in variables] == [
            HAS_AUDIT_LOGS,
            {"id": {"_eq": "sub-1"}},
            {"_and": [{"id": {"_gt": "sub-2"}}, HAS_AUDIT_LOGS]},
        ]
        assert [v.get("where") for v in variables] == [None, {"id": {"_gt": "log-2"}}, None]
        assert result.saved_states == [
            SkioResumeConfig(last_id="log-2", parent_id="sub-1"),
            SkioResumeConfig(parent_id="sub-1"),
            SkioResumeConfig(parent_id="sub-2"),
            SkioResumeConfig(parent_id="sub-3"),
        ]
        assert result.response is not None and result.response.sort_mode is None

    def test_incremental_filters_both_parents_and_rows_on_the_watermark(self) -> None:
        result = _run(
            [
                _parents(
                    [("sub-1", [_child("session-1", "updated_at")])],
                    relationship="CancelFlowV2Sessions",
                )
            ],
            endpoint="cancel_flow_v2_sessions",
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        watermark = {"updated_at": {"_gte": "2026-01-01T00:00:00+00:00"}}
        variables = result.requests[0].json()["variables"]
        assert variables["where"] == watermark
        assert variables["parentWhere"] == {"CancelFlowV2Sessions": watermark}
        assert variables["orderBy"] == [{"updated_at": "asc"}, {"id": "asc"}]
        assert [row["id"] for row in result.rows] == ["session-1"]

    @parameterized.expand(
        [
            (
                "mid_parent_ending_on_page_boundary",
                SkioResumeConfig(last_id="log-2", parent_id="sub-1"),
                [_parents([("sub-1", [])]), _parents([("sub-2", [_child("log-3")])])],
                [{"id": {"_eq": "sub-1"}}, {"_and": [{"id": {"_gt": "sub-1"}}, HAS_AUDIT_LOGS]}],
            ),
            (
                "after_finished_parent",
                SkioResumeConfig(parent_id="sub-1"),
                [_parents([("sub-2", [_child("log-3")])])],
                [{"_and": [{"id": {"_gt": "sub-1"}}, HAS_AUDIT_LOGS]}],
            ),
        ]
    )
    def test_resumes_from_saved_parent_cursor(
        self,
        _name: str,
        resume_state: SkioResumeConfig,
        script: list[ScriptedResponse],
        expected_parent_wheres: list[dict[str, Any]],
    ) -> None:
        result = _run(script, endpoint="audit_logs", resume_state=resume_state)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["log-3"]
        assert [request.json()["variables"]["parentWhere"] for request in result.requests] == expected_parent_wheres
        assert result.final_state == SkioResumeConfig(parent_id="sub-2")


class TestValidateCredentials:
    def test_valid_token(self) -> None:
        with scripted_network(always(_response(_page(_rows(0, 1))))):
            assert validate_credentials(TOKEN) == (True, None)

    def test_invalid_token_maps_to_user_message(self) -> None:
        with scripted_network(always(_response(INVALID_TOKEN_BODY))):
            assert validate_credentials(TOKEN) == (False, "Invalid Skio API token")

    def test_other_graphql_error_surfaces_message(self) -> None:
        with scripted_network(always(_response({"errors": [{"message": "query is not in any of the allowlists"}]}))):
            valid, message = validate_credentials(TOKEN)
        assert valid is False
        assert message is not None and "query is not in any of the allowlists" in message


def test_get_rows_is_a_generator_and_defers_requests() -> None:
    # SourceResponse.items is called lazily; building the iterator must not hit the API.
    session = MagicMock()
    with patch(
        "products.warehouse_sources.sources.skio.skio.make_tracked_session",
        return_value=session,
    ):
        generator = get_rows(
            api_token=TOKEN,
            endpoint="subscriptions",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
    assert isinstance(generator, Iterator)
    session.post.assert_not_called()
