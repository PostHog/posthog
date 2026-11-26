import pytest

from requests.exceptions import ConnectionError

from products.warehouse_sources.sources.kajabi._config import KajabiSourceConfig
from products.warehouse_sources.sources.kajabi.source import KajabiSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


@pytest.fixture
def config() -> KajabiSourceConfig:
    return KajabiSourceConfig(client_id="test-client", client_secret="test-secret", site_id="123")


@pytest.mark.parametrize(
    ("schema", "status", "valid", "message"),
    [
        (None, 200, True, None),
        (None, 403, True, None),
        (None, 401, False, "rejected the access token"),
        ("offers", 403, False, "required read permission"),
        ("offers", 404, False, "HTTP 404"),
    ],
)
def test_credential_probe_distinguishes_invalid_tokens_from_table_permissions(
    config: KajabiSourceConfig, schema: str | None, status: int, valid: bool, message: str | None
) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"access_token": "test-access-token", "expires_in": 3600}),
            ScriptedResponse(status=status, json={"errors": [{"status": str(status)}]}),
        ]
    ) as network:
        accepted, reason = KajabiSource().validate_credentials(config, 1, schema)
    assert accepted is valid
    if message is None:
        assert reason is None
    else:
        assert reason is not None and message in reason
    assert network.requests_log[-1].path == ("/v1/me" if schema is None else "/v1/offers")


@pytest.mark.parametrize(("status", "message"), [(400, "rejected the client credentials"), (429, "Try again later")])
def test_token_exchange_errors_return_safe_messages(config: KajabiSourceConfig, status: int, message: str) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"error": "invalid_client"})]):
        accepted, reason = KajabiSource().validate_credentials(config, 1)
    assert accepted is False
    assert reason is not None and message in reason
    assert config.client_secret not in reason


@pytest.mark.parametrize(
    ("schema", "parent_path", "child_path"),
    [
        ("contact_offers", "/v1/contacts", "/v1/contacts/p%2F1/relationships/offers"),
        ("offer_products", "/v1/offers", "/v1/offers/p%2F1/relationships/products"),
    ],
)
@pytest.mark.parametrize(
    ("parents", "parent_status", "child_status", "valid"),
    [
        ([], 200, None, True),
        ([{"id": "p/1"}], 200, 200, True),
        ([{"id": "p/1"}], 200, 403, False),
        ([], 403, None, False),
    ],
)
def test_relationship_probe_uses_a_parent_from_the_selected_site(
    config: KajabiSourceConfig,
    schema: str,
    parent_path: str,
    child_path: str,
    parents: list[dict[str, str]],
    parent_status: int,
    child_status: int | None,
    valid: bool,
) -> None:
    script = [
        ScriptedResponse(json={"access_token": "test-access-token", "expires_in": 3600}),
        ScriptedResponse(status=parent_status, json={"data": parents}),
    ]
    if child_status is not None:
        script.append(ScriptedResponse(status=child_status, json={"data": []}))
    with scripted_network(script) as network:
        accepted, _ = KajabiSource().validate_credentials(config, 1, schema)
    assert accepted is valid
    assert network.requests_log[1].path == parent_path
    assert network.requests_log[1].param("filter[site_id]") == "123"
    if child_status is not None:
        assert network.requests_log[-1].path == child_path


def test_unknown_schema_is_rejected_before_network_access(config: KajabiSourceConfig) -> None:
    with scripted_network([]) as network:
        accepted, reason = KajabiSource().validate_credentials(config, 1, "unknown")
    assert accepted is False
    assert reason is not None and "not supported" in reason
    assert network.requests_log == []


def test_connection_failure_returns_a_safe_message(config: KajabiSourceConfig) -> None:
    with scripted_network([ConnectionError("test-secret")]):
        accepted, reason = KajabiSource().validate_credentials(config, 1)
    assert accepted is False
    assert reason == "Could not connect to Kajabi. Try again later."
