from collections.abc import Callable
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap import mailtrap
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.mailtrap import (
    MAILTRAP_BASE_URL,
    MailtrapResumeConfig,
    MailtrapRetryableError,
    check_access,
    get_rows,
    mailtrap_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.settings import (
    ENDPOINTS,
    MAILTRAP_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = mailtrap._fetch_page.__wrapped__  # type: ignore[attr-defined]

FetchFn = Callable[..., Any]


class _FakeResumableManager:
    def __init__(self, state: MailtrapResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MailtrapResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MailtrapResumeConfig | None:
        return self._state

    def save_state(self, data: MailtrapResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    fetch: FetchFn,
    endpoint: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[dict]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(mailtrap, "_fetch_page", fetch)
        monkeypatch.setattr(mailtrap, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(batch)
        return rows
    finally:
        monkeypatch.undo()


class TestGetRows:
    def test_email_logs_follows_next_page_cursor_until_null(self) -> None:
        manager = _FakeResumableManager()
        pages = {
            None: {"messages": [{"message_id": "m1"}], "next_page_cursor": "c2", "total_count": 2},
            "c2": {"messages": [{"message_id": "m2"}], "next_page_cursor": None, "total_count": 2},
        }

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            return pages[params.get("search_after")]

        rows = _collect(manager, fetch, "email_logs")
        assert rows == [{"message_id": "m1"}, {"message_id": "m2"}]
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.cursor for s in manager.saved] == ["c2"]

    def test_email_logs_incremental_sends_sent_after_on_every_page(self) -> None:
        manager = _FakeResumableManager()
        seen_params: list[dict] = []
        pages = {
            None: {"messages": [{"message_id": "m1"}], "next_page_cursor": "c2"},
            "c2": {"messages": [{"message_id": "m2"}], "next_page_cursor": None},
        }

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            seen_params.append(params)
            return pages[params.get("search_after")]

        _collect(
            manager,
            fetch,
            "email_logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        # The server-side bound must ride along with the cursor, or later pages walk unbounded
        # through already-synced history.
        assert len(seen_params) == 2
        assert all(p.get("filters[sent_after]") == "2026-01-01T00:00:00Z" for p in seen_params)

    def test_email_logs_full_refresh_sends_no_time_filter(self) -> None:
        manager = _FakeResumableManager()
        seen_params: list[dict] = []

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            seen_params.append(params)
            return {"messages": [{"message_id": "m1"}], "next_page_cursor": None}

        _collect(manager, fetch, "email_logs")
        assert "filters[sent_after]" not in seen_params[0]

    def test_email_logs_resumes_from_saved_cursor(self) -> None:
        manager = _FakeResumableManager(MailtrapResumeConfig(cursor="c2"))
        seen_cursors: list[Optional[str]] = []

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            seen_cursors.append(params.get("search_after"))
            return {"messages": [{"message_id": "m2"}], "next_page_cursor": None}

        rows = _collect(manager, fetch, "email_logs")
        assert rows == [{"message_id": "m2"}]
        # The first page must never be re-fetched on resume.
        assert seen_cursors == ["c2"]

    def test_suppressions_paginates_by_last_row_id_until_short_page(self) -> None:
        manager = _FakeResumableManager()
        page_size = MAILTRAP_ENDPOINTS["suppressions"].page_size
        assert page_size is not None
        full_page = [{"id": f"s{i}"} for i in range(page_size)]
        short_page = [{"id": "last"}]

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            return short_page if params.get("last_id") == full_page[-1]["id"] else full_page

        rows = _collect(manager, fetch, "suppressions")
        assert len(rows) == page_size + 1
        # The cursor advances from the last row of the full page; the short page ends the sync.
        assert [s.cursor for s in manager.saved] == [full_page[-1]["id"]]

    def test_suppressions_incremental_sends_start_time(self) -> None:
        manager = _FakeResumableManager()
        seen_params: list[dict] = []

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            seen_params.append(params)
            return [{"id": "s1"}]

        _collect(
            manager,
            fetch,
            "suppressions",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        assert seen_params[0]["start_time"] == "2026-01-01T00:00:00Z"

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _FakeResumableManager()

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            return {"messages": [], "next_page_cursor": None}

        rows = _collect(manager, fetch, "email_logs")
        assert rows == []
        assert manager.saved == []

    @parameterized.expand(
        [
            ("email_templates", [{"id": 1}]),
            ("contact_lists", [{"id": 2, "name": "list"}]),
            ("accounts", [{"id": 3, "name": "acct"}]),
        ]
    )
    def test_unpaginated_bare_array_endpoints_fetch_once(self, endpoint: str, body: list[dict]) -> None:
        manager = _FakeResumableManager()
        calls: list[dict] = []

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            calls.append(params)
            return body

        rows = _collect(manager, fetch, endpoint)
        assert rows == body
        assert len(calls) == 1
        assert manager.saved == []

    def test_sending_domains_unwraps_data_key(self) -> None:
        manager = _FakeResumableManager()

        def fetch(session: Any, path: str, params: dict, logger: Any) -> Any:
            return {"data": [{"id": 1, "domain_name": "example.com"}]}

        rows = _collect(manager, fetch, "sending_domains")
        assert rows == [{"id": 1, "domain_name": "example.com"}]

    @parameterized.expand(
        [
            ("email_logs_bare_list", "email_logs", [{"message_id": "m1"}]),
            ("email_logs_missing_key", "email_logs", {"total_count": 0}),
            ("templates_wrapped", "email_templates", {"data": []}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, endpoint: str, body: Any) -> None:
        manager = _FakeResumableManager()
        with pytest.raises(MailtrapRetryableError):
            _collect(manager, lambda *args, **kwargs: body, endpoint)


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else []
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(MailtrapRetryableError):
            _fetch_page_unwrapped(session, "/api/email_logs", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/api/email_logs", {}, MagicMock())

    def test_success_returns_body_and_sends_params(self) -> None:
        body = {"messages": [{"message_id": "m1"}], "next_page_cursor": None}
        session = self._session_returning(200, body)
        params = {"search_after": "c2", "filters[sent_after]": "2026-01-01T00:00:00Z"}
        assert _fetch_page_unwrapped(session, "/api/email_logs", params, MagicMock()) == body
        args, kwargs = session.get.call_args
        assert args[0] == f"{MAILTRAP_BASE_URL}/api/email_logs"
        assert kwargs["params"] == params


class TestCheckAccess:
    def _session(self, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Mailtrap returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(mailtrap, "make_tracked_session", return_value=self._session(response)):
            assert check_access("token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(mailtrap, "make_tracked_session", return_value=session):
            status, message = check_access("token")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Mailtrap API token"),
            ("forbidden", 403, False, "Invalid Mailtrap API token"),
            ("server_error", 500, False, "Mailtrap returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(mailtrap, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("token") == (expected_valid, expected_message)


class TestMailtrapSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = mailtrap_source(
            api_token="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        config = MAILTRAP_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.incremental_param:
            # The watermark must only commit once a sync completes: email_logs is documented
            # newest-first and suppressions ordering is undocumented.
            assert response.sort_mode == "desc"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None

    def test_email_logs_primary_key_is_message_id(self) -> None:
        assert MAILTRAP_ENDPOINTS["email_logs"].primary_keys == ["message_id"]
