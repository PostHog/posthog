from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous import tremendous
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.settings import (
    ENDPOINTS,
    TREMENDOUS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.tremendous import (
    TremendousResumeConfig,
    TremendousRetryableError,
    _to_iso_datetime,
    base_url_for_environment,
    check_access,
    get_rows,
    tremendous_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = tremendous._fetch_page.__wrapped__  # type: ignore[attr-defined]

ORDERS_PAGE_SIZE = TREMENDOUS_ENDPOINTS["orders"].page_size


class _FakeResumableManager:
    def __init__(self, state: TremendousResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TremendousResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TremendousResumeConfig | None:
        return self._state

    def save_state(self, data: TremendousResumeConfig) -> None:
        self.saved.append(data)


def _page(size: int) -> list[dict]:
    return [{"id": f"ID{i}"} for i in range(size)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[int, list[dict]],
        endpoint: str = "orders",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        requested_params: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, data_key: str, params: dict[str, Any], logger: Any) -> list[dict]:
            requested_params.append(params)
            return pages[params["offset"]] if "offset" in params else pages[0]

        monkeypatch.setattr(tremendous, "_fetch_page", fake_fetch)
        monkeypatch.setattr(tremendous, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="tremendous-key",
            environment="production",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(batch)
        return rows, requested_params

    def test_pins_redirects_off(self, monkeypatch: Any) -> None:
        # Redirect-following would replay the Bearer key to whatever host Tremendous redirects to.
        captured: list[dict[str, Any]] = []

        def fake_session(**kwargs: Any) -> Any:
            captured.append(kwargs)
            return MagicMock()

        monkeypatch.setattr(tremendous, "_fetch_page", lambda *a, **k: [])
        monkeypatch.setattr(tremendous, "make_tracked_session", fake_session)
        list(
            get_rows(
                api_key="tremendous-key",
                environment="production",
                endpoint="orders",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert captured and captured[0]["allow_redirects"] is False

    def test_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, params = self._collect(manager, monkeypatch, {0: [{"id": "A"}, {"id": "B"}]})
        assert rows == [{"id": "A"}, {"id": "B"}]
        assert params == [{"limit": ORDERS_PAGE_SIZE, "offset": 0}]
        # The page was short, so we stopped without persisting resume state.
        assert manager.saved == []

    def test_advances_offset_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {0: _page(ORDERS_PAGE_SIZE), ORDERS_PAGE_SIZE: [{"id": "LAST"}]}
        rows, params = self._collect(manager, monkeypatch, pages)
        assert len(rows) == ORDERS_PAGE_SIZE + 1
        assert [p["offset"] for p in params] == [0, ORDERS_PAGE_SIZE]
        # State is saved after yielding the full first page, then the short page terminates.
        assert [s.offset for s in manager.saved] == [ORDERS_PAGE_SIZE]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(TremendousResumeConfig(offset=1000))
        rows, params = self._collect(manager, monkeypatch, {1000: [{"id": "X"}]})
        assert rows == [{"id": "X"}]
        # The initial (offset=0) page must never be re-fetched on resume.
        assert [p["offset"] for p in params] == [1000]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, {0: []})
        assert rows == []
        assert manager.saved == []

    def test_incremental_watermark_sent_as_created_at_gte_on_every_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        watermark = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        pages = {0: _page(ORDERS_PAGE_SIZE), ORDERS_PAGE_SIZE: []}
        _, params = self._collect(
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        assert all(p["created_at[gte]"] == "2026-01-02T03:04:05+00:00" for p in params)

    def test_full_refresh_sends_no_created_at_filter(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, params = self._collect(manager, monkeypatch, {0: [{"id": "A"}]})
        assert all("created_at[gte]" not in p for p in params)

    def test_unpaginated_endpoint_fetches_once_without_params(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, params = self._collect(manager, monkeypatch, {0: [{"id": "M1"}, {"id": "M2"}]}, endpoint="members")
        assert rows == [{"id": "M1"}, {"id": "M2"}]
        assert params == [{}]
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"orders": [], "total_count": 0}
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
        with pytest.raises(TremendousRetryableError):
            _fetch_page_unwrapped(session, "https://www.tremendous.com/api/v2/orders", "orders", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://www.tremendous.com/api/v2/orders", "orders", {}, MagicMock())

    def test_success_returns_items_under_data_key(self) -> None:
        session = self._session_returning(200, {"orders": [{"id": "A"}], "total_count": 1})
        items = _fetch_page_unwrapped(session, "https://www.tremendous.com/api/v2/orders", "orders", {}, MagicMock())
        assert items == [{"id": "A"}]

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "A"}]),
            ("missing_data_key", {"total_count": 0}),
            ("data_key_not_a_list", {"orders": {"id": "A"}}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(TremendousRetryableError):
            _fetch_page_unwrapped(session, "https://www.tremendous.com/api/v2/orders", "orders", {}, MagicMock())


class TestHelpers:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05+00:00"),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05+00:00"),
            ("date", date(2026, 1, 2), "2026-01-02T00:00:00+00:00"),
            ("string_passthrough", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
            ("none", None, None),
            ("empty_string", "", None),
        ]
    )
    def test_to_iso_datetime(self, _name: str, value: Any, expected: str | None) -> None:
        assert _to_iso_datetime(value) == expected

    @parameterized.expand(
        [
            ("production", "https://www.tremendous.com/api/v2"),
            ("sandbox", "https://testflight.tremendous.com/api/v2"),
            # Unknown values fall back to production rather than building a bad URL.
            ("bogus", "https://www.tremendous.com/api/v2"),
        ]
    )
    def test_base_url_for_environment(self, environment: str, expected: str) -> None:
        assert base_url_for_environment(environment) == expected


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
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
            ("server_error", 500, False, 500, "Tremendous returned HTTP 500"),
        ]
    )
    @patch(f"{tremendous.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_session.return_value = self._session(response)
        assert check_access("tremendous-key", "production") == (expected_status, expected_message)

    @patch(f"{tremendous.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("tremendous-key", "production")
        assert status == 0
        assert message is not None and "boom" in message

    @patch(f"{tremendous.__name__}.make_tracked_session")
    def test_pins_redirects_off(self, mock_session: MagicMock) -> None:
        # Redirect-following would replay the Bearer key to whatever host Tremendous redirects to.
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        mock_session.return_value = self._session(response)
        check_access("tremendous-key", "production")
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @patch(f"{tremendous.__name__}.make_tracked_session")
    def test_probe_targets_selected_environment(self, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        session = self._session(response)
        mock_session.return_value = session
        check_access("tremendous-key", "sandbox")
        url = session.get.call_args.args[0]
        assert url.startswith("https://testflight.tremendous.com/api/v2")

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Tremendous API key (check that it matches the selected environment)"),
            ("forbidden", 403, False, "Invalid Tremendous API key (check that it matches the selected environment)"),
            ("server_error", 500, False, "Tremendous returned HTTP 500"),
        ]
    )
    @patch(f"{tremendous.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("tremendous-key", "production") == (expected_valid, expected_message)


class TestTremendousSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = tremendous_source(
            api_key="tremendous-key",
            environment="production",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Tremendous lists are creation-date DESC; declaring asc would corrupt the incremental watermark.
        assert response.sort_mode == "desc"
        if TREMENDOUS_ENDPOINTS[endpoint].partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["created_at"]
        else:
            assert response.partition_mode is None

    def test_partition_keys_are_stable_creation_timestamps(self) -> None:
        # Partition keys must never be updated_at-style fields, which rewrite partitions every sync.
        assert {c.partition_key for c in TREMENDOUS_ENDPOINTS.values()} == {"created_at", None}
