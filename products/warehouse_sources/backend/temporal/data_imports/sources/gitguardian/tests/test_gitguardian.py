from datetime import date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gitguardian import (
    GitguardianSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.gitguardian import (
    GitGuardianResumeConfig,
    GitGuardianRetryableError,
    check_endpoint_access,
    resolve_base_url,
    validate_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.source import GitguardianSource

BASE_URL = "https://api.gitguardian.com"


def _driver(base_url: str | None = None) -> SourceDriver:
    return SourceDriver(GitguardianSource(), GitguardianSourceConfig(api_key="gg_sat_x", base_url=base_url))


def _page(rows: Any, next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(json=rows, headers=headers)


class TestResolveBaseUrl:
    @parameterized.expand(
        [
            ("blank", None, "https://api.gitguardian.com"),
            ("empty", "", "https://api.gitguardian.com"),
            ("trailing_slash", "https://api.eu1.gitguardian.com/", "https://api.eu1.gitguardian.com"),
            (
                "self_hosted_path_prefix",
                "https://gitguardian.acme.internal/exposed",
                "https://gitguardian.acme.internal/exposed",
            ),
        ]
    )
    def test_resolve(self, _name: str, given: str | None, expected: str) -> None:
        assert resolve_base_url(given) == expected


class TestValidateBaseUrl:
    @parameterized.expand(
        [
            ("default", "https://api.gitguardian.com"),
            ("self_hosted_https", "https://gitguardian.acme.dev"),
        ]
    )
    def test_https_urls_pass(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is None

    @parameterized.expand(
        [
            # Plaintext would send the secret token in the clear.
            ("http", "http://gitguardian.acme.dev"),
            # `urlsplit` reads the host as example.com, but requests connects to 169.254.169.254.
            ("backslash_authority_confusion", "https://169.254.169.254\\@example.com"),
        ]
    )
    def test_unsafe_urls_are_rejected(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is not None


class TestLinkHeaderPagination:
    def test_honeytoken_events_fetch_every_status(self) -> None:
        result = _driver().run("honeytoken_events", [_page([]), _page([]), _page([])])
        assert result.raised is None
        assert result.params("status") == ["open", "archived", "allowed"]

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 1, 10), "2026-01-03T00:00:00Z"),
            ("date_value", date(2026, 1, 10), "2026-01-03T00:00:00Z"),
        ]
    )
    def test_incremental_value_types_are_formatted_utc(self, _name: str, value: Any, expected: str) -> None:
        result = _driver().run(
            "secret_incidents",
            [_page([{"id": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=value,
        )
        assert result.raised is None
        assert result.params("date_after") == [expected]
        assert result.params("ordering") == ["date"]

    @parameterized.expand(
        [
            # Mutable triage fields: re-pull a 7-day trailing window, walking the detection date.
            ("secret_incidents", "/v1/incidents/secrets", "2026-01-03T00:00:00Z", "date"),
            ("public_secret_incidents", "/v1/public-incidents/secrets", "2026-01-03T00:00:00Z", "date"),
            # Immutable rows and no `ordering` param on the API: exact watermark, no ordering sent.
            ("audit_logs", "/v1/audit_logs", "2026-01-10T00:00:00Z", None),
        ]
    )
    def test_incremental_request_shaping(
        self, endpoint: str, path: str, expected_date_after: str, expected_ordering: str | None
    ) -> None:
        result = _driver().run(
            endpoint,
            [_page([{"id": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10),
        )
        assert result.raised is None
        assert result.paths == [path]
        assert result.params("date_after") == [expected_date_after]
        assert result.params("ordering") == [expected_ordering]

    @parameterized.expand([("secret_incidents",), ("public_secret_incidents",)])
    def test_share_url_bearer_link_is_stripped(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_page([{"id": 1, "share_url": "https://dashboard.example.com/share/fake-token", "severity": "high"}])],
        )
        assert result.raised is None
        assert result.rows == [{"id": 1, "severity": "high"}]

    def test_cross_origin_next_link_is_refused(self) -> None:
        # Pagination URLs are fetched with the Authorization token attached; a tampered Link
        # header must not be able to steer the token to another host.
        result = _driver().run(
            "secret_incidents",
            [_page([{"id": 1}], next_url="https://attacker.example/v1/incidents/secrets?cursor=abc")],
        )
        assert isinstance(result.raised, ValueError)
        assert "cross-origin" in str(result.raised)
        assert result.paths == ["/v1/incidents/secrets"]

    def test_non_list_response_raises_instead_of_yielding_garbage(self) -> None:
        result = _driver().run("secret_incidents", [_page({"detail": "Not found."})])
        assert isinstance(result.raised, ValueError)
        assert "non-list response" in str(result.raised)
        assert result.rows == []


class TestFanOut:
    def test_walks_every_parent_page_and_each_childs_pages(self) -> None:
        teams_next = f"{BASE_URL}/v1/teams?cursor=t2&per_page=100"
        child_next = f"{BASE_URL}/v1/teams/1/team_memberships?cursor=m2&per_page=100"
        result = _driver().run(
            "team_memberships",
            [
                _page([{"id": 1}], next_url=teams_next),
                _page([{"id": 10, "team_id": 1}], next_url=child_next),
                _page([{"id": 11, "team_id": 1}]),
                _page([{"id": 2}]),
                _page([{"id": 20, "team_id": 2}]),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [10, 11, 20]
        assert result.urls == [
            f"{BASE_URL}/v1/teams?per_page=100",
            f"{BASE_URL}/v1/teams/1/team_memberships?per_page=100",
            child_next,
            teams_next,
            f"{BASE_URL}/v1/teams/2/team_memberships?per_page=100",
        ]
        assert result.saved_states == []

    @parameterized.expand(
        [
            (
                "notes_carry_incident_id",
                "secret_incident_notes",
                [
                    f"{BASE_URL}/v1/incidents/secrets?per_page=100&ordering=date",
                    f"{BASE_URL}/v1/incidents/secrets/7/notes?per_page=100&ordering=created_at",
                ],
                [{"id": 3, "incident_id": 7, "comment": "Rotated the key"}],
                [{"id": 3, "incident_id": 7, "comment": "Rotated the key"}],
            ),
            (
                "leaks_are_unpaginated_and_get_incident_id",
                "secret_incident_leaks",
                [
                    f"{BASE_URL}/v1/incidents/secrets?per_page=100&ordering=date",
                    f"{BASE_URL}/v1/incidents/secrets/7/leaks",
                ],
                [{"source": "github_gist", "name": "fake-gist", "url": "https://gist.example.com/abc"}],
                [
                    {
                        "source": "github_gist",
                        "name": "fake-gist",
                        "url": "https://gist.example.com/abc",
                        "incident_id": 7,
                    }
                ],
            ),
            (
                "team_sources_get_team_id",
                "team_sources",
                [f"{BASE_URL}/v1/teams?per_page=100", f"{BASE_URL}/v1/teams/7/sources?per_page=100"],
                [{"id": 42, "full_name": "example-org/example-repo"}],
                [{"id": 42, "full_name": "example-org/example-repo", "team_id": 7}],
            ),
        ]
    )
    def test_child_rows_are_keyed_to_their_parent(
        self,
        _name: str,
        endpoint: str,
        expected_urls: list[str],
        child_rows: list[dict[str, Any]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(endpoint, [_page([{"id": 7}]), _page(child_rows)])
        assert result.raised is None
        assert result.urls == expected_urls
        assert result.rows == expected_rows
        assert result.response is not None
        primary_keys = result.response.primary_keys or []
        assert primary_keys and all(key in row for row in result.rows for key in primary_keys)

    def test_parent_deleted_mid_sync_is_skipped(self) -> None:
        result = _driver().run(
            "team_memberships",
            [
                _page([{"id": 1}, {"id": 2}]),
                ScriptedResponse(status=404),
                _page([{"id": 20, "team_id": 2}]),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [20]

    def test_child_denial_is_not_swallowed(self) -> None:
        result = _driver().run(
            "team_memberships",
            [_page([{"id": 1}]), ScriptedResponse(status=403)],
        )
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v1/teams", "/v1/teams/1/team_memberships"]


class TestResumeCheckpoints:
    def test_cross_origin_resume_url_is_refused(self) -> None:
        # Resume URLs come from persisted state; a tampered value must not receive the token either.
        result = _driver().run(
            "secret_incidents",
            [],
            resume_state=GitGuardianResumeConfig(url="https://attacker.example/v1/incidents/secrets?cursor=abc"),
        )
        assert isinstance(result.raised, ValueError)
        assert "cross-origin" in str(result.raised)
        assert result.requests == []

    @parameterized.expand(
        [
            ("public_secret_incidents", "/v1/public-incidents/secrets"),
            ("audit_logs", "/v1/audit_logs"),
        ]
    )
    def test_incremental_endpoints_resume_from_the_saved_page(self, endpoint: str, path: str) -> None:
        saved_url = f"{BASE_URL}{path}?cursor=c2&per_page=100"
        result = _driver().run(
            endpoint,
            [_page([{"id": 2}])],
            resume_state=GitGuardianResumeConfig(url=saved_url),
        )
        assert result.raised is None
        assert result.urls == [saved_url]
        assert result.rows == [{"id": 2}]
        assert result.saved_states == [GitGuardianResumeConfig(url=saved_url)]
        assert result.final_state is None

    def test_full_refresh_endpoints_never_checkpoint(self) -> None:
        # sources/members/teams merge nothing on resume, so a restart re-reads from page one.
        previous = GitGuardianResumeConfig(url=f"{BASE_URL}/v1/sources?cursor=old")
        result = _driver().run("sources", [_page([{"id": 1}])], resume_state=previous)
        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.urls == [f"{BASE_URL}/v1/sources?per_page=100"]
        assert result.saved_states == []
        assert result.final_state == previous


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("gg_sat_x", BASE_URL)
        assert valid is expected_valid
        assert (error is None) is expected_valid
        assert {request.path for request in network.requests_log} == {"/v1/health"}
        assert network.requests_log[0].headers["authorization"] == "Token gg_sat_x"
        assert network.session_options[0]["allow_redirects"] is False

    def test_network_error_is_invalid_not_raised(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            valid, error = validate_credentials("gg_sat_x", BASE_URL)
        assert valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/v1/health"}


class TestCheckEndpointAccess:
    def test_denial_surfaces_the_apis_own_detail_message(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=403, json={"detail": "You do not have the required incidents:read scope."})]
        ):
            reason = check_endpoint_access("gg_sat_x", BASE_URL, "secret_incidents")
        assert reason == "You do not have the required incidents:read scope."

    @parameterized.expand(
        [
            ("secret_incidents", "incidents:read"),
            ("sources", "sources:read"),
            ("honeytokens", "honeytokens:read"),
            ("custom_tags", "custom_tags:read"),
            ("audit_logs", "audit_logs:read"),
            ("public_developers", "public-perimeter:read"),
        ]
    )
    def test_denial_without_detail_names_the_required_scope(self, endpoint: str, scope: str) -> None:
        with scripted_network([ScriptedResponse(status=403, body=b"no json")]):
            reason = check_endpoint_access("gg_sat_x", BASE_URL, endpoint)
        assert reason is not None and scope in reason

    @parameterized.expand(
        [
            ("throttle", 429),
            ("server_error", 500),
        ]
    )
    def test_non_denial_errors_do_not_block_the_table(self, _name: str, status_code: int) -> None:
        # Only a real 401/403 is a missing scope; a throttle or blip must not mark the table
        # unreachable in the schema picker.
        with scripted_network(always(ScriptedResponse(status=status_code))):
            reason = check_endpoint_access("gg_sat_x", BASE_URL, "secret_incidents")
        assert reason is None

    def test_network_error_does_not_block_the_table(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            reason = check_endpoint_access("gg_sat_x", BASE_URL, "secret_incidents")
        assert reason is None

    @parameterized.expand(
        [
            ("team_memberships", "/v1/teams"),
            ("secret_incident_activity_logs", "/v1/incidents/secrets"),
        ]
    )
    def test_fan_out_endpoints_probe_their_parent(self, endpoint: str, parent_path: str) -> None:
        # The child path needs a real parent id; probing the placeholder would 404 and hide a
        # missing scope. The parent carries the same scope.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            check_endpoint_access("gg_sat_x", BASE_URL, endpoint)
        assert [request.path for request in network.requests_log] == [parent_path]

    def test_team_sources_probes_teams_and_sources(self) -> None:
        with scripted_network([ScriptedResponse(status=200), ScriptedResponse(status=200)]) as network:
            reason = check_endpoint_access("gg_sat_x", BASE_URL, "team_sources")
        assert reason is None
        assert [request.path for request in network.requests_log] == ["/v1/teams", "/v1/sources"]

    def test_team_sources_without_sources_scope_is_blocked(self) -> None:
        with scripted_network([ScriptedResponse(status=200), ScriptedResponse(status=403, body=b"no json")]):
            reason = check_endpoint_access("gg_sat_x", BASE_URL, "team_sources")
        assert reason is not None and "sources:read" in reason

    def test_unpaginated_endpoint_is_probed_without_paging_params(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            check_endpoint_access("gg_sat_x", BASE_URL, "public_developers")
        assert [request.url for request in network.requests_log] == [f"{BASE_URL}/v1/public-perimeter/developers"]


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_is_retried(self, _name: str, status_code: int) -> None:
        result = _driver().run(
            "secret_incidents",
            [ScriptedResponse(status=status_code), _page([{"id": 1}])],
        )
        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.paths == ["/v1/incidents/secrets", "/v1/incidents/secrets"]

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_persistent_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        result = _driver().run("secret_incidents", always(ScriptedResponse(status=status_code)))
        assert isinstance(result.raised, GitGuardianRetryableError)

    def test_unauthorized_raises_and_is_not_retried(self) -> None:
        result = _driver().run("secret_incidents", [ScriptedResponse(status=401)])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v1/incidents/secrets"]


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("secret_incidents", ["date"], "asc"),
            ("secret_occurrences", ["date"], "asc"),
            ("public_secret_incidents", ["date"], "asc"),
            # No `ordering` param, so the watermark must only be promoted when the sync completes.
            ("audit_logs", ["date"], "desc"),
        ]
    )
    def test_incremental_endpoints_partition_on_stable_detection_date(
        self, endpoint: str, expected_partition: list[str], expected_sort_mode: str
    ) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_keys == expected_partition
        assert result.response.primary_keys == ["id"]
        assert result.response.sort_mode == expected_sort_mode

    @parameterized.expand([("sources",), ("honeytokens",), ("members",), ("teams",), ("custom_tags",)])
    def test_full_refresh_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
