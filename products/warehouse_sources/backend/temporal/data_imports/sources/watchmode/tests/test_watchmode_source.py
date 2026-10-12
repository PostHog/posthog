import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.watchmode import (
    WatchmodeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.source import WatchmodeSource


class TestWatchmodeSource:
    def setup_method(self) -> None:
        self.source = WatchmodeSource()
        self.config = WatchmodeSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_validate_credentials_maps_status_codes(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(lambda _request: ScriptedResponse(status=status_code)) as network:
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert network.requests_log[0].path == "/v1/status/"
        assert network.requests_log[0].headers["x-api-key"] == "test-key"
        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error

    def test_validate_credentials_disables_redirects(self) -> None:
        # A cross-host redirect would otherwise replay the `X-API-Key` header off-host,
        # leaking the key; the validation probe must pin redirects off.
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})]
        ) as network:
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/v1/status/"
        assert network.requests_log[0].headers["x-api-key"] == "test-key"
        assert network.session_options[0]["allow_redirects"] is False
        assert valid is False
        assert error

    def test_validate_credentials_handles_connection_errors(self) -> None:
        def connection_error(_request: RecordedRequest) -> ScriptedResponse:
            raise requests.ConnectionError("connection refused")

        with scripted_network(connection_error):
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid is False
        assert error is not None and "Watchmode" in error

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_http_errors_are_non_retryable(self, status_code: int) -> None:
        # A bad API key must fail the sync permanently instead of retrying forever, so
        # the patterns have to match the exact HTTPError text raise_for_status produces.
        response = requests.Response()
        response.status_code = status_code
        response.url = "https://api.watchmode.com/v1/list-titles/"
        response.reason = "Unauthorized" if status_code == 401 else "Forbidden"

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable_errors)
