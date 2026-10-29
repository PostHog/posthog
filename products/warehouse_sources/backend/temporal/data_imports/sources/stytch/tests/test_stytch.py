from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stytch import StytchSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.settings import ENDPOINTS, STYTCH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source import StytchSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.stytch import (
    StytchAPIError,
    StytchResumeConfig,
    build_users_search_body,
    check_endpoint_access,
    validate_credentials,
)


def _response(payload: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=payload)


def _driver() -> SourceDriver:
    return SourceDriver(StytchSource(), StytchSourceConfig(project_id="project-live-x", secret="secret"))


def _search_page(data_key: str, items: list[dict[str, Any]], next_cursor: str | None) -> dict[str, Any]:
    return {data_key: items, "results_metadata": {"total": len(items), "next_cursor": next_cursor}}


class TestBuildUsersSearchBody:
    @pytest.mark.parametrize(
        "value, expected_filter_value",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            (date(2026, 1, 2), "2026-01-02T00:00:00Z"),
            ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ],
    )
    def test_incremental_body_uses_rfc3339_created_at_filter(self, value, expected_filter_value):
        body = build_users_search_body(should_use_incremental_field=True, db_incremental_field_last_value=value)
        assert body["query"] == {
            "operator": "AND",
            "operands": [{"filter_name": "created_at_greater_than", "filter_value": expected_filter_value}],
        }


class TestCheckEndpointAccess:
    @pytest.mark.parametrize(
        "error_type, expected_reason",
        [
            (
                "invalid_consumer_endpoint",
                "The users and sessions tables only exist for Stytch consumer projects, and this is a B2B project. Sync the organizations and members tables instead.",
            ),
            (
                "invalid_b2b_endpoint",
                "The organizations, members, sso_connections, organization_connected_apps and member_connected_apps tables only exist for Stytch B2B projects, and this is a consumer project. Sync the users and sessions tables instead.",
            ),
            ("some_other_denial", "Not available for this Stytch project (some_other_denial)"),
        ],
    )
    def test_product_line_mismatch_names_the_tables_to_use_instead(self, error_type, expected_reason):
        with scripted_network([_response({"error_type": error_type}, 400)]):
            assert check_endpoint_access("project-live-x", "secret", "/v1/users/search") == expected_reason


class TestGetRowsUsers:
    def test_resumes_from_saved_cursor(self):
        result = _driver().run(
            "users",
            [_response(_search_page("results", [{"user_id": "u9"}], None))],
            resume_state=StytchResumeConfig(cursor="cursor-5"),
        )

        assert result.requests[0].json()["cursor"] == "cursor-5"

    def test_a_run_with_no_saved_state_starts_without_a_cursor(self):
        result = _driver().run("users", [_response(_search_page("results", [{"user_id": "u9"}], None))])

        assert "cursor" not in result.requests[0].json()

    def test_incremental_filter_sent_on_every_page(self):
        result = _driver().run(
            "users",
            [
                _response(_search_page("results", [{"user_id": "u1"}], "cursor-2")),
                _response(_search_page("results", [{"user_id": "u2"}], None)),
            ],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
        )

        assert len(result.requests) == 2
        for request in result.requests:
            operands = request.json()["query"]["operands"]
            assert operands[0]["filter_name"] == "created_at_greater_than"

    def test_auth_error_raises_with_error_type(self):
        result = _driver().run("users", [_response({"error_type": "invalid_secret_authentication"}, 401)])

        assert isinstance(result.raised, StytchAPIError)
        assert "error_type=invalid_secret_authentication" in str(result.raised)

    def test_search_timeout_is_retried_and_recovers(self):
        # Stytch's own backend search timeout comes back as a 400, not a 5xx, but it's the same
        # transient condition — it must be retried in-process rather than raised as a hard error.
        result = _driver().run(
            "users",
            [
                _response({"error_type": "search_timeout"}, 400),
                _response(_search_page("results", [{"user_id": "u1"}], None)),
            ],
        )

        assert [item["user_id"] for item in result.rows] == ["u1"]
        assert len(result.requests) == 2


class TestGetRowsSessions:
    def test_saves_users_cursor_between_pages(self):
        result = _driver().run(
            "sessions",
            [
                _response(_search_page("results", [{"user_id": "u1"}], "cursor-2")),
                _response({"sessions": [{"session_id": "s1", "user_id": "u1"}]}),
                _response(_search_page("results", [], None)),
            ],
        )

        assert [state.cursor for state in result.saved_states] == ["cursor-2"]


class TestGetRowsMembers:
    def test_resume_bookmark_skips_completed_chunks(self):
        org_page = _response(_search_page("organizations", [{"organization_id": f"org-{i}"} for i in range(150)], None))
        member_page = _response(_search_page("members", [{"member_id": "m-late"}], None))

        # 150 sorted orgs chunk into [0..99] and [100..149]; the bookmark points at chunk two.
        sorted_ids = sorted(f"org-{i}" for i in range(150))
        result = _driver().run(
            "members",
            route(
                {
                    "/v1/b2b/organizations/search": [org_page],
                    "/v1/b2b/organizations/members/search": [member_page],
                }
            ),
            resume_state=StytchResumeConfig(cursor="member-cursor-3", org_bookmark=sorted_ids[100]),
        )

        member_calls = [request for request in result.requests if request.path.endswith("/members/search")]
        assert len(member_calls) == 1
        assert member_calls[0].json()["organization_ids"] == sorted_ids[100:]
        assert member_calls[0].json()["cursor"] == "member-cursor-3"


class TestGetRowsRbacPolicy:
    POLICY = {
        "policy": {
            "roles": [{"role_id": "stytch_admin", "description": "Admin", "permissions": []}],
            "resources": [{"resource_id": "documents", "description": "Docs", "actions": ["read"]}],
            "scopes": [{"scope": "read:documents", "description": "Read docs", "permissions": []}],
        }
    }

    @pytest.mark.parametrize(
        "script, expected_paths",
        [
            ([POLICY], ["/v1/b2b/rbac/policy"]),
            (
                [{"error_type": "invalid_b2b_endpoint"}, POLICY],
                ["/v1/b2b/rbac/policy", "/v1/rbac/policy"],
            ),
        ],
        ids=["b2b_project", "consumer_project_falls_back"],
    )
    def test_reads_the_policy_of_either_product_line(self, script, expected_paths):
        responses = [_response(payload, 400 if "error_type" in payload else 200) for payload in script]
        result = _driver().run("rbac_policy", responses)

        assert result.raised is None
        assert [request.path for request in result.requests] == expected_paths
        assert [(row["entry_type"], row["entry_id"]) for row in result.rows] == [
            ("role", "stytch_admin"),
            ("resource", "documents"),
            ("scope", "read:documents"),
        ]

    def test_other_errors_do_not_fall_back(self):
        result = _driver().run("rbac_policy", [_response({"error_type": "unauthorized_credentials"}, 401)])

        assert isinstance(result.raised, StytchAPIError)
        assert len(result.requests) == 1


def _org_search(org_ids: list[str]) -> ScriptedResponse:
    return _response(_search_page("organizations", [{"organization_id": org_id} for org_id in org_ids], None))


class TestGetRowsOrganizationFanOut:
    def test_sso_connections_drop_idp_secrets_and_tag_the_protocol(self):
        connections = {
            "saml_connections": [
                {
                    "connection_id": "saml-1",
                    "organization_id": "org-1",
                    "encryption_private_keys": [{"private_key_id": "key-1", "private_key": "fake-pem"}],
                }
            ],
            "oidc_connections": [{"connection_id": "oidc-1", "organization_id": "org-1", "client_secret": "fake"}],
            "external_connections": [{"connection_id": "ext-1", "organization_id": "org-1"}],
        }
        result = _driver().run(
            "sso_connections",
            route(
                {
                    "/v1/b2b/organizations/search": [_org_search(["org-1"])],
                    "/v1/b2b/sso/org-1": [_response(connections)],
                }
            ),
        )

        assert [(row["connection_id"], row["connection_type"]) for row in result.rows] == [
            ("saml-1", "saml"),
            ("oidc-1", "oidc"),
            ("ext-1", "external"),
        ]
        assert "client_secret" not in result.rows[1]
        assert result.rows[0]["encryption_private_keys"] == [{"private_key_id": "key-1"}]

    @pytest.mark.parametrize(
        "resume_bookmark, expected_org_paths",
        [
            (None, ["org-a", "org-b", "org-c"]),
            ("org-b", ["org-b", "org-c"]),
            # The bookmarked organization was deleted between attempts: resume at the next one.
            ("org-bb", ["org-c"]),
        ],
    )
    def test_walks_organizations_from_the_bookmark_and_skips_deleted_ones(self, resume_bookmark, expected_org_paths):
        apps = {"connected_apps": [{"connected_app_id": "app-1"}]}
        result = _driver().run(
            "organization_connected_apps",
            route(
                {
                    "/v1/b2b/organizations/search": [_org_search(["org-c", "org-a", "org-b"])],
                    "/v1/b2b/organizations/org-a/connected_apps": [_response(apps)],
                    # Deleted after the organization search ran.
                    "/v1/b2b/organizations/org-b/connected_apps": [
                        _response({"error_type": "organization_not_found"}, 404)
                    ],
                    "/v1/b2b/organizations/org-c/connected_apps": [_response(apps)],
                }
            ),
            resume_state=StytchResumeConfig(org_bookmark=resume_bookmark) if resume_bookmark else None,
        )

        assert result.raised is None
        fetched = [
            request.path.split("/")[4] for request in result.requests if request.path.endswith("/connected_apps")
        ]
        assert fetched == expected_org_paths
        assert [(row["organization_id"], row["connected_app_id"]) for row in result.rows] == [
            (org_id, "app-1") for org_id in expected_org_paths if org_id != "org-b"
        ]

    def test_stages_the_next_organization_before_yielding(self):
        apps = {"connected_apps": [{"connected_app_id": "app-1"}]}
        result = _driver().run(
            "organization_connected_apps",
            route(
                {
                    "/v1/b2b/organizations/search": [_org_search(["org-a", "org-b"])],
                    "/v1/b2b/organizations/org-a/connected_apps": [_response(apps)],
                    "/v1/b2b/organizations/org-b/connected_apps": [_response(apps)],
                }
            ),
        )

        assert [state.org_bookmark for state in result.saved_states] == ["org-b"]


class TestGetRowsMemberConnectedApps:
    def test_fetches_each_member_across_member_search_pages(self):
        result = _driver().run(
            "member_connected_apps",
            route(
                {
                    "/v1/b2b/organizations/search": [_org_search(["org-1"])],
                    "/v1/b2b/organizations/members/search": [
                        _response(
                            _search_page("members", [{"member_id": "m-1", "organization_id": "org-1"}], "page-2")
                        ),
                        _response(_search_page("members", [{"member_id": "m-2", "organization_id": "org-1"}], None)),
                    ],
                    "/v1/b2b/organizations/org-1/members/m-1/connected_apps": [
                        _response({"connected_apps": [{"connected_app_id": "app-1", "scopes_granted": "openid"}]})
                    ],
                    "/v1/b2b/organizations/org-1/members/m-2/connected_apps": [_response({"connected_apps": []})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"connected_app_id": "app-1", "scopes_granted": "openid", "organization_id": "org-1", "member_id": "m-1"}
        ]
        member_searches = [request.json() for request in result.requests if request.path.endswith("/members/search")]
        assert [body.get("cursor") for body in member_searches] == [None, "page-2"]
        assert [(state.org_bookmark, state.cursor) for state in result.saved_states] == [("org-1", "page-2")]

    @pytest.mark.parametrize(
        "member_bookmark, expected_members",
        [
            (None, ["m-1", "m-2", "m-3"]),
            ("m-2", ["m-2", "m-3"]),
            # The bookmarked member was deleted between attempts: re-read the whole page.
            ("m-gone", ["m-1", "m-2", "m-3"]),
        ],
    )
    def test_resumes_at_the_bookmarked_member(self, member_bookmark, expected_members):
        members = [{"member_id": member_id, "organization_id": "org-1"} for member_id in ["m-1", "m-2", "m-3"]]
        apps = {"connected_apps": [{"connected_app_id": "app-1"}]}
        result = _driver().run(
            "member_connected_apps",
            route(
                {
                    "/v1/b2b/organizations/search": [_org_search(["org-1"])],
                    "/v1/b2b/organizations/members/search": [_response(_search_page("members", members, None))],
                    **{
                        f"/v1/b2b/organizations/org-1/members/{member_id}/connected_apps": [_response(apps)]
                        for member_id in ["m-1", "m-2", "m-3"]
                    },
                }
            ),
            resume_state=StytchResumeConfig(cursor="page-2", org_bookmark="org-1", member_bookmark=member_bookmark),
        )

        assert result.raised is None
        assert [row["member_id"] for row in result.rows] == expected_members
        member_searches = [request.json() for request in result.requests if request.path.endswith("/members/search")]
        assert [body.get("cursor") for body in member_searches] == ["page-2"]
        # Each yield stages the next unread member on the same page.
        assert [(state.cursor, state.member_bookmark) for state in result.saved_states] == [
            ("page-2", member_id) for member_id in expected_members[1:]
        ]


class TestStytchSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = STYTCH_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, []).response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Stytch search ordering is undocumented, so the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestHttpSampleCaptureDisabled:
    """Stytch responses carry end-user PII, so every credentialed request path must build its
    tracked session with capture disabled and the secret redacted — reverting either leaks PII
    into the shared HTTP sample bucket."""

    EXPECTED_OPTIONS = {"capture": False, "redact_values": ("secret",)}

    def _drive_validate(self) -> list[dict[str, Any]]:
        with scripted_network([_response({}, 200)]) as network:
            validate_credentials("project-live-x", "secret")
        return network.session_options

    def _drive_check_access(self) -> list[dict[str, Any]]:
        with scripted_network([_response({}, 200)]) as network:
            check_endpoint_access("project-live-x", "secret", "/v1/users/search")
        return network.session_options

    def _drive_get_rows(self) -> list[dict[str, Any]]:
        return _driver().run("users", [_response(_search_page("results", [], None))]).session_options

    @pytest.mark.parametrize("driver", ["_drive_validate", "_drive_check_access", "_drive_get_rows"])
    def test_credentialed_paths_disable_capture_and_redact_secret(self, driver):
        session_options = getattr(self, driver)()

        assert session_options
        assert all(options == self.EXPECTED_OPTIONS for options in session_options)
