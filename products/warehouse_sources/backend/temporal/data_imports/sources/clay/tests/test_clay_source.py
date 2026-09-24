from typing import Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.clay.source import ClaySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clay import ClaySourceConfig


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (None, ["t_first", "t_second"]),
        (["t_second"], ["t_second"]),
        (["t_unknown"], []),
    ],
)
def test_get_schemas_lists_configured_tables(names: Optional[list[str]], expected: list[str]) -> None:
    config = ClaySourceConfig(api_key="clay_test_key", table_ids="t_first\nhttps://app.clay.com/tables/t_second")

    schemas = ClaySource().get_schemas(config, team_id=1, names=names)

    assert [schema.name for schema in schemas] == expected
    assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
