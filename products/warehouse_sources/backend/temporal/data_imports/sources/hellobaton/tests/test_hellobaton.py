import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.hellobaton import (
    HellobatonResumeConfig,
    hellobaton_source,
    normalize_company,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hellobaton module.
HELLOBATON_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.hellobaton.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, *, next_url: str | None = None) -> Response:
    """A Baton DRF page: `results` list plus a `next` cursor URL (absent on the last page)."""
    body: dict[str, Any] = {"results": items or [], "next": next_url}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://acme.hellobaton.com/api/projects/"
    return resp


def _make_manager(resume_state: HellobatonResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared. The prepared mock carries a valid same-host URL so the ``allowed_hosts``
    guard (which inspects ``prepared.url``) passes.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = "https://acme.hellobaton.com/api/projects/"
        return prepared

    session.prepare_request.side_effect = _prepare
    if responses:
        session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "projects"):
    return hellobaton_source(
        company="acme",
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestNormalizeCompany:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("acme", "acme"),
            ("acme.hellobaton.com", "acme"),
            ("https://acme.hellobaton.com", "acme"),
            ("acme.hellobaton.com/", "acme"),
            ("acme-corp", "acme-corp"),
            ("  acme  ", "acme"),
        ],
    )
    def test_valid_companies(self, value: str, expected: str) -> None:
        assert normalize_company(value) == expected

    @pytest.mark.parametrize(
        "value",
        ["acme/../evil", "acme.evil.com", "acme@evil.com", "", "ac me", "acme-"],
    )
    def test_invalid_companies_raise(self, value: str) -> None:
        # The api_key must never be retargeted off <company>.hellobaton.com.
        with pytest.raises(ValueError):
            normalize_company(value)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_next_is_absent(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], next_url="https://acme.hellobaton.com/api/projects/?page=2"),
                _response([{"id": 3}], next_url=None),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert [r["id"] for r in rows] == [1, 2, 3]
        # Stops when `next` is absent — never probes a third (would-be 404) page.
        assert session.send.call_count == 2
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_size_sent_on_every_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": 1}], next_url="https://acme.hellobaton.com/api/projects/?page=2"),
                _response([{"id": 2}], next_url=None),
            ],
        )

        _rows(_source(_make_manager()))
        # Baton caps page size at 100; request the max on every page.
        assert all(p["page_size"] == 100 for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_results(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_url=None)])

        rows = _rows(_source(_make_manager(), endpoint="companies"))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_more_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], next_url="https://acme.hellobaton.com/api/projects/?page=2"),
                _response([{"id": 2}], next_url=None),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager))

        # Checkpoint points at the next page after page 1; the last page (no `next`) saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HellobatonResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_saves_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], next_url=None)])

        manager = _make_manager()
        _rows(_source(manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 2}], next_url=None)])

        rows = _rows(_source(_make_manager(HellobatonResumeConfig(next_page=2)), endpoint="tasks"))

        assert [r["id"] for r in rows] == [2]
        assert params[0]["page"] == 2
        assert session.send.call_count == 1


class TestErrorHandling:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_and_scrubs_api_key(self, MockSession) -> None:
        # The api_key rides in the query string; a 4xx must fail loud (non-retryable) while never
        # leaking the key into the raised error the user sees, and still expose the status text
        # get_non_retryable_errors() matches on.
        session = MockSession.return_value
        _wire(session, [])
        resp = Response()
        resp.status_code = 401
        resp.reason = "Unauthorized"
        resp.url = "https://acme.hellobaton.com/api/projects/?api_key=supersecret&page_size=100&page=1"
        resp._content = b""
        session.send.side_effect = [resp]

        source = hellobaton_source(
            company="acme",
            api_key="supersecret",
            endpoint="projects",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(source)

        message = str(exc_info.value)
        assert "supersecret" not in message
        assert "401 Client Error: Unauthorized" in message


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False)],
    )
    @mock.patch(HELLOBATON_SESSION_PATCH)
    def test_maps_probe_status(self, mock_session, status_code: int, expected_ok: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, status = validate_credentials("acme", "key")
        assert ok is expected_ok
        assert status == status_code

    @mock.patch(HELLOBATON_SESSION_PATCH)
    def test_transport_error_is_not_validated(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("acme", "key") == (False, None)

    def test_malformed_company_raises_before_probe(self) -> None:
        # _base_url validates the company, so a bad instance fails before any network call.
        with pytest.raises(ValueError):
            validate_credentials("acme/../evil", "key")
