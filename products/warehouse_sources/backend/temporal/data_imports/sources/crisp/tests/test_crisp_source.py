import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.source import CrispSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crisp import CrispSourceConfig


@pytest.mark.parametrize(
    ("status", "schema", "valid", "message"),
    [
        (200, None, True, None),
        (401, None, False, "Crisp rejected the token"),
        (403, None, False, "Crisp denied access"),
        (403, "people", False, "Crisp denied access to this table"),
        (404, None, False, "Crisp could not find the workspace"),
        (200, "messages", True, None),
    ],
)
def test_credential_probe_maps_workspace_and_table_errors(
    config: CrispSourceConfig, status: int, schema: str | None, valid: bool, message: str | None
) -> None:
    body = {
        "error": status != 200,
        "reason": "resolved" if status == 200 else "unauthorized",
        "data": {"website_id": config.website_id} if schema is None else [],
    }
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        result = CrispSource().validate_credentials(config, team_id=1, schema_name=schema)
    assert result[0] is valid
    if message is None:
        assert result[1] is None
    else:
        assert result[1] is not None and message in result[1]
    request = network.requests_log[0]
    assert request.path == (
        f"/v1/website/{config.website_id}"
        if schema is None
        else f"/v1/website/{config.website_id}/{'conversations/1' if schema == 'messages' else 'people/profiles/1'}"
    )
    assert request.headers["x-crisp-tier"] == "website"


def test_credential_probe_does_not_wait_out_a_rate_limit_like_a_sync(config: CrispSourceConfig) -> None:
    with scripted_network(
        always(ScriptedResponse(status=429, json={"error": True, "reason": "rate_limited"}))
    ) as network:
        assert CrispSource().validate_credentials(config, team_id=1) == (
            False,
            "Couldn't reach Crisp to check your credentials. Try again in a few minutes.",
        )
    assert len(network.requests_log) <= 5


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("website_id", "https://example.com/website", "workspace UUID"),
        ("token_identifier", "example:identifier", "token identifier and key"),
        ("token_identifier", "identifiér", "token identifier and key"),
        ("token_key", "key\u200b", "token identifier and key"),
    ],
)
def test_invalid_credentials_fail_before_network(
    config: CrispSourceConfig, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    with scripted_network([]) as network:
        valid, error = CrispSource().validate_credentials(config, team_id=1)
    assert not valid
    assert error is not None and message in error
    assert network.requests_log == []
