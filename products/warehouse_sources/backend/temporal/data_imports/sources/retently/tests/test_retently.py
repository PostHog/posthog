import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_client
from products.warehouse_sources.backend.temporal.data_imports.sources.retently import retently
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.retently import (
    PAGE_SIZE,
    RetentlyResumeConfig,
    _format_start_date,
    retently_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: Any = None, *, status_code: int = 200, content: bytes | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = content if content is not None else json.dumps(body).encode()
    return resp


def _make_manager(resume_state: RetentlyResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        snapshots.append(dict(request.params or {}))
        return MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _run(
    endpoint: str,
    responses: list[Response],
    manager: MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], MagicMock]:
    session = MagicMock()
    snapshots = _wire(session, responses)
    with patch(CLIENT_SESSION_PATCH, return_value=session):
        response = retently_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager or _make_manager(),
            **kwargs,
        )
        rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]
    return rows, snapshots, session


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("epoch_passthrough", 1704067200, "1704067200"),
            ("string_passthrough", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_format_start_date(self, _name: str, value: object, expected: str) -> None:
        assert _format_start_date(value) == expected


class TestEnvelopeShapes:
    @parameterized.expand(
        [
            # Records nested under `data.<key>` — feedback, outbox, customers, companies.
            ("nested_in_data", "feedback", {"data": {"responses": [{"id": "1"}], "pages": 1}}, [{"id": "1"}]),
            # /reports returns a bare list under `data`.
            ("bare_list_under_data", "reports", {"data": [{"campaignId": "c1"}]}, [{"campaignId": "c1"}]),
            # Campaigns/templates document the array at the top level, outside `data`.
            ("top_level_array", "campaigns", {"campaigns": [{"id": "c1"}]}, [{"id": "c1"}]),
        ]
    )
    def test_documented_envelope_shapes_yield_rows(self, _name: str, endpoint: str, body: Any, expected: list) -> None:
        rows, _, _ = _run(endpoint, [_response(body)])
        assert rows == expected

    @parameterized.expand(
        [
            ("not_a_dict", [{"id": "1"}]),
            ("no_recognisable_array", {"data": {"total": 3, "tags": ["a"], "other": ["b"]}}),
        ]
    )
    def test_unexpected_payloads_are_retried_then_fail(self, _name: str, body: Any) -> None:
        # An unexpected 200-body shape is treated as transient: retried, and exhausting retries
        # raises rather than silently syncing garbage rows.
        with patch.object(rest_client.RESTClient._send_request.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(rest_client.RESTClientRetryableError):
                _run("feedback", [_response(body)] * 5)


class TestPagination:
    def test_walks_pages_using_pages_metadata_inside_data(self) -> None:
        bodies = [
            {"data": {"responses": [{"id": "1"}], "page": 1, "pages": 2}},
            {"data": {"responses": [{"id": "2"}], "page": 2, "pages": 2}},
        ]
        rows, snapshots, _ = _run("feedback", [_response(b) for b in bodies])
        assert [r["id"] for r in rows] == ["1", "2"]
        # Stops at the last page — never requests page 3.
        assert [s["page"] for s in snapshots] == [1, 2]

    def test_top_level_pages_metadata_keeps_paginating(self) -> None:
        # The customers docs place `pages` at the top level; a short page must not end the loop
        # while the metadata says more pages exist (e.g. the API caps `limit` below our request).
        bodies = [
            {"data": {"subscribers": [{"id": "1"}]}, "page": 1, "pages": 2},
            {"data": {"subscribers": [{"id": "2"}]}, "page": 2, "pages": 2},
        ]
        rows, snapshots, _ = _run("customers", [_response(b) for b in bodies])
        assert [r["id"] for r in rows] == ["1", "2"]
        assert len(snapshots) == 2

    def test_short_page_ends_loop_without_pages_metadata(self) -> None:
        rows, snapshots, _ = _run("feedback", [_response({"data": {"responses": [{"id": "1"}]}})])
        assert rows == [{"id": "1"}]
        assert len(snapshots) == 1

    def test_empty_first_page_yields_nothing(self) -> None:
        rows, snapshots, _ = _run("feedback", [_response({"data": {"responses": [], "page": 1, "pages": 0}})])
        assert rows == []
        assert len(snapshots) == 1

    @parameterized.expand(
        [
            ("campaigns", {"campaigns": [{"id": "c1"}]}),
            ("templates", {"templates": [{"id": "t1"}]}),
            ("reports", {"data": [{"campaignId": "c1"}]}),
        ]
    )
    def test_unpaginated_endpoints_make_one_request_without_page_params(self, endpoint: str, body: Any) -> None:
        rows, snapshots, _ = _run(endpoint, [_response(body)])
        assert len(rows) == 1
        assert len(snapshots) == 1
        assert "page" not in snapshots[0]
        assert "limit" not in snapshots[0]

    def test_requests_ascending_sort_and_limit_for_page_stability(self) -> None:
        _, snapshots, _ = _run("outbox", [_response({"data": {"surveys": [{"customerId": "1"}], "pages": 1}})])
        assert snapshots[0]["sort"] == "surveyCreatedDate"
        assert snapshots[0]["limit"] == PAGE_SIZE
        assert snapshots[0]["page"] == 1


class TestIncremental:
    def test_start_date_sent_when_incremental(self) -> None:
        _, snapshots, _ = _run(
            "feedback",
            [_response({"data": {"responses": [{"id": "1"}], "pages": 1}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert snapshots[0]["startDate"] == "2026-03-04T02:58:14Z"
        assert snapshots[0]["sort"] == "createdDate"

    @parameterized.expand(
        [
            ("full_refresh_run", False, datetime(2026, 3, 4, tzinfo=UTC)),
            ("first_incremental_run_has_no_watermark", True, None),
        ]
    )
    def test_start_date_omitted(self, _name: str, should_use: bool, last_value: Any) -> None:
        _, snapshots, _ = _run(
            "feedback",
            [_response({"data": {"responses": [{"id": "1"}], "pages": 1}})],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
        )
        assert "startDate" not in snapshots[0]

    def test_full_refresh_endpoint_ignores_incremental_inputs(self) -> None:
        _, snapshots, _ = _run(
            "customers",
            [_response({"data": {"subscribers": [{"id": "1"}], "pages": 1}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "startDate" not in snapshots[0]


class TestResume:
    def test_resume_starts_from_saved_page(self) -> None:
        manager = _make_manager(RetentlyResumeConfig(page=3))
        rows, snapshots, _ = _run(
            "feedback",
            [_response({"data": {"responses": [{"id": "9"}], "page": 3, "pages": 3}})],
            manager=manager,
        )
        assert rows == [{"id": "9"}]
        assert snapshots[0]["page"] == 3

    def test_state_saved_after_yield_with_next_page(self) -> None:
        bodies = [
            {"data": {"responses": [{"id": "1"}], "pages": 2}},
            {"data": {"responses": [{"id": "2"}], "pages": 2}},
        ]
        manager = _make_manager()
        _run("feedback", [_response(b) for b in bodies], manager=manager)
        # Only the transition to page 2 is checkpointed; the final page saves nothing (a crash
        # after the last yield just re-fetches page 2 and merge dedupes).
        assert [call.args[0].page for call in manager.save_state.call_args_list] == [2]


class TestRetries:
    @parameterized.expand(
        [
            ("rate_limited", _response({}, status_code=429)),
            ("server_error", _response({}, status_code=500)),
            # A truncated / partial JSON body (a page cut off mid-stream) starts like JSON but fails
            # to parse, so it must retry the single request, not fail the sync. A non-JSON body (e.g.
            # an HTML error page) is treated as non-retryable and is not covered here.
            ("truncated_body", _response(content=b'{"data": {"responses": [')),
        ]
    )
    def test_transient_failures_are_retried(self, _name: str, first_response: Response) -> None:
        responses = [first_response, _response({"data": {"responses": [{"id": "1"}], "pages": 1}})]
        with patch.object(rest_client.RESTClient._send_request.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            rows, _, session = _run("feedback", responses)
        assert rows == [{"id": "1"}]
        assert session.send.call_count == 2

    def test_auth_error_raises_immediately(self) -> None:
        with pytest.raises(requests.HTTPError):
            _run("feedback", [_response({"message": "Account not found"}, status_code=401)])


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Retently API key"),
            ("forbidden", 403, False, "Invalid Retently API key"),
            ("server_error_is_inconclusive", 500, False, "Retently returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with patch.object(retently, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("key")
        assert ok is expected_ok
        if expected_msg is None:
            assert message is None
        else:
            assert message is not None and expected_msg in message
        assert session.get.call_args.args[0].endswith("/ping")

    def test_network_error_is_inconclusive_not_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(retently, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("key")
        assert ok is False
        assert message is not None and "Could not connect to Retently" in message


class TestSourceResponse:
    @parameterized.expand(
        [
            ("customers", ["id"], "createdDate", "asc"),
            ("companies", ["id"], "createdDate", "asc"),
            # feedback is the only incremental endpoint: "desc" defers the watermark to the end of
            # a successful sync because the API's sort behavior could not be live-verified.
            ("feedback", ["id"], "createdDate", "desc"),
            ("outbox", None, None, "asc"),
            ("campaigns", ["id"], None, "asc"),
            ("templates", ["id"], None, "asc"),
            ("reports", ["campaignId"], None, "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str] | None, partition_key: str | None, sort_mode: str
    ) -> None:
        with patch(CLIENT_SESSION_PATCH, return_value=MagicMock(headers={})):
            response = retently_source(
                api_key="key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"

    @parameterized.expand(ENDPOINTS)
    def test_every_declared_endpoint_builds_a_response(self, endpoint: str) -> None:
        with patch(CLIENT_SESSION_PATCH, return_value=MagicMock(headers={})):
            response = retently_source(
                api_key="key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        assert response.name == endpoint
