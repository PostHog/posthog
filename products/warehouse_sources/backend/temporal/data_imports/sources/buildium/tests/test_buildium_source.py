import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.source import BuildiumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildium import (
    BuildiumSourceConfig,
)


@pytest.mark.parametrize(
    ("schema_name", "expected_path"),
    [
        (None, "/v1/rentals"),
        ("bills", "/v1/bills"),
        ("lease_transactions", "/v1/leases"),
        ("general_ledger_transactions", "/v1/glaccounts"),
        ("custom_field_definitions", "/v1/customfields/entityType/Rentals/definitions"),
    ],
)
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, (True, None)),
        (401, (False, AUTH_ERROR)),
        (403, (False, PERMISSION_ERROR)),
        (500, (False, "Couldn't reach Buildium (RealPage) to check your credentials. Try again in a few minutes.")),
    ],
)
def test_validate_credentials(
    schema_name: str | None, expected_path: str, status: int, expected: tuple[bool, str | None]
) -> None:
    config = BuildiumSourceConfig(client_id="example-client", client_secret="example-secret")
    answer = ScriptedResponse(status=status)
    script = always(answer) if status == 500 else [answer]
    with scripted_network(script) as network:
        assert BuildiumSource().validate_credentials(config, 1, schema_name) == expected

    assert network.requests_log
    if status != 500:
        assert len(network.requests_log) == 1
    for request in network.requests_log:
        assert request.path == expected_path
        assert request.param("limit") == "1"
        assert request.headers["x-buildium-client-id"] == config.client_id
        assert request.headers["x-buildium-client-secret"] == config.client_secret
