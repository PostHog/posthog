from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty import (
    PAGE_SIZE,
    PagerDutyResumeConfig,
    _build_params,
    _format_incremental_value,
    _get_headers,
    get_rows,
    pagerduty_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.settings import PAGERDUTY_ENDPOINTS

PAGERDUTY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty"


class FakeResumableManager:
    """In-memory stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, resume_state: Optional[PagerDutyResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[PagerDutyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[PagerDutyResumeConfig]:
        return self._resume_state

    def save_state(self, data: PagerDutyResumeConfig) -> None:
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
            f"{status_code} Client Error: error for url: https://api.pagerduty.com", response=error_response
        )
    return response


def _patch_session(get_side_effect: Any) -> Any:
    session = MagicMock()
    session.get.side_effect = get_side_effect
    return patch(f"{PAGERDUTY_MODULE}.make_tracked_session", return_value=session), session


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestHeaders:
    def test_token_auth_header(self) -> None:
        headers = _get_headers("tok_abc")
        assert headers["Authorization"] == "Token token=tok_abc"
        assert headers["Accept"] == "application/vnd.pagerduty+json;version=2"


class TestBuildParams:
    def test_full_refresh_incremental_endpoint_sends_stable_sort_only(self) -> None:
        params = _build_params(
            PAGERDUTY_ENDPOINTS["incidents"],
            offset=0,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params == {"limit": PAGE_SIZE, "offset": 0, "sort_by": "created_at:asc"}

    def test_incremental_endpoint_sends_since(self) -> None:
        params = _build_params(
            PAGERDUTY_ENDPOINTS["incidents"],
            offset=200,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert params["offset"] == 200
        assert params["sort_by"] == "created_at:asc"
        assert params["since"] == "2026-01-01T00:00:00+00:00"

    def test_non_incremental_endpoint_has_no_sort_or_since(self) -> None:
        params = _build_params(
            PAGERDUTY_ENDPOINTS["users"],
            offset=0,
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
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        ctx, _ = _patch_session([_mock_response(status_code, body={}, text="boom")])
        with ctx:
            ok, status, _error = validate_credentials("tok")
        assert ok is expected_ok
        assert status == expected_status

    def test_transport_failure_returns_zero_status(self) -> None:
        ctx, _ = _patch_session(requests.ConnectionError("no network"))
        with ctx:
            ok, status, error = validate_credentials("tok")
        assert ok is False
        assert status == 0
        assert error == "no network"

    def test_uses_endpoint_path_when_schema_given(self) -> None:
        ctx, session = _patch_session([_mock_response(200)])
        with ctx:
            validate_credentials("tok", endpoint="incidents")
        called_url = session.get.call_args.args[0]
        assert called_url.startswith("https://api.pagerduty.com/incidents?")


class TestGetRows:
    def test_paginates_and_yields_lists_of_dicts(self) -> None:
        page1 = _mock_response(200, body={"incidents": [{"id": "1"}, {"id": "2"}], "more": True})
        page2 = _mock_response(200, body={"incidents": [{"id": "3"}], "more": False})
        manager = FakeResumableManager()

        ctx, session = _patch_session([page1, page2])
        with ctx:
            batches = list(
                get_rows("tok", "incidents", MagicMock(), manager)  # type: ignore[arg-type]
            )

        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        assert session.get.call_count == 2

    def test_saves_state_after_yielding_each_page(self) -> None:
        page1 = _mock_response(200, body={"incidents": [{"id": "1"}], "more": True})
        page2 = _mock_response(200, body={"incidents": [{"id": "2"}], "more": False})
        manager = FakeResumableManager()

        ctx, _ = _patch_session([page1, page2])
        with ctx:
            list(get_rows("tok", "incidents", MagicMock(), manager))  # type: ignore[arg-type]

        # State is checkpointed once (the next offset) after the first page is yielded;
        # the final page sets more=False so no further checkpoint is written.
        assert [s.offset for s in manager.saved_states] == [PAGE_SIZE]

    def test_advances_offset_between_pages(self) -> None:
        page1 = _mock_response(200, body={"incidents": [{"id": "1"}], "more": True})
        page2 = _mock_response(200, body={"incidents": [{"id": "2"}], "more": False})
        manager = FakeResumableManager()

        ctx, session = _patch_session([page1, page2])
        with ctx:
            list(get_rows("tok", "incidents", MagicMock(), manager))  # type: ignore[arg-type]

        first_url = session.get.call_args_list[0].args[0]
        second_url = session.get.call_args_list[1].args[0]
        assert "offset=0" in first_url
        assert f"offset={PAGE_SIZE}" in second_url

    def test_resumes_from_saved_offset(self) -> None:
        manager = FakeResumableManager(resume_state=PagerDutyResumeConfig(offset=PAGE_SIZE))
        page = _mock_response(200, body={"incidents": [{"id": "x"}], "more": False})

        ctx, session = _patch_session([page])
        with ctx:
            list(get_rows("tok", "incidents", MagicMock(), manager))  # type: ignore[arg-type]

        assert f"offset={PAGE_SIZE}" in session.get.call_args_list[0].args[0]

    def test_empty_page_stops_iteration(self) -> None:
        page = _mock_response(200, body={"incidents": [], "more": True})
        manager = FakeResumableManager()

        ctx, session = _patch_session([page])
        with ctx:
            batches = list(get_rows("tok", "incidents", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == []
        assert session.get.call_count == 1

    def test_uses_envelope_key_per_endpoint(self) -> None:
        page = _mock_response(200, body={"services": [{"id": "svc_1"}], "more": False})
        manager = FakeResumableManager()

        ctx, _ = _patch_session([page])
        with ctx:
            batches = list(get_rows("tok", "services", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "svc_1"}]]


class TestPagerDutySourceResponse:
    def test_incidents_partitioned_on_created_at(self) -> None:
        response = pagerduty_source("tok", "incidents", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    def test_unpartitioned_endpoint_has_no_partition_settings(self) -> None:
        response = pagerduty_source("tok", "users", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None

    @pytest.mark.parametrize("endpoint", list(PAGERDUTY_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = pagerduty_source("tok", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == [PAGERDUTY_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)
