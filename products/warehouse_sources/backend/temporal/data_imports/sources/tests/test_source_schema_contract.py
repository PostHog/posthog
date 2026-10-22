"""Two schema checks for every source in the registry, so that no source needs its own copy of them.

1. `get_schemas(names=[...])` returns exactly the schemas that it names.
2. An extraction for a schema that the source does not know fails before it sends a request, and the
   error names that schema.

A source that this test cannot drive has an entry in an allowlist below, with the reason. That source
keeps its own test for the check. An entry that starts to pass must leave its list, so the lists only
get shorter.
"""

from typing import Any

import pytest

from posthog.dataclasses import frozen

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import _BaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DatabaseBlockedError,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tests.contract_harness import (
    is_stub,
    native_driver,
    placeholder_configs,
)

ALL_SOURCES: dict[str, _BaseSource[Any]] = {
    str(source_type): source for source_type, source in SourceRegistry.get_all_sources().items()
}
SOURCE_NAMES = sorted(ALL_SOURCES)
# A scaffolded source has no schema list and no extraction code until its implementation ships.
LISTING_SOURCE_NAMES = [
    name for name in SOURCE_NAMES if type(ALL_SOURCES[name]).get_schemas is not _BaseSource.get_schemas
]
EXTRACTING_SOURCE_NAMES = [name for name in SOURCE_NAMES if not is_stub(ALL_SOURCES[name])]

UNKNOWN_SCHEMA = "contract_unknown_schema"
TEAM_ID = 1
PASS = "pass"

# Sources whose schema list this test cannot read. Reasons:
# `driver`: the source imports a driver that opens connections the fake network cannot see.
# `network`: `get_schemas` sends a request, because the vendor supplies the list.
# `config`: `get_schemas` rejects every placeholder config.
# `empty`: `get_schemas` returns no schema for a placeholder config.
SCHEMA_FILTER_NOT_CHECKABLE: dict[str, str] = {
    "AmazonS3": "network",
    "AwsAthena": "network",
    "AwsDocumentDB": "driver",
    "AzureBlob": "network",
    "BigQuery": "driver",
    "Baserow": "network",
    "CheckoutCom": "network",
    "ClickHouse": "network",
    "CloudflareD1": "network",
    "CloudflareR2": "config",
    "Convex": "config",
    "CosmosDB": "config",
    "Custom": "config",
    "Databricks": "driver",
    "DoIt": "network",
    "DynamoDB": "network",
    "Elasticsearch": "network",
    "Firebase": "config",
    "GoogleAds": "driver",
    "GoogleCloudStorage": "network",
    "GoogleSheets": "config",
    "Kafka": "driver",
    "MSSQL": "driver",
    "Modal": "driver",
    "MongoDB": "driver",
    "Motherduck": "driver",
    "MySQL": "driver",
    "Neo4j": "config",
    "Neon": "driver",
    "PlanetScaleMySQL": "driver",
    "PlanetScalePostgres": "driver",
    "Postgres": "driver",
    "Redshift": "driver",
    "SFTP": "config",
    "Sanity": "network",
    "Slack": "network",
    "Snowflake": "driver",
    "Supabase": "driver",
    "TemporalIO": "driver",
    "Trino": "network",
    "Vitally": "network",
    "Webflow": "network",
}

# Sources whose extraction for an unknown schema this test cannot check. Reasons:
# `driver`: the source imports a driver that opens connections the fake network cannot see.
# `database`: the extraction reads the application database before it checks the schema.
# `config`: the extraction rejects every placeholder config before it checks the schema.
# `cursor`: the extraction needs a source cursor manager, which `SourceDriver` does not supply.
# `request`: the extraction sends a request before it checks the schema, or the vendor supplies the list.
# `webhook`: the schemas are webhook-only, so the extraction accepts any name and yields no rows.
UNKNOWN_SCHEMA_NOT_CHECKABLE: dict[str, str] = {
    "AmazonS3": "request",
    "Attentive": "webhook",
    "AwsAthena": "request",
    "AwsDocumentDB": "driver",
    "AzureBlob": "request",
    "AzureLogAnalytics": "request",
    "Baserow": "request",
    "BigQuery": "driver",
    "BingAds": "database",
    "CdcOpenData": "request",
    "Clari": "request",
    "Clay": "request",
    "ClickHouse": "database",
    "Cliniko": "request",
    "CloudflareD1": "request",
    "CloudflareR2": "config",
    "Convex": "cursor",
    "CosmosDB": "config",
    "Custom": "config",
    "CustomerIO": "webhook",
    "Databricks": "driver",
    "Depot": "cursor",
    "DoIt": "request",
    "DynamoDB": "request",
    "Elasticsearch": "request",
    "FileUpload": "config",
    "FullStory": "request",
    "Github": "config",
    "GoogleAds": "driver",
    "GoogleCloudStorage": "request",
    "GoogleSheets": "config",
    "Hatchet": "config",
    "HelpScout": "database",
    "Hubspot": "database",
    "Instagram": "database",
    "Intercom": "database",
    "Kafka": "driver",
    "Linear": "database",
    "Logicmonitor": "config",
    "MSSQL": "driver",
    "MicrosoftClarity": "request",
    "Modal": "driver",
    "MongoDB": "driver",
    "Motherduck": "driver",
    "MySQL": "driver",
    "Neon": "driver",
    "Pardot": "database",
    "PinterestAds": "database",
    "PlanetScaleMySQL": "driver",
    "PlanetScalePostgres": "driver",
    "Polar": "request",
    "Postgres": "driver",
    "ProofpointTap": "cursor",
    "RedditAds": "database",
    "Redshift": "driver",
    "SFTP": "config",
    "Salesforce": "database",
    "Sanity": "request",
    "Slack": "config",
    "SnapchatAds": "database",
    "Snowflake": "driver",
    "Supabase": "driver",
    "TemporalIO": "driver",
    "TikTokAds": "database",
    "Trino": "config",
    "TwitterAds": "database",
    "YouTubeAnalytics": "database",
    "Zero": "request",
}

# Sources that reject an unknown schema before any request, but whose error does not name the schema.
# A person who reads the sync error cannot see which table failed. Each entry is a message to fix.
UNKNOWN_SCHEMA_MESSAGE_WITHOUT_NAME = {
    "Arcade",
    "AwsComputeOptimizer",
    "AzureApplicationInsights",
    "Calendarific",
    "Criteo",
    "Embrace",
    "Fintoc",
    "Neo4j",
    "NoaaCdo",
    "SodaCloud",
    "UsTreasuryFiscalData",
}


# Sources that treat `names=[]` like `names=None` and return every schema. Each entry is a defect to fix.
EMPTY_NAMES_RETURNS_ALL_SCHEMAS = {"Fillout", "LlamaCloud", "RedditAds", "Salesforce", "Sentry", "Typeform"}


@frozen
class SchemaListing:
    status: str
    config: Any = None
    names: tuple[str, ...] = ()


def _list_schemas(source: _BaseSource[Any]) -> SchemaListing:
    if native_driver(source) is not None:
        return SchemaListing(status="driver")

    # A source can hide schemas until an optional field is set, so the config that lists the most schemas
    # is the one that exercises the filter on all of them.
    best: SchemaListing | None = None
    reasons: set[str] = set()
    for config in placeholder_configs(source._config_class):
        names: tuple[str, ...] = ()
        with scripted_network([]) as network:
            try:
                names = tuple(schema.name for schema in source.get_schemas(config, team_id=TEAM_ID))
            except Exception:
                reasons.add("config")
        if network.requests_log:
            reasons.add("network")
        elif network.blocked_database_reads:
            reasons.add("database")
        elif names:
            if best is None or len(names) > len(best.names):
                best = SchemaListing(status=PASS, config=config, names=names)
        else:
            reasons.add("empty")
    if best is not None:
        return best
    return SchemaListing(status=next((r for r in ("network", "database", "config", "empty") if r in reasons), "none"))


def _filtered(source: _BaseSource[Any], config: Any, names: list[str]) -> tuple[list[str], int]:
    with scripted_network([]) as network:
        result = [schema.name for schema in source.get_schemas(config, team_id=TEAM_ID, names=names)]
    return result, len(network.requests_log)


def _unknown_schema_status(source: _BaseSource[Any]) -> str:
    if native_driver(source) is not None:
        return "driver"

    statuses: set[str] = set()
    for config in placeholder_configs(source._config_class):
        result = SourceDriver(source, config).run(UNKNOWN_SCHEMA, [])
        if result.requests:
            statuses.add("request")
        elif result.raised is None:
            statuses.add("accepted")
        elif isinstance(result.raised, DatabaseBlockedError):
            statuses.add("database")
        elif UNKNOWN_SCHEMA not in str(result.raised):
            statuses.add("unnamed")
        else:
            return PASS
    return next((s for s in ("unnamed", "database", "request", "accepted") if s in statuses), "none")


@pytest.mark.parametrize("name", LISTING_SOURCE_NAMES, ids=str)
def test_get_schemas_returns_only_the_named_schemas(name: str) -> None:
    source = ALL_SOURCES[name]
    listing = _list_schemas(source)
    if name in SCHEMA_FILTER_NOT_CHECKABLE:
        assert listing.status != PASS, f"{name} passes now. Remove it from SCHEMA_FILTER_NOT_CHECKABLE."
        return
    assert listing.status == PASS, (
        f"{name}: get_schemas on a placeholder config gives `{listing.status}`. Make the schema list "
        "static, or add the source to SCHEMA_FILTER_NOT_CHECKABLE with the reason."
    )

    first, last = listing.names[0], listing.names[-1]
    samples = list(dict.fromkeys([first, last]))
    for sample in samples:
        assert _filtered(source, listing.config, [sample]) == ([sample], 0)
    assert _filtered(source, listing.config, samples) == (samples, 0)
    assert _filtered(source, listing.config, [UNKNOWN_SCHEMA]) == ([], 0)
    assert _filtered(source, listing.config, [first, UNKNOWN_SCHEMA]) == ([first], 0)

    empty, requests = _filtered(source, listing.config, [])
    assert requests == 0
    if name in EMPTY_NAMES_RETURNS_ALL_SCHEMAS:
        assert empty != [], f"{name} passes now. Remove it from EMPTY_NAMES_RETURNS_ALL_SCHEMAS."
    else:
        assert empty == [], f"{name}: get_schemas(names=[]) returns {empty}. An empty list names no schema."


@pytest.mark.parametrize("name", EXTRACTING_SOURCE_NAMES, ids=str)
def test_unknown_schema_fails_before_any_request(name: str) -> None:
    status = _unknown_schema_status(ALL_SOURCES[name])
    if name in UNKNOWN_SCHEMA_NOT_CHECKABLE:
        assert status != PASS, f"{name} passes now. Remove it from UNKNOWN_SCHEMA_NOT_CHECKABLE."
        return
    if name in UNKNOWN_SCHEMA_MESSAGE_WITHOUT_NAME:
        assert status == "unnamed", f"{name} gives `{status}`. Remove it from UNKNOWN_SCHEMA_MESSAGE_WITHOUT_NAME."
        return
    assert status == PASS, (
        f"{name}: an extraction for `{UNKNOWN_SCHEMA}` gives `{status}`. It must raise an error that names "
        "the schema, before it sends a request."
    )


@pytest.mark.parametrize(
    ("allowlist", "checked"),
    [
        (set(SCHEMA_FILTER_NOT_CHECKABLE), LISTING_SOURCE_NAMES),
        (set(UNKNOWN_SCHEMA_NOT_CHECKABLE), EXTRACTING_SOURCE_NAMES),
        (EMPTY_NAMES_RETURNS_ALL_SCHEMAS, LISTING_SOURCE_NAMES),
        (UNKNOWN_SCHEMA_MESSAGE_WITHOUT_NAME, EXTRACTING_SOURCE_NAMES),
    ],
    ids=["schema_filter", "unknown_schema", "empty_names", "unknown_schema_message"],
)
def test_allowlists_name_only_checked_sources(allowlist: set[str], checked: list[str]) -> None:
    assert sorted(allowlist - set(checked)) == []
