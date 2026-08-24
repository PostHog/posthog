from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class OpenAlexEndpointConfig:
    name: str
    # Path segment of the entity list endpoint, e.g. `/works`.
    path: str
    # Every OpenAlex entity is keyed by its canonical OpenAlex URL, e.g.
    # `https://openalex.org/W3038568908`. Unique across the whole entity type.
    primary_key: str = "id"
    # Date OpenAlex first indexed the record. Stable (unlike `updated_date`, which moves on
    # every metadata revision), so it is safe to partition on.
    partition_key: Optional[str] = "created_date"
    # Name of the source config field holding an optional OpenAlex filter expression that
    # scopes this table. Only set for the entity types too large to sync in full.
    filter_config_field: Optional[str] = None
    # Value passed as `sort=`. Only `works` has a free, time-ordered sort, and it is the only
    # endpoint whose response order we can guarantee.
    sort: Optional[str] = None
    # Rows carry large nested structures (abstracts, reference lists), so batch them tighter
    # than the pipeline default to keep the source-to-Arrow conversion off the memory ceiling.
    large_rows: bool = False


OPENALEX_ENDPOINTS: dict[str, OpenAlexEndpointConfig] = {
    "works": OpenAlexEndpointConfig(
        name="works",
        path="/works",
        filter_config_field="works_filter",
        sort="publication_date",
        large_rows=True,
    ),
    "authors": OpenAlexEndpointConfig(
        name="authors",
        path="/authors",
        filter_config_field="authors_filter",
    ),
    "awards": OpenAlexEndpointConfig(
        name="awards",
        path="/awards",
        filter_config_field="awards_filter",
    ),
    "sources": OpenAlexEndpointConfig(name="sources", path="/sources"),
    "institutions": OpenAlexEndpointConfig(name="institutions", path="/institutions"),
    "publishers": OpenAlexEndpointConfig(name="publishers", path="/publishers"),
    "funders": OpenAlexEndpointConfig(name="funders", path="/funders"),
    "topics": OpenAlexEndpointConfig(name="topics", path="/topics"),
    "keywords": OpenAlexEndpointConfig(name="keywords", path="/keywords"),
    "domains": OpenAlexEndpointConfig(name="domains", path="/domains"),
    "fields": OpenAlexEndpointConfig(name="fields", path="/fields"),
    "subfields": OpenAlexEndpointConfig(name="subfields", path="/subfields"),
    "sdgs": OpenAlexEndpointConfig(name="sdgs", path="/sdgs"),
    "countries": OpenAlexEndpointConfig(name="countries", path="/countries"),
    "continents": OpenAlexEndpointConfig(name="continents", path="/continents"),
    "languages": OpenAlexEndpointConfig(name="languages", path="/languages"),
    "work_types": OpenAlexEndpointConfig(name="work_types", path="/work-types"),
    "source_types": OpenAlexEndpointConfig(name="source_types", path="/source-types"),
    "institution_types": OpenAlexEndpointConfig(name="institution_types", path="/institution-types"),
    "licenses": OpenAlexEndpointConfig(name="licenses", path="/licenses"),
}

ENDPOINTS = tuple(OPENALEX_ENDPOINTS.keys())

# OpenAlex gates its record-modification filters (`from_updated_date`, `from_created_date`) and
# `sort=updated_date` behind a Premium, Institutional or Partner plan — a free key gets
# "Plan upgrade required" back. `from_publication_date` is free, so `works` is the one table
# with a usable server-side timestamp filter. It tracks when a paper was published rather than
# when OpenAlex last revised it, so an incremental run picks up newly published work but not
# late edits to older records; full refresh those when you need the corrections. Incremental
# runs also cap the window at today, because OpenAlex carries future publication dates and one
# of those rows would otherwise checkpoint a watermark nothing can lower again.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "works": [incremental_field("publication_date", IncrementalFieldType.Date)],
}
