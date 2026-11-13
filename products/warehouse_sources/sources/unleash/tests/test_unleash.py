from datetime import UTC, datetime
from typing import Any, Optional

from unittest.mock import patch

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.unleash import unleash
from products.warehouse_sources.sources.unleash._config import UnleashSourceConfig
from products.warehouse_sources.sources.unleash.settings import PAGE_SIZE
from products.warehouse_sources.sources.unleash.source import UnleashSource
from products.warehouse_sources.sources.unleash.unleash import (
    UnleashHostNotAllowedError,
    UnleashResumeConfig,
    check_endpoint_permissions,
    metrics_hours_back,
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


def _features_page(request: RecordedRequest, features: list[dict[str, Any]]) -> ScriptedResponse:
    offset = int(request.param("offset") or 0)
    limit = int(request.param("limit") or PAGE_SIZE)
    return ScriptedResponse(json={"features": features[offset : offset + limit], "total": len(features)})


class TestEvents:
    @parameterized.expand(
        [
            ("full_refresh", False, datetime(2026, 3, 10, 0, 30, tzinfo=UTC), [None]),
            # `from` is a day-granular, server-timezone date, so the cutoff steps back one day.
            ("incremental_datetime", True, datetime(2026, 3, 10, 0, 30, tzinfo=UTC), ["IS:2026-03-09"]),
            ("incremental_iso_string", True, "2026-03-01T23:59:59.000Z", ["IS:2026-02-28"]),
            ("incremental_first_sync", True, None, [None]),
        ]
    )
    def test_from_filter_follows_the_watermark(
        self, _name: str, incremental: bool, last_value: Any, expected_from: list[Optional[str]]
    ) -> None:
        result = _driver().run(
            "events",
            [ScriptedResponse(json={"events": [{"id": 1, "createdAt": "2026-03-10T01:00:00.000Z"}], "total": 1})],
            should_use_incremental_field=incremental,
            incremental_field="createdAt",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.paths == ["/api/admin/search/events"]
        assert result.params("from") == expected_from
        assert result.rows == [{"id": 1, "createdAt": "2026-03-10T01:00:00.000Z"}]

    def test_walks_offsets_and_resumes_from_saved_offset(self) -> None:
        events = [{"id": i} for i in range(1500, 0, -1)]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            offset = int(request.param("offset") or 0)
            return ScriptedResponse(json={"events": events[offset : offset + 1000], "total": len(events)})

        result = _driver().run("events", respond)
        resumed = _driver().run("events", respond, resume_state=UnleashResumeConfig(offset=1000))

        assert len(result.rows) == 1500
        assert result.params("offset") == ["0", "1000"]
        assert result.params("limit") == ["1000", "1000"]
        assert result.saved_states == [UnleashResumeConfig(offset=1000)]
        assert resumed.params("offset") == ["1000"]
        assert len(resumed.rows) == 500


class TestFeatureFanout:
    FEATURES = [
        {"name": "checkout", "project": "web"},
        {"name": "gone", "project": "web"},
        {"name": "search", "project": "api"},
    ]

    def test_feature_strategies_flattens_environments_and_skips_archived_flags(self) -> None:
        feature_bodies: dict[str, Any] = {
            "/api/admin/projects/web/features/checkout": {
                "name": "checkout",
                "environments": [
                    {
                        "name": "production",
                        "enabled": True,
                        "strategies": [
                            {"id": "s-1", "name": "flexibleRollout", "parameters": {"rollout": "25"}},
                            {"id": "s-2", "name": "default", "featureName": "checkout"},
                        ],
                    },
                    {"name": "development", "enabled": False, "strategies": []},
                ],
            },
            "/api/admin/projects/api/features/search": {
                "name": "search",
                "environments": [{"name": "development", "enabled": False, "strategies": [{"id": "s-3"}]}],
            },
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/admin/search/features":
                return _features_page(request, self.FEATURES)
            if request.path in feature_bodies:
                return ScriptedResponse(json=feature_bodies[request.path])
            # A flag archived after the listing.
            return ScriptedResponse(status=404, json={"message": "not found"})

        result = _driver().run("feature_strategies", respond)

        assert result.raised is None
        assert result.paths == [
            "/api/admin/search/features",
            "/api/admin/projects/web/features/checkout",
            "/api/admin/projects/web/features/gone",
            "/api/admin/projects/api/features/search",
        ]
        assert result.rows == [
            {
                "id": "s-1",
                "name": "flexibleRollout",
                "parameters": {"rollout": "25"},
                "featureName": "checkout",
                "project": "web",
                "environment": "production",
                "environmentEnabled": True,
            },
            {
                "id": "s-2",
                "name": "default",
                "featureName": "checkout",
                "project": "web",
                "environment": "production",
                "environmentEnabled": True,
            },
            {
                "id": "s-3",
                "featureName": "search",
                "project": "api",
                "environment": "development",
                "environmentEnabled": False,
            },
        ]

    def test_feature_metrics_requests_each_flag_and_fills_the_flag_name(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/admin/search/features":
                return _features_page(request, self.FEATURES[:1])
            return ScriptedResponse(
                json={
                    "version": 1,
                    "maturity": "stable",
                    "data": [
                        {"appName": "shop", "environment": "production", "timestamp": "2026-03-10T10:00:00.000Z"},
                    ],
                }
            )

        result = _driver().run("feature_metrics", respond)

        assert result.raised is None
        assert result.paths == ["/api/admin/search/features", "/api/admin/client-metrics/features/checkout/raw"]
        assert result.params("hoursBack") == [None, "48"]
        assert result.rows == [
            {
                "appName": "shop",
                "environment": "production",
                "timestamp": "2026-03-10T10:00:00.000Z",
                "featureName": "checkout",
            }
        ]

    def test_fanout_checkpoint_tracks_the_parent_page_and_resumes_there(self) -> None:
        features = [{"name": f"flag-{i}", "project": "web"} for i in range(2 * PAGE_SIZE + 1)]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/admin/search/features":
                return _features_page(request, features)
            return ScriptedResponse(json={"data": []})

        first = _driver().run("feature_metrics", respond)
        last_state = first.saved_states[-1].fanout_state

        assert first.raised is None
        # A resume starts one parent page back, so the checkpoint keeps at most two pages of flags.
        assert last_state["parent"] == {"offset": PAGE_SIZE}
        assert len(last_state["completed"]) <= PAGE_SIZE + 1

        resumed = _driver().run("feature_metrics", respond, resume_state=first.saved_states[-1])

        assert resumed.raised is None
        assert [offset for offset in resumed.params("offset") if offset] == [str(PAGE_SIZE), str(2 * PAGE_SIZE)]
        assert len(resumed.requests) == 2

    @parameterized.expand(
        [
            ("first_sync", None, 48),
            ("synced_an_hour_ago", datetime(2026, 3, 10, 11, 0, tzinfo=UTC), 2),
            ("synced_ninety_minutes_ago", "2026-03-10T10:30:00.000Z", 3),
            ("synced_just_now", datetime(2026, 3, 10, 12, 0, tzinfo=UTC), 1),
            ("older_than_retention", datetime(2026, 3, 1, tzinfo=UTC), 48),
        ]
    )
    def test_metrics_hours_back_covers_the_gap_since_the_watermark(
        self, _name: str, last_value: Any, expected: int
    ) -> None:
        assert metrics_hours_back(last_value, now=datetime(2026, 3, 10, 12, 0, tzinfo=UTC)) == expected


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

    def test_fanout_tables_probe_the_flag_listing_they_walk(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/admin/search/features":
                return ScriptedResponse(status=403, json={"message": "No access to flags."})
            return ScriptedResponse(json={"events": [], "total": 0})

        with scripted_network(respond) as network:
            result = check_endpoint_permissions(
                BASE_URL, TOKEN, ["feature_strategies", "feature_metrics", "events"], team_id=1
            )

        assert result == {
            "feature_strategies": "No access to flags.",
            "feature_metrics": "No access to flags.",
            "events": None,
        }
        assert "{" not in "".join(request.path for request in network.requests_log)

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
