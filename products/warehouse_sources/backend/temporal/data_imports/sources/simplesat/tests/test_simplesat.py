from typing import Any, Optional

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat import simplesat
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.settings import (
    ENDPOINTS,
    SIMPLESAT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.simplesat import (
    SIMPLESAT_BASE_URL,
    SimplesatResumeConfig,
    SimplesatRetryableError,
    check_access,
    get_rows,
    simplesat_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = simplesat._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SimplesatResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SimplesatResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SimplesatResumeConfig | None:
        return self._state

    def save_state(self, data: SimplesatResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[Optional[str], tuple[list[dict], Optional[str]]],
        endpoint: str = "surveys",
    ) -> list[dict]:
        # Keyed by `next_url` (None for the first request), value is (items, next_url) for that page.
        seen_urls: list[str] = []

        def fake_fetch(
            session: Any,
            method: str,
            url: str,
            list_key: str,
            params: Any,
            json_body: Any,
            logger: Any,
        ) -> tuple[list[dict], Optional[str]]:
            seen_urls.append(url)
            # On the first request `params` is set; on cursor follow-ups it is None.
            key = url if url in pages else None
            return pages[key]

        monkeypatch.setattr(simplesat, "_fetch_page", fake_fetch)
        monkeypatch.setattr(simplesat, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="ss-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_with_null_next_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"id": 1}, {"id": 2}], None)})
        assert rows == [{"id": 1}, {"id": 2}]
        # `next` is null, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_next_url_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        next_url = f"{SIMPLESAT_BASE_URL}/surveys?page=2&page_size=100"
        pages: dict[Optional[str], tuple[list[dict], Optional[str]]] = {
            None: ([{"id": 1}], next_url),
            next_url: ([{"id": 2}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}]
        # State is saved with the cursor after the first page, then we stop on the null `next`.
        assert [s.next_url for s in manager.saved] == [next_url]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        next_url = f"{SIMPLESAT_BASE_URL}/surveys?page=2&page_size=100"
        manager = _FakeResumableManager(SimplesatResumeConfig(next_url=next_url))
        # The first page URL must never be fetched on resume.
        pages: dict[Optional[str], tuple[list[dict], Optional[str]]] = {next_url: ([{"id": 5}], None)}
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 5}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], None)})
        assert rows == []
        assert manager.saved == []

    def test_off_origin_next_url_raises(self, monkeypatch: Any) -> None:
        # A pagination cursor pointing off the Simplesat API origin must not be followed — it would
        # leak the customer's API key to another host.
        manager = _FakeResumableManager()
        evil = "https://evil.example.com/api/v1/surveys?page=2"
        with pytest.raises(SimplesatRetryableError):
            self._collect(manager, monkeypatch, {None: ([{"id": 1}], evil)})

    def test_off_origin_resume_url_raises(self, monkeypatch: Any) -> None:
        # A tampered saved cursor is rejected before any request is made.
        evil = "https://evil.example.com/api/v1/surveys?page=2"
        manager = _FakeResumableManager(SimplesatResumeConfig(next_url=evil))
        with pytest.raises(SimplesatRetryableError):
            self._collect(manager, monkeypatch, {evil: ([{"id": 5}], None)})


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"surveys": []}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        session.post.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(SimplesatRetryableError):
            _fetch_page_unwrapped(session, "GET", f"{SIMPLESAT_BASE_URL}/surveys", "surveys", {}, None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "GET", f"{SIMPLESAT_BASE_URL}/surveys", "surveys", {}, None, MagicMock())

    def test_success_extracts_list_and_next(self) -> None:
        body = {"surveys": [{"id": 1}], "count": 1, "next": None, "previous": None}
        session = self._session_returning(200, body)
        items, next_url = _fetch_page_unwrapped(
            session, "GET", f"{SIMPLESAT_BASE_URL}/surveys", "surveys", {}, None, MagicMock()
        )
        assert items == [{"id": 1}]
        assert next_url is None

    def test_success_returns_next_url(self) -> None:
        next_url = f"{SIMPLESAT_BASE_URL}/surveys?page=2"
        body = {"surveys": [{"id": 1}], "next": next_url}
        session = self._session_returning(200, body)
        _items, returned = _fetch_page_unwrapped(
            session, "GET", f"{SIMPLESAT_BASE_URL}/surveys", "surveys", {}, None, MagicMock()
        )
        assert returned == next_url

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": 1}])
        with pytest.raises(SimplesatRetryableError):
            _fetch_page_unwrapped(session, "GET", f"{SIMPLESAT_BASE_URL}/surveys", "surveys", {}, None, MagicMock())

    def test_non_list_resource_key_is_retryable(self) -> None:
        session = self._session_returning(200, {"surveys": {"nope": 1}})
        with pytest.raises(SimplesatRetryableError):
            _fetch_page_unwrapped(session, "GET", f"{SIMPLESAT_BASE_URL}/surveys", "surveys", {}, None, MagicMock())

    def test_missing_resource_key_is_retryable(self) -> None:
        # A response envelope without the resource key must fail loudly rather than sync zero rows.
        session = self._session_returning(200, {"count": 0, "next": None})
        with pytest.raises(SimplesatRetryableError):
            _fetch_page_unwrapped(session, "GET", f"{SIMPLESAT_BASE_URL}/surveys", "surveys", {}, None, MagicMock())

    def test_post_endpoint_uses_post_with_json_body(self) -> None:
        body = {"answers": [{"id": 1}], "next": None}
        session = self._session_returning(200, body)
        url = f"{SIMPLESAT_BASE_URL}/answers/search"
        items, _next = _fetch_page_unwrapped(session, "POST", url, "answers", {"page_size": 100}, {}, MagicMock())
        assert items == [{"id": 1}]
        session.post.assert_called_once()
        _, kwargs = session.post.call_args
        assert kwargs["json"] == {}
        session.get.assert_not_called()


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(simplesat, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, ok, expected_status, expected_message",
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Simplesat returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, ok: bool, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._patch_session(monkeypatch, response)
        assert check_access("ss-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("ss-key")
        assert status == 0
        assert message is not None and "boom" in message

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Simplesat API key"),
            (403, False, "Invalid Simplesat API key"),
            (500, False, "Simplesat returned HTTP 500"),
        ],
    )
    def test_validate_credentials(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._patch_session(monkeypatch, response)
        assert validate_credentials("ss-key") == (expected_valid, expected_message)


class TestSimplesatSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = simplesat_source(
            api_key="ss-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SIMPLESAT_ENDPOINTS.values())
        assert set(SIMPLESAT_ENDPOINTS) == set(ENDPOINTS)

    def test_list_key_matches_endpoint_name(self) -> None:
        assert all(config.list_key == config.name for config in SIMPLESAT_ENDPOINTS.values())
