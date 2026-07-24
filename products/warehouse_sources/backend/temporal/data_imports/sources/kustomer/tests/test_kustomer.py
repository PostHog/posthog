import json
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer import (
    KustomerResumeConfig,
    _base_url,
    _clean_org_name,
    kustomer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.settings import (
    ENDPOINTS,
    KUSTOMER_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the kustomer module.
KUSTOMER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
)


def _response(items: list[dict[str, Any]], next_link: str | None = None) -> Response:
    body: dict[str, Any] = {"data": items, "links": {}}
    if next_link:
        body["links"]["next"] = next_link
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: KustomerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Wire a mock session and capture each request's URL AT SEND TIME.

    ``request.url`` is set per page by the paginator, so snapshot it when the
    request is prepared rather than inspecting the shared ``Request`` after."""
    session.headers = {}
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(org_name: str, api_key: str, endpoint: str, manager: mock.MagicMock):
    return kustomer_source(
        org_name=org_name,
        api_key=api_key,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestCleanOrgName:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("myorg", "myorg"),
            (" myorg ", "myorg"),
            ("https://myorg.kustomerapp.com", "myorg"),
            ("myorg.api.kustomerapp.com/v1", "myorg"),
            ("my-org", "my-org"),
        ],
    )
    def test_valid_org_names(self, value, expected):
        assert _clean_org_name(value) == expected

    @pytest.mark.parametrize("value", ["", "my org", "org?x=1", "../evil"])
    def test_invalid_org_names_raise(self, value):
        with pytest.raises(ValueError):
            _clean_org_name(value)

    def test_base_url(self):
        assert _base_url("myorg") == "https://myorg.api.kustomerapp.com"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # Role-scoped keys without the customers grant still 403; only 401
            # means the key itself is bad.
            (403, True),
            (401, False),
        ],
    )
    @mock.patch(KUSTOMER_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("myorg", "key") is expected

    @mock.patch(KUSTOMER_SESSION_PATCH)
    def test_validate_credentials_rejects_bad_org_without_request(self, mock_session):
        assert validate_credentials("my org!", "key") is False
        mock_session.return_value.get.assert_not_called()

    @mock.patch(KUSTOMER_SESSION_PATCH)
    def test_validate_credentials_swallows_transport_errors(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("myorg", "key") is False


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_links_next_and_absolutizes(self, MockSession):
        session = MockSession.return_value
        urls = _wire(
            session,
            [
                _response([{"id": "1"}], next_link="/v1/customers?page%5Bafter%5D=abc&page%5Bsize%5D=100"),
                _response([{"id": "2"}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("myorg", "key", "customers", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        manager.save_state.assert_called_once()
        saved_url = manager.save_state.call_args.args[0].next_url
        assert saved_url.startswith("https://myorg.api.kustomerapp.com/v1/customers?")
        # The second request targets the absolutized next link.
        assert urls[1] == saved_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_uses_endpoint_path_and_page_size(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        _rows(_source("myorg", "key", "conversations", _make_manager()))

        # First request goes to the endpoint path; page[size] rides in params.
        url = session.prepare_request.call_args_list[0].args[0].url
        parsed = urlparse(url)
        assert parsed.path == "/v1/conversations"
        params = session.prepare_request.call_args_list[0].args[0].params
        assert params["page[size]"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        urls = _wire(session, [_response([{"id": "9"}])])

        resume_url = "https://myorg.api.kustomerapp.com/v1/customers?page%5Bafter%5D=resume"
        manager = _make_manager(KustomerResumeConfig(next_url=resume_url))

        _rows(_source("myorg", "key", "customers", manager))

        assert urls[0] == resume_url

    @pytest.mark.parametrize(
        "next_link",
        [
            "https://attacker.com/steal",
            "//attacker.com/steal",
            "http://myorg.api.kustomerapp.com/v1/customers",  # downgraded scheme
            "https://myorg.api.kustomerapp.com.evil.com/v1/customers",  # look-alike host
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_link_is_rejected(self, MockSession, next_link):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], next_link=next_link)])

        manager = _make_manager()
        with pytest.raises(ValueError):
            _rows(_source("myorg", "key", "customers", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_state_is_rejected(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}])])

        manager = _make_manager(KustomerResumeConfig(next_url="https://attacker.com/steal"))

        with pytest.raises(ValueError):
            _rows(_source("myorg", "key", "customers", manager))

        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_next_link_stops(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([], next_link="/v1/customers?page%5Bafter%5D=loop")])

        manager = _make_manager()
        rows = _rows(_source("myorg", "key", "customers", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_auth_header_is_applied(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}])])

        _rows(_source("myorg", "secret-key", "customers", _make_manager()))

        prepared_request = session.prepare_request.call_args_list[0].args[0]
        # Framework bearer auth attaches the Authorization header to the request.
        auth = prepared_request.auth
        req = mock.MagicMock()
        req.headers = {}
        auth(req)
        assert req.headers["Authorization"] == "Bearer secret-key"


class TestKustomerSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = KUSTOMER_ENDPOINTS[endpoint]
        response = _source("myorg", "key", endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        # JSON:API rows nest timestamps under attributes — no partitioning.
        assert response.partition_mode is None
        assert response.partition_keys is None
