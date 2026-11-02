import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statsig import (
    StatsigSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.source import StatsigSource


@pytest.mark.parametrize(
    ("status", "schema", "expected", "message"),
    [
        (200, None, True, None),
        (401, None, False, "Statsig rejected your API key."),
        (403, None, True, None),
        (403, "metrics", False, "Your Console API key cannot read this table."),
        (200, "metrics", True, None),
    ],
)
def test_credential_probe_distinguishes_invalid_key_and_table_permissions(
    status: int, schema: str | None, expected: bool, message: str | None
) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json={"data": [], "message": "Access denied" if status != 200 else "OK"})]
    ) as network:
        valid, error = StatsigSource().validate_credentials(
            StatsigSourceConfig(api_key="console-test-key"), team_id=1, schema_name=schema
        )

    assert valid is expected
    assert error is None if message is None else error is not None and message in error
    request = network.requests_log[0]
    assert request.path == ("/console/v1/metrics/list" if schema == "metrics" else "/console/v1/gates")
    assert request.param("limit") == "1"
    assert request.headers["statsig-api-key"] == "console-test-key"
    assert request.headers["statsig-api-version"] == "20240601"


def test_credential_probe_does_not_report_unrelated_errors_as_invalid_key() -> None:
    with scripted_network([ScriptedResponse(status=400, json={"message": "Invalid request"})]):
        with pytest.raises(HTTPError) as error:
            StatsigSource().validate_credentials(StatsigSourceConfig(api_key="console-test-key"), team_id=1)

    assert error.value.response is not None
    assert error.value.response.status_code == 400


def test_unknown_table_does_not_probe_an_unrelated_endpoint() -> None:
    with scripted_network([]) as network:
        valid, message = StatsigSource().validate_credentials(
            StatsigSourceConfig(api_key="console-test-key"), team_id=1, schema_name="unknown"
        )

    assert valid is False
    assert message is not None and "not supported" in message
    assert network.requests_log == []
