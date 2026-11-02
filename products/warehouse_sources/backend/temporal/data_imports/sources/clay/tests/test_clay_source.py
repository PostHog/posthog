from typing import Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.clay.source import ClaySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clay import ClaySourceConfig


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (None, ["t_first", "t_second", "credit_balances"]),
        (["t_second"], ["t_second"]),
        (["credit_balances"], ["credit_balances"]),
        (["t_unknown"], []),
    ],
)
def test_get_schemas_lists_configured_tables(names: Optional[list[str]], expected: list[str]) -> None:
    config = ClaySourceConfig(api_key="clay_test_key", table_ids="t_first\nhttps://app.clay.com/tables/t_second")

    schemas = ClaySource().get_schemas(config, team_id=1, names=names)

    assert [schema.name for schema in schemas] == expected
    assert all(
        not schema.supports_incremental and schema.supports_append == (schema.name == "credit_balances")
        for schema in schemas
    )


@pytest.mark.parametrize(
    ("schema_name", "expected_table_ids"),
    [
        (None, ["t_first", "t_second"]),
        ("t_second", ["t_second"]),
        ("credit_balances", ["t_first", "t_second"]),
    ],
)
def test_validate_credentials_probes_only_real_tables(
    schema_name: Optional[str], expected_table_ids: list[str]
) -> None:
    config = ClaySourceConfig(api_key="clay_test_key", table_ids="t_first t_second")

    with scripted_network(lambda request: ScriptedResponse(json={"data": []})) as network:
        valid, _ = ClaySource().validate_credentials(config, team_id=1, schema_name=schema_name)

    assert valid is True
    queried_tables = [
        request.json()["query"]["tables"][0]["id"]
        for request in network.requests_log
        if request.path == "/public/v0/tables/query"
    ]
    assert queried_tables == expected_table_ids
