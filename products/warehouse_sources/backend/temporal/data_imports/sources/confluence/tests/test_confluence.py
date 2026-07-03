import base64
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence import (
    ConfluenceResumeConfig,
    _get_headers,
    _resolve_next_url,
    confluence_source,
    get_rows,
    is_valid_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import (
    CONFLUENCE_ENDPOINTS,
    ENDPOINTS,
)


def _mock_response(status_code: int, json_body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_body if json_body is not None else {}
    response.text = text

    def raise_for_status() -> None:
        if not response.ok:
            raise Exception(f"{status_code} Client Error")

    response.raise_for_status.side_effect = raise_for_status
    return response


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


class TestResolveNextUrl:
    @parameterized.expand(
        [
            (
                "relative_path",
                {"_links": {"next": "/wiki/api/v2/pages?cursor=abc"}},
                "https://acme.atlassian.net/wiki/api/v2/pages?cursor=abc",
            ),
            (
                "absolute_url",
                {"_links": {"next": "https://acme.atlassian.net/wiki/api/v2/pages?cursor=xyz"}},
                "https://acme.atlassian.net/wiki/api/v2/pages?cursor=xyz",
            ),
            ("no_next_key", {"_links": {}}, None),
            ("no_links_key", {"results": []}, None),
            ("null_next", {"_links": {"next": None}}, None),
        ]
    )
    def test_resolve_next_url(self, _name: str, data: dict, expected: str | None) -> None:
        assert _resolve_next_url("acme", data) == expected


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
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(
        self,
        _name: str,
        status_code: int,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = _mock_response(status_code)

        is_valid, message = validate_credentials("acme", "you@example.com", "token", schema_name=schema_name)

        assert is_valid is expected_valid
        assert message == expected_message

    def test_invalid_subdomain_short_circuits(self) -> None:
        is_valid, message = validate_credentials("evil.com", "you@example.com", "token")
        assert is_valid is False
        assert message is not None and "subdomain" in message


class TestConfluenceSource:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape_for_endpoint(self, endpoint: str) -> None:
        response = confluence_source(
            subdomain="acme",
            email="you@example.com",
            api_token="token",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
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


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence.make_tracked_session"
    )
    def test_paginates_until_no_next_and_saves_state(self, mock_session: mock.MagicMock) -> None:
        page1 = _mock_response(
            200,
            {"results": [{"id": "1"}, {"id": "2"}], "_links": {"next": "/wiki/api/v2/pages?cursor=p2"}},
        )
        page2 = _mock_response(200, {"results": [{"id": "3"}], "_links": {}})
        mock_session.return_value.get.side_effect = [page1, page2]

        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        batches = list(
            get_rows(
                subdomain="acme",
                email="you@example.com",
                api_token="token",
                endpoint="pages",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
            )
        )

        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        # State saved once, after the first page (which has a next cursor).
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, ConfluenceResumeConfig)
        assert saved.next_url == "https://acme.atlassian.net/wiki/api/v2/pages?cursor=p2"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session: mock.MagicMock) -> None:
        page = _mock_response(200, {"results": [{"id": "9"}], "_links": {}})
        mock_session.return_value.get.return_value = page

        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = ConfluenceResumeConfig(
            next_url="https://acme.atlassian.net/wiki/api/v2/pages?cursor=resumed"
        )

        list(
            get_rows(
                subdomain="acme",
                email="you@example.com",
                api_token="token",
                endpoint="pages",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
            )
        )

        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://acme.atlassian.net/wiki/api/v2/pages?cursor=resumed"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence.make_tracked_session"
    )
    def test_empty_results_does_not_yield(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(200, {"results": [], "_links": {}})
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        batches = list(
            get_rows(
                subdomain="acme",
                email="you@example.com",
                api_token="token",
                endpoint="spaces",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
            )
        )

        assert batches == []
        manager.save_state.assert_not_called()
