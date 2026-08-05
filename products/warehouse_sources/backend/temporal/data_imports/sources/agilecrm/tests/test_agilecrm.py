import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.agilecrm import (
    AgileCRMResumeConfig,
    agilecrm_source,
    base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import AGILECRM_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the agilecrm module.
AGILECRM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.agilecrm.make_tracked_session"
)

PAGE_SIZE = AGILECRM_ENDPOINTS["contacts"].page_size


def _response(body: Any) -> Response:
    # Agile CRM list endpoints return a bare JSON array as the body.
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AgileCRMResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "contacts"):
    return agilecrm_source(
        domain="acme",
        email="a@b.com",
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestBaseUrl:
    @parameterized.expand(
        [
            ("simple", "acme", "https://acme.agilecrm.com/dev/api"),
            ("with_hyphen", "my-company", "https://my-company.agilecrm.com/dev/api"),
            ("trims_whitespace", "  acme  ", "https://acme.agilecrm.com/dev/api"),
        ]
    )
    def test_valid_domains(self, _name: str, domain: str, expected: str) -> None:
        assert base_url(domain) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            # A `#`/`/`/`.` in the domain could break out of the agilecrm.com host and retarget the
            # basic-auth credentials at an attacker-controlled server, so these must be rejected.
            ("fragment_breakout", "evil.com#"),
            ("slash_breakout", "evil.com/"),
            ("dotted", "evil.com"),
            ("at_breakout", "user@evil.com"),
        ]
    )
    def test_invalid_domains_rejected(self, _name: str, domain: str) -> None:
        with pytest.raises(ValueError):
            base_url(domain)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        first_page = [{"id": i} for i in range(PAGE_SIZE - 1)] + [{"id": PAGE_SIZE, "cursor": "CURSOR1"}]
        second_page = [{"id": 9001}]  # short page -> terminal
        params = _wire(session, [_response(first_page), _response(second_page)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == PAGE_SIZE + 1
        # First request has no cursor; the second carries the cursor from the last item of page one.
        assert "cursor" not in params[0]
        assert params[0]["page_size"] == PAGE_SIZE
        assert params[1]["cursor"] == "CURSOR1"
        # The cursor is navigation metadata and must never leak into the warehouse rows.
        assert all("cursor" not in row for row in rows)
        # Checkpoint saved after the first page (points at the next page); the short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AgileCRMResumeConfig(cursor="CURSOR1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_full_page_has_no_cursor(self, MockSession) -> None:
        # A full page whose last item carries no cursor must terminate rather than loop forever.
        session = MockSession.return_value
        full_page_no_cursor = [{"id": i} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full_page_no_cursor), _response([{"id": 1}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page_even_with_cursor(self, MockSession) -> None:
        # A short page is terminal even if its last item still carries a cursor.
        session = MockSession.return_value
        short_page = [{"id": 1}, {"id": 2, "cursor": "DANGLING"}]
        _wire(session, [_response(short_page), _response([{"id": 3}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert session.send.call_count == 1
        assert all("cursor" not in row for row in rows)
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_uses_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        manager = _make_manager(AgileCRMResumeConfig(cursor="SAVED"))
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}]
        assert params[0]["cursor"] == "SAVED"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "something went wrong"})])

        # A 200 object body means the response shape changed — fail loud, not silently mis-sync.
        with pytest.raises(ValueError, match="Required a list response body"):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        with mock.patch(AGILECRM_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            assert validate_credentials("acme", "a@b.com", "key") is expected

    def test_invalid_domain_short_circuits_to_false(self) -> None:
        # An invalid domain must fail before any request is attempted.
        with mock.patch(AGILECRM_SESSION_PATCH) as mock_session:
            assert validate_credentials("evil.com#", "a@b.com", "key") is False
            mock_session.assert_not_called()

    def test_network_error_is_false(self) -> None:
        with mock.patch(AGILECRM_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("acme", "a@b.com", "key") is False
