from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.helpscout import (
    HelpScoutSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.helpscout import (
    HelpScoutResumeConfig,
    _client_config,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.settings import (
    ENDPOINTS,
    HELP_SCOUT_API_BASE,
    HELP_SCOUT_API_BASE_V3,
    HELP_SCOUT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source import HelpScoutSource


def _page(embedded_key: str, items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"_embedded": {embedded_key: items}, "_links": {}}
    if next_url:
        body["_links"]["next"] = {"href": next_url}
    return ScriptedResponse(json=body)


def _run(
    endpoint: str,
    script: Script,
    *,
    resume_state: HelpScoutResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    source = HelpScoutSource()
    config = HelpScoutSourceConfig(helpscout_integration_id=456)
    with mock.patch.object(source, "_get_access_token", return_value="token"):
        return SourceDriver(source, config).run(endpoint, script, resume_state=resume_state, **inputs)


class TestAuth:
    def test_client_config_sends_bearer_token(self) -> None:
        # The token now comes from the Integration, so the source must not mint its own.
        auth = _client_config("token", HELP_SCOUT_API_BASE)["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "token"

    def test_client_config_pins_requests_to_the_api_host(self) -> None:
        # Pagination follows `_links.next.href` out of the response body, so the client must
        # refuse off-host URLs and redirects rather than replay the bearer token elsewhere.
        config = _client_config("token", HELP_SCOUT_API_BASE)
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False

    def test_client_config_excludes_requests_from_sample_capture(self) -> None:
        # Conversation subjects and thread bodies are free-text, customer-authored support
        # content, so responses must not land in HTTP sample capture.
        assert _client_config("token", HELP_SCOUT_API_BASE)["capture"] is False

    def test_off_host_next_link_is_rejected(self) -> None:
        result = _run(
            "mailboxes",
            [_page("mailboxes", [{"id": 1}], next_url="https://evil.example.com/v2/mailboxes?page=2")],
            api_version="v2",
        )

        assert isinstance(result.raised, ValueError)
        assert "evil.example.com" in str(result.raised)
        assert result.paths == ["/v2/mailboxes"]
        assert result.rows == [{"id": 1}]


class TestVersionRouting:
    @pytest.mark.parametrize(
        "api_version,endpoint,base",
        [
            ("v2", "conversations", HELP_SCOUT_API_BASE),
            ("v2", "customers", HELP_SCOUT_API_BASE),
            ("v2", "mailboxes", HELP_SCOUT_API_BASE),
            ("v3", "conversations", HELP_SCOUT_API_BASE_V3),
            ("v3", "customers", HELP_SCOUT_API_BASE_V3),
            # Help Scout has no v3 route for these, so a v3 pin keeps them on v2.
            ("v3", "mailboxes", HELP_SCOUT_API_BASE),
            ("v3", "users", HELP_SCOUT_API_BASE),
            ("v3", "tags", HELP_SCOUT_API_BASE),
            ("v3", "workflows", HELP_SCOUT_API_BASE),
            ("v3", "organizations", HELP_SCOUT_API_BASE),
            ("v3", "teams", HELP_SCOUT_API_BASE),
        ],
    )
    def test_request_url_follows_the_pinned_version(self, api_version: str, endpoint: str, base: str) -> None:
        result = _run(endpoint, [_page(HELP_SCOUT_ENDPOINTS[endpoint].embedded_key, [])], api_version=api_version)

        assert result.raised is None
        assert [url.partition("?")[0] for url in result.urls] == [f"{base}/{endpoint}"]

    def test_unknown_version_is_rejected(self) -> None:
        result = _run("conversations", [], api_version="v9")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported Help Scout API version" in str(result.raised)
        assert result.requests == []


class TestTopLevelPagination:
    def test_paginates_via_hal_next_link(self) -> None:
        next_url = f"{HELP_SCOUT_API_BASE}/mailboxes?page=2"
        result = _run(
            "mailboxes",
            [
                _page("mailboxes", [{"id": 1}, {"id": 2}], next_url=next_url),
                _page("mailboxes", [{"id": 3}]),
            ],
            api_version="v2",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.urls == [f"{HELP_SCOUT_API_BASE}/mailboxes", next_url]

    def test_first_request_uses_endpoint_path_with_no_params(self) -> None:
        result = _run("tags", [_page("tags", [])])

        assert result.urls == [f"{HELP_SCOUT_API_BASE}/tags"]
        assert result.queries[0] == {}

    def test_resumes_from_saved_state(self) -> None:
        resume_url = f"{HELP_SCOUT_API_BASE}/users?page=3"
        result = _run(
            "users",
            [_page("users", [{"id": 9}])],
            resume_state=HelpScoutResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.urls == [resume_url]
        assert result.queries[0] == {"page": ("3",)}
        assert result.rows == [{"id": 9}]

    def test_saves_state_after_each_non_terminal_page(self) -> None:
        next_url = f"{HELP_SCOUT_API_BASE}/workflows?page=2"
        result = _run(
            "workflows",
            [_page("workflows", [{"id": 1}], next_url=next_url), _page("workflows", [{"id": 2}])],
        )

        assert result.raised is None
        assert result.saved_states == [HelpScoutResumeConfig(next_url=next_url)]
        assert result.committed_states == [HelpScoutResumeConfig(next_url=next_url)]

    def test_terminal_single_page_saves_no_state(self) -> None:
        result = _run("tags", [_page("tags", [{"id": 1}])])

        assert result.raised is None
        assert result.saved_states == []

    def test_missing_embedded_block_yields_nothing(self) -> None:
        # A 200 body without an `_embedded` block is a legitimate empty page, not an error.
        result = _run("mailboxes", [ScriptedResponse(json={"page": {"totalElements": 0}, "_links": {}})])

        assert result.raised is None
        assert result.rows == []


class TestIncrementalParams:
    def test_conversations_incremental_sends_modified_since_and_sort(self) -> None:
        result = _run(
            "conversations",
            [_page("conversations", [])],
            api_version="v2",
            incremental_field="modifiedAt",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        assert result.requests[0].param("modifiedSince") == "2024-01-01T00:00:00Z"
        assert result.requests[0].param("sortField") == "modifiedAt"
        assert result.requests[0].param("sortOrder") == "asc"

    def test_conversations_full_refresh_sorts_on_created_at(self) -> None:
        result = _run("conversations", [_page("conversations", [])], api_version="v2")

        assert result.requests[0].param("modifiedSince") is None
        assert result.requests[0].param("sortField") == "createdAt"
        assert result.requests[0].param("sortOrder") == "asc"

    def test_customers_incremental_sends_modified_since(self) -> None:
        result = _run(
            "customers",
            [_page("customers", [])],
            api_version="v2",
            incremental_field="modifiedAt",
            db_incremental_field_last_value="2024-06-01T00:00:00Z",
        )

        assert result.requests[0].param("modifiedSince") == "2024-06-01T00:00:00Z"

    @pytest.mark.parametrize("endpoint", ["conversations", "customers"])
    def test_v3_incremental_sends_only_modified_since(self, endpoint: str) -> None:
        result = _run(
            endpoint,
            [_page(endpoint, [])],
            api_version="v3",
            incremental_field="modifiedAt",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        assert result.queries[0] == {"modifiedSince": ("2024-01-01T00:00:00Z",)}

    @pytest.mark.parametrize("endpoint", ["conversations", "customers"])
    def test_v3_full_refresh_sends_no_sort_params(self, endpoint: str) -> None:
        # v3 rejects sortField/sortOrder with a 400, so the v2 full-refresh sort must not leak in.
        result = _run(endpoint, [_page(endpoint, [])], api_version="v3")

        assert result.queries[0] == {}

    @pytest.mark.parametrize(
        "endpoint,expected_query",
        [
            ("mailboxes", {}),
            ("users", {}),
            ("tags", {}),
            ("workflows", {}),
            ("teams", {}),
            # The default lastInteractionAt sort reorders rows mid-sync, so a stable sort is sent.
            ("organizations", {"sort": ("name,asc",)}),
        ],
    )
    def test_endpoints_without_sort_support_send_only_static_params(
        self, endpoint: str, expected_query: dict[str, tuple[str, ...]]
    ) -> None:
        result = _run(endpoint, [_page(HELP_SCOUT_ENDPOINTS[endpoint].embedded_key, [])])

        assert result.queries[0] == expected_query


class TestRetries:
    @pytest.mark.parametrize("retryable_status", [429, 500, 503])
    def test_retryable_status_triggers_retry_then_succeeds(self, retryable_status: int) -> None:
        result = _run(
            "conversations",
            [ScriptedResponse(status=retryable_status, json={}), _page("conversations", [{"id": 1}])],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert len(result.requests) == 2

    def test_non_retryable_4xx_raises_immediately(self) -> None:
        result = _run("conversations", [ScriptedResponse(status=403, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestFanout:
    @pytest.mark.parametrize(
        "api_version,endpoint,parent,child_path,base",
        [
            ("v2", "threads", "conversations", "conversations/42/threads", HELP_SCOUT_API_BASE),
            ("v3", "threads", "conversations", "conversations/42/threads", HELP_SCOUT_API_BASE_V3),
            ("v2", "mailbox_fields", "mailboxes", "mailboxes/42/fields", HELP_SCOUT_API_BASE),
            # Mailbox fields have no v3 route, so a v3 pin keeps parent and child on v2.
            ("v3", "mailbox_fields", "mailboxes", "mailboxes/42/fields", HELP_SCOUT_API_BASE),
        ],
    )
    def test_parent_and_child_endpoints(
        self, api_version: str, endpoint: str, parent: str, child_path: str, base: str
    ) -> None:
        result = _run(
            endpoint,
            [_page(parent, [{"id": 42}]), _page(HELP_SCOUT_ENDPOINTS[endpoint].embedded_key, [{"id": 7}])],
            api_version=api_version,
        )

        assert result.raised is None
        assert result.urls == [f"{base}/{parent}", f"{base}/{child_path}"]
        assert result.queries == [{}, {}]

    @pytest.mark.parametrize(
        "endpoint,parent,parent_key",
        [("threads", "conversations", "conversation_id"), ("mailbox_fields", "mailboxes", "mailbox_id")],
    )
    def test_child_rows_carry_the_parent_id(self, endpoint: str, parent: str, parent_key: str) -> None:
        result = _run(
            endpoint,
            [_page(parent, [{"id": 42}]), _page(HELP_SCOUT_ENDPOINTS[endpoint].embedded_key, [{"id": 7, "x": "y"}])],
        )

        assert result.raised is None
        assert result.rows == [{parent_key: 42, "id": 7, "x": "y"}]

    def test_resume_seeds_fanout_state(self) -> None:
        state = {"completed": ["/conversations/1/threads"], "current": None, "child_state": None}
        result = _run(
            "threads",
            [_page("conversations", [{"id": 1}, {"id": 2}]), _page("threads", [{"id": 8}])],
            resume_state=HelpScoutResumeConfig(fanout_state=state),
        )

        assert result.raised is None
        assert result.paths == ["/v3/conversations", "/v3/conversations/2/threads"]

    def test_checkpoints_fanout_progress(self) -> None:
        result = _run(
            "threads",
            [_page("conversations", [{"id": 1}]), _page("threads", [{"id": 7}])],
        )

        assert result.raised is None
        assert any(
            state.fanout_state and "/conversations/1/threads" in state.fanout_state["completed"]
            for state in result.saved_states
        )


def _report_page(results: list[dict[str, Any]], page: int, pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={"facets": {}, "results": results, "page": page, "count": 0, "pages": pages})


class TestHappinessRatingsReport:
    def test_walks_pages_until_the_last_page(self) -> None:
        result = _run(
            "happiness_ratings",
            [
                _report_page([{"id": 1, "threadid": 10}], page=1, pages=2),
                _report_page([{"id": 2, "threadid": 20}], page=2, pages=2),
            ],
        )

        assert result.raised is None
        assert [row["threadid"] for row in result.rows] == [10, 20]
        assert result.paths == ["/v2/reports/happiness/ratings", "/v2/reports/happiness/ratings"]
        assert [request.param("page") for request in result.requests] == ["1", "2"]
        first = result.requests[0]
        assert first.param("start") == "2011-01-01T00:00:00Z"
        assert first.param("end") is not None
        assert first.param("sortField") == "number"
        assert first.param("sortOrder") == "ASC"
        # The window end stays fixed across pages so page offsets don't shift mid-sync.
        assert result.requests[1].param("end") == first.param("end")
        assert result.saved_states == [HelpScoutResumeConfig(page=2, report_end=first.param("end") or "")]

    def test_resumes_from_saved_page_and_window(self) -> None:
        result = _run(
            "happiness_ratings",
            [_report_page([{"id": 3, "threadid": 30}], page=3, pages=3)],
            resume_state=HelpScoutResumeConfig(page=3, report_end="2024-05-01T00:00:00Z"),
        )

        assert result.raised is None
        assert result.requests[0].param("page") == "3"
        assert result.requests[0].param("end") == "2024-05-01T00:00:00Z"
        assert result.rows == [{"id": 3, "threadid": 30}]


class TestSourceResponseShape:
    @pytest.mark.parametrize(
        "api_version,desc_endpoints",
        [
            ("v2", {}),
            # v3 lists are newest-first, not ordered by the modifiedAt watermark.
            ("v3", {"conversations": "desc", "customers": "desc"}),
        ],
    )
    def test_response_metadata_per_top_level_endpoint(self, api_version: str, desc_endpoints: dict[str, str]) -> None:
        for endpoint in ENDPOINTS:
            config = HELP_SCOUT_ENDPOINTS[endpoint]
            if config.fanout or config.is_report:
                continue
            result = _run(endpoint, [_page(config.embedded_key, [])], api_version=api_version)
            response = result.response

            assert result.raised is None
            assert response is not None
            assert response.name == endpoint
            assert response.primary_keys == config.primary_key
            assert response.sort_mode == desc_endpoints.get(endpoint, "asc")
            assert response.partition_mode == ("datetime" if config.partition_key else None)
            assert response.partition_keys == ([config.partition_key] if config.partition_key else None)

    def test_threads_response_uses_composite_primary_key(self) -> None:
        result = _run("threads", [_page("conversations", [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == ["conversation_id", "id"]


class TestValidateCredentials:
    def test_source_create_probes_users_me(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            ok, error = validate_credentials("token", "v2", schema_name=None)

        assert ok is True
        assert error is None
        assert network.requests_log[0].url == f"{HELP_SCOUT_API_BASE}/users/me"

    def test_probe_sessions_exclude_sample_capture(self) -> None:
        # /users/me and the schema probes can return customer-authored free-text content
        # (e.g. a conversation subject), so neither must land in HTTP sample capture.
        with scripted_network([ScriptedResponse(status=200), ScriptedResponse(status=200)]) as network:
            validate_credentials("token", "v2", schema_name=None)
            validate_credentials("token", "v2", schema_name="mailboxes")

        assert [options["capture"] for options in network.session_options] == [False, False]

    def test_revoked_token_fails_at_source_create(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]):
            ok, error = validate_credentials("token", "v2", schema_name=None)

        assert ok is False
        assert error is not None

    def test_schema_probe_success(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]):
            ok, error = validate_credentials("token", "v2", schema_name="mailboxes")

        assert ok is True
        assert error is None

    def test_schema_probe_401_reports_auth_error(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]):
            ok, error = validate_credentials("token", "v2", schema_name="mailboxes")

        assert ok is False
        assert error is not None and "authentication failed" in error

    def test_unknown_schema_fails_without_probing(self) -> None:
        with scripted_network([]) as network:
            ok, error = validate_credentials("token", "v2", schema_name="not_a_table")

        assert ok is False
        assert error == "Unknown Help Scout table 'not_a_table'"
        assert network.requests_log == []

    @pytest.mark.parametrize(
        "api_version,schema_name,expected_url",
        [
            ("v2", "threads", f"{HELP_SCOUT_API_BASE}/conversations"),
            ("v3", "threads", f"{HELP_SCOUT_API_BASE_V3}/conversations"),
            ("v3", "mailbox_fields", f"{HELP_SCOUT_API_BASE}/mailboxes"),
            ("v3", "customers", f"{HELP_SCOUT_API_BASE_V3}/customers"),
            ("v3", "mailboxes", f"{HELP_SCOUT_API_BASE}/mailboxes"),
            ("v3", None, f"{HELP_SCOUT_API_BASE}/users/me"),
        ],
    )
    def test_probe_url_follows_the_pinned_version(
        self, api_version: str, schema_name: str | None, expected_url: str
    ) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            ok, _error = validate_credentials("token", api_version, schema_name=schema_name)

        assert ok is True
        assert network.requests_log[0].url == expected_url

    def test_report_probe_sends_a_window_and_maps_403_to_the_plan_error(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            ok, error = validate_credentials("token", "v3", schema_name="happiness_ratings")

        assert ok is False
        assert error is not None and "Plus and Pro" in error
        url = network.requests_log[0].url
        assert url.startswith(f"{HELP_SCOUT_API_BASE}/reports/happiness/ratings?start=")
        assert "&end=" in url
