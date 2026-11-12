import pytest

from products.warehouse_sources.sources.moneybird._config import MoneybirdSourceConfig
from products.warehouse_sources.sources.moneybird.source import MoneybirdSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network

ADMINISTRATIONS = [{"id": "123456789", "name": "Example BV"}, {"id": "987654321", "name": "Other BV"}]


@pytest.mark.parametrize(
    ("administration_id", "response", "expected_valid", "expected_message_start"),
    [
        (" 123456789 ", ScriptedResponse(json=ADMINISTRATIONS), True, None),
        ("555", ScriptedResponse(json=ADMINISTRATIONS), False, "Your API token can't access this administration"),
        (
            "123456789",
            ScriptedResponse(status=401, json={"error": "Token is invalid", "symbolic": {"token": "invalid"}}),
            False,
            "Moneybird rejected your API token",
        ),
        (
            "123456789",
            ScriptedResponse(status=403, json={"error": "IP is blacklisted for API usage"}),
            False,
            "Moneybird refused the request",
        ),
    ],
)
def test_validate_credentials_checks_the_token_and_the_administration(
    administration_id: str,
    response: ScriptedResponse,
    expected_valid: bool,
    expected_message_start: str | None,
) -> None:
    config = MoneybirdSourceConfig(api_token="test-token", administration_id=administration_id)

    with scripted_network(always(response)) as network:
        valid, message = MoneybirdSource().validate_credentials(config, team_id=1)

    assert valid is expected_valid
    assert (message or "").startswith(expected_message_start or "")
    assert [request.path for request in network.requests_log] == ["/api/v2/administrations.json"]


@pytest.mark.parametrize("administration_id", ["https://moneybird.com/123456789", "123/../456", ""])
def test_validate_credentials_rejects_an_administration_id_that_is_not_a_number(administration_id: str) -> None:
    config = MoneybirdSourceConfig(api_token="test-token", administration_id=administration_id)

    with scripted_network([]) as network:
        valid, message = MoneybirdSource().validate_credentials(config, team_id=1)

    assert not valid
    assert message is not None and message.startswith("Enter the administration ID as a number")
    assert network.requests_log == []
