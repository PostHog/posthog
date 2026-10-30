from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.skio import SkioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio import (
    SkioAPIError,
    SkioResumeConfig,
    _build_where,
    _format_timestamp,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.skio.source import SkioSource

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
        "products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio.make_tracked_session",
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
