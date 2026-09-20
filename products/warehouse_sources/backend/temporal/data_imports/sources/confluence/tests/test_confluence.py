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
    return _raw_response(body)


def _v1_response(results: list[dict[str, Any]], start: int = 0, limit: int = 200) -> Response:
    """A v1 collection page, which echoes back the window the site actually applied."""
    return _raw_response({"results": results, "start": start, "limit": limit, "size": len(results)})


def _raw_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
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
        assert response.primary_keys == config.primary_keys
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
        assert snapshots[0]["params"]["limit"] == CONFLUENCE_ENDPOINTS["pages"].page_size
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


class TestV1Pagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_the_window_the_site_applied_not_the_one_requested(self, MockSession: mock.MagicMock) -> None:
        # The site caps the page at 50 even though the source asks for 200. Treating the short
        # page as the last one would silently truncate the table at 50 rows.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _v1_response([{"id": str(i)} for i in range(50)], start=0, limit=50),
                _v1_response([{"id": "50"}], start=50, limit=50),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("groups", manager))

        assert len(rows) == 51
        assert snapshots[0]["params"]["start"] == 0
        assert snapshots[1]["params"]["start"] == 50
        assert manager.save_state.call_args.args[0] == ConfluenceResumeConfig(offset=50)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_v1_response([{"id": "g"}], start=400, limit=200)])

        _rows(_source("groups", _make_manager(ConfluenceResumeConfig(offset=400))))

        assert snapshots[0]["params"]["start"] == 400

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_users_are_read_out_of_the_search_results(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _v1_response(
                    [
                        {"entityType": "user", "title": "Ada", "user": {"accountId": "a1", "publicName": "Ada"}},
                        {"entityType": "user", "title": "Bo", "user": {"accountId": "b2", "publicName": "Bo"}},
                    ],
                    limit=200,
                )
            ],
        )

        rows = _rows(_source("users", _make_manager()))

        assert [row["accountId"] for row in rows] == ["a1", "b2"]
        assert snapshots[0]["url"] == "https://acme.atlassian.net/wiki/rest/api/search/user"
        assert snapshots[0]["params"]["cql"] == "type=user"


class TestFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_versions_fan_out_per_page_and_carry_the_page_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "100"}, {"id": "200"}], next_path=None),
                _response([{"number": 1, "authorId": "a"}, {"number": 2, "authorId": "b"}], next_path=None),
                _response([{"number": 1, "authorId": "c"}], next_path=None),
            ],
        )

        rows = _rows(_source("page_versions", _make_manager()))

        assert [(row["pageId"], row["number"]) for row in rows] == [("100", 1), ("100", 2), ("200", 1)]
        assert snapshots[1]["url"] == "https://acme.atlassian.net/wiki/api/v2/pages/100/versions"
        assert snapshots[2]["url"] == "https://acme.atlassian.net/wiki/api/v2/pages/200/versions"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_group_members_carry_the_group_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _v1_response([{"id": "grp-1", "name": "confluence-users"}], limit=200),
                _v1_response([{"accountId": "a1"}, {"accountId": "b2"}], limit=200),
            ],
        )

        rows = _rows(_source("group_members", _make_manager()))

        assert [(row["groupId"], row["accountId"]) for row in rows] == [("grp-1", "a1"), ("grp-1", "b2")]
        assert snapshots[1]["url"] == "https://acme.atlassian.net/wiki/rest/api/group/grp-1/membersByGroupId"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_views_yield_one_row_per_page_from_a_bare_object(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "100"}, {"id": "200"}], next_path=None),
                _raw_response({"id": 100, "count": 42}),
                _raw_response({"id": 200, "count": 7}),
            ],
        )

        rows = _rows(_source("page_views", _make_manager()))

        assert [(row["pageId"], row["count"]) for row in rows] == [("100", 42), ("200", 7)]
        assert snapshots[1]["url"] == "https://acme.atlassian.net/wiki/rest/api/analytics/content/100/views"
        # The page listing still asks for full pages, but the analytics endpoint takes no
        # page-size param, so none is sent to it.
        assert snapshots[0]["params"]["limit"] == CONFLUENCE_ENDPOINTS["pages"].page_size
        assert "limit" not in snapshots[1]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_trashed_since_the_listing_is_skipped(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "100"}, {"id": "200"}], next_path=None),
                _raw_response({"message": "not found"}, status_code=404),
                _raw_response({"id": 200, "count": 7}),
            ],
        )

        rows = _rows(_source("page_viewers", _make_manager()))

        assert [(row["pageId"], row["count"]) for row in rows] == [("200", 7)]
