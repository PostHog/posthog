import base64
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.settings import XMATTERS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters import (
    PAGE_SIZE,
    XmattersResumeConfig,
    _base_url,
    _build_params,
    _format_incremental_value,
    _get_headers,
    get_rows,
    is_valid_subdomain,
    validate_credentials,
    xmatters_source,
)

XMATTERS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters"


class FakeResumableManager:
    """In-memory stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, resume_state: Optional[XmattersResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[XmattersResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[XmattersResumeConfig]:
        return self._resume_state

    def save_state(self, data: XmattersResumeConfig) -> None:
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
            f"{status_code} Client Error: error for url: https://acme.xmatters.com", response=error_response
        )
    return response


def _patch_session(get_side_effect: Any) -> Any:
    session = MagicMock()
    session.get.side_effect = get_side_effect
    return patch(f"{XMATTERS_MODULE}.make_tracked_session", return_value=session), session


def _page(items: list[dict], next_url: Optional[str] = None) -> dict:
    body: dict[str, Any] = {"count": len(items), "total": len(items), "data": items}
    if next_url is not None:
        body["links"] = {"next": next_url}
    return body


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


class TestSubdomainValidation:
    @pytest.mark.parametrize("subdomain", ["acme", "acme-corp", "a", "acme123", "123acme"])
    def test_valid_subdomains(self, subdomain: str) -> None:
        assert is_valid_subdomain(subdomain) is True
        assert _base_url(subdomain) == f"https://{subdomain}.xmatters.com/api/xm/1"

    # An editor-controlled subdomain like `attacker.example/` would make the worker send its
    # requests (and Basic auth header) to an arbitrary host instead of *.xmatters.com (SSRF).
    @pytest.mark.parametrize(
        "subdomain",
        [
            "attacker.example/",
            "user@evil.example",
            "acme.evil.example",
            "127.0.0.1:8443/",
            "acme/path",
            "acme?x=",
            "acme#frag",
            "",
            "-acme",
            "acme-",
            "a" * 64,
        ],
    )
    def test_hostile_subdomains_rejected(self, subdomain: str) -> None:
        assert is_valid_subdomain(subdomain) is False
        with pytest.raises(ValueError):
            _base_url(subdomain)


class TestHeaders:
    def test_basic_auth_header(self) -> None:
        headers = _get_headers("svc", "secret")
        expected = base64.b64encode(b"svc:secret").decode("ascii")
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestBuildParams:
    def test_events_full_refresh_sends_stable_sort_only(self) -> None:
        params = _build_params(
            XMATTERS_ENDPOINTS["events"],
            offset=0,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params == {"limit": PAGE_SIZE, "offset": 0, "sortBy": "START_TIME", "sortOrder": "ASCENDING"}

    def test_events_incremental_sends_from(self) -> None:
        params = _build_params(
            XMATTERS_ENDPOINTS["events"],
            offset=2000,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert params["offset"] == 2000
        assert params["sortBy"] == "START_TIME"
        assert params["sortOrder"] == "ASCENDING"
        assert params["from"] == "2026-01-01T00:00:00+00:00"

    def test_reference_endpoint_has_no_sort_or_from(self) -> None:
        params = _build_params(
            XMATTERS_ENDPOINTS["people"],
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
            ok, status, _error = validate_credentials("acme", "svc", "secret")
        assert ok is expected_ok
        assert status == expected_status

    def test_transport_failure_returns_zero_status(self) -> None:
        ctx, _ = _patch_session(requests.ConnectionError("no network"))
        with ctx:
            ok, status, error = validate_credentials("acme", "svc", "secret")
        assert ok is False
        assert status == 0
        assert error == "no network"

    def test_probe_targets_instance_subdomain_and_endpoint_path(self) -> None:
        ctx, session = _patch_session([_mock_response(200)])
        with ctx:
            validate_credentials("acme", "svc", "secret", endpoint="events")
        called_url = session.get.call_args.args[0]
        assert called_url.startswith("https://acme.xmatters.com/api/xm/1/events?")


class TestGetRows:
    def test_paginates_following_links_next(self) -> None:
        page1 = _mock_response(200, body=_page([{"id": "1"}, {"id": "2"}], next_url="/api/xm/1/events?offset=1000"))
        page2 = _mock_response(200, body=_page([{"id": "3"}]))
        manager = FakeResumableManager()

        ctx, session = _patch_session([page1, page2])
        with ctx:
            batches = list(get_rows("acme", "svc", "secret", "events", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        assert session.get.call_count == 2

    def test_saves_state_after_yielding_each_page(self) -> None:
        page1 = _mock_response(200, body=_page([{"id": "1"}], next_url="/api/xm/1/events?offset=1000"))
        page2 = _mock_response(200, body=_page([{"id": "2"}]))
        manager = FakeResumableManager()

        ctx, _ = _patch_session([page1, page2])
        with ctx:
            list(get_rows("acme", "svc", "secret", "events", MagicMock(), manager))  # type: ignore[arg-type]

        # Checkpoint written once (next offset) after the first page; the last page has no
        # `links.next` so no further checkpoint.
        assert [s.offset for s in manager.saved_states] == [PAGE_SIZE]

    def test_advances_offset_between_pages(self) -> None:
        page1 = _mock_response(200, body=_page([{"id": "1"}], next_url="/api/xm/1/events?offset=1000"))
        page2 = _mock_response(200, body=_page([{"id": "2"}]))
        manager = FakeResumableManager()

        ctx, session = _patch_session([page1, page2])
        with ctx:
            list(get_rows("acme", "svc", "secret", "events", MagicMock(), manager))  # type: ignore[arg-type]

        assert "offset=0" in session.get.call_args_list[0].args[0]
        assert f"offset={PAGE_SIZE}" in session.get.call_args_list[1].args[0]

    def test_resumes_from_saved_offset(self) -> None:
        manager = FakeResumableManager(resume_state=XmattersResumeConfig(offset=PAGE_SIZE))
        page = _mock_response(200, body=_page([{"id": "x"}]))

        ctx, session = _patch_session([page])
        with ctx:
            list(get_rows("acme", "svc", "secret", "events", MagicMock(), manager))  # type: ignore[arg-type]

        assert f"offset={PAGE_SIZE}" in session.get.call_args_list[0].args[0]

    def test_empty_page_stops_iteration(self) -> None:
        page = _mock_response(200, body=_page([], next_url="/api/xm/1/events?offset=1000"))
        manager = FakeResumableManager()

        ctx, session = _patch_session([page])
        with ctx:
            batches = list(get_rows("acme", "svc", "secret", "events", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == []
        assert session.get.call_count == 1

    def test_stops_when_no_next_link_and_partial_page(self) -> None:
        # A short page without a `links.next` terminates without another request.
        page = _mock_response(200, body=_page([{"id": "1"}]))
        manager = FakeResumableManager()

        ctx, session = _patch_session([page])
        with ctx:
            batches = list(get_rows("acme", "svc", "secret", "people", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "1"}]]
        assert session.get.call_count == 1


class TestXmattersSourceResponse:
    def test_events_partitioned_on_created(self) -> None:
        response = xmatters_source("acme", "svc", "secret", "events", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    def test_reference_endpoint_has_no_partition_settings(self) -> None:
        response = xmatters_source("acme", "svc", "secret", "people", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None

    @pytest.mark.parametrize("endpoint", list(XMATTERS_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = xmatters_source("acme", "svc", "secret", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == [XMATTERS_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)
