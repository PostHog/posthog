from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io import reply_io
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.reply_io import (
    MAX_RETRY_AFTER_SECONDS,
    PAGE_SIZE,
    ReplyIoResumeConfig,
    ReplyIoRetryableError,
    _parse_retry_after,
    _wait_reply_io,
    check_access,
    check_endpoint_permissions,
    get_rows,
    reply_io_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.settings import (
    ENDPOINTS,
    REPLY_IO_ENDPOINTS,
)

# Call the undecorated functions so the tenacity retry/backoff wrappers don't slow failure-path tests.
_fetch_page_unwrapped = reply_io._fetch_page.__wrapped__  # type: ignore[attr-defined]
_fetch_all_unwrapped = reply_io._fetch_all.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: ReplyIoResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ReplyIoResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ReplyIoResumeConfig | None:
        return self._state

    def save_state(self, data: ReplyIoResumeConfig) -> None:
        self.saved.append(data)


def _page(start_id: int, count: int) -> list[dict]:
    return [{"id": start_id + i} for i in range(count)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[int, tuple[list[dict], bool]],
        endpoint: str = "contacts",
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, skip: int, limit: int, logger: Any) -> tuple[list[dict], bool]:
            return pages[skip]

        monkeypatch.setattr(reply_io, "_fetch_page", fake_fetch)
        monkeypatch.setattr(reply_io, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="reply-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_hasmore_false_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: ([{"id": 1}, {"id": 2}], False)})
        assert rows == [{"id": 1}, {"id": 2}]
        # hasMore is false, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_offset_pagination_until_hasmore_false(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[int, tuple[list[dict], bool]] = {
            0: (_page(0, PAGE_SIZE), True),
            PAGE_SIZE: ([{"id": 9999}], False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == PAGE_SIZE + 1
        # State is saved after the first page (offset advances by the page length), then we stop.
        assert [s.skip for s in manager.saved] == [PAGE_SIZE]

    def test_offset_advances_by_rows_received_not_page_size(self, monkeypatch: Any) -> None:
        # If the server caps pages below our requested `top`, advancing by PAGE_SIZE would skip rows.
        manager = _FakeResumableManager()
        pages: dict[int, tuple[list[dict], bool]] = {
            0: (_page(0, 100), True),
            100: (_page(100, 40), False),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert len(rows) == 140
        assert [s.skip for s in manager.saved] == [100]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(ReplyIoResumeConfig(skip=200))
        # The initial (skip=0) page must never be fetched on resume.
        rows = self._collect(manager, monkeypatch, {200: ([{"id": 201}], False)})
        assert rows == [{"id": 201}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {0: ([], False)})
        assert rows == []
        assert manager.saved == []

    @parameterized.expand([("custom_fields",), ("email_template_folders",)])
    def test_unpaginated_endpoint_fetches_once_without_state(self, endpoint: str) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = [{"id": 1}, {"id": 2}]
        session = MagicMock()
        session.get.return_value = response
        manager = _FakeResumableManager()

        with patch(f"{reply_io.__name__}.make_tracked_session", return_value=session):
            rows = [
                row
                for batch in get_rows(
                    api_key="reply-key",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
                for row in batch
            ]

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.get.call_count == 1
        # Bare-array endpoints take no pagination params and never persist resume state.
        assert "params" not in session.get.call_args.kwargs
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None, headers: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"items": [], "hasMore": False}
        response.text = ""
        response.headers = headers or {}
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(ReplyIoRetryableError):
            _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())

    def test_rate_limit_carries_retry_after_header(self) -> None:
        session = self._session_returning(429, headers={"Retry-After": "42"})
        with pytest.raises(ReplyIoRetryableError) as exc_info:
            _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())
        assert exc_info.value.retry_after == 42.0

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())

    def test_success_returns_items_and_hasmore(self) -> None:
        session = self._session_returning(200, {"items": [{"id": 1}], "hasMore": True})
        items, has_more = _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())
        assert items == [{"id": 1}]
        assert has_more is True

    @parameterized.expand(
        [
            ("bare_array_body", [{"id": 1}]),
            ("missing_items_key", {"hasMore": False}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(ReplyIoRetryableError):
            _fetch_page_unwrapped(session, "/contacts", 0, PAGE_SIZE, MagicMock())

    def test_sends_top_and_skip_params(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "/tasks", 250, PAGE_SIZE, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"top": PAGE_SIZE, "skip": 250}

    def test_fetch_all_rejects_non_array_body(self) -> None:
        session = self._session_returning(200, {"items": []})
        with pytest.raises(ReplyIoRetryableError):
            _fetch_all_unwrapped(session, "/custom-fields", MagicMock())


class TestRetryAfter:
    @parameterized.expand(
        [
            ("delta_seconds", "42", 42.0),
            ("zero_floor", "-5", 0.0),
            ("garbage", "not-a-date", None),
            ("missing", None, None),
        ]
    )
    def test_parse_retry_after(self, _name: str, value: str | None, expected: float | None) -> None:
        assert _parse_retry_after(value) == expected

    def test_wait_prefers_server_retry_after_capped(self) -> None:
        state = MagicMock()
        state.outcome.exception.return_value = ReplyIoRetryableError("throttled", retry_after=10_000.0)
        assert _wait_reply_io(state) == MAX_RETRY_AFTER_SECONDS

        state.outcome.exception.return_value = ReplyIoRetryableError("throttled", retry_after=7.0)
        assert _wait_reply_io(state) == 7.0


class TestCredentials:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @staticmethod
    def _response(status: int) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        return response

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Reply API key"),
            ("forbidden", 403, False, "Invalid Reply API key"),
            ("server_error", 500, False, "Reply returned HTTP 500"),
        ]
    )
    @patch(f"{reply_io.__name__}.make_tracked_session")
    def test_validate_credentials_at_source_create(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value = self._session(self._response(status))
        assert validate_credentials("reply-key") == (expected_valid, expected_message)

    @patch(f"{reply_io.__name__}.make_tracked_session")
    def test_validate_credentials_for_endpoint_names_missing_scope(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(self._response(403))
        valid, message = validate_credentials("reply-key", endpoint="sequences")
        assert valid is False
        assert message == "Your Reply API key is missing the `sequences:read` scope"

    @patch(f"{reply_io.__name__}.make_tracked_session")
    def test_check_access_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("reply-key", "/whoami")
        assert status == 0
        assert message is not None and "boom" in message


class TestEndpointPermissions:
    @patch(f"{reply_io.__name__}.check_access")
    def test_endpoints_sharing_a_scope_share_one_probe(self, mock_access: MagicMock) -> None:
        mock_access.return_value = (200, None)
        results = check_endpoint_permissions("reply-key", list(ENDPOINTS))
        assert results == dict.fromkeys(ENDPOINTS)
        distinct_scopes = {config.scope for config in REPLY_IO_ENDPOINTS.values()}
        assert mock_access.call_count == len(distinct_scopes)

    @patch(f"{reply_io.__name__}.check_access")
    def test_missing_scope_marks_every_endpoint_behind_it(self, mock_access: MagicMock) -> None:
        def by_path(api_key: str, path: str, paginated: bool = False) -> tuple[int, None]:
            return (403, None) if path == REPLY_IO_ENDPOINTS["contacts"].path else (200, None)

        mock_access.side_effect = by_path
        results = check_endpoint_permissions("reply-key", list(ENDPOINTS))
        denied = {name for name, reason in results.items() if reason is not None}
        assert denied == {name for name, config in REPLY_IO_ENDPOINTS.items() if config.scope == "contacts:read"}
        assert results["contacts"] == "Your Reply API key is missing the `contacts:read` scope"

    @parameterized.expand([("throttled", 429), ("server_error", 500), ("connection_error", 0)])
    @patch(f"{reply_io.__name__}.check_access")
    def test_transient_errors_do_not_block_the_picker(self, _name: str, status: int, mock_access: MagicMock) -> None:
        mock_access.return_value = (status, None)
        results = check_endpoint_permissions("reply-key", ["contacts"])
        assert results == {"contacts": None}

    @patch(f"{reply_io.__name__}.check_access")
    def test_unknown_endpoint_reported_reachable_without_probe(self, mock_access: MagicMock) -> None:
        results = check_endpoint_permissions("reply-key", ["not_a_table"])
        assert results == {"not_a_table": None}
        mock_access.assert_not_called()


class TestReplyIoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = reply_io_source(
            api_key="reply-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Most Reply resources expose no stable creation timestamp, so we don't partition.
        assert response.partition_mode is None
