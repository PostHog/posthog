from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.groq.groq import (
    GROQ_BASE_URL,
    GroqRetryableError,
    _fetch_page,
    _get_headers,
    _next_cursor,
    get_rows,
    groq_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.groq.groq"


def _response(*, body: Any = None, status: int = 200, ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = ok
    response.text = "" if body is None else str(body)
    response.json.return_value = body if body is not None else {}
    if not ok:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error: Unauthorized for url: {GROQ_BASE_URL}/models", response=response
        )
    return response


def _session_returning(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _collect_rows(batches: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in batches:
        rows.extend(batch)
    return rows


class TestGroq:
    def test_get_headers_uses_bearer_auth(self) -> None:
        headers = _get_headers("gsk_secret")
        assert headers["Authorization"] == "Bearer gsk_secret"
        assert headers["Accept"] == "application/json"

    @parameterized.expand(
        [
            ("cursor_present", {"paging": {"next_cursor": "abc"}}, "abc"),
            ("no_paging", {"data": []}, None),
            ("empty_cursor", {"paging": {"next_cursor": ""}}, None),
            ("null_cursor", {"paging": {"next_cursor": None}}, None),
            ("paging_not_dict", {"paging": "nope"}, None),
        ]
    )
    def test_next_cursor(self, _name: str, body: dict, expected: str | None) -> None:
        assert _next_cursor(body) == expected

    def test_fetch_page_returns_body_on_success(self) -> None:
        session = _session_returning([_response(body={"object": "list", "data": [{"id": "batch_1"}]})])
        body = _fetch_page(session, f"{GROQ_BASE_URL}/batches", _get_headers("k"), MagicMock())
        assert body == {"object": "list", "data": [{"id": "batch_1"}]}

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_fetch_page_client_error_raises(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)])
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, f"{GROQ_BASE_URL}/models", _get_headers("k"), MagicMock())

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_fetch_page_retryable_status_retries_then_raises(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)] * 5)
        with patch("time.sleep"), pytest.raises(GroqRetryableError):
            _fetch_page(session, f"{GROQ_BASE_URL}/models", _get_headers("k"), MagicMock())
        assert session.get.call_count == 5

    def test_fetch_page_non_dict_body_is_retryable(self) -> None:
        session = _session_returning([_response(body=["unexpected"])] * 5)
        with patch("time.sleep"), pytest.raises(GroqRetryableError):
            _fetch_page(session, f"{GROQ_BASE_URL}/models", _get_headers("k"), MagicMock())

    @parameterized.expand([("files",), ("models",)])
    def test_get_rows_non_paginated_reads_single_page(self, endpoint: str) -> None:
        # files and models are flat `data` arrays; the transport must not attempt a second request
        # even if a stray cursor is present in the body.
        responses = [_response(body={"data": [{"id": "a"}, {"id": "b"}], "paging": {"next_cursor": "x"}})]
        session = _session_returning(responses)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", endpoint, MagicMock()))
        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.get.call_count == 1

    def test_get_rows_batches_follows_cursor_across_pages(self) -> None:
        responses = [
            _response(body={"data": [{"id": "batch_1"}], "paging": {"next_cursor": "cur1"}}),
            _response(body={"data": [{"id": "batch_2"}], "paging": {"next_cursor": "cur2"}}),
            _response(body={"data": [{"id": "batch_3"}]}),  # no cursor -> last page
        ]
        session = _session_returning(responses)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "batches", MagicMock()))
        assert [r["id"] for r in rows] == ["batch_1", "batch_2", "batch_3"]
        assert session.get.call_count == 3
        # The cursor from each page must be forwarded as the `cursor` param on the next request.
        cursors = [call.kwargs["params"] for call in session.get.call_args_list]
        assert cursors == [None, {"cursor": "cur1"}, {"cursor": "cur2"}]

    def test_get_rows_skips_empty_data_page(self) -> None:
        responses = [_response(body={"data": []})]
        session = _session_returning(responses)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "models", MagicMock()))
        assert rows == []

    def test_get_rows_non_list_data_is_retryable(self) -> None:
        # A `data` field that isn't a list (error payload or changed API shape) must not be yielded as
        # a page of rows; it breaks the Iterator[list[dict]] contract.
        responses = [_response(body={"data": {"unexpected": "object"}})]
        session = _session_returning(responses)
        with patch(f"{MODULE}.make_tracked_session", return_value=session), pytest.raises(GroqRetryableError):
            _collect_rows(get_rows("k", "models", MagicMock()))

    @parameterized.expand(
        [
            ("batches", "created_at"),
            ("files", "created_at"),
            ("models", "created"),
        ]
    )
    def test_groq_source_maps_primary_keys_and_partitioning(self, endpoint: str, partition_key: str) -> None:
        response = groq_source("k", endpoint, MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]

    @parameterized.expand(
        [
            ("empty_key", "   ", None, None, False, None),
            ("valid", "gsk_ok", 200, True, True, 200),
            ("invalid", "gsk_bad", 401, False, False, 401),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        api_key: str,
        status: int | None,
        ok: bool,
        expected_ok: bool,
        expected_status: int | None,
    ) -> None:
        session = MagicMock()
        if status is not None:
            session.get.return_value = _response(status=status, ok=ok, body={})
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            result_ok, result_status = validate_credentials(api_key)
        assert result_ok is expected_ok
        assert result_status == expected_status

    def test_validate_credentials_empty_key_skips_request(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as make_session:
            ok, status = validate_credentials("   ")
        assert ok is False
        assert status is None
        make_session.assert_not_called()

    def test_validate_credentials_swallows_transport_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            ok, status = validate_credentials("gsk_x")
        assert ok is False
        assert status is None
