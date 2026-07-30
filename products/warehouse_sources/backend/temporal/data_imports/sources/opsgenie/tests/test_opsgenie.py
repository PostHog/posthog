from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.opsgenie import (
    PAGE_SIZE,
    OpsgenieResumeConfig,
    _build_params,
    _get_headers,
    _to_epoch_ms,
    get_rows,
    opsgenie_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.settings import OPSGENIE_ENDPOINTS

OPSGENIE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.opsgenie"


class FakeResumableManager:
    """In-memory stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, resume_state: Optional[OpsgenieResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[OpsgenieResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[OpsgenieResumeConfig]:
        return self._resume_state

    def save_state(self, data: OpsgenieResumeConfig) -> None:
        self.saved_states.append(data)


def _mock_response(status_code: int = 200, body: Any = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = text
    response.json.return_value = body if body is not None else {}
    if not response.ok:
        error_response = requests.Response()
        error_response.status_code = status_code
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: error for url: https://api.opsgenie.com", response=error_response
        )
    return response


def _patch_session(get_side_effect: Any) -> Any:
    session = MagicMock()
    session.get.side_effect = get_side_effect
    return patch(f"{OPSGENIE_MODULE}.make_tracked_session", return_value=session), session


def _page(items: list[dict], has_next: bool) -> MagicMock:
    body: dict[str, Any] = {"data": items}
    if has_next:
        body["paging"] = {"next": "https://api.opsgenie.com/v2/alerts?offset=next"}
    return _mock_response(200, body=body)


def _query_params(call: Any) -> dict[str, list[str]]:
    return parse_qs(urlparse(call.args[0]).query)


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094000),
            (datetime(2026, 3, 4, 2, 58, 14), 1772593094000),
            (date(2026, 3, 4), 1772582400000),
            ("2026-03-04T02:58:14Z", 1772593094000),
            ("2026-03-04T02:58:14+00:00", 1772593094000),
            (1772593094000, 1772593094000),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_conversion(self, value: Any, expected: Optional[int]) -> None:
        assert _to_epoch_ms(value) == expected


class TestHeaders:
    def test_genie_key_auth_header(self) -> None:
        assert _get_headers("key_abc")["Authorization"] == "GenieKey key_abc"


class TestBuildParams:
    def test_search_endpoint_full_refresh_sends_stable_sort_without_query(self) -> None:
        params = _build_params(
            OPSGENIE_ENDPOINTS["alerts"],
            offset=0,
            window_start_ms=None,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params == {"limit": PAGE_SIZE, "offset": 0, "sort": "createdAt", "order": "asc"}

    def test_search_endpoint_incremental_sends_created_at_query(self) -> None:
        params = _build_params(
            OPSGENIE_ENDPOINTS["alerts"],
            offset=200,
            window_start_ms=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert params["offset"] == 200
        assert params["query"] == "createdAt >= 1767225600000"

    def test_window_takes_precedence_over_incremental_cursor(self) -> None:
        params = _build_params(
            OPSGENIE_ENDPOINTS["alerts"],
            offset=0,
            window_start_ms=1800000000000,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert params["query"] == "createdAt >= 1800000000000"

    def test_non_search_endpoint_sends_no_sort_or_query(self) -> None:
        params = _build_params(
            OPSGENIE_ENDPOINTS["users"],
            offset=0,
            window_start_ms=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert params == {"limit": PAGE_SIZE, "offset": 0}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (422, False, 422),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        ctx, _ = _patch_session([_mock_response(status_code, body={}, text="boom")])
        with ctx:
            ok, status, _error = validate_credentials("key", "us")
        assert ok is expected_ok
        assert status == expected_status

    def test_transport_failure_returns_zero_status(self) -> None:
        ctx, _ = _patch_session(requests.ConnectionError("no network"))
        with ctx:
            ok, status, error = validate_credentials("key", "us")
        assert ok is False
        assert status == 0
        assert error == "no network"

    def test_uses_endpoint_path_when_schema_given(self) -> None:
        ctx, session = _patch_session([_mock_response(200)])
        with ctx:
            validate_credentials("key", "us", endpoint="incidents")
        assert session.get.call_args.args[0].startswith("https://api.opsgenie.com/v1/incidents?")

    @pytest.mark.parametrize(
        "region,expected_host",
        [
            ("us", "https://api.opsgenie.com"),
            ("eu", "https://api.eu.opsgenie.com"),
            ("unknown", "https://api.opsgenie.com"),
        ],
    )
    def test_region_selects_base_url(self, region: str, expected_host: str) -> None:
        ctx, session = _patch_session([_mock_response(200)])
        with ctx:
            validate_credentials("key", region)
        assert session.get.call_args.args[0].startswith(expected_host)


class TestGetRows:
    def test_paginates_and_yields_lists_of_dicts(self) -> None:
        page1 = _page([{"id": str(i)} for i in range(PAGE_SIZE)], has_next=True)
        page2 = _page([{"id": "last"}], has_next=False)
        manager = FakeResumableManager()

        ctx, session = _patch_session([page1, page2])
        with ctx:
            batches = list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        assert len(batches) == 2
        assert batches[1] == [{"id": "last"}]
        assert session.get.call_count == 2
        assert _query_params(session.get.call_args_list[1])["offset"] == [str(PAGE_SIZE)]

    def test_saves_state_after_yielding_each_page(self) -> None:
        page1 = _page([{"id": str(i)} for i in range(PAGE_SIZE)], has_next=True)
        page2 = _page([{"id": "last"}], has_next=False)
        manager = FakeResumableManager()

        ctx, _ = _patch_session([page1, page2])
        with ctx:
            list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        # State is checkpointed once (the next offset) after the first page is yielded;
        # the final page has no next link so no further checkpoint is written.
        assert [s.offset for s in manager.saved_states] == [PAGE_SIZE]

    def test_resumes_from_saved_offset_and_window(self) -> None:
        manager = FakeResumableManager(
            resume_state=OpsgenieResumeConfig(offset=PAGE_SIZE, window_start_ms=1700000000000)
        )
        page = _page([{"id": "x"}], has_next=False)

        ctx, session = _patch_session([page])
        with ctx:
            list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        params = _query_params(session.get.call_args_list[0])
        assert params["offset"] == [str(PAGE_SIZE)]
        assert params["query"] == ["createdAt >= 1700000000000"]

    def test_empty_page_stops_iteration(self) -> None:
        page = _page([], has_next=True)
        manager = FakeResumableManager()

        ctx, session = _patch_session([page])
        with ctx:
            batches = list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == []
        assert session.get.call_count == 1

    def test_full_page_without_next_link_stops_iteration(self) -> None:
        page = _page([{"id": str(i)} for i in range(PAGE_SIZE)], has_next=False)
        manager = FakeResumableManager()

        ctx, session = _patch_session([page])
        with ctx:
            batches = list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        assert len(batches) == 1
        assert session.get.call_count == 1

    def test_non_paginated_endpoint_fetches_once_without_state(self) -> None:
        page = _mock_response(200, body={"data": [{"id": "team_1"}]})
        manager = FakeResumableManager()

        ctx, session = _patch_session([page])
        with ctx:
            batches = list(get_rows("key", "us", "teams", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "team_1"}]]
        assert session.get.call_count == 1
        assert manager.saved_states == []
        assert "offset" not in _query_params(session.get.call_args_list[0])

    def test_search_cap_reslices_into_new_created_at_window(self) -> None:
        items = [{"id": str(i), "createdAt": "2026-01-02T00:00:00Z"} for i in range(PAGE_SIZE)]
        page1 = _page(items, has_next=True)
        page2 = _page([{"id": "in-window"}], has_next=False)
        manager = FakeResumableManager()

        ctx, session = _patch_session([page1, page2])
        with ctx, patch(f"{OPSGENIE_MODULE}.MAX_SEARCH_RESULTS", PAGE_SIZE):
            batches = list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        assert len(batches) == 2
        second_params = _query_params(session.get.call_args_list[1])
        # The offset resets and the query re-anchors on the last row's createdAt instead
        # of truncating at the 20,000-result cap.
        assert second_params["offset"] == ["0"]
        assert second_params["query"] == [f"createdAt >= {int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)}"]
        assert manager.saved_states[-1].offset == 0
        assert manager.saved_states[-1].window_start_ms == int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)

    def test_search_cap_stops_when_window_cannot_advance(self) -> None:
        window_ms = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)
        items = [{"id": str(i), "createdAt": "2026-01-02T00:00:00Z"} for i in range(PAGE_SIZE)]
        page = _page(items, has_next=True)
        manager = FakeResumableManager(resume_state=OpsgenieResumeConfig(offset=0, window_start_ms=window_ms))

        ctx, session = _patch_session([page])
        with ctx, patch(f"{OPSGENIE_MODULE}.MAX_SEARCH_RESULTS", PAGE_SIZE):
            batches = list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        # Every row shares the current window's createdAt, so re-slicing would loop on the
        # same page forever — the iterator yields what it has and stops instead.
        assert len(batches) == 1
        assert session.get.call_count == 1

    def test_retries_on_429_then_succeeds(self) -> None:
        rate_limited = _mock_response(429)
        page = _page([{"id": "1"}], has_next=False)
        manager = FakeResumableManager()

        ctx, session = _patch_session([rate_limited, page])
        with ctx, patch(f"{OPSGENIE_MODULE}.wait_exponential_jitter", return_value=lambda retry_state: 0):
            batches = list(get_rows("key", "us", "alerts", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "1"}]]
        assert session.get.call_count == 2


class TestOpsgenieSourceResponse:
    def test_alerts_partitioned_on_created_at(self) -> None:
        response = opsgenie_source("key", "us", "alerts", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["createdAt"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    def test_unpartitioned_endpoint_has_no_partition_settings(self) -> None:
        response = opsgenie_source("key", "us", "users", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None

    @pytest.mark.parametrize("endpoint", list(OPSGENIE_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = opsgenie_source("key", "us", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == [OPSGENIE_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)
