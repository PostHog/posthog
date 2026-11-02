from datetime import UTC, datetime
from typing import Any, Optional

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gitbook import (
    GitBookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.gitbook import (
    GITBOOK_BASE_URL,
    PAGE_SIZE,
    GitBookResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import (
    ENDPOINTS,
    GITBOOK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.source import GitBookSource


def _driver() -> SourceDriver:
    return SourceDriver(GitBookSource(), GitBookSourceConfig(api_token="gb-token"))


def _page(items: list[dict[str, Any]], *, next_page: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"items": items}
    if next_page is not None:
        body["next"] = {"page": next_page}
    return ScriptedResponse(json=body)


class TestTopLevel:
    def test_resumes_from_saved_page_token(self) -> None:
        result = _driver().run(
            "organizations", [_page([{"id": "org2"}])], resume_state=GitBookResumeConfig(next_page="tok2")
        )
        assert result.raised is None
        assert result.rows == [{"id": "org2"}]
        assert result.params("page") == ["tok2"]

    @parameterized.expand(
        [
            ("first_page", None, {"limit": PAGE_SIZE}),
            ("later_page", "tok2", {"limit": PAGE_SIZE, "page": "tok2"}),
        ]
    )
    def test_request_params_carry_limit_and_page_token(
        self, _name: str, page: Optional[str], expected: dict[str, Any]
    ) -> None:
        result = _driver().run("organizations", [_page([{"id": "org1"}], next_page="tok2"), _page([{"id": "org2"}])])
        assert result.raised is None
        request = result.requests[0 if page is None else 1]
        assert request.url.partition("?")[0] == f"{GITBOOK_BASE_URL}/orgs"
        assert request.path == "/v1/orgs"
        assert request.query == {key: (str(value),) for key, value in expected.items()}


class TestFanOut:
    def test_org_fanout_injects_parent_id_into_rows(self) -> None:
        result = _driver().run(
            "members",
            route(
                {
                    "/orgs": [_page([{"id": "org1"}, {"id": "org2"}])],
                    "/orgs/org1/members": [_page([{"id": "user1"}])],
                    "/orgs/org2/members": [_page([{"id": "user1"}, {"id": "user2"}])],
                }
            ),
        )
        assert result.raised is None
        # The same user id in two orgs stays distinguishable via the injected organization_id.
        assert result.rows == [
            {"id": "user1", "organization_id": "org1"},
            {"id": "user1", "organization_id": "org2"},
            {"id": "user2", "organization_id": "org2"},
        ]

    def test_spaces_rows_keep_api_shape_without_injection(self) -> None:
        result = _driver().run(
            "spaces",
            route(
                {
                    "/orgs": [_page([{"id": "org1"}])],
                    "/orgs/org1/spaces": [_page([{"id": "sp1", "organization": "org1"}])],
                }
            ),
        )
        assert result.raised is None
        assert result.rows == [{"id": "sp1", "organization": "org1"}]

    def test_pages_tree_is_flattened_with_parent_links(self) -> None:
        tree = {
            "pages": [
                {
                    "id": "p1",
                    "type": "document",
                    "pages": [{"id": "p1a", "type": "document", "pages": [{"id": "p1a1", "type": "link"}]}],
                },
                {"id": "g1", "type": "group", "pages": [{"id": "p2", "type": "document", "pages": []}]},
            ]
        }
        result = _driver().run(
            "pages",
            route(
                {
                    "/orgs": [_page([{"id": "org1"}])],
                    "/orgs/org1/spaces": [_page([{"id": "sp1"}])],
                    "/spaces/sp1/content/pages": [ScriptedResponse(json=tree)],
                }
            ),
        )
        assert result.raised is None
        assert result.rows == [
            {"id": "p1", "type": "document", "space_id": "sp1", "parent_page_id": None},
            {"id": "p1a", "type": "document", "space_id": "sp1", "parent_page_id": "p1"},
            {"id": "p1a1", "type": "link", "space_id": "sp1", "parent_page_id": "p1a"},
            {"id": "g1", "type": "group", "space_id": "sp1", "parent_page_id": None},
            {"id": "p2", "type": "document", "space_id": "sp1", "parent_page_id": "g1"},
        ]
        # The pages endpoint is not paginated, so it gets no `limit`.
        assert result.requests[-1].url == f"{GITBOOK_BASE_URL}/spaces/sp1/content/pages"
        assert result.requests[-1].path == "/v1/spaces/sp1/content/pages"
        assert result.requests[-1].query == {}

    @parameterized.expand(
        [
            (
                "site_questions",
                "sites",
                "/orgs/{org}/sites/{parent}/questions",
                "site_id",
                {"id": "q1"},
                {"id": "q1"},
            ),
            (
                "team_members",
                "teams",
                "/orgs/{org}/teams/{parent}/members",
                "team_id",
                {"organization": {"id": "membership1", "user": {"id": "user1"}}, "team": {"role": "member"}},
                {
                    "organization": {"id": "membership1", "user": {"id": "user1"}},
                    "team": {"role": "member"},
                    "user_id": "user1",
                },
            ),
        ]
    )
    def test_org_nested_fanout_binds_and_injects_both_parent_ids(
        self,
        endpoint: str,
        parent_segment: str,
        child_path: str,
        parent_key: str,
        api_row: dict[str, Any],
        expected_row: dict[str, Any],
    ) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    "/orgs": [_page([{"id": "org1"}, {"id": "org2"}])],
                    f"/orgs/org1/{parent_segment}": [_page([{"id": "x1"}])],
                    f"/orgs/org2/{parent_segment}": [_page([{"id": "x1"}])],
                    child_path.format(org="org1", parent="x1"): [_page([dict(api_row)])],
                    child_path.format(org="org2", parent="x1"): [_page([dict(api_row)])],
                }
            ),
        )
        assert result.raised is None
        # The same child id under two organizations stays distinguishable via organization_id.
        assert result.rows == [
            {**expected_row, "organization_id": "org1", parent_key: "x1"},
            {**expected_row, "organization_id": "org2", parent_key: "x1"},
        ]

    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 5, 1, 12, 30, 15, 250000, tzinfo=UTC), "2026-05-01T12:30:15Z"),
            ("incremental_first_sync", True, None, "1970-01-01T00:00:00Z"),
            ("full_refresh", False, datetime(2026, 5, 1, tzinfo=UTC), None),
        ]
    )
    def test_site_answers_filter_on_watermark_only_when_incremental(
        self, _name: str, incremental: bool, last_value: Optional[datetime], expected_from: Optional[str]
    ) -> None:
        answers = "/v1/orgs/org1/sites/s1/answers"
        result = _driver().run(
            "site_answers",
            route(
                {
                    "/orgs": [_page([{"id": "org1"}])],
                    "/orgs/org1/sites": [_page([{"id": "s1"}])],
                    answers: [_page([{"id": "a1"}], next_page="tok2"), _page([{"id": "a2"}])],
                }
            ),
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
            incremental_field="createdAt" if incremental else None,
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a1", "a2"]
        answer_requests = [request for request in result.requests if request.path == answers]
        assert len(answer_requests) == 2
        # The watermark filter stays on every page, not just the first.
        assert all(request.param("from") == expected_from for request in answer_requests)

    def test_resume_skips_completed_parents_and_resumes_current_at_token(self) -> None:
        result = _driver().run(
            "teams",
            route(
                {
                    "/orgs": [_page([{"id": "org1"}, {"id": "org2"}, {"id": "org3"}])],
                    "/orgs/org2/teams": [_page([{"id": "t2"}])],
                    "/orgs/org3/teams": [_page([{"id": "t3"}])],
                }
            ),
            resume_state=GitBookResumeConfig(
                fanout_state={
                    "completed": ["/orgs/org1/teams"],
                    "current": "/orgs/org2/teams",
                    "child_state": {"cursor": "tok2"},
                }
            ),
        )
        assert result.raised is None
        assert result.paths == ["/v1/orgs", "/v1/orgs/org2/teams", "/v1/orgs/org3/teams"]
        assert result.requests[1].param("page") == "tok2"
        assert result.rows == [
            {"id": "t2", "organization_id": "org2"},
            {"id": "t3", "organization_id": "org3"},
        ]


class TestFailLoud:
    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_items", {"count": 1})])
    def test_unexpected_payload_fails_loud(self, _name: str, raw_body: Any) -> None:
        # A 200 body that isn't {"items": [...]} means the response shape changed — fail loud.
        result = _driver().run("organizations", [ScriptedResponse(json=raw_body)])
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise(self, _name: str, status: int) -> None:
        result = _driver().run("organizations", [ScriptedResponse(status=status, json={"items": []})])
        assert isinstance(result.raised, HTTPError)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("gb-token") == (expected_valid, expected_message)
        assert network.requests_log[0].path == "/v1/user"
        assert network.requests_log[0].headers["authorization"] == "Bearer gb-token"

    def test_connection_error_is_not_validated(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("gb-token") == (False, "Could not validate GitBook API token")
        assert {request.path for request in network.requests_log} == {"/v1/user"}


class TestSourceResponse:
    @parameterized.expand(
        [
            ("organizations", ["id"]),
            ("spaces", ["id"]),
            ("collections", ["id"]),
            ("sites", ["organization_id", "id"]),
            ("members", ["organization_id", "id"]),
            ("teams", ["organization_id", "id"]),
            ("change_requests", ["space", "id"]),
            ("comments", ["space_id", "id"]),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_primary_keys
        # No stable creation timestamp exists on every object, so we don't partition by datetime.
        assert result.response.partition_mode is None

    def test_endpoint_catalog_is_consistent(self) -> None:
        assert set(GITBOOK_ENDPOINTS) == set(ENDPOINTS)
        # Fan-out endpoints whose ids are not documented as globally unique must carry the parent
        # id in their composite key, and that column must actually be injected into rows.
        for config in GITBOOK_ENDPOINTS.values():
            if config.parent_id_key is not None and config.parent_id_key in config.primary_keys:
                assert config.parent is not None
