from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every collection's search supports a server-side updated_at gte predicate
# ordered ascending, so the incremental menu is shared.
_UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Searches return only the fields you ask for, so each collection enumerates a
# conservative set of well-documented field_ids (unknown ids 400 the request).
_COMMON_FIELD_IDS = ["identifier", "created_at", "updated_at"]


@dataclass
class CrunchbaseEndpointConfig:
    name: str
    # Collection slug in POST /v4/data/searches/{collection}.
    collection: str
    field_ids: list[str] = field(default_factory=lambda: list(_COMMON_FIELD_IDS))
    primary_key: str = "uuid"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_UPDATED_AT_INCREMENTAL_FIELDS))
    # Every entity carries an immutable created_at.
    partition_key: str = "created_at"


CRUNCHBASE_ENDPOINTS: dict[str, CrunchbaseEndpointConfig] = {
    "organizations": CrunchbaseEndpointConfig(
        name="organizations",
        collection="organizations",
        field_ids=[
            *_COMMON_FIELD_IDS,
            "short_description",
            "website_url",
            "founded_on",
            "categories",
            "location_identifiers",
            "funding_total",
            "num_employees_enum",
            "operating_status",
        ],
    ),
    "people": CrunchbaseEndpointConfig(
        name="people",
        collection="people",
        field_ids=[*_COMMON_FIELD_IDS, "first_name", "last_name"],
    ),
    "funding_rounds": CrunchbaseEndpointConfig(
        name="funding_rounds",
        collection="funding_rounds",
        field_ids=[
            *_COMMON_FIELD_IDS,
            "announced_on",
            "investment_type",
            "money_raised",
            "funded_organization_identifier",
            "num_investors",
        ],
    ),
    "acquisitions": CrunchbaseEndpointConfig(
        name="acquisitions",
        collection="acquisitions",
        field_ids=[*_COMMON_FIELD_IDS, "announced_on", "acquirer_identifier", "acquiree_identifier", "price"],
    ),
    "investments": CrunchbaseEndpointConfig(
        name="investments",
        collection="investments",
        field_ids=[
            *_COMMON_FIELD_IDS,
            "announced_on",
            "investor_identifier",
            "funding_round_identifier",
            "money_invested",
        ],
    ),
    "ipos": CrunchbaseEndpointConfig(
        name="ipos",
        collection="ipos",
        field_ids=[*_COMMON_FIELD_IDS, "went_public_on", "stock_symbol", "money_raised", "valuation"],
    ),
    "funds": CrunchbaseEndpointConfig(
        name="funds",
        collection="funds",
        field_ids=[*_COMMON_FIELD_IDS, "announced_on", "money_raised", "name"],
    ),
}

ENDPOINTS = tuple(CRUNCHBASE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CRUNCHBASE_ENDPOINTS.items() if config.incremental_fields
}
