import json
import base64
from types import SimpleNamespace
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip import (
    DripResumeConfig,
    _base_params,
    drip_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import DRIP_ENDPOINTS, ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the drip module.
DRIP_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip.make_tracked_session"


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _page(data_key: str, items: list[dict[str, Any]], total_pages: int | None = None) -> Response:
    body: dict[str, Any] = {data_key: items}
    if total_pages is not None:
        body["meta"] = {"total_pages": total_pages}
    return _response(body)


def _make_manager(resume: DripResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[SimpleNamespace]:
    """Wire a mock session and capture each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    captured: list[SimpleNamespace] = []

    def _prepare(request: Any) -> mock.MagicMock:
        captured.append(SimpleNamespace(params=dict(request.params or {}), auth=request.auth))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return captured


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(session: mock.MagicMock, endpoint: str, manager: mock.MagicMock) -> list[dict[str, Any]]:
    return _rows(
        drip_source(
            api_token="token",
            account_id="9999",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )
    )


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_token_as_username_empty_password(self, MockSession) -> None:
        session = MockSession.return_value
        captured = _wire(session, [_page("forms", [{"id": 1}])])

        _run(session, "forms", _make_manager())

        auth = captured[0].auth
        assert isinstance(auth, HttpBasicAuth)
        prepared = PreparedRequest()
        prepared.prepare(method="GET", url="https://api.getdrip.com/v2/9999/forms")
        auth(prepared)
        expected = base64.b64encode(b"token:").decode("ascii")
        assert prepared.headers["Authorization"] == f"Basic {expected}"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_accept_header_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("forms", [{"id": 1}])])

        _run(session, "forms", _make_manager())
        assert session.headers.get("Accept") == "application/json"


class TestBaseParams:
    @parameterized.expand(
        [
            ("subscribers", {"per_page": 1000}),
            ("campaigns", {"per_page": 100, "sort": "created_at", "direction": "asc"}),
            ("broadcasts", {"per_page": 100, "sort": "created_at", "direction": "asc"}),
            ("workflows", {"per_page": 100}),
            ("forms", {}),
            ("goals", {}),
        ]
    )
    def test_base_params(self, endpoint, expected) -> None:
        assert _base_params(endpoint) == expected

    @parameterized.expand(
        [
            ("subscribers", {"per_page": 1000, "page": 1}),
            ("campaigns", {"per_page": 100, "sort": "created_at", "direction": "asc", "page": 1}),
            ("broadcasts", {"per_page": 100, "sort": "created_at", "direction": "asc", "page": 1}),
            ("workflows", {"per_page": 100, "page": 1}),
            # Non-paginated endpoints still send page=1 (mirrors the original hand-rolled source).
            ("forms", {"page": 1}),
            ("goals", {"page": 1}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_params_sent_on_first_request(self, endpoint, expected, MockSession) -> None:
        session = MockSession.return_value
        captured = _wire(session, [_page(DRIP_ENDPOINTS[endpoint].data_key, [{"id": 1}])])

        _run(session, endpoint, _make_manager())

        assert captured[0].params == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_last_page_via_meta(self, MockSession) -> None:
        session = MockSession.return_value
        captured = _wire(
            session,
            [
                _page("subscribers", [{"id": 1}], total_pages=2),
                _page("subscribers", [{"id": 2}], total_pages=2),
            ],
        )

        rows = _run(session, "subscribers", _make_manager())

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 2
        assert captured[0].params["page"] == 1
        assert captured[1].params["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page("subscribers", [{"id": 1}], total_pages=2),
                _page("subscribers", [{"id": 2}], total_pages=2),
            ],
        )
        manager = _make_manager()

        _run(session, "subscribers", manager)

        # State advances to page 2 once page 1 is yielded; the final page saves nothing further.
        manager.save_state.assert_called_once_with(DripResumeConfig(next_page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        captured = _wire(session, [_page("subscribers", [{"id": 5}], total_pages=3)])
        manager = _make_manager(DripResumeConfig(next_page=3))

        _run(session, "subscribers", manager)

        # Starts at the resume point (page 3) and stops, since total_pages == 3.
        assert captured[0].params["page"] == 3
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_then_partial_terminates_without_meta(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(100)]  # workflows per_page == 100
        partial_page = [{"id": i} for i in range(100, 140)]
        _wire(session, [_page("workflows", full_page), _page("workflows", partial_page)])

        rows = _run(session, "workflows", _make_manager())

        assert [r["id"] for r in rows] == list(range(140))
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_for_non_paginated_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("forms", [{"id": 1}, {"id": 2}])])
        manager = _make_manager()

        rows = _run(session, "forms", manager)

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Drip API token"),
            ("forbidden", 403, False, "Invalid Drip API token"),
            ("not_found", 404, False, "Drip account ID not found. Please check your account ID."),
            ("server_error", 500, False, "Drip API returned an unexpected status (500)"),
        ]
    )
    @mock.patch(DRIP_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, _name, status_code, expected_valid, expected_message, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, message = validate_credentials("token", "9999")

        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(DRIP_SESSION_PATCH)
    def test_validate_credentials_connection_error(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, message = validate_credentials("token", "9999")

        assert is_valid is False
        assert message == "Could not connect to the Drip API"


class TestDripSourceResponse:
    @parameterized.expand(list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint, _MockSession) -> None:
        response = drip_source(
            api_token="token",
            account_id="9999",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )

        config = DRIP_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_subscribers_partitions_on_created_at(self, _MockSession) -> None:
        response = drip_source(
            api_token="token",
            account_id="9999",
            endpoint="subscribers",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"
