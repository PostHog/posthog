from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source import FlutterwaveSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flutterwave import (
    FlutterwaveSourceConfig,
)


class TestGetSchemas:
    @parameterized.expand(
        [
            ("transactions",),
            ("settlements",),
            ("refunds",),
            ("transfers",),
            ("chargebacks",),
            ("payment_plans",),
            ("subscriptions",),
            ("subaccounts",),
            ("beneficiaries",),
        ]
    )
    def test_every_endpoint_is_full_refresh(self, endpoint: str) -> None:
        # Flutterwave v3 has no update cursor and its records mutate after creation, so no endpoint
        # may advertise incremental sync (a created_at watermark would strand later status changes).
        schemas = {s.name: s for s in FlutterwaveSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.flutterwave.com/v3/transactions?page=1",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.flutterwave.com/v3/settlements"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        assert any(key in observed for key in FlutterwaveSource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.flutterwave.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.flutterwave.com/v3/transactions",
            ),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.flutterwave.com/v3/transfers"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        assert not any(key in observed for key in FlutterwaveSource().get_non_retryable_errors())


class TestSourceForPipeline:
    def test_threads_credentials_endpoint_and_api_version(self) -> None:
        result = SourceDriver(FlutterwaveSource(), FlutterwaveSourceConfig(secret_key="FLWSECK-test")).run(
            "transactions",
            [ScriptedResponse(json={"status": "success", "meta": {"page_info": {"total_pages": 1}}, "data": []})],
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == "Bearer FLWSECK-test"
        assert result.requests[0].path == "/v3/transactions"
        # An unset pin must resolve to default_version, not fall through as None and break the URL.
        assert result.requests[0].url.startswith("https://api.flutterwave.com/v3/transactions")
