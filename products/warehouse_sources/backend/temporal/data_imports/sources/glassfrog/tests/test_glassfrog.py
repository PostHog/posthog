import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.glassfrog import (
    GlassfrogSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.glassfrog import (
    GLASSFROG_BASE_URL,
    GLASSFROG_PAGE_SIZE,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.settings import GLASSFROG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.source import GlassfrogSource


def _driver(api_key: str = "gf_key") -> SourceDriver:
    return SourceDriver(GlassfrogSource(), GlassfrogSourceConfig(api_key=api_key))


class TestGetRows:
    def test_repeated_page_raises_instead_of_looping(self) -> None:
        full_page = [{"id": i} for i in range(GLASSFROG_PAGE_SIZE)]
        result = _driver().run("tensions", [ScriptedResponse(json={"tensions": full_page})] * 2)

        assert isinstance(result.raised, ValueError)
        assert "same rows" in str(result.raised)
        assert len(result.requests) == 2

    def test_missing_resource_key_raises(self) -> None:
        # v3 responses wrap rows under a resource key ({"circles": [...]}); a body without it is an
        # unexpected/error shape. Raise so the sync fails loudly instead of syncing zero rows.
        result = _driver().run("circles", [ScriptedResponse(json={"message": "something else"})])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    @parameterized.expand(
        [
            (
                name,
                config.path,
                config.data_selector,
                f"?per_page={GLASSFROG_PAGE_SIZE}"
                + ("&exclude_completed=false" if name == "actions" else "")
                + "&page=1",
            )
            for name, config in GLASSFROG_ENDPOINTS.items()
        ]
    )
    def test_each_endpoint_requests_its_path_and_unwraps_its_key(
        self, endpoint: str, path: str, data_selector: str, query: str
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={data_selector: [{"id": 42}]})])

        assert result.raised is None
        assert result.rows == [{"id": 42}]
        assert result.urls == [f"{GLASSFROG_BASE_URL}{path}{query}"]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_after_retries(self, _name: str, status_code: int) -> None:
        result = _driver().run("circles", always(ScriptedResponse(status=status_code, json={"error": "nope"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        # 5 attempts before giving up.
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_immediately(self, _name: str, status_code: int) -> None:
        result = _driver().run(
            "circles", [ScriptedResponse(status=status_code, json={"message": "api key not specified or not valid"})]
        )

        assert isinstance(result.raised, requests.HTTPError)
        # Client errors are not retried — they can never succeed on retry.
        assert len(result.requests) == 1


class TestKeyRedaction:
    def test_source_session_redacts_key(self) -> None:
        # The API key must be masked in tracked HTTP logs/samples, not left recoverable from a bucket.
        result = _driver("gf_secret").run("circles", [ScriptedResponse(json={"circles": []})])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("gf_secret",)
        # Response bodies carry people names/emails the scrubbers can't fully recognise.
        assert result.session_options[0]["capture"] is False
        # The key rides a custom header, which `requests` would replay across a cross-origin
        # redirect — the sync session must never follow redirects.
        assert result.session_options[0]["allow_redirects"] is False

    def test_validate_credentials_redacts_key(self) -> None:
        with scripted_network([ScriptedResponse(json={"circles": []})]) as network:
            assert validate_credentials("gf_secret") is True

        assert network.session_options[0]["redact_values"] == ("gf_secret",)
        assert network.session_options[0]["capture"] is False
        assert network.session_options[0]["allow_redirects"] is False


class TestValidateCredentials:
    def test_probes_circles_with_key_header_and_no_redirects(self) -> None:
        # The key rides a custom header, which requests would replay across a cross-origin redirect.
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})]
        ) as network:
            assert validate_credentials("gf_key") is False

        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == f"{GLASSFROG_BASE_URL}/circles"
        assert network.requests_log[0].headers["x-auth-token"] == "gf_key"


class TestGlassfrogSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in GLASSFROG_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={endpoint: []})])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        if endpoint in ("actions", "projects", "tensions"):
            # Partition on the stable creation timestamp — only these GlassFrog resources have one.
            assert response.partition_keys == ["created_at"]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
