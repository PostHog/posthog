import re

import pytest

from posthog.schema import SourceFieldInputConfig

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

ALL_SOURCES = SourceRegistry.get_all_sources()
SOURCE_TYPES = sorted(ALL_SOURCES.keys(), key=str)
STATIC_CATALOG_SOURCES = sorted(
    (source_type for source_type, source in ALL_SOURCES.items() if source.lists_tables_without_credentials),
    key=str,
)

# Sources that declare a credential-free catalog but cannot actually list one: `get_schemas`
# raises on a placeholder config, so they publish no public docs today. Every entry below is a
# contradiction to resolve, not an exemption — either stop advertising a static catalog or make
# discovery work without credentials.
CANNOT_LIST_WITHOUT_CREDENTIALS = {"Github"}

# Sources whose curated descriptions are keyed to names `get_schemas` never returns, so those
# descriptions reach nobody. Fix the key or expose the endpoint, then drop the entry.
DESCRIPTIONS_NOT_IN_SCHEMAS = {
    "BrowserUse",
    "CheckoutCom",
    "EZOfficeInventory",
    "Giphy",
    "GoogleSearchConsole",
    "OpenWeather",
    "Pexels",
    "ShipStation",
    "USCensus",
    "UsBea",
    "ZendeskSunshine",
}

# Static-catalog sources with no curated descriptions at all: every table falls back to LLM
# enrichment. Adding descriptions is an improvement, so drop the entry when one does.
SOURCES_WITHOUT_CURATED_DESCRIPTIONS = {"ActiveCampaign", "Airtable", "ApifyDataset", "PgAnalyze"}

CREDENTIAL_FIELD = re.compile(r"api[_-]?key|access[_-]?key|token|secret|password|passphrase|private[_-]?key", re.I)

# The public half of a keypair, each paired with a `*_secret` field that is marked secret. A name
# ending in `_id`/`_ids` is exempt for the same reason without needing an entry here.
PUBLIC_CREDENTIAL_HALVES = {
    "Adjust.app_tokens",
    "ConfluentCloud.api_key",
    "Fleetio.account_token",
    "Gong.access_key",
    "Imagga.api_key",
}


def _schema_names(source) -> set[str]:
    return {schema.name for schema in source.get_schemas(source._placeholder_config(), team_id=0)}


@pytest.mark.parametrize("source_type", STATIC_CATALOG_SOURCES, ids=str)
def test_static_catalog_sources_can_list_tables_without_credentials(source_type):
    source = ALL_SOURCES[source_type]
    expected_to_fail = str(source_type) in CANNOT_LIST_WITHOUT_CREDENTIALS

    try:
        _schema_names(source)
    except Exception as error:
        assert expected_to_fail, (
            f"{source_type} sets lists_tables_without_credentials but get_schemas raises {error!r}, "
            f"so it publishes no table catalog. Make discovery credential-free, or clear the flag."
        )
        return

    assert not expected_to_fail, (
        f"{source_type} now lists tables without credentials — remove it from CANNOT_LIST_WITHOUT_CREDENTIALS."
    )


@pytest.mark.parametrize("source_type", STATIC_CATALOG_SOURCES, ids=str)
def test_canonical_descriptions_are_keyed_by_schema_name(source_type):
    source = ALL_SOURCES[source_type]
    if str(source_type) in CANNOT_LIST_WITHOUT_CREDENTIALS:
        return

    descriptions = source.get_canonical_descriptions()
    if str(source_type) in SOURCES_WITHOUT_CURATED_DESCRIPTIONS:
        assert not descriptions, (
            f"{source_type} now curates descriptions — remove it from SOURCES_WITHOUT_CURATED_DESCRIPTIONS."
        )
        return
    assert descriptions, (
        f"{source_type} curates no table descriptions, so every table falls back to LLM enrichment. "
        f"Add them, or record it in SOURCES_WITHOUT_CURATED_DESCRIPTIONS."
    )

    stray = set(descriptions) - _schema_names(source)
    if str(source_type) in DESCRIPTIONS_NOT_IN_SCHEMAS:
        assert stray, f"{source_type} is clean — remove it from DESCRIPTIONS_NOT_IN_SCHEMAS."
        return

    assert not stray, (
        f"{source_type} describes {sorted(stray)}, which get_schemas never returns, so those "
        f"descriptions never render. Fix the key to match the schema name, or expose the endpoint."
    )


@pytest.mark.parametrize("source_type", STATIC_CATALOG_SOURCES, ids=str)
def test_documented_tables_match_the_schemas_they_describe(source_type):
    source = ALL_SOURCES[source_type]
    if str(source_type) in CANNOT_LIST_WITHOUT_CREDENTIALS:
        return

    # get_documented_tables swallows every exception and degrades to [], so a source that starts
    # raising goes quiet rather than failing. Asserting it is non-empty is what catches that.
    tables = source.get_documented_tables()
    assert tables, f"{source_type} publishes no documented tables — get_documented_tables swallowed an error."
    assert {table["name"] for table in tables} == _schema_names(source)


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_credential_fields_are_marked_secret(source_type):
    source = ALL_SOURCES[source_type]

    for field in source.get_source_config.fields:
        if not isinstance(field, SourceFieldInputConfig) or not CREDENTIAL_FIELD.search(field.name):
            continue
        # `*_id`/`*_ids` name the public identifier half of a keypair, never the credential.
        if field.name.endswith(("_id", "_ids")):
            continue
        if f"{source_type}.{field.name}" in PUBLIC_CREDENTIAL_HALVES:
            continue

        assert field.secret, (
            f"{source_type}.{field.name} looks like a credential but is not marked secret, so it "
            f"stays readable after the source is connected. Set secret=True, or record it in "
            f"PUBLIC_CREDENTIAL_HALVES if it is the public half of a keypair."
        )
