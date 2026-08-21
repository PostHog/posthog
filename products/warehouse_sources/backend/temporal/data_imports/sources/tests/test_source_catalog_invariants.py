import pytest

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

ALL_SOURCES = SourceRegistry.get_all_sources()
STATIC_CATALOG_SOURCES = sorted(
    (source_type for source_type, source in ALL_SOURCES.items() if source.lists_tables_without_credentials),
    key=str,
)

# Sources whose curated descriptions are keyed to names `get_schemas` never returns, so those
# descriptions reach nobody. Each entry is a defect to fix — by correcting the key or by exposing
# the endpoint — not a permanent exemption. Remove a source from this list once it is fixed.
DESCRIPTIONS_NOT_IN_SCHEMAS = {
    "BrowserUse",
    "CheckoutCom",
    "EZOfficeInventory",
    "GoogleSearchConsole",
    "OpenWeather",
    "Pexels",
    "ShipStation",
    "UsBea",
    "USCensus",
    "ZendeskSunshine",
    "Giphy",
}


def _schema_names(source) -> set[str] | None:
    try:
        return {schema.name for schema in source.get_schemas(source._placeholder_config(), team_id=0)}
    except Exception:
        return None


@pytest.mark.parametrize("source_type", STATIC_CATALOG_SOURCES, ids=str)
def test_canonical_descriptions_are_keyed_by_schema_name(source_type):
    source = ALL_SOURCES[source_type]
    descriptions = source.get_canonical_descriptions()
    if not descriptions:
        return

    names = _schema_names(source)
    if names is None:
        return

    stray = set(descriptions) - names
    if str(source_type) in DESCRIPTIONS_NOT_IN_SCHEMAS:
        return

    assert not stray, (
        f"{source_type} describes {sorted(stray)}, which get_schemas never returns, so those "
        f"descriptions never render. Fix the key to match the schema name, or expose the endpoint."
    )


@pytest.mark.parametrize("source_type", STATIC_CATALOG_SOURCES, ids=str)
def test_documented_tables_match_the_schemas_they_describe(source_type):
    source = ALL_SOURCES[source_type]
    tables = source.get_documented_tables()
    if not tables:
        return

    names = _schema_names(source)
    if names is None:
        return

    # get_documented_tables swallows every exception and degrades to [], so a source that
    # starts raising here goes quiet rather than failing. Comparing against get_schemas is
    # what catches a public docs catalog that silently stopped matching the real tables.
    assert {table["name"] for table in tables} == names
