from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence import (
    ConfluenceLinkPaginator,
    ConfluenceResumeConfig,
    is_valid_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import (
    CONFLUENCE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.source import ConfluenceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.confluence import (
    ConfluenceSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        ConfluenceSource(), ConfluenceSourceConfig(subdomain="acme", email="you@example.com", api_token="token")
    )


def _response(results: list[dict[str, Any]], next_path: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"results": results, "_links": {"next": next_path} if next_path else {}})


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
    def test_validate_credentials_status_mapping(
        self,
        _name: str,
        status_code: int,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, message = validate_credentials("acme", "you@example.com", "token", schema_name=schema_name)

        assert is_valid is expected_valid
        assert message == expected_message
        assert {request.path for request in network.requests_log} == {"/wiki/api/v2/spaces"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}

    def test_transport_error_is_not_validated(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("acme", "you@example.com", "token")
        assert is_valid is False
        assert message == "Couldn't reach Confluence to check your credentials. Try again in a few minutes."
        assert {request.path for request in network.requests_log} == {"/wiki/api/v2/spaces"}

    @parameterized.expand(
        [
            ("bare", "acme"),
            ("host", "acme.atlassian.net"),
            ("url_with_path", "https://acme.atlassian.net/wiki/spaces/HOME"),
            ("padded_mixed_case_host", " Acme.Atlassian.net/ "),
        ]
    )
    def test_pasted_site_address_probes_the_atlassian_site(self, _name: str, subdomain: str) -> None:
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            is_valid, _ = validate_credentials(subdomain, "you@example.com", "token")

        assert is_valid is True
        assert network.requests_log
        assert all(
            request.url.lower().startswith("https://acme.atlassian.net/wiki/api/v2/")
            for request in network.requests_log
        )

    @parameterized.expand(
        [
            ("other_host", "evil.com"),
            ("atlassian_lookalike", "acme.atlassian.net.evil.com"),
            ("other_host_url", "https://evil.com/acme.atlassian.net"),
        ]
    )
    def test_invalid_subdomain_short_circuits(self, _name: str, subdomain: str) -> None:
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            is_valid, message = validate_credentials(subdomain, "you@example.com", "token")

        assert is_valid is False
        assert message is not None and "subdomain" in message
        assert network.requests_log == []


class TestConfluenceSource:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape_for_endpoint(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([])])
        assert result.raised is None
        response = result.response
        assert response is not None
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
    def test_paginates_until_no_next_and_saves_state(self) -> None:
        result = _driver().run(
            "pages",
            [
                _response([{"id": "1"}, {"id": "2"}], next_path="/wiki/api/v2/pages?cursor=p2"),
                _response([{"id": "3"}], next_path=None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        # First request hits the base path with the page limit; params carry limit only.
        assert result.requests[0].path == "/wiki/api/v2/pages"
        assert result.requests[0].origin == "https://acme.atlassian.net"
        assert result.queries[0] == {"limit": (str(CONFLUENCE_ENDPOINTS["pages"].limit),)}
        # State saved once, after the first page (which has a next cursor), pointing at the
        # relative next link resolved to an absolute site URL.
        assert result.saved_states == [
            ConfluenceResumeConfig(next_url="https://acme.atlassian.net/wiki/api/v2/pages?cursor=p2")
        ]

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
    def test_next_link_resolved_for_second_request(self, _name: str, next_path: str, expected_url: str) -> None:
        result = _driver().run(
            "pages",
            [_response([{"id": "1"}], next_path=next_path), _response([{"id": "2"}], next_path=None)],
        )

        assert result.raised is None
        assert result.requests[1].path == "/wiki/api/v2/pages"
        assert result.requests[1].origin == "https://acme.atlassian.net"
        assert result.requests[1].param("cursor") == expected_url.split("cursor=", 1)[1]
        assert result.saved_states == [ConfluenceResumeConfig(next_url=expected_url)]

    def test_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "pages",
            [_response([{"id": "9"}], next_path=None)],
            resume_state=ConfluenceResumeConfig(next_url="https://acme.atlassian.net/wiki/api/v2/pages?cursor=resumed"),
        )

        assert result.raised is None
        assert result.requests[0].path == "/wiki/api/v2/pages"
        assert result.requests[0].origin == "https://acme.atlassian.net"
        assert result.requests[0].param("cursor") == "resumed"

    @pytest.mark.parametrize(
        "next_path,expected_url",
        [
            ("/wiki/api/v2/pages?cursor=p2", "https://acme.atlassian.net/wiki/api/v2/pages?cursor=p2"),
            (
                "https://acme.atlassian.net/wiki/api/v2/pages?cursor=p2",
                "https://acme.atlassian.net/wiki/api/v2/pages?cursor=p2",
            ),
        ],
    )
    def test_paginator_prefixes_a_relative_link_when_the_response_has_no_url(
        self, next_path: str, expected_url: str
    ) -> None:
        response = mock.MagicMock()
        response.json.return_value = {"_links": {"next": next_path}}
        paginator = ConfluenceLinkPaginator("https://acme.atlassian.net")

        paginator.update_state(response)

        assert paginator.get_resume_state() == {"next_url": expected_url}


def _permission(operation: str, principal_type: str, principal_id: str) -> dict[str, Any]:
    return {"operation": operation, "principal": {"principalType": principal_type, "principalId": principal_id}}


class TestPermissionsFanout:
    @parameterized.expand(
        [
            ("page_permissions", "/wiki/api/v2/pages", "pageId"),
            ("blogpost_permissions", "/wiki/api/v2/blogposts", "blogPostId"),
        ]
    )
    def test_walks_each_parent_and_skips_deleted_ones(
        self, endpoint: str, parent_path: str, parent_column: str
    ) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    f"{parent_path}/1/permissions": [
                        _response(
                            [_permission("read", "user", "u1")],
                            next_path=f"{parent_path}/1/permissions?cursor=c2",
                        ),
                        _response([_permission("update", "group", "g1")]),
                    ],
                    f"{parent_path}/2/permissions": [ScriptedResponse(status=404)],
                    f"{parent_path}/3/permissions": [_response([_permission("read", "user", "u3")])],
                    parent_path: [_response([{"id": "1"}, {"id": "2"}, {"id": "3"}])],
                }
            ),
        )

        assert result.raised is None
        assert [
            (row[parent_column], row["operation"], row["principalType"], row["principalId"]) for row in result.rows
        ] == [("1", "read", "user", "u1"), ("1", "update", "group", "g1"), ("3", "read", "user", "u3")]
        assert all("principal" not in row for row in result.rows)
        assert result.requests[2].param("cursor") == "c2"
