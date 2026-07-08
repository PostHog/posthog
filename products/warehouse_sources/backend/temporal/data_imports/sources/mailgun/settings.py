from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["paging", "skip"]


@dataclass
class MailgunEndpointConfig:
    name: str
    # Path relative to the regional API host. Contains a `{domain}` placeholder for
    # domain-scoped endpoints, which fan out over every sending domain on the account.
    path: str
    domain_scoped: bool = False
    # "paging" endpoints return opaque next/previous URLs in a `paging` object and
    # terminate with an empty `items` page; "skip" endpoints use limit/skip offsets.
    pagination: PaginationStyle = "paging"
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    partition_format: Optional[PartitionFormat] = None


# Only the Events API exposes a server-side timestamp filter (`begin`/`end` epoch seconds
# with `ascending=yes`), so it's the only endpoint advertised as incremental. Domains,
# suppressions, mailing lists, tags, and templates have no updated-at filter — full
# refresh only. Domain-scoped rows get a `domain` column injected so primary keys stay
# unique across domains.
MAILGUN_ENDPOINTS: dict[str, MailgunEndpointConfig] = {
    "domains": MailgunEndpointConfig(
        name="domains",
        path="/v4/domains",
        pagination="skip",
        page_size=1000,
        primary_keys=["id"],
    ),
    "events": MailgunEndpointConfig(
        name="events",
        path="/v3/{domain}/events",
        domain_scoped=True,
        # Events API caps pages at 300 items.
        page_size=300,
        primary_keys=["domain", "id"],
        partition_key="timestamp",
        partition_format="day",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "bounces": MailgunEndpointConfig(
        name="bounces",
        path="/v3/{domain}/bounces",
        domain_scoped=True,
        page_size=1000,
        primary_keys=["domain", "address"],
        partition_key="created_at",
        partition_format="month",
    ),
    "complaints": MailgunEndpointConfig(
        name="complaints",
        path="/v3/{domain}/complaints",
        domain_scoped=True,
        page_size=1000,
        primary_keys=["domain", "address"],
        partition_key="created_at",
        partition_format="month",
    ),
    "unsubscribes": MailgunEndpointConfig(
        name="unsubscribes",
        path="/v3/{domain}/unsubscribes",
        domain_scoped=True,
        page_size=1000,
        primary_keys=["domain", "address"],
        partition_key="created_at",
        partition_format="month",
    ),
    "mailing_lists": MailgunEndpointConfig(
        name="mailing_lists",
        path="/v3/lists/pages",
        page_size=100,
        primary_keys=["address"],
    ),
    "tags": MailgunEndpointConfig(
        name="tags",
        path="/v3/{domain}/tags",
        domain_scoped=True,
        page_size=100,
        primary_keys=["domain", "tag"],
    ),
    "templates": MailgunEndpointConfig(
        name="templates",
        path="/v3/{domain}/templates",
        domain_scoped=True,
        page_size=100,
        # Template names are unique per domain; list items aren't guaranteed an `id`.
        primary_keys=["domain", "name"],
    ),
}

ENDPOINTS = tuple(MAILGUN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILGUN_ENDPOINTS.items() if config.incremental_fields
}
