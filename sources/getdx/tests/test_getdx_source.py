import pytest

from sources.getdx._config import GetdxSourceConfig
from sources.getdx.source import GetdxSource


@pytest.mark.parametrize("names,expected", [([], []), (["teams", "missing"], ["teams"]), (["users"], ["users"])])
def test_schema_selection(names: list[str], expected: list[str]) -> None:
    schemas = GetdxSource().get_schemas(GetdxSourceConfig(api_key="test-token"), team_id=1, names=names)
    assert [schema.name for schema in schemas] == expected
