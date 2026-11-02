from base64 import b64encode
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imagga import ImaggaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga import (
    _daily_usage_rows,
    imagga_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source import ImaggaSource

# A representative /usage result, shaped after Imagga's public docs example.
_USAGE_RESULT = {
    "billing_period_start": "18 of Oct, 2018",
    "billing_period_end": "18 of Nov, 2018",
    "monthly_limit": 2000,
    "daily_for": "23 of Oct, 2018",
    "daily_processed": 3,
    "daily_requests": 3,
    "last_usage": 1540300613,
    "concurrency": {"max": 2, "now": 1},
    "daily": {"1519603200": 1, "1540252800": 3},
    "monthly": {"2018-10": 30},
}


def _usage_body(result: Any) -> dict[str, Any]:
    return {"result": result, "status": {"type": "success"}}


def _driver() -> SourceDriver:
    return SourceDriver(ImaggaSource(), ImaggaSourceConfig(api_key="key", api_secret="secret"))


class TestDailyUsageRows:
    @parameterized.expand([("missing", {}), ("wrong_type", {"daily": []}), ("null", {"daily": None})])
    def test_returns_empty_when_no_daily_histogram(self, _name: str, result: dict[str, Any]) -> None:
        assert _daily_usage_rows(result) == []

    def test_skips_unparseable_timestamp_keys(self) -> None:
        rows = _daily_usage_rows({"daily": {"not-a-timestamp": 5, "1519603200": 1}})
        assert [r["timestamp"] for r in rows] == [1519603200]


class TestUsageEndpoint:
    @parameterized.expand([("null_result", None), ("empty_result", {})])
    def test_empty_result_yields_nothing(self, _name: str, result: Any) -> None:
        run = _driver().run("usage", [ScriptedResponse(json=_usage_body(result))])
        assert run.raised is None
        assert run.rows == []

    def test_without_primary_key_yields_nothing(self) -> None:
        # A non-empty snapshot missing `billing_period_start` must not be yielded — merging on an
        # absent primary key column fails the sync permanently instead of producing an empty batch.
        run = _driver().run(
            "usage",
            [ScriptedResponse(json=_usage_body({"monthly_limit": 2000, "concurrency": {"max": 2, "now": 1}}))],
        )
        assert run.raised is None
        assert run.rows == []


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("unavailable", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        run = _driver().run(
            "usage",
            [
                ScriptedResponse(status=status, json={}, headers={"Retry-After": "0"}),
                ScriptedResponse(json=_usage_body(_USAGE_RESULT)),
            ],
        )
        assert run.raised is None
        assert len(run.rows) == 1
        assert run.paths == ["/v2/usage", "/v2/usage"]

    def test_client_error_raises_http_error(self) -> None:
        run = _driver().run("usage", [ScriptedResponse(status=401, json={"status": {"text": "unauthorized"}})])
        assert isinstance(run.raised, HTTPError)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("key", "secret") is expected
        assert [request.path for request in network.requests_log] == ["/v2/usage"]

    def test_redacts_secret_and_uses_basic_auth(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("key", "secret") is True
        # The secret is masked by value in logs/samples, and travels via Basic auth.
        assert network.session_options[0]["redact_values"] == ("secret",)
        assert network.requests_log[0].headers["authorization"] == "Basic " + b64encode(b"key:secret").decode()


class TestImaggaSourceResponse:
    @parameterized.expand([("usage", ["billing_period_start"]), ("daily_usage", ["date"])])
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = imagga_source("key", "secret", endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
