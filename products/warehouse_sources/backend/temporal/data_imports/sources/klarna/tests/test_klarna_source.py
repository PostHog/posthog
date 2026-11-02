import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klarna import KlarnaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.source import KlarnaSource


@pytest.mark.parametrize(
    ("status", "schema", "success", "message"),
    [
        (200, None, True, None),
        (401, None, False, "Klarna rejected your credentials."),
        (403, None, True, None),
        (403, "transactions", False, "Klarna denied access."),
    ],
)
def test_credential_probe_distinguishes_invalid_keys_and_missing_access(
    status: int, schema: str | None, success: bool, message: str | None
) -> None:
    config = KlarnaSourceConfig(api_key="klarna_test_api_fake", region="na", environment="playground")
    with scripted_network(
        [
            ScriptedResponse(
                status=status, json={"error_code": "UNAUTHORIZED", "error_messages": [], "correlation_id": "fake"}
            )
        ]
    ) as network:
        valid, error = KlarnaSource().validate_credentials(config, 1, schema_name=schema)

    assert valid is success
    assert (error is None) if message is None else error is not None and message in error
    assert network.requests_log[0].url == (
        f"https://api-na.playground.klarna.com/settlements/v1/{schema or 'payouts'}?size=1&offset=0"
    )
    assert network.requests_log[0].headers["authorization"] == "Basic klarna_test_api_fake"


@pytest.mark.parametrize(("api_key", "schema"), [("", None), ("klarna_test_api_fake", "orders")])
def test_invalid_local_inputs_do_not_send_credentials(api_key: str, schema: str | None) -> None:
    with scripted_network([]) as network:
        valid, error = KlarnaSource().validate_credentials(KlarnaSourceConfig(api_key=api_key), 1, schema_name=schema)

    assert valid is False
    assert error is not None
    assert network.requests_log == []


def test_probe_bad_request_keeps_the_vendor_failure() -> None:
    with scripted_network([ScriptedResponse(status=400, json={"error_code": "BAD_VALUE"})]):
        with pytest.raises(HTTPError, match="400 Client Error"):
            KlarnaSource().validate_credentials(KlarnaSourceConfig(api_key="klarna_test_api_fake"), 1)


@pytest.mark.parametrize("status", [204, 302])
def test_probe_rejects_non_200_success_responses(status: int) -> None:
    with scripted_network([ScriptedResponse(status=status)]):
        with pytest.raises(ValueError, match="unexpected response"):
            KlarnaSource().validate_credentials(KlarnaSourceConfig(api_key="klarna_test_api_fake"), 1)


@pytest.mark.parametrize(
    ("endpoint", "incremental_field", "error_type"),
    [("orders", None, UnknownResourceError), ("payouts", "payout_date", ValueError)],
)
def test_unsupported_tables_and_sync_modes_fail_before_http(
    endpoint: str, incremental_field: str | None, error_type: type[Exception]
) -> None:
    result = SourceDriver(KlarnaSource(), KlarnaSourceConfig(api_key="klarna_test_api_fake")).run(
        endpoint, [], incremental_field=incremental_field
    )

    assert isinstance(result.raised, error_type)
    assert result.requests == []
