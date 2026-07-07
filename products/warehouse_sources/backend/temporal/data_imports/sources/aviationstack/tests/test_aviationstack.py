from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack import aviationstack
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack import (
    AviationstackAPIError,
    AviationstackResumeConfig,
    AviationstackRetryableError,
    _fetch_page,
    aviationstack_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import (
    AVIATIONSTACK_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack"


def _response(
    *, data: Any = None, total: int | None = None, status: int = 200, ok: bool = True, error: dict | None = None
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = ok
    response.reason = "Client Error" if status < 500 else "Server Error"
    # Real requests responses expose the full URL (access_key included) on `response.url`.
    response.url = "https://api.aviationstack.com/v1/airlines?access_key=supersecret&limit=1"
    body: dict[str, Any] = {}
    if error is not None:
        body["error"] = error
    else:
        body["data"] = data if data is not None else []
        body["pagination"] = {"limit": 100, "offset": 0, "count": len(data or []), "total": total}
    response.json.return_value = body
    return response


def _session_returning(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _resume_manager(saved: AviationstackResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = saved is not None
    manager.load_state.return_value = saved
    return manager


def _collect_rows(tables: Any) -> list[dict]:
    rows: list[dict] = []
    for table in tables:
        rows.extend(table.to_pylist())
    return rows


class TestFetchPage:
    def test_returns_body_on_success(self) -> None:
        session = _session_returning([_response(data=[{"id": 1}], total=1)])
        body = _fetch_page(session, "https://api.aviationstack.com/v1/airlines", {"access_key": "k"}, MagicMock())
        assert body["data"] == [{"id": 1}]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_http_client_error_raises(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)])
        with pytest.raises(requests.HTTPError) as exc:
            _fetch_page(session, "https://api.aviationstack.com/v1/airlines", {"access_key": "k"}, MagicMock())
        # The access_key must never appear in the error message — it's logged downstream via str(error).
        assert "supersecret" not in str(exc.value)
        assert "access_key" not in str(exc.value)

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_retries_then_raises(self, _name: str, status: int) -> None:
        session = _session_returning([_response(status=status, ok=False)] * 5)
        with patch("time.sleep"), pytest.raises(AviationstackRetryableError):
            _fetch_page(session, "https://api.aviationstack.com/v1/airlines", {"access_key": "k"}, MagicMock())
        assert session.get.call_count == 5

    def test_body_error_envelope_raises_permanent(self) -> None:
        session = _session_returning([_response(error={"code": "invalid_access_key", "message": "bad"})])
        with pytest.raises(AviationstackAPIError) as exc:
            _fetch_page(session, "https://api.aviationstack.com/v1/airlines", {"access_key": "k"}, MagicMock())
        # The stable [code] token is what get_non_retryable_errors matches on.
        assert "[invalid_access_key]" in str(exc.value)

    def test_body_error_envelope_rate_limit_is_retryable(self) -> None:
        session = _session_returning([_response(error={"code": "rate_limit_reached", "message": "slow down"})] * 5)
        with patch("time.sleep"), pytest.raises(AviationstackRetryableError):
            _fetch_page(session, "https://api.aviationstack.com/v1/airlines", {"access_key": "k"}, MagicMock())
        assert session.get.call_count == 5


class TestGetRows:
    def test_paginates_until_total_reached(self) -> None:
        page1 = [{"id": i} for i in range(2)]
        page2 = [{"id": i} for i in range(2, 4)]
        session = _session_returning([_response(data=page1, total=4), _response(data=page2, total=4)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "airlines", MagicMock(), _resume_manager(), page_size=2))
        assert [r["id"] for r in rows] == [0, 1, 2, 3]
        assert session.get.call_count == 2

    def test_stops_on_short_page(self) -> None:
        # A page shorter than the limit means there's no further page, even without a total.
        session = _session_returning([_response(data=[{"id": 1}], total=None)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "airlines", MagicMock(), _resume_manager(), page_size=100))
        assert [r["id"] for r in rows] == [1]
        assert session.get.call_count == 1

    def test_stops_on_empty_first_page(self) -> None:
        session = _session_returning([_response(data=[], total=0)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "airlines", MagicMock(), _resume_manager(), page_size=100))
        assert rows == []
        assert session.get.call_count == 1

    def test_resumes_from_saved_offset(self) -> None:
        session = _session_returning([_response(data=[{"id": 9}], total=None)])
        manager = _resume_manager(AviationstackResumeConfig(next_offset=200))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            _collect_rows(get_rows("k", "airlines", MagicMock(), manager, page_size=100))
        # The first (and only) request must start from the persisted offset, not 0.
        assert session.get.call_args_list[0].kwargs["params"]["offset"] == 200

    def test_saves_state_after_yielding_a_batch(self) -> None:
        # Batcher flushes at 2000 rows, so two full 2000-row pages force a mid-stream yield + save.
        page1 = [{"id": i} for i in range(2000)]
        page2 = [{"id": i} for i in range(2000, 4000)]
        session = _session_returning([_response(data=page1, total=4000), _response(data=page2, total=4000)])
        manager = _resume_manager()
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("k", "airlines", MagicMock(), manager, page_size=2000))
        assert len(rows) == 4000
        # State is saved with the next offset to resume from, only while more pages remain.
        manager.save_state.assert_called_once_with(AviationstackResumeConfig(next_offset=2000))


class TestAviationstackSource:
    @parameterized.expand(
        [
            ("airlines", ["id"]),
            ("airports", ["id"]),
            ("countries", ["id"]),
            ("flights", None),
            ("routes", None),
        ]
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_keys: list[str] | None) -> None:
        response = aviationstack_source("k", endpoint, MagicMock(), _resume_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in AVIATIONSTACK_ENDPOINTS:
            response = aviationstack_source("k", endpoint, MagicMock(), _resume_manager())
            assert response.name == endpoint
            assert callable(response.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, {"data": []}, True),
            ("unauthorized", 401, {"error": {"code": "invalid_access_key"}}, False),
            ("ok_status_but_error_body", 200, {"error": {"code": "usage_limit_reached"}}, False),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status: int, body: dict, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        response.json.return_value = body
        session = MagicMock()
        session.get.return_value = response
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("k") is expected

    def test_validate_credentials_handles_network_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("k") is False


def test_module_exposes_base_url() -> None:
    assert aviationstack.AVIATIONSTACK_BASE_URL == "https://api.aviationstack.com/v1"
