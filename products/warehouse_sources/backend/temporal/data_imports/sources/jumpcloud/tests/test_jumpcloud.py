import json
from collections.abc import Callable
from typing import Any

from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jumpcloud import (
    JumpcloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.jumpcloud import (
    EVENTS_PAGE_SIZE,
    REST_PAGE_SIZE,
    JumpcloudResumeConfig,
    JumpcloudRetryableError,
    _parse_search_after,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import (
    ENDPOINTS,
    JUMPCLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source import JumpcloudSource


def _driver() -> SourceDriver:
    return SourceDriver(JumpcloudSource(), JumpcloudSourceConfig(api_key="key"))


def _page(endpoint: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
    config = JUMPCLOUD_ENDPOINTS[endpoint]
    if config.api == "v1":
        return ScriptedResponse(json={"results": rows})
    if config.data_key:
        return ScriptedResponse(json={config.data_key: rows})
    return ScriptedResponse(json=rows)


def _fanout_script(
    endpoint: str,
    parent_pages: list[list[dict[str, Any]]],
    children: dict[str, list[dict[str, Any]] | int],
) -> Callable[[RecordedRequest], ScriptedResponse]:
    config = JUMPCLOUD_ENDPOINTS[endpoint]
    parent_config = JUMPCLOUD_ENDPOINTS[config.parent or ""]

    def respond(request: RecordedRequest) -> ScriptedResponse:
        assert request.method == "GET"
        skip = int(request.param("skip") or "0")
        if request.path == parent_config.path:
            index = skip // REST_PAGE_SIZE
            rows = parent_pages[index] if index < len(parent_pages) else []
            return _page(parent_config.name, rows)
        parent_id = request.path.split("/")[4]
        assert request.path == config.path.replace("{parent_id}", parent_id)
        child = children.get(parent_id, [])
        if isinstance(child, int):
            return ScriptedResponse(status=child)
        return _page(endpoint, child[skip : skip + REST_PAGE_SIZE])

    return respond


class TestRequest:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_exhaust_retries(self, _name: str, status: int) -> None:
        result = _driver().run("users", always(ScriptedResponse(status=status)))
        assert isinstance(result.raised, JumpcloudRetryableError)
        assert len(result.requests) >= 5
        assert set(result.paths) == {"/api/systemusers"}

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error_without_retrying(self, _name: str, status: int) -> None:
        result = _driver().run("users", [ScriptedResponse(status=status)])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/api/systemusers"]

    def test_429_carries_server_retry_after(self) -> None:
        result = _driver().run("users", always(ScriptedResponse(status=429, headers={"Retry-After": "7"})))
        assert isinstance(result.raised, JumpcloudRetryableError)
        assert result.raised.retry_after == 7.0

    @parameterized.expand([("moved_permanently", 301), ("temporary_redirect", 307)])
    def test_redirects_are_rejected_not_followed(self, _name: str, status: int) -> None:
        # The session carries the API key in x-api-key; following a redirect would replay it
        # to the redirect target, so the request must refuse redirects entirely.
        result = _driver().run("users", [ScriptedResponse(status=status, headers={"Location": "https://evil.example"})])
        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/api/systemusers"]


class TestParseSearchAfter:
    @parameterized.expand(
        [
            ("valid_cursor", json.dumps([1747608000000, "abc"]), [1747608000000, "abc"]),
            ("missing_header", None, None),
            ("empty_string", "", None),
            ("garbage", "not-json", None),
            ("non_array", '{"a": 1}', None),
            ("empty_array", "[]", None),
        ]
    )
    def test_parsing(self, _name: str, raw: str | None, expected: list[Any] | None) -> None:
        assert _parse_search_after(raw, MagicMock()) == expected


class TestRestRows:
    @staticmethod
    def _run(endpoint: str, script: Script, *, resume_state: JumpcloudResumeConfig | None = None) -> DriveResult:
        result = _driver().run(endpoint, script, resume_state=resume_state)
        assert all(request.method == "GET" for request in result.requests)
        return result

    def test_v1_resumes_from_saved_skip(self) -> None:
        result = self._run(
            "users", [_page("users", [{"_id": "last"}])], resume_state=JumpcloudResumeConfig(skip=REST_PAGE_SIZE)
        )
        # Resuming at skip=REST_PAGE_SIZE skips the already-synced first page.
        assert result.raised is None
        assert result.rows == [{"_id": "last"}]
        assert result.params("skip") == [str(REST_PAGE_SIZE)]

    @parameterized.expand(
        [
            ("bare_array", "user_groups", "https://console.jumpcloud.com/api/v2/usergroups?"),
            ("wrapped_alerts", "alerts", "https://console.jumpcloud.com/api/v2/alerts?"),
            (
                "wrapped_risk_events",
                "identity_risk_events",
                "https://console.jumpcloud.com/api/v2/identityrisk/events?",
            ),
        ]
    )
    def test_v2_endpoint_rows(self, _name: str, endpoint: str, url_prefix: str) -> None:
        result = self._run(endpoint, [_page(endpoint, [{"id": "g1"}])])
        assert result.raised is None
        assert result.rows == [{"id": "g1"}]
        assert result.urls[0].startswith(url_prefix)

    def test_system_insights_pages_with_its_larger_page_size(self) -> None:
        page_size = JUMPCLOUD_ENDPOINTS["system_insights_apps"].page_size
        assert page_size is not None and page_size > REST_PAGE_SIZE
        full_page = [{"system_id": "s1", "name": f"app{i}"} for i in range(page_size)]
        result = self._run(
            "system_insights_apps",
            [_page("system_insights_apps", full_page), _page("system_insights_apps", [{"system_id": "s2"}])],
        )
        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert result.paths == ["/api/v2/systeminsights/apps"] * 2
        assert result.params("limit") == [str(page_size)] * 2
        assert result.saved_states == [JumpcloudResumeConfig(skip=page_size)]

    def test_applications_strips_saml_private_key_before_emitting(self) -> None:
        # An SSO application row carries its SAML IdP signing key at `config.idpPrivateKey.value`;
        # it must never reach the warehouse, while the rest of the config is kept.
        row = {
            "_id": "app1",
            "name": "Okta",
            "config": {
                "idpPrivateKey": {"value": "-----BEGIN PRIVATE KEY-----secret"},
                "idpEntityId": {"value": "https://idp.example"},
            },
        }
        result = self._run("applications", [_page("applications", [row])])
        assert result.raised is None
        assert result.rows == [
            {"_id": "app1", "name": "Okta", "config": {"idpEntityId": {"value": "https://idp.example"}}}
        ]

    @parameterized.expand(
        [
            ("applications", False),
            ("users", True),
            ("application_users", False),
            ("system_users", True),
            ("policy_results", False),
            ("policy_statuses", False),
        ]
    )
    def test_secret_bearing_endpoint_disables_http_sample_capture(self, endpoint: str, expected_capture: bool) -> None:
        # HTTP sample capture writes the raw response body before row-level `redact_keys` runs, so
        # endpoints that redact secrets (applications' SAML key) must opt out of capture entirely.
        listing = JUMPCLOUD_ENDPOINTS[endpoint].parent or endpoint
        result = self._run(endpoint, [_page(listing, [])])
        assert result.raised is None
        assert [options["capture"] for options in result.session_options] == [expected_capture]

    @parameterized.expand([("v1", "users"), ("v2_wrapped", "alerts")])
    def test_non_wrapped_payload_raises_value_error(self, _name: str, endpoint: str) -> None:
        result = self._run(endpoint, [ScriptedResponse(json=[{"_id": "a"}])])
        assert isinstance(result.raised, ValueError)


class TestFanoutRows:
    def test_injects_parent_id_into_each_child_row(self) -> None:
        member = {"id": "u1", "type": "user", "paths": [[{"to": {"id": "u1", "type": "user"}}]]}
        result = _driver().run(
            "user_group_members",
            _fanout_script(
                "user_group_members",
                [[{"id": "g1"}, {"id": "g2"}]],
                {"g1": [member], "g2": [{"id": "u1", "type": "user", "paths": []}]},
            ),
        )
        # The same user in two groups must stay two distinct rows under the composite key.
        assert result.raised is None
        assert result.rows == [
            {**member, "group_id": "g1"},
            {"id": "u1", "type": "user", "paths": [], "group_id": "g2"},
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["group_id", "id"]
        assert result.urls[1].startswith("https://console.jumpcloud.com/api/v2/usergroups/g1/membership?")
        assert result.saved_states == []

    def test_reads_v1_parent_ids_and_pages_children(self) -> None:
        many_users = [{"id": f"u{i}", "type": "user"} for i in range(REST_PAGE_SIZE + 1)]
        result = _driver().run("system_users", _fanout_script("system_users", [[{"_id": "s1"}]], {"s1": many_users}))
        assert result.raised is None
        assert len(result.rows) == REST_PAGE_SIZE + 1
        assert {row["system_id"] for row in result.rows} == {"s1"}
        assert [request.url.split("?")[0] for request in result.requests[1:]] == [
            "https://console.jumpcloud.com/api/v2/systems/s1/users"
        ] * 2

    def test_alert_occurrences_read_wrapped_alerts_and_occurrences(self) -> None:
        occurrence = {"alertObjectId": "a1", "occurredAt": "2026-01-01T00:00:00Z", "context": {}}
        result = _driver().run(
            "alert_occurrences",
            _fanout_script("alert_occurrences", [[{"objectId": "a1"}, {"objectId": "a2"}]], {"a1": [occurrence]}),
        )
        assert result.raised is None
        assert result.rows == [{**occurrence, "alert_id": "a1"}]
        assert [request.url.split("?")[0] for request in result.requests[1:]] == [
            "https://console.jumpcloud.com/api/v2/alerts/a1/occurrences",
            "https://console.jumpcloud.com/api/v2/alerts/a2/occurrences",
        ]

    def test_checkpoints_parent_offset_after_each_full_parent_page(self) -> None:
        full_page = [{"_id": f"a{i}"} for i in range(REST_PAGE_SIZE)]
        result = _driver().run(
            "application_users",
            _fanout_script("application_users", [full_page, [{"_id": "last"}]], {"last": [{"id": "u1"}]}),
        )
        assert result.raised is None
        assert result.rows == [{"id": "u1", "application_id": "last"}]
        assert result.saved_states == [JumpcloudResumeConfig(skip=REST_PAGE_SIZE)]

    def test_resumes_from_saved_parent_offset(self) -> None:
        full_page = [{"_id": f"a{i}"} for i in range(REST_PAGE_SIZE)]
        result = _driver().run(
            "application_user_groups",
            _fanout_script("application_user_groups", [full_page, [{"_id": "last"}]], {}),
            resume_state=JumpcloudResumeConfig(skip=REST_PAGE_SIZE),
        )
        assert result.raised is None
        assert result.params("skip")[0] == str(REST_PAGE_SIZE)
        assert [request.url.split("?")[0] for request in result.requests[1:]] == [
            "https://console.jumpcloud.com/api/v2/applications/last/usergroups"
        ]

    def test_parent_deleted_mid_sync_is_skipped(self) -> None:
        result = _driver().run(
            "system_group_members",
            _fanout_script(
                "system_group_members",
                [[{"id": "gone"}, {"id": "g2"}]],
                {"gone": 404, "g2": [{"id": "s1", "type": "system"}]},
            ),
        )
        assert result.raised is None
        assert result.rows == [{"id": "s1", "type": "system", "group_id": "g2"}]

    def test_child_permission_error_is_raised(self) -> None:
        result = _driver().run("system_users", _fanout_script("system_users", [[{"_id": "s1"}]], {"s1": 403}))
        assert isinstance(result.raised, requests.HTTPError)


class TestEventRows:
    def test_follows_search_after_cursor_and_checkpoints_after_yield(self) -> None:
        full_page = [{"id": str(i)} for i in range(EVENTS_PAGE_SIZE)]
        cursor = [1747608000000, "evt"]
        result = _driver().run(
            "events",
            [
                ScriptedResponse(json=full_page, headers={"X-Search_After": json.dumps(cursor)}),
                ScriptedResponse(json=[{"id": "last"}]),
            ],
        )
        bodies = [request.json() for request in result.requests]
        assert result.raised is None
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.paths == ["/insights/directory/v1/events"] * 2
        assert len(result.rows) == EVENTS_PAGE_SIZE + 1
        # First request has no cursor; the second carries the header cursor back in the body.
        assert "search_after" not in bodies[0]
        assert bodies[1]["search_after"] == cursor
        # Both pages of one run query the identical pinned window (search_after requires it).
        assert bodies[1]["start_time"] == bodies[0]["start_time"]
        assert bodies[1]["end_time"] == bodies[0]["end_time"]
        assert result.saved_states == [
            JumpcloudResumeConfig(
                search_after=cursor, start_time=bodies[0]["start_time"], end_time=bodies[0]["end_time"]
            )
        ]

    def test_resumes_with_saved_window_and_cursor(self) -> None:
        cursor = [123, "evt"]
        result = _driver().run(
            "events",
            [ScriptedResponse(json=[{"id": "e2"}])],
            resume_state=JumpcloudResumeConfig(
                search_after=cursor, start_time="2026-07-01T00:00:00Z", end_time="2026-07-14T00:00:00Z"
            ),
        )
        body = result.requests[0].json()
        assert result.raised is None
        assert result.requests[0].method == "POST"
        assert result.paths == ["/insights/directory/v1/events"]
        assert body["search_after"] == cursor
        assert body["start_time"] == "2026-07-01T00:00:00Z"
        assert body["end_time"] == "2026-07-14T00:00:00Z"

    def test_non_list_payload_raises_value_error(self) -> None:
        result = _driver().run("events", [ScriptedResponse(json={"error": "unexpected"})])
        assert isinstance(result.raised, ValueError)
        assert result.requests[0].method == "POST"
        assert result.paths == ["/insights/directory/v1/events"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_key", 401, None, False),
            # A 403 at source-create means the key is real but this probe is out of the admin's
            # role — creation must go through.
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "users", False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]):
            ok, _error = validate_credentials("key", schema_name=schema_name)
        assert ok is expected_ok

    def test_events_schema_probes_the_insights_endpoint(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            ok, _error = validate_credentials("key", schema_name="events")
        assert ok is True
        assert network.requests_log[0].url == "https://api.jumpcloud.com/insights/directory/v1/events"
        assert network.requests_log[0].json()["limit"] == 1

    def test_fanout_schema_probes_the_parent_listing(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            ok, _error = validate_credentials("key", schema_name="application_users")
        assert ok is True
        assert network.requests_log[0].url == "https://console.jumpcloud.com/api/applications?limit=1"
        # The parent listing carries SAML signing keys, so the probe must not be sample-captured.
        assert network.session_options[0]["capture"] is False


class TestJumpcloudSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        listing = JUMPCLOUD_ENDPOINTS[name].parent or name
        result = _driver().run(name, [_page(listing, [])])
        response = result.response
        config = JUMPCLOUD_ENDPOINTS[name]
        assert result.raised is None
        assert response is not None
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        # Directory Insights response ordering is undocumented, so the events stream defers
        # its watermark to job end (desc); everything else is plain ascending full refresh.
        assert response.sort_mode == ("desc" if config.api == "insights" else "asc")
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_partition_keys_are_stable_fields(self) -> None:
        # Guards against accidentally partitioning on a churning field like lastContact.
        assert all(
            cfg.partition_key in (None, "created", "createdAt", "startedAt", "timestamp")
            for cfg in JUMPCLOUD_ENDPOINTS.values()
        )
