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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlewebfonts import (
    GoogleWebfontsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.google_webfonts import (
    GOOGLE_WEBFONTS_API_KEY_HEADER,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import (
    ENDPOINTS,
    GOOGLE_WEBFONTS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.source import GoogleWebfontsSource


def _driver(api_key: str = "AIza-key") -> SourceDriver:
    return SourceDriver(GoogleWebfontsSource(), GoogleWebfontsSourceConfig(api_key=api_key))


class TestGetRows:
    def test_key_rides_header_auth_and_never_lands_in_url(self) -> None:
        # The key must ride the X-goog-api-key header (redacted by value), never the request URL.
        result = _driver("AIza-secret").run(
            "webfonts", [ScriptedResponse(json={"kind": "webfonts#webfontList", "items": [{"family": "Roboto"}]})]
        )

        assert result.raised is None
        assert result.rows == [{"family": "Roboto"}]
        assert result.requests[0].headers[GOOGLE_WEBFONTS_API_KEY_HEADER.lower()] == "AIza-secret"
        assert "AIza-secret" not in result.urls[0]
        # RESTClient builds its tracked session with the auth secret in redact_values.
        assert result.session_options[0]["redact_values"] == ("AIza-secret",)

    def test_retries_exhausted_raises(self) -> None:
        result = _driver().run("webfonts", always(ScriptedResponse(status=503, json={"error": "boom"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    def test_client_error_surfaces_and_is_not_retried(self) -> None:
        # A 400 (invalid key) is a permanent, non-retryable auth error — it must surface once
        # (get_non_retryable_errors matches on the "400 ... for url: <host>" message).
        result = _driver().run("webfonts", [ScriptedResponse(status=400, json={"error": "boom"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "400" in str(result.raised)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            (400, False, "Invalid Google API key"),
        ]
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_msg: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("AIza-key") == (expected_valid, expected_msg)

        assert network.requests_log[0].headers[GOOGLE_WEBFONTS_API_KEY_HEADER.lower()] == "AIza-key"


class TestGoogleWebfontsSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = GOOGLE_WEBFONTS_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json={"items": []})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        assert result.response.sort_mode == "asc"
        assert result.response.partition_count == 1
        assert result.response.partition_size == 1
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
