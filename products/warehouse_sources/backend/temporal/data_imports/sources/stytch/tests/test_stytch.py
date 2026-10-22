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
                "The organizations and members tables only exist for Stytch B2B projects, and this is a consumer project. Sync the users and sessions tables instead.",
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
