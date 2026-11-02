import pytest

from requests.exceptions import ConnectTimeout

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.looker import LookerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.looker.source import LookerSource


@pytest.mark.parametrize(
    ("login_status", "schema_name", "table_status", "expected_error"),
    [
        (200, None, None, None),
        (401, None, None, "Looker rejected the login"),
        (403, None, None, "Looker rejected the login"),
        (429, None, None, "Looker could not complete the login"),
        (503, None, None, "Looker could not complete the login"),
        (200, "users", 200, None),
        (200, "users", 403, "Your Looker user cannot read this table"),
        (200, "users", 401, "Looker rejected the request"),
    ],
)
def test_validation_probes_only_the_login_or_selected_table(
    login_status: int, schema_name: str | None, table_status: int | None, expected_error: str | None
) -> None:
    responses = [ScriptedResponse(status=login_status, json={"access_token": "example-token", "expires_in": 3600})]
    if table_status is not None:
        responses.append(ScriptedResponse(status=table_status, json=[{"id": "example-user"}]))
    config = LookerSourceConfig(
        instance_url="https://example.looker.com:443", client_id="example-client", client_secret="example-secret"
    )
    with scripted_network(responses) as network:
        valid, error = LookerSource().validate_credentials(config, 1, schema_name)
    assert valid is (expected_error is None)
    if expected_error is None:
        assert error is None
    else:
        assert error is not None and error.startswith(expected_error)
    assert len(network.requests_log) == len(responses)
    if schema_name is not None:
        assert network.requests_log[-1].param("limit") == "1"


@pytest.mark.parametrize(
    "instance_url",
    [
        "http://example.looker.com",
        "https://user:password@example.looker.com",
        "https://example.looker.com/api/3.1",
        "https://example.looker.com/folders/home",
        "https://example.looker.com?client_secret=example-secret",
        "https://example.looker.com#fragment",
        "https://example.looker.com:invalid",
        "https://example.looker.com:0",
        "https://example.looker.com:70000",
        "https://exa mple.looker.com",
    ],
)
def test_invalid_instance_url_does_not_send_credentials(instance_url: str) -> None:
    config = LookerSourceConfig(instance_url=instance_url, client_id="example-client", client_secret="example-secret")
    with scripted_network([]) as network:
        valid, error = LookerSource().validate_credentials(config, 1)
    assert not valid
    assert error is not None and error.startswith("Enter")
    assert network.requests_log == []


def test_unknown_table_does_not_start_a_login() -> None:
    config = LookerSourceConfig(
        instance_url="https://example.looker.com", client_id="example-client", client_secret="example-secret"
    )
    with scripted_network([]) as network:
        valid, error = LookerSource().validate_credentials(config, 1, "queries")
    assert not valid
    assert error == "This Looker table is not supported. Select a supported table."
    assert network.requests_log == []


def test_connection_failure_returns_guidance_without_exposing_credentials() -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        raise ConnectTimeout("example-secret")

    config = LookerSourceConfig(
        instance_url="https://example.looker.com", client_id="example-client", client_secret="example-secret"
    )
    with scripted_network(respond):
        valid, error = LookerSource().validate_credentials(config, 1)
    assert not valid
    assert error == "PostHog could not connect to Looker. Check the instance URL and its TLS certificate."
