import json
import base64
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence import (
    ConfluenceResumeConfig,
    _get_headers,
    confluence_source,
    is_valid_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import (
    CONFLUENCE_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the confluence module.
CONFLUENCE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence.make_tracked_session"
)


def _response(results: list[dict[str, Any]], next_path: str | None = None) -> Response:
    body: dict[str, Any] = {"results": results, "_links": {"next": next_path} if next_path else {}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ConfluenceResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    The paginator mutates the single ``Request`` in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return confluence_source(
        subdomain="acme",
        email="you@example.com",
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestSubdomainValidation:
    @parameterized.expand(
        [
            ("simple", "mycompany", True),
            ("with_hyphen", "my-company", True),
            ("alphanumeric", "team123", True),
            ("empty", "", False),
            ("with_dot", "evil.com", False),
            ("with_slash", "evil/path", False),
            ("with_protocol", "https://evil", False),
            ("leading_hyphen", "-bad", False),
        ]
    )
    def test_is_valid_subdomain(self, _name: str, subdomain: str, expected: bool) -> None:
        assert is_valid_subdomain(subdomain) is expected


class TestHeaders:
    def test_basic_auth_header(self) -> None:
        headers = _get_headers("you@example.com", "token123")
        expected = base64.b64encode(b"you@example.com:token123").decode()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True, None),
            ("bad_token", 401, None, False, "Invalid Confluence credentials. Check your email and API token."),
            ("forbidden_source_create", 403, None, True, None),
            (
                "forbidden_specific_schema",
                403,
                "pages",
                False,
                "Your Confluence account does not have permission to access this resource.",
            ),
            ("other_status", 500, None, False, "Confluence API returned status 500."),
        ]
    )
    @mock.patch(CONFLUENCE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self,
        _name: str,
        status_code: int,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, message = validate_credentials("acme", "you@example.com", "token", schema_name=schema_name)

        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(CONFLUENCE_SESSION_PATCH)
    def test_transport_error_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, message = validate_credentials("acme", "you@example.com", "token")
        assert is_valid is False
        assert message is None

    def test_invalid_subdomain_short_circuits(self) -> None:
        is_valid, message = validate_credentials("evil.com", "you@example.com", "token")
        assert is_valid is False
        assert message is not None and "subdomain" in message


class TestConfluenceSource:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape_for_endpoint(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        config = CONFLUENCE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([("spaces", "createdAt"), ("pages", "createdAt"), ("labels", None)])
    def test_partition_key_matches_endpoint(self, endpoint: str, expected_partition: str | None) -> None:
        assert CONFLUENCE_ENDPOINTS[endpoint].partition_key == expected_partition


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_no_next_and_saves_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "1"}, {"id": "2"}], next_path="/wiki/api/v2/pages?cursor=p2"),
                _response([{"id": "3"}], next_path=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("pages", manager))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # First request hits the base path with the page limit; params carry limit only.
        assert snapshots[0]["url"] == "https://acme.atlassian.net/wiki/api/v2/pages"
        assert snapshots[0]["params"]["limit"] == CONFLUENCE_ENDPOINTS["pages"].limit
        # State saved once, after the first page (which has a next cursor), pointing at the
        # relative next link resolved to an absolute site URL.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ConfluenceResumeConfig(
            next_url="https://acme.atlassian.net/wiki/api/v2/pages?cursor=p2"
        )

    @parameterized.expand(
        [
            ("relative_path", "/wiki/api/v2/pages?cursor=p2", "https://acme.atlassian.net/wiki/api/v2/pages?cursor=p2"),
            (
                "absolute_url",
                "https://acme.atlassian.net/wiki/api/v2/pages?cursor=xyz",
                "https://acme.atlassian.net/wiki/api/v2/pages?cursor=xyz",
            ),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_next_link_resolved_for_second_request(
        self, _name: str, next_path: str, expected_url: str, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_response([{"id": "1"}], next_path=next_path), _response([{"id": "2"}], next_path=None)],
        )

        _rows(_source("pages", _make_manager()))

        assert snapshots[1]["url"] == expected_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "9"}], next_path=None)])

        manager = _make_manager(
            ConfluenceResumeConfig(next_url="https://acme.atlassian.net/wiki/api/v2/pages?cursor=resumed")
        )
        _rows(_source("pages", manager))

        assert snapshots[0]["url"] == "https://acme.atlassian.net/wiki/api/v2/pages?cursor=resumed"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_results_yields_nothing_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_path=None)])

        manager = _make_manager()
        rows = _rows(_source("spaces", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()
