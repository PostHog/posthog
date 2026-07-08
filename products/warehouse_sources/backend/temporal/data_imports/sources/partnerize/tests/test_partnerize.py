from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize import partnerize
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.partnerize import (
    DEFAULT_START_DATE,
    PARTNERIZE_BASE_URL,
    PartnerizeResumeConfig,
    PartnerizeRetryableError,
    _format_start_date,
    _unwrap_rows,
    check_access,
    get_rows,
    partnerize_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import (
    ENDPOINTS,
    PARTNERIZE_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_get_json_unwrapped = partnerize._get_json.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: PartnerizeResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PartnerizeResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PartnerizeResumeConfig | None:
        return self._state

    def save_state(self, data: PartnerizeResumeConfig) -> None:
        self.saved.append(data)


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2020, 3, 8, 17, 18, 33, tzinfo=UTC), "2020-03-08T17:18:33Z"),
            ("naive_datetime", datetime(2020, 3, 8, 17, 18, 33), "2020-03-08T17:18:33Z"),
            ("date", date(2020, 3, 8), "2020-03-08T00:00:00Z"),
            # Watermarks read back from the warehouse arrive as strings in Partnerize's own format.
            ("api_format_string", "2020-03-08 17:18:33", "2020-03-08T17:18:33Z"),
            ("iso_string", "2020-03-08T17:18:33+00:00", "2020-03-08T17:18:33Z"),
            ("unparseable_string", "not a date at all 12345 67890", DEFAULT_START_DATE),
            ("none", None, DEFAULT_START_DATE),
        ]
    )
    def test_coerces_watermark_to_iso_z(self, _name: str, value: Any, expected: str) -> None:
        assert _format_start_date(value) == expected


class TestUnwrapRows:
    def test_strips_single_key_item_wrapper(self) -> None:
        data = {"campaigns": [{"campaign": {"campaign_id": "10l176", "title": "Demo"}}]}
        rows = _unwrap_rows(data, PARTNERIZE_ENDPOINTS["campaigns"])
        assert rows == [{"campaign_id": "10l176", "title": "Demo"}]

    def test_missing_wrapper_key_yields_item_as_is(self) -> None:
        # Defensive: if the API returns flat rows, they pass through unmodified.
        data = {"conversions": [{"conversion_id": "111111l314"}]}
        rows = _unwrap_rows(data, PARTNERIZE_ENDPOINTS["conversions"])
        assert rows == [{"conversion_id": "111111l314"}]

    def test_missing_data_key_is_retryable(self) -> None:
        with pytest.raises(PartnerizeRetryableError):
            _unwrap_rows({"count": 0}, PARTNERIZE_ENDPOINTS["clicks"])


class TestGetJson:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {}
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
        with pytest.raises(PartnerizeRetryableError):
            _get_json_unwrapped(session, "https://api.partnerize.com/reference/country", None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _get_json_unwrapped(session, "https://api.partnerize.com/reference/country", None, MagicMock())

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": 1}])
        with pytest.raises(PartnerizeRetryableError):
            _get_json_unwrapped(session, "https://api.partnerize.com/reference/country", None, MagicMock())


def _collect_rows(
    monkeypatch: Any,
    manager: _FakeResumableManager,
    responses: list[dict[str, Any]],
    endpoint: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> tuple[list[dict], list[tuple[str, dict | None]]]:
    """Run get_rows against queued fake responses, returning (rows, requests made)."""
    calls: list[tuple[str, dict | None]] = []
    queue = list(responses)

    def fake_get_json(session: Any, url: str, params: dict | None, logger: Any) -> dict[str, Any]:
        calls.append((url, params))
        return queue.pop(0)

    monkeypatch.setattr(partnerize, "_get_json", fake_get_json)
    monkeypatch.setattr(partnerize, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        application_key="app-key",
        user_api_key="api-key",
        publisher_id="111111l92",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    ):
        rows.extend(batch)
    return rows, calls


def _conversion_page(ids: list[str], limit: int) -> dict[str, Any]:
    return {
        "conversions": [{"conversion_data": {"conversion_id": i}} for i in ids],
        "limit": limit,
        "count": len(ids),
    }


class TestReportRows:
    def test_paginates_by_offset_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = [_conversion_page(["a", "b"], limit=2), _conversion_page(["c"], limit=2)]
        rows, calls = _collect_rows(monkeypatch, manager, pages, "conversions")

        assert [r["conversion_id"] for r in rows] == ["a", "b", "c"]
        assert [params["offset"] for _, params in calls if params] == [0, 2]
        # State is saved after the full first page is yielded, then the short page terminates.
        assert [s.offset for s in manager.saved] == [2]

    def test_short_first_page_stops_without_saving(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, calls = _collect_rows(monkeypatch, manager, [_conversion_page(["a"], limit=300)], "conversions")
        assert len(rows) == 1
        assert len(calls) == 1
        assert manager.saved == []

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PartnerizeResumeConfig(offset=600))
        _, calls = _collect_rows(monkeypatch, manager, [_conversion_page([], limit=300)], "conversions")
        assert calls[0][1] is not None and calls[0][1]["offset"] == 600

    def test_full_refresh_uses_default_start_date(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect_rows(monkeypatch, manager, [_conversion_page([], limit=300)], "conversions")
        assert calls[0][1] is not None and calls[0][1]["start_date"] == DEFAULT_START_DATE

    def test_incremental_windows_from_watermark(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect_rows(
            monkeypatch,
            manager,
            [_conversion_page([], limit=300)],
            "conversions",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01 12:00:00",
            incremental_field="conversion_time",
        )
        params = calls[0][1]
        assert params is not None
        assert params["start_date"] == "2024-05-01T12:00:00Z"
        # The default window filters on the conversion time, no date_type override needed.
        assert "date_type" not in params

    def test_last_modified_cursor_sets_date_type(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect_rows(
            monkeypatch,
            manager,
            [_conversion_page([], limit=300)],
            "conversions",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01 12:00:00",
            incremental_field="last_modified",
        )
        params = calls[0][1]
        assert params is not None and params["date_type"] == "last_updated"

    def test_report_url_contains_publisher_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect_rows(monkeypatch, manager, [_conversion_page([], limit=300)], "conversions")
        assert calls[0][0] == f"{PARTNERIZE_BASE_URL}/reporting/report_publisher/publisher/111111l92/conversion.json"


class TestListRows:
    def test_follows_hypermedia_next_page_and_saves_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        next_url = f"{PARTNERIZE_BASE_URL}/reference/country?page=2"
        pages: list[dict[str, Any]] = [
            {
                "countries": [{"country": {"ref_country_id": 1}}],
                "hypermedia": {"pagination": {"next_page": next_url}},
            },
            {"countries": [{"country": {"ref_country_id": 2}}]},
        ]
        rows, calls = _collect_rows(monkeypatch, manager, pages, "countries")

        assert [r["ref_country_id"] for r in rows] == [1, 2]
        assert calls[1][0] == next_url
        assert [s.next_url for s in manager.saved] == [next_url]

    def test_relative_next_page_is_resolved_against_base(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: list[dict[str, Any]] = [
            {
                "campaigns": [{"campaign": {"campaign_id": "10l1"}}],
                "hypermedia": {"pagination": {"next_page": "/user/publisher/111111l92/campaign/a?page=2"}},
            },
            {"campaigns": []},
        ]
        _, calls = _collect_rows(monkeypatch, manager, pages, "campaigns")
        assert calls[1][0] == f"{PARTNERIZE_BASE_URL}/user/publisher/111111l92/campaign/a?page=2"

    def test_single_page_stops_without_saving(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, calls = _collect_rows(
            monkeypatch, manager, [{"countries": [{"country": {"ref_country_id": 1}}]}], "countries"
        )
        assert len(rows) == 1
        assert len(calls) == 1
        assert manager.saved == []

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = f"{PARTNERIZE_BASE_URL}/reference/country?page=5"
        manager = _FakeResumableManager(PartnerizeResumeConfig(next_url=resume_url))
        _, calls = _collect_rows(monkeypatch, manager, [{"countries": []}], "countries")
        assert calls[0][0] == resume_url


class TestPartnerizeSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = partnerize_source(
            application_key="app-key",
            user_api_key="api-key",
            publisher_id="111111l92",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        config = PARTNERIZE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.kind == "report":
            # The reports document no ordering guarantee, so the watermark only commits on completion.
            assert response.sort_mode == "desc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None


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
            ("not_found", 404, False, 404, None),
            ("server_error", 500, False, 500, "Partnerize returned HTTP 500"),
        ]
    )
    @patch(f"{partnerize.__name__}.make_tracked_session")
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
        assert check_access("app-key", "api-key", "111111l92") == (expected_status, expected_message)

    @patch(f"{partnerize.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("app-key", "api-key", "111111l92")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("not_found", 404, False),
            ("server_error", 500, False),
        ]
    )
    @patch(f"{partnerize.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        valid, message = validate_credentials("app-key", "api-key", "111111l92")
        assert valid is expected_valid
        assert (message is None) is expected_valid
