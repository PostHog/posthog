from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.settings import (
    FLUTTERWAVE_API_V3,
    FLUTTERWAVE_API_V4,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source import FlutterwaveSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flutterwave import (
    FlutterwaveSourceConfig,
)


class TestGetSchemas:
    @parameterized.expand([(FLUTTERWAVE_API_V3,), (FLUTTERWAVE_API_V4,)])
    def test_every_endpoint_is_full_refresh(self, api_version: str) -> None:
        # Flutterwave has no update cursor on either version and its records mutate after creation, so
        # no endpoint may advertise incremental sync (a created_at watermark would strand later status
        # changes).
        for schema in FlutterwaveSource().get_schemas(MagicMock(), team_id=1, api_version=api_version):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @parameterized.expand(
        [
            (
                "v3",
                FLUTTERWAVE_API_V3,
                {
                    "transactions",
                    "settlements",
                    "refunds",
                    "transfers",
                    "chargebacks",
                    "payment_plans",
                    "subscriptions",
                    "subaccounts",
                    "beneficiaries",
                    "banks",
                    "wallet_statement",
                    "bill_payments",
                },
            ),
            (
                "v4",
                FLUTTERWAVE_API_V4,
                {"transactions", "settlements", "refunds", "transfers", "chargebacks", "beneficiaries"},
            ),
            # An unpinned call (the creation wizard) discovers the default version's tables.
            ("unpinned", None, {"transactions", "settlements", "refunds", "transfers", "chargebacks", "beneficiaries"}),
        ]
    )
    def test_table_set_follows_the_pin(self, _name: str, api_version: str | None, expected: set[str]) -> None:
        schemas = FlutterwaveSource().get_schemas(MagicMock(), team_id=1, api_version=api_version)
        assert {s.name for s in schemas} == expected


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.flutterwave.com/v3/transactions?page=1",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.flutterwave.com/v3/settlements"),
            (
                "v4_unauthorized",
                "401 Client Error: Unauthorized for url: https://f4bexperience.flutterwave.com/charges?page=1",
            ),
            ("v4_forbidden", "403 Client Error: Forbidden for url: https://f4bexperience.flutterwave.com/settlements"),
            (
                "v4_token_rejected",
                "HTTP 401 from the OAuth2 token endpoint: invalid_client [oauth2_token_config_error]",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        assert any(key in observed for key in FlutterwaveSource().get_non_retryable_errors())


class TestSourceForPipeline:
    @parameterized.expand(
        [
            ("v3_pin", FLUTTERWAVE_API_V3, "https://api.flutterwave.com/v3/transactions", "Bearer FLWSECK-test"),
            # An unset pin must resolve to default_version (v4), not fall through as None and break the URL.
            ("unpinned", None, "https://f4bexperience.flutterwave.com/charges", "Bearer minted-token"),
            ("v4_pin", FLUTTERWAVE_API_V4, "https://f4bexperience.flutterwave.com/charges", "Bearer minted-token"),
        ]
    )
    def test_threads_credentials_endpoint_and_api_version(
        self, _name: str, api_version: str | None, url: str, authorization: str
    ) -> None:
        empty = ScriptedResponse(json={"status": "success", "meta": {"page_info": {"total_pages": 1}}, "data": []})
        token = ScriptedResponse(json={"access_token": "minted-token", "expires_in": 600})
        config = FlutterwaveSourceConfig(
            secret_key="FLWSECK-test", client_id="client-test", client_secret="secret-test"
        )
        result = SourceDriver(FlutterwaveSource(), config).run(
            "transactions",
            route({"/openid-connect/token": [token], "/transactions": [empty], "/charges": [empty]}),
            should_use_incremental_field=False,
            api_version=api_version,
        )

        assert result.raised is None
        data_request = result.requests[-1]
        assert data_request.url.startswith(url)
        assert data_request.headers["authorization"] == authorization
