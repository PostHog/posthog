import json
from datetime import UTC, datetime
from typing import Any, Optional

from unittest.mock import patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse import discourse
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.discourse import (
    POSTS_PAGE_SIZE,
    DiscourseHostNotAllowedError,
    DiscoursePostsPaginator,
    DiscourseResumeConfig,
    DiscourseUserActionsPaginator,
    hostname_of,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.settings import USER_ACTIONS_PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source import DiscourseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.discourse import (
    DiscourseSourceConfig,
)

BASE_URL = "https://forum.example.com"
API_KEY = "secret-key"
API_USERNAME = "system"


def _post(post_id: int) -> dict[str, Any]:
    return {"id": post_id, "topic_id": 1, "raw": f"post {post_id}"}


def _json_response(body: Any) -> requests.Response:
    resp = requests.Response()
    resp.status_code = 200
    resp.url = f"{BASE_URL}/probe"
    resp._content = json.dumps(body).encode()
    return resp


def _driver(base_url: str = BASE_URL) -> SourceDriver:
    return SourceDriver(
        DiscourseSource(), DiscourseSourceConfig(base_url=base_url, api_key=API_KEY, api_username=API_USERNAME)
    )


def _action(created_at: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "action_type": 5,
        "created_at": created_at,
        "target_user_id": 7,
        "acting_user_id": 9,
        "topic_id": 3,
        "post_number": 2,
    }
    row.update(overrides)
    return row


class TestNormalizeAndHostname:
    @parameterized.expand(
        [
            ("plain", "https://forum.example.com", "https://forum.example.com"),
            ("trailing_slash", "https://forum.example.com/", "https://forum.example.com"),
            ("no_scheme", "forum.example.com", "https://forum.example.com"),
            ("whitespace", "  https://forum.example.com  ", "https://forum.example.com"),
        ]
    )
    def test_normalize_base_url(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_base_url(raw) == expected

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://forum.example.com"),
            ("userinfo", "https://169.254.169.254@forum.example.com"),
            ("backslash", "https://169.254.169.254\\@forum.example.com"),
            ("encoded_backslash", "https://169.254.169.254%5C@forum.example.com"),
        ]
    )
    def test_hostname_of_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        assert hostname_of(raw_url) is None


class TestDiscoursePostsPaginator:
    def test_empty_page_stops(self) -> None:
        paginator = DiscoursePostsPaginator(stop_at_or_before=None)
        paginator.update_state(_json_response({"latest_posts": []}), data=[])
        assert paginator.has_next_page is False

    def test_resume_state_round_trip(self) -> None:
        paginator = DiscoursePostsPaginator()
        data = [_post(i) for i in range(POSTS_PAGE_SIZE, 0, -1)]
        paginator.update_state(_json_response({"latest_posts": data}), data=data)
        state = paginator.get_resume_state()
        assert state == {"before": 1}

        resumed = DiscoursePostsPaginator()
        assert state is not None
        resumed.set_resume_state(state)
        assert resumed._before == 1
        assert resumed.has_next_page is True


class TestPipelineTransport:
    def test_topics_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "topics",
            [
                ScriptedResponse(json={"topic_list": {"topics": [{"id": 99}]}}),
                ScriptedResponse(json={"topic_list": {"topics": []}}),
            ],
            resume_state=DiscourseResumeConfig(page=3),
        )
        assert result.raised is None
        assert result.rows == [{"id": 99}]
        assert result.params("page") == ["3", "4"]

    def test_users_flattens_nested_user_object(self) -> None:
        result = _driver().run(
            "users",
            [
                ScriptedResponse(
                    json={
                        "directory_items": [
                            {"id": 32, "post_count": 10, "user": {"id": 32, "username": "codinghorror"}}
                        ]
                    }
                ),
                ScriptedResponse(json={"directory_items": []}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": 32, "post_count": 10, "username": "codinghorror"}]

    def test_posts_incremental_stops_at_watermark(self) -> None:
        page1 = [_post(i) for i in range(129, 79, -1)]  # ids 129..80
        result = _driver().run(
            "posts",
            [ScriptedResponse(json={"latest_posts": page1})],
            db_incremental_field_last_value=80,
            incremental_field="id",
        )
        assert result.raised is None
        assert result.rows == page1
        assert len(result.requests) == 1

    def test_posts_resumes_from_saved_before_cursor(self) -> None:
        result = _driver().run(
            "posts",
            [ScriptedResponse(json={"latest_posts": [_post(5)]})],
            resume_state=DiscourseResumeConfig(before=500),
        )
        assert result.raised is None
        assert result.rows == [_post(5)]
        assert result.params("before") == ["500"]

    def test_auth_headers_sent_without_bearer_or_basic_scheme(self) -> None:
        result = _driver().run("categories", [ScriptedResponse(json={"category_list": {"categories": []}})])
        assert result.raised is None
        assert result.requests[0].headers["api-key"] == API_KEY
        assert result.requests[0].headers["api-username"] == API_USERNAME
        assert "authorization" not in result.requests[0].headers

    def test_blocks_unsafe_hosts(self) -> None:
        with patch.object(discourse, "_is_host_safe", return_value=(False, "blocked")):
            result = _driver("https://10.0.0.1").run("categories", [])
        assert isinstance(result.raised, DiscourseHostNotAllowedError)

    def test_blocks_ambiguous_url(self) -> None:
        result = _driver("https://169.254.169.254\\@forum.example.com").run("categories", [])
        assert isinstance(result.raised, DiscourseHostNotAllowedError)

    @parameterized.expand(
        [
            ("categories", ["id"]),
            ("topics", ["id"]),
            ("posts", ["id"]),
            ("tags", ["id"]),
            ("groups", ["id"]),
            ("users", ["id"]),
        ]
    )
    def test_source_returns_declared_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    @parameterized.expand([("categories",), ("tags",), ("groups",), ("users",), ("topics",)])
    def test_non_post_endpoints_sort_mode_is_ascending(self, endpoint: str) -> None:
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.sort_mode == "asc"


class TestDiscourseUserActionsPaginator:
    WATERMARK = datetime(2026, 3, 1, tzinfo=UTC)

    def _page(self, rows: list[dict[str, Any]], watermark: Optional[datetime]) -> DiscourseUserActionsPaginator:
        paginator = DiscourseUserActionsPaginator(limit=USER_ACTIONS_PAGE_SIZE, stop_at_or_before=watermark)
        paginator.update_state(_json_response({"user_actions": rows}), data=rows)
        return paginator

    @parameterized.expand([("short_page", 1, False), ("full_page", USER_ACTIONS_PAGE_SIZE, True)])
    def test_full_refresh_walks_on_only_while_pages_stay_full(
        self, _name: str, row_count: int, expects_next_page: bool
    ) -> None:
        rows = [_action("2026-01-01T00:00:00.000Z")] * row_count
        assert self._page(rows, None).has_next_page is expects_next_page

    @parameterized.expand(
        [
            # The whole page is already synced, so this user's walk is done.
            ("page_predates_the_watermark", ["2026-02-28T12:00:00.000Z"] * USER_ACTIONS_PAGE_SIZE, False),
            # Only the first row is newer, but the rest of the stream still has to be walked.
            (
                "page_still_holds_newer_rows",
                ["2026-03-05T00:00:00.000Z"] + ["2026-02-01T00:00:00.000Z"] * (USER_ACTIONS_PAGE_SIZE - 1),
                True,
            ),
            # Nothing on the page can be compared against the watermark, so it proves nothing
            # about how far back the walk has got.
            ("unparsable_timestamps", ["not-a-date"] * USER_ACTIONS_PAGE_SIZE, True),
        ]
    )
    def test_incremental_stops_only_once_a_whole_page_predates_the_watermark(
        self, _name: str, created_ats: list[str], expects_next_page: bool
    ) -> None:
        rows = [_action(created_at) for created_at in created_ats]
        assert self._page(rows, self.WATERMARK).has_next_page is expects_next_page


class TestAdminUsers:
    def test_sorts_ascending_by_creation_date_and_never_asks_for_emails(self) -> None:
        # `show_emails=true` writes a staff action log entry per request, so a sync of a large
        # forum would bury the customer's own audit log.
        result = _driver().run("admin_users", [ScriptedResponse(json=[])])
        assert result.raised is None
        assert result.requests[0].param("order") == "created"
        assert result.requests[0].param("asc") == "true"
        assert result.requests[0].param("show_emails") is None


class TestGroupMembers:
    @parameterized.expand([("restricted_roster", 403), ("group_gone", 404)])
    def test_skips_a_group_whose_roster_cannot_be_read(self, _name: str, status: int) -> None:
        result = _driver().run(
            "group_members",
            [
                ScriptedResponse(json={"groups": [{"id": 41, "name": "secret"}, {"id": 42, "name": "staff"}]}),
                ScriptedResponse(status=status, json={"errors": ["nope"]}),
                ScriptedResponse(json={"members": [{"id": 2}], "meta": {"total": 1}}),
                ScriptedResponse(json={"groups": []}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": 2, "group_id": 42, "group_name": "staff"}]


class TestUserActions:
    def test_narrows_to_public_actions_and_drops_post_text(self) -> None:
        # With no server-side filter the stream carries every action type, and the admin
        # identity also reads whispers and hidden posts, so both narrowing steps run over the
        # response instead.
        reply = _action("2026-03-05T00:00:00.000Z", excerpt="post body", edit_reason="typo")
        private_message = _action("2026-03-04T00:00:00.000Z", action_type=12)
        result = _driver().run(
            "user_actions",
            [
                ScriptedResponse(json=[{"id": 7, "username": "alice"}]),
                ScriptedResponse(json={"user_actions": [reply, private_message]}),
                ScriptedResponse(json=[]),
            ],
        )
        assert result.raised is None
        assert result.rows == [_action("2026-03-05T00:00:00.000Z")]

    def test_incremental_stops_walking_a_user_at_the_watermark(self) -> None:
        page = [_action("2026-02-28T12:00:00.000Z")] * USER_ACTIONS_PAGE_SIZE
        result = _driver().run(
            "user_actions",
            [
                ScriptedResponse(json=[{"id": 7, "username": "alice"}]),
                ScriptedResponse(json={"user_actions": page}),
                ScriptedResponse(json=[]),
            ],
            incremental_field="created_at",
            db_incremental_field_last_value="2026-03-01T00:00:00Z",
        )
        assert result.raised is None
        assert len(result.rows) == USER_ACTIONS_PAGE_SIZE
        # One parent page, one child page, one terminal parent page: the child never walked on.
        assert result.paths == ["/admin/users.json", "/user_actions.json", "/admin/users.json"]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("unavailable", 503)])
    def test_retryable_statuses_are_retried_then_succeed(self, _name: str, status: int) -> None:
        result = _driver().run(
            "categories",
            [
                ScriptedResponse(status=status, json={}),
                ScriptedResponse(json={"category_list": {"categories": [{"id": 1}]}}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 2

    def test_persistent_server_error_exhausts_retries(self) -> None:
        result = _driver().run("categories", always(ScriptedResponse(status=500, json={})))
        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_permanent_statuses_raise_http_error(self, _name: str, status: int) -> None:
        result = _driver().run("categories", [ScriptedResponse(status=status, json={"errors": ["nope"]})])
        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand([("moved", 301), ("found", 302), ("temporary", 307)])
    def test_redirects_are_refused(self, _name: str, status: int) -> None:
        result = _driver().run(
            "categories", [ScriptedResponse(status=status, json={}, headers={"Location": "https://evil.example.com"})]
        )
        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised).lower()


class TestValidateCredentials:
    def _validate(self, script: Script, schema_name: Optional[str] = None) -> tuple[bool, Optional[str]]:
        with scripted_network(script):
            return validate_credentials(BASE_URL, API_KEY, API_USERNAME, schema_name=schema_name, team_id=1)

    def test_validate_credentials_rejects_403_for_scoped_probe(self) -> None:
        body = {"errors": ["The API username or key is invalid."], "error_type": "invalid_access"}
        valid, message = self._validate([ScriptedResponse(status=403, json=body)], schema_name="posts")
        assert valid is False
        assert message == "The API username or key is invalid."

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A scoped API key may not cover the /session/current.json probe even though it's valid
        # for the tables the user actually wants to sync — source creation must still go through.
        body = {"errors": ["The API username or key is invalid."], "error_type": "invalid_access"}
        assert self._validate([ScriptedResponse(status=403, json=body)]) == (True, None)

    def test_validate_credentials_rejects_redirects(self) -> None:
        valid, _ = self._validate([ScriptedResponse(status=302, headers={"Location": "https://evil.example.com"})])
        assert valid is False

    def test_validate_credentials_rejects_unsafe_host(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(discourse, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        valid, message = validate_credentials(BASE_URL, API_KEY, API_USERNAME, team_id=1)
        assert valid is False
        assert message == "blocked"

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://forum.example.com"),
            ("userinfo", "https://169.254.169.254@forum.example.com"),
            ("backslash", "https://169.254.169.254\\@forum.example.com"),
        ]
    )
    def test_validate_credentials_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        valid, message = validate_credentials(raw_url, API_KEY, API_USERNAME, team_id=1)
        assert valid is False
        assert message == "Invalid Discourse instance URL"

    def test_validate_credentials_handles_connection_errors(self) -> None:
        valid, message = self._validate(always(ConnectionResetError("boom")))
        assert valid is False
        assert message is not None and "Could not connect to Discourse" in message

    def test_validate_credentials_generic_error_status(self) -> None:
        valid, message = self._validate(always(ScriptedResponse(status=500, json={})))
        assert valid is False
        assert message == "Discourse returned HTTP 500"
