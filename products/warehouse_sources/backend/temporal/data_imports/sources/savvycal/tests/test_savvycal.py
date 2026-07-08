from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal import savvycal
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.savvycal import (
    SAVVYCAL_BASE_URL,
    SavvyCalResumeConfig,
    SavvyCalRetryableError,
    check_access,
    get_rows,
    savvycal_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.settings import (
    ENDPOINTS,
    SAVVYCAL_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = savvycal._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SavvyCalResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SavvyCalResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SavvyCalResumeConfig | None:
        return self._state

    def save_state(self, data: SavvyCalResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        pages: dict[str | None, tuple[list[dict], Optional[str]]],
        endpoint: str = "events",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        requested_params: list[dict[str, Any]] = []

        def fake_fetch(
            session: Any, path: str, params: dict[str, Any], logger: Any
        ) -> tuple[list[dict], Optional[str]]:
            requested_params.append(params)
            return pages[params.get("after")]

        rows: list[dict] = []
        with (
            patch.object(savvycal, "_fetch_page", fake_fetch),
            patch.object(savvycal, "make_tracked_session", return_value=MagicMock()),
        ):
            for batch in get_rows(
                api_key="pt_secret_key",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ):
                rows.extend(batch)
        return rows, requested_params

    def test_single_page_yields_and_stops(self) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, {None: ([{"id": "a"}, {"id": "b"}], None)})
        assert rows == [{"id": "a"}, {"id": "b"}]
        # A null after cursor ends the sync without persisting resume state.
        assert manager.saved == []

    def test_follows_after_cursor_until_null(self) -> None:
        manager = _FakeResumableManager()
        pages: dict[str | None, tuple[list[dict], Optional[str]]] = {
            None: ([{"id": "a"}], "cur_2"),
            "cur_2": ([{"id": "b"}], None),
        }
        rows, params = self._collect(manager, pages)
        assert rows == [{"id": "a"}, {"id": "b"}]
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.after for s in manager.saved] == ["cur_2"]
        # The first request must not carry an after param; the second must.
        assert "after" not in params[0]
        assert params[1]["after"] == "cur_2"

    def test_resumes_from_saved_cursor(self) -> None:
        manager = _FakeResumableManager(SavvyCalResumeConfig(after="cur_2"))
        # The first page must never be fetched on resume.
        rows, _ = self._collect(manager, {"cur_2": ([{"id": "b"}], None)})
        assert rows == [{"id": "b"}]

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, {None: ([], None)})
        assert rows == []
        assert manager.saved == []

    def test_events_full_refresh_widens_default_filters(self) -> None:
        # SavvyCal defaults to period=upcoming, state=confirmed, attendance=attending — any of
        # those silently drops most of the account's history from a warehouse import.
        _, params = self._collect(_FakeResumableManager(), {None: ([], None)})
        assert params[0]["period"] == "all"
        assert params[0]["state"] == "all"
        assert params[0]["attendance"] == "any"
        assert params[0]["direction"] == "asc"
        assert params[0]["limit"] == 100
        assert "from" not in params[0]

    @parameterized.expand(
        [
            ("datetime", datetime(2026, 3, 5, 14, 30, tzinfo=UTC), "2026-03-05"),
            ("date", date(2026, 3, 5), "2026-03-05"),
        ]
    )
    def test_events_incremental_maps_watermark_to_fixed_window(
        self, _name: str, watermark: Any, expected_from: str
    ) -> None:
        _, params = self._collect(
            _FakeResumableManager(),
            {None: ([], None)},
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        assert params[0]["period"] == "fixed"
        assert params[0]["from"] == expected_from

    def test_resume_reuses_saved_from_bound_over_new_watermark(self) -> None:
        # The saved cursor was minted under the original `from` bound; recomputing it from an
        # advanced watermark would pair the cursor with a different query.
        manager = _FakeResumableManager(SavvyCalResumeConfig(after="cur_2", from_date="2026-01-01"))
        pages: dict[str | None, tuple[list[dict], Optional[str]]] = {
            "cur_2": ([{"id": "b"}], "cur_3"),
            "cur_3": ([], None),
        }
        _, params = self._collect(
            manager,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert all(p["from"] == "2026-01-01" for p in params)
        # The re-saved state carries the same original bound forward.
        assert manager.saved[0].from_date == "2026-01-01"

    def test_webhooks_secret_is_redacted(self) -> None:
        # The webhook signing secret must never reach the warehouse table.
        manager = _FakeResumableManager()
        rows, _ = self._collect(
            manager,
            {None: ([{"id": "wbhk_1", "url": "https://x", "secret": "whsec_leak"}], None)},
            endpoint="webhooks",
        )
        assert rows == [{"id": "wbhk_1", "url": "https://x"}]

    def test_non_events_endpoint_sends_no_event_filters(self) -> None:
        _, params = self._collect(_FakeResumableManager(), {None: ([], None)}, endpoint="links")
        assert params[0] == {"limit": 100}

    def test_incremental_flag_ignored_for_full_refresh_endpoint(self) -> None:
        _, params = self._collect(
            _FakeResumableManager(),
            {None: ([], None)},
            endpoint="webhooks",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert "from" not in params[0]
        assert "period" not in params[0]


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"entries": [], "metadata": {"after": None}}
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
        with pytest.raises(SavvyCalRetryableError):
            _fetch_page_unwrapped(session, "/events", {"limit": 100}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("bad_request", 400)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/events", {"limit": 100}, MagicMock())

    def test_success_returns_entries_and_after_cursor(self) -> None:
        body = {"entries": [{"id": "a"}], "metadata": {"after": "cur_2", "before": None, "limit": 100}}
        session = self._session_returning(200, body)
        rows, after = _fetch_page_unwrapped(session, "/events", {"limit": 100}, MagicMock())
        assert rows == [{"id": "a"}]
        assert after == "cur_2"
        args, kwargs = session.get.call_args
        assert args[0] == f"{SAVVYCAL_BASE_URL}/events"
        assert kwargs["params"] == {"limit": 100}

    def test_null_after_returns_none(self) -> None:
        body = {"entries": [{"id": "a"}], "metadata": {"after": None, "before": "cur_1", "limit": 100}}
        session = self._session_returning(200, body)
        _, after = _fetch_page_unwrapped(session, "/events", {"limit": 100}, MagicMock())
        assert after is None

    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_entries", {"metadata": {"after": None}})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(SavvyCalRetryableError):
            _fetch_page_unwrapped(session, "/links", {"limit": 100}, MagicMock())


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
            ("server_error", 500, False, 500, "SavvyCal returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(savvycal, "make_tracked_session", return_value=self._session(response)):
            assert check_access("pt_secret_key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(savvycal, "make_tracked_session", return_value=session):
            status, message = check_access("pt_secret_key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid SavvyCal personal access token"),
            ("forbidden", 403, False, "Invalid SavvyCal personal access token"),
            ("server_error", 500, False, "SavvyCal returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(savvycal, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("pt_secret_key") == (expected_valid, expected_message)


class TestSavvyCalSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = savvycal_source(
            api_key="pt_secret_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    def test_events_partition_on_stable_created_at(self) -> None:
        response = savvycal_source(
            api_key="pt_secret_key", endpoint="events", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        # start_at moves on reschedule; partitioning must stay on the immutable creation timestamp.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_links_have_no_partitioning(self) -> None:
        # The Link schema exposes no creation timestamp to partition on.
        response = savvycal_source(
            api_key="pt_secret_key", endpoint="links", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SAVVYCAL_ENDPOINTS.values())
        assert set(SAVVYCAL_ENDPOINTS) == set(ENDPOINTS)
