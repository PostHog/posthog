from unittest.mock import patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.unstructured import (
    UnstructuredSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.source import UnstructuredSource
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.unstructured import (
    DEFAULT_BASE_URL,
    WORKFLOWS_PAGE_SIZE,
    UnstructuredResumeConfig,
    UnstructuredRetryableError,
    normalize_base_url,
    validate_credentials,
)

MIXINS_IS_CLOUD = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud"


def _driver(base_url: str | None = None, api_key: str = "key") -> SourceDriver:
    return SourceDriver(UnstructuredSource(), UnstructuredSourceConfig(api_key=api_key, base_url=base_url))


class TestNormalizeBaseUrl:
    @parameterized.expand(
        [
            ("none_falls_back", None, DEFAULT_BASE_URL),
            ("empty_falls_back", "", DEFAULT_BASE_URL),
            ("whitespace_falls_back", "   ", DEFAULT_BASE_URL),
            ("strips_trailing_slash", "https://custom.example.com/", "https://custom.example.com"),
            ("custom_host_kept", "https://eu.platform.example.com", "https://eu.platform.example.com"),
        ]
    )
    def test_normalize_base_url(self, _name: str, value: str | None, expected: str) -> None:
        assert normalize_base_url(value) == expected


class TestFetch:
    @parameterized.expand([("rate_limited", 429), ("bad_gateway", 502), ("server_error", 500)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        result = _driver().run("jobs", always(ScriptedResponse(status=status, json={"detail": "later"})))

        assert isinstance(result.raised, UnstructuredRetryableError)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _driver().run("jobs", [ScriptedResponse(status=status, json={"detail": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand([("moved_permanently", 301), ("found", 302), ("temporary_redirect", 307)])
    def test_redirect_response_raises(self, _name: str, status: int) -> None:
        # The session never follows redirects (SSRF hardening); a 30x must surface as an error so a
        # customer-controlled host can't quietly point a credentialed request at another origin.
        result = _driver().run(
            "jobs", [ScriptedResponse(status=status, headers={"Location": "https://evil.example.com"})]
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert result.urls == [f"{DEFAULT_BASE_URL}/api/v1/jobs/"]

    def test_non_list_body_returns_empty(self) -> None:
        # A shape change (envelope instead of bare array) must degrade to an empty sync, not crash.
        result = _driver().run("jobs", [ScriptedResponse(json={"data": []})])

        assert result.raised is None
        assert result.rows == []


class TestGetRows:
    def test_paginated_walks_pages_until_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(WORKFLOWS_PAGE_SIZE)]
        last_page = [{"id": "last"}]
        result = _driver().run("workflows", [ScriptedResponse(json=full_page), ScriptedResponse(json=last_page)])

        assert result.items == [full_page, last_page]
        assert len(result.requests) == 2
        # First request starts at page 1.
        assert result.params("page") == ["1", "2"]
        # State is saved after the full page (more to come); the short page ends the walk.
        assert result.saved_states == [UnstructuredResumeConfig(next_page=2)]

    def test_paginated_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "workflows",
            [ScriptedResponse(json=[{"id": "x"}])],
            resume_state=UnstructuredResumeConfig(next_page=3),
        )

        assert result.items == [[{"id": "x"}]]
        # Resumed straight into the saved page rather than restarting at page 1.
        assert result.params("page") == ["3"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("workflows", [ScriptedResponse(json=[{"id": "x"}])])

        assert result.params("page") == ["1"]

    @parameterized.expand(["sources", "destinations"])
    def test_connector_config_is_stripped(self, endpoint: str) -> None:
        # The connector `config` object holds raw secrets (DB passwords, OAuth tokens, cloud keys); it
        # must never be persisted. Non-secret inventory fields are kept.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json=[{"id": "c1", "name": "prod", "type": "s3", "config": {"key": "AKIA...", "secret": "shh"}}]
                )
            ],
        )

        assert result.items == [[{"id": "c1", "name": "prod", "type": "s3"}]]

    def test_session_pins_redirects_off_and_redacts_key(self) -> None:
        # Locks in the SSRF hardening: the credentialed session must never follow redirects and must
        # register the key for value-based redaction so it can't leak off-origin or into a sample.
        result = _driver(api_key="secret-key").run("jobs", [ScriptedResponse(json=[])])

        assert result.session_options[0]["allow_redirects"] is False
        assert result.session_options[0]["redact_values"] == ("secret-key",)

    @parameterized.expand([("secret_endpoint", "sources", False), ("plain_endpoint", "jobs", True)])
    def test_capture_disabled_for_secret_bearing_endpoints(self, _name: str, endpoint: str, capture: bool) -> None:
        # The adapter captures the raw body before `_drop_sensitive_fields` runs, so capture must be
        # off for endpoints whose responses carry the connector `config` secrets.
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.session_options[0]["capture"] is capture

    def test_unsafe_host_blocks_fetch(self) -> None:
        # A host resolving to an internal address must be rejected before the key is ever sent.
        with patch(MIXINS_IS_CLOUD, return_value=True):
            result = _driver("https://169.254.169.254").run("jobs", [])

        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    @parameterized.expand(
        [
            ("raw_backslash_userinfo", "https://169.254.169.254\\@example.com"),
            ("userinfo", "https://user@169.254.169.254"),
            ("encoded_backslash", "https://169.254.169.254%5c@example.com"),
            ("encoded_at", "https://169.254.169.254%40example.com"),
        ]
    )
    def test_parser_differential_host_is_rejected(self, _name: str, base_url: str) -> None:
        # urlparse and the HTTP client disagree on the host for these URLs, so `169.254.169.254\@x`
        # validates as `x` yet the client may connect to the IP. Reject on the character screen before
        # any request, with no host-safety override, so the rejection can only come from the screen itself.
        result = _driver(base_url).run("jobs", [])

        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestUnstructuredSource:
    @parameterized.expand(["workflows", "jobs", "sources", "destinations"])
    def test_source_response_contract(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # created_at is stable (set once at creation) so partitions never churn.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json=[] if status == 200 else {"detail": "no"})]):
            ok, _msg = validate_credentials(DEFAULT_BASE_URL, "key", team_id=1)
        assert ok is expected

    def test_session_pins_redirects_off_and_redacts_key(self) -> None:
        # Validation carries the key to a user-configurable host; pin redirects off and redact the key.
        with scripted_network([ScriptedResponse(json=[])]) as network:
            validate_credentials(DEFAULT_BASE_URL, "secret-key", team_id=1)

        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == ("secret-key",)

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            ok, _msg = validate_credentials(DEFAULT_BASE_URL, "key", team_id=1)
        assert ok is False

    def test_unsafe_host_rejected_before_request(self) -> None:
        with patch(MIXINS_IS_CLOUD, return_value=True), scripted_network([]) as network:
            ok, msg = validate_credentials("https://169.254.169.254", "key", team_id=1)
        assert ok is False
        assert msg is not None and "internal or private IP" in msg
        assert network.requests_log == []

    @parameterized.expand(
        [
            ("raw_backslash_userinfo", "https://169.254.169.254\\@example.com"),
            ("userinfo", "https://user@169.254.169.254"),
            ("encoded_backslash", "https://169.254.169.254%5c@example.com"),
        ]
    )
    def test_parser_differential_host_is_rejected(self, _name: str, base_url: str) -> None:
        # Validation carries the key to the host, so the same parser-differential bypass must be
        # rejected here before any request, with no host-safety override.
        with scripted_network([]) as network:
            ok, _msg = validate_credentials(base_url, "key", team_id=1)
        assert ok is False
        assert network.requests_log == []
