import json
from types import SimpleNamespace
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip import (
    DripResumeConfig,
    _base_params,
    drip_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import (
    CAMPAIGN_SUBSCRIBER_STATUSES,
    DRIP_ENDPOINTS,
    ENDPOINTS,
)

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


class TestScalarEndpoints:
    @parameterized.expand(
        [
            ("tags", "tag", ["Customer", "SEO"]),
            ("custom_field_identifiers", "identifier", ["first_name", "last_name"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_strings_become_single_column_rows(self, endpoint, column, values, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page(DRIP_ENDPOINTS[endpoint].data_key, values)])

        rows = _run(session, endpoint, _make_manager())

        assert rows == [{column: value} for value in values]


class TestCampaignSubscribersFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_pages_are_followed_per_campaign(self, MockSession) -> None:
        session = MockSession.return_value
        responses = []
        for index, _status in enumerate(CAMPAIGN_SUBSCRIBER_STATUSES):
            responses.append(_page("campaigns", [{"id": 10}]))
            responses.append(_page("subscribers", [{"id": f"a{index}"}], total_pages=2))
            responses.append(_page("subscribers", [{"id": f"b{index}"}], total_pages=2))
        captured = _wire(session, responses)

        rows = _run(session, "campaign_subscribers", _make_manager())

        assert [row["id"] for row in rows] == ["a0", "b0", "a1", "b1", "a2", "b2"]
        child_pages = [c.params["page"] for c in captured if "status" in c.params]
        assert child_pages == [1, 2, 1, 2, 1, 2]
