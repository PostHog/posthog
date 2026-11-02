import json

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import always
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sanity import SanitySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sanity.source import SanitySource


def config(**overrides: str) -> SanitySourceConfig:
    return SanitySourceConfig(
        **{"project_id": "abc12345", "dataset": "production", "api_token": "test-sanity-token", **overrides}
    )


@pytest.mark.parametrize(
    ("status", "schema_name", "valid", "message"),
    [
        (200, None, True, None),
        (401, None, False, "rejected the API token"),
        (403, None, True, None),
        (403, "article", False, "cannot read this dataset"),
        (404, None, False, "does not exist"),
        (410, None, False, "no longer supports"),
    ],
)
def test_credentials_map_auth_errors_and_check_the_selected_type(
    status: int, schema_name: str | None, valid: bool, message: str | None
) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"result": [], "error": "Access denied"})]) as network:
        success, error = SanitySource().validate_credentials(config(), team_id=1, schema_name=schema_name)

    assert success is valid
    if message is None:
        assert error is None
    else:
        assert error and message in error
    request = network.requests_log[0]
    if schema_name is None:
        assert request.param("query") == "count(*[0...1])"
    else:
        assert request.param("query") == "*[_type == $type][0...1]{_id, _updatedAt}"
        assert json.loads(request.param("$type") or "null") == schema_name


def test_credentials_do_not_label_a_server_failure_as_invalid_credentials() -> None:
    with scripted_network(always(ScriptedResponse(status=500, json={"error": "Internal Server Error"}))):
        assert SanitySource().validate_credentials(config(), team_id=1) == (
            False,
            "Couldn't reach Sanity to check your credentials. Try again in a few minutes.",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"project_id": "example.com/path"},
        {"project_id": "user@internal"},
        {"dataset": "production?query=*"},
        {"dataset": "../other"},
        {"api_token": ""},
    ],
)
def test_invalid_connection_fields_fail_before_the_token_is_sent(overrides: dict[str, str]) -> None:
    with scripted_network([]) as network:
        success, error = SanitySource().validate_credentials(config(**overrides), team_id=1)

    assert success is False
    assert error
    assert network.requests_log == []


@pytest.mark.parametrize("types", [[], ["post", "author", "sanity.imageAsset", "post"]])
def test_discovery_builds_tables_from_remote_types_and_keeps_asset_tables(types: list[str]) -> None:
    with scripted_network([ScriptedResponse(json={"result": types})]) as network:
        schemas = SanitySource().get_schemas(config(), team_id=1, api_version="2025-02-19")

    assert [schema.name for schema in schemas] == sorted(set(types) | {"sanity.imageAsset", "sanity.fileAsset"})
    assert network.requests_log[0].path == "/v2025-02-19/data/query/production"
    assert "array::unique" in (network.requests_log[0].param("query") or "")
    assert network.requests_log[0].param("perspective") == "raw"


def test_discovery_does_not_hide_an_invalid_response_as_an_empty_dataset() -> None:
    with scripted_network([ScriptedResponse(json={"result": {"types": []}})]):
        with pytest.raises(ValueError, match="document type list"):
            SanitySource().get_schemas(config(), team_id=1)
