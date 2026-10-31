from typing import Any, Optional

from unittest.mock import patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.unleash import (
    UnleashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash import unleash
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.source import UnleashSource
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.unleash import (
    PAGE_SIZE,
    UnleashHostNotAllowedError,
    UnleashResumeConfig,
    check_endpoint_permissions,
    normalize_instance_url,
    validate_credentials,
)

MIXINS_IS_CLOUD = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud"

BASE_URL = "https://unleash.example.com"
TOKEN = "user:secret-token"


def _driver(instance_url: str = BASE_URL) -> SourceDriver:
    return SourceDriver(UnleashSource(), UnleashSourceConfig(instance_url=instance_url, api_token=TOKEN))


class TestNormalizeAndHeaders:
    @parameterized.expand(
        [
            ("plain", "https://unleash.example.com", "https://unleash.example.com"),
            ("trailing_slash", "https://unleash.example.com/", "https://unleash.example.com"),
            ("api_suffix", "https://unleash.example.com/api", "https://unleash.example.com"),
            ("api_admin_suffix", "https://unleash.example.com/api/admin/", "https://unleash.example.com"),
            ("no_scheme", "unleash.example.com", "https://unleash.example.com"),
            ("whitespace", "  https://unleash.example.com  ", "https://unleash.example.com"),
            (
                # Unleash cloud URLs carry the instance name as a path prefix — it must be preserved.
                "cloud_path_prefix",
                "https://us.app.unleash-hosted.com/my-instance/",
                "https://us.app.unleash-hosted.com/my-instance",
            ),
            (
                "cloud_path_prefix_with_api_suffix",
                "https://us.app.unleash-hosted.com/my-instance/api/admin",
                "https://us.app.unleash-hosted.com/my-instance",
            ),
        ]
    )
    def test_normalize_instance_url(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_instance_url(raw) == expected


class TestPipelineTransport:
    def test_paginated_endpoint_walks_offsets_and_saves_state_after_yield(self) -> None:
        full_page = [{"name": f"flag-{i}"} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "features",
            [
                ScriptedResponse(json={"features": full_page, "total": PAGE_SIZE + 2}),
                ScriptedResponse(json={"features": [{"name": "x"}, {"name": "y"}], "total": PAGE_SIZE + 2}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 2
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        # Stable ascending sort keeps page boundaries fixed while walking offsets.
        assert result.params("sortBy") == ["createdAt"] * 2
        assert result.params("sortOrder") == ["asc"] * 2
        assert result.params("limit") == [str(PAGE_SIZE)] * 2
        # State is saved once — after the first (full) page, pointing at the next offset.
        assert result.saved_states == [UnleashResumeConfig(offset=PAGE_SIZE)]

    def test_paginated_endpoint_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "features",
            [ScriptedResponse(json={"features": [{"name": "x"}], "total": PAGE_SIZE + 1})],
            resume_state=UnleashResumeConfig(offset=PAGE_SIZE),
        )

        assert result.rows == [{"name": "x"}]
        assert result.params("offset") == [str(PAGE_SIZE)]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("features", [ScriptedResponse(json={"features": [{"name": "x"}], "total": 1})])

        assert result.params("offset") == ["0"]

    def test_blocks_unsafe_hosts(self) -> None:
        with patch(MIXINS_IS_CLOUD, return_value=True):
            result = _driver("https://10.0.0.1").run("projects", [])

        assert isinstance(result.raised, UnleashHostNotAllowedError)
        assert result.requests == []

    def test_blocks_ambiguous_url(self) -> None:
        result = _driver("https://169.254.169.254\\@unleash.example.com").run("projects", [])

        assert isinstance(result.raised, UnleashHostNotAllowedError)
        assert result.requests == []

    @parameterized.expand(
        [
            ("features", ["name"]),
            # A tag has no id — its identity is the (type, value) pair; a single-column key here
            # would seed duplicate rows and multi-match on every merge.
            ("tags", ["type", "value"]),
        ]
    )
    def test_source_returns_declared_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={endpoint: [], "total": 0})])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("unavailable", 503)])
    def test_retryable_statuses_are_retried_then_succeed(self, _name: str, status: int) -> None:
        result = _driver().run(
            "projects",
            [
                ScriptedResponse(status=status, json={}),
                ScriptedResponse(json={"version": 1, "projects": [{"id": "a"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 2

    def test_persistent_server_error_exhausts_retries(self) -> None:
        result = _driver().run("projects", always(ScriptedResponse(status=500, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_permanent_statuses_raise_http_error(self, _name: str, status: int) -> None:
        result = _driver().run("projects", [ScriptedResponse(status=status, json={"message": "no"})])

        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand([("moved", 301), ("found", 302), ("temporary", 307)])
    def test_redirects_are_refused(self, _name: str, status: int) -> None:
        # The session never follows redirects — a 3xx would move the sync off the validated host
        # (SSRF), so it must fail rather than be treated as an empty page.
        result = _driver().run(
            "projects",
            [ScriptedResponse(status=status, json={}, headers={"Location": "https://evil.example.com"})],
        )

        assert isinstance(result.raised, ValueError)
        assert "edirect" in str(result.raised)
        assert result.paths == ["/api/admin/projects"]

    @parameterized.expand(
        [
            # A 200 whose body isn't the expected list shape is treated as a transient glitch and
            # retried (the retryable counterpart of the old _extract_rows guard).
            ("wrapped_missing_key", "projects", {"version": 1}),
            ("wrapped_got_array", "projects", [{"id": "a"}]),
            ("bare_got_object", "context_fields", {"fields": []}),
        ]
    )
    def test_unexpected_200_body_shape_is_retried_then_raises(self, _name: str, endpoint: str, body: Any) -> None:
        result = _driver().run(endpoint, always(ScriptedResponse(json=body)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5


class TestValidateCredentials:
    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"projects": []})]) as network:
            assert validate_credentials(BASE_URL, TOKEN, team_id=1) == (True, None)

        assert [request.path for request in network.requests_log] == ["/api/admin/projects"]
        assert network.requests_log[0].headers["authorization"] == TOKEN

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid token may lack the permission for the probe endpoint; source creation must
        # still go through, and per-schema syncs surface their own permission errors.
        with scripted_network([ScriptedResponse(status=403, json={"message": "denied"})]):
            assert validate_credentials(BASE_URL, TOKEN, team_id=1) == (True, None)

    def test_validate_credentials_rejects_403_for_scoped_probe(self) -> None:
        with scripted_network([ScriptedResponse(status=403, json={"message": "denied"})]):
            valid, message = validate_credentials(BASE_URL, TOKEN, schema_name="users", team_id=1)

        assert valid is False
        assert message == "denied"

    def test_validate_credentials_rejects_redirects(self) -> None:
        # A redirect could bounce the probe to an internal address, defeating the host check.
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://10.0.0.1"})]) as network:
            valid, _ = validate_credentials(BASE_URL, TOKEN, team_id=1)

        assert valid is False
        assert len(network.requests_log) == 1

    def test_validate_credentials_rejects_unsafe_host(self) -> None:
        with patch(MIXINS_IS_CLOUD, return_value=True), scripted_network([]) as network:
            valid, message = validate_credentials("https://10.0.0.1", TOKEN, team_id=1)

        assert valid is False
        assert message is not None and "internal or private IP" in message
        assert network.requests_log == []

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://unleash.example.com"),
            # Parser-differential SSRF guards: urlparse and urllib3 disagree on where the
            # authority ends for backslash/userinfo URLs, so validation could approve one host
            # while requests connects to another.
            ("userinfo", "https://169.254.169.254@unleash.example.com"),
            ("backslash", "https://169.254.169.254\\@unleash.example.com"),
            ("encoded_backslash", "https://169.254.169.254%5C@unleash.example.com"),
        ]
    )
    def test_validate_credentials_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        with scripted_network([]) as network:
            valid, message = validate_credentials(raw_url, TOKEN, team_id=1)

        assert valid is False
        assert message == "Invalid Unleash instance URL"
        assert network.requests_log == []

    @parameterized.expand(
        [
            # The token rides in the Authorization header, so plaintext http is rejected on cloud
            # (public egress) but allowed off cloud (self-hosted controls its own network path).
            ("http_on_cloud", True, "http://unleash.example.com", None),
            ("http_off_cloud", False, "http://unleash.example.com", "unleash.example.com"),
            ("https_on_cloud", True, "https://unleash.example.com", "unleash.example.com"),
        ]
    )
    def test_validated_hostname_requires_https_only_on_cloud(
        self, _name: str, cloud: bool, url: str, expected: Optional[str]
    ) -> None:
        with patch.object(unleash, "is_cloud", return_value=cloud):
            assert unleash._validated_hostname(url) == expected


class TestCheckEndpointPermissions:
    def test_flags_admin_gated_tables(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/api/admin/user-admin"):
                return ScriptedResponse(status=403, json={"message": "You need the ADMIN permission."})
            return ScriptedResponse(json={"projects": [], "features": [], "total": 0})

        with scripted_network(respond):
            result = check_endpoint_permissions(BASE_URL, TOKEN, ["projects", "features", "users"], team_id=1)

        assert result["projects"] is None
        assert result["features"] is None
        assert result["users"] is not None and "Admin root role" in result["users"]

    @parameterized.expand(
        [
            # Transient failures are not permission problems — they must not flag the table.
            ("server_error", 500, None),
            ("throttled", 429, None),
            ("invalid_token", 401, "Invalid Unleash API token"),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: Optional[str]) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            result = check_endpoint_permissions(BASE_URL, TOKEN, ["projects"], team_id=1)

        assert result["projects"] == expected

    def test_treats_network_blips_as_reachable(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert check_endpoint_permissions(BASE_URL, TOKEN, ["projects"], team_id=1) == {"projects": None}

    def test_blocks_unsafe_host_for_all_endpoints(self) -> None:
        with patch(MIXINS_IS_CLOUD, return_value=True), scripted_network([]) as network:
            result = check_endpoint_permissions("https://10.0.0.1", TOKEN, ["projects", "users"], team_id=1)

        assert result["projects"] is not None and "internal or private IP" in result["projects"]
        assert result["users"] == result["projects"]
        assert network.requests_log == []

    def test_rejects_ambiguous_url_for_all_endpoints(self) -> None:
        result = check_endpoint_permissions(
            "https://169.254.169.254\\@unleash.example.com", TOKEN, ["projects", "users"], team_id=1
        )
        assert result == {"projects": "Invalid Unleash instance URL", "users": "Invalid Unleash instance URL"}
