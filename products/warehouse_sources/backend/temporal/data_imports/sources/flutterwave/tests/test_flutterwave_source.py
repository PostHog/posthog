from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source import FlutterwaveSource

SOURCE_MODULE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source.flutterwave_source"
)


def _source_inputs(**overrides: Any) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = overrides.get("schema_name", "transactions")
    inputs.team_id = overrides.get("team_id", 1)
    inputs.job_id = overrides.get("job_id", "job-1")
    inputs.api_version = overrides.get("api_version", None)
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2024-01-15 00:00:00")
    return inputs


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
        with patch(SOURCE_MODULE_PATCH) as mock_source:
            FlutterwaveSource().source_for_pipeline(
                config=MagicMock(secret_key="FLWSECK-test"),
                resumable_source_manager=MagicMock(),
                inputs=_source_inputs(schema_name="transactions", should_use_incremental_field=False),
            )
        kwargs = mock_source.call_args.kwargs
        assert kwargs["secret_key"] == "FLWSECK-test"
        assert kwargs["endpoint"] == "transactions"
        # An unset pin must resolve to default_version, not fall through as None and break the URL.
        assert kwargs["api_version"] == "v3"
