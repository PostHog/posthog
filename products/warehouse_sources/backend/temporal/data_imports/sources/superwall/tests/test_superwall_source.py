import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.superwall import (
    SuperwallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.superwall.source import SuperwallSource


@pytest.mark.parametrize(
    ("status", "schema_name", "expected", "message"),
    [
        (200, None, True, None),
        (401, None, False, "invalid or revoked"),
        (403, None, True, None),
        (403, "products", False, "products:read"),
        (404, "webhook_events", False, "project and application IDs"),
    ],
)
def test_credentials_distinguish_invalid_key_from_missing_scope(
    status: int, schema_name: str | None, expected: bool, message: str | None
) -> None:
    config = SuperwallSourceConfig(api_key="test_api_key", project_id="project_test", application_id="application_test")
    with scripted_network(
        [
            ScriptedResponse(
                status=status, json={"code": "insufficient_permissions" if status == 403 else "invalid_api_key"}
            )
        ]
    ) as network:
        valid, error = SuperwallSource().validate_credentials(config, 1, schema_name=schema_name)
    assert valid is expected
    if message:
        assert error is not None and message in error
    else:
        assert error is None
    request = network.requests_log[0]
    assert request.path == (
        "/v2/products"
        if schema_name == "products"
        else "/v2/projects/project_test/events"
        if schema_name == "webhook_events"
        else "/v2/projects"
    )
    if schema_name == "products":
        assert request.param("project_id") == "project_test"
        assert request.param("limit") == "1"


def test_unknown_schema_rejects_without_a_probe() -> None:
    config = SuperwallSourceConfig(api_key="test_api_key", project_id="project_test", application_id="application_test")
    with scripted_network([]) as network:
        valid, error = SuperwallSource().validate_credentials(config, 1, schema_name="unknown")
    assert valid is False
    assert error is not None and "Unknown Superwall table" in error
    assert network.requests_log == []


def test_validation_does_not_accept_other_http_errors() -> None:
    config = SuperwallSourceConfig(api_key="test_api_key", project_id="project_test", application_id="application_test")
    with scripted_network([ScriptedResponse(status=400, json={"code": "parameter_invalid"})]):
        with pytest.raises(HTTPError):
            SuperwallSource().validate_credentials(config, 1)
