from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class OctolensEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Path under `/api/<version>`, e.g. `/mentions`."""
    primary_key: list[str]
    method: Literal["get", "post"] = "get"
    data_selector: str = "data"
    paginated: bool = False
    """True only for the cursor-paginated mentions feed. The dimension endpoints document no
    pagination parameters and return the full collection in one response."""
    partition_key: Optional[str] = None
    """A STABLE creation-time field to partition on. `None` disables partitioning."""
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Only the mentions feed accepts a server-side date filter (`filters.startDate` on the POST body),
# so it is the one incremental table. Keywords, feeds, notifications and members expose no date
# filter and no pagination, so they full-refresh in a single request each.
MENTIONS_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.DateTime,
        "field": "timestamp",
        "field_type": IncrementalFieldType.DateTime,
    },
]

OCTOLENS_ENDPOINTS: dict[str, OctolensEndpointConfig] = {
    "mentions": OctolensEndpointConfig(
        name="mentions",
        path="/mentions",
        primary_key=["sourceId"],
        method="post",
        paginated=True,
        partition_key="timestamp",
        incremental_fields=MENTIONS_INCREMENTAL_FIELDS,
    ),
    "keywords": OctolensEndpointConfig(name="keywords", path="/keywords", primary_key=["id"]),
    "feeds": OctolensEndpointConfig(name="feeds", path="/feeds", primary_key=["id"]),
    "notifications": OctolensEndpointConfig(name="notifications", path="/notifications", primary_key=["id"]),
    "org_members": OctolensEndpointConfig(name="org_members", path="/org/members", primary_key=["id"]),
}

ENDPOINTS = tuple(OCTOLENS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OCTOLENS_ENDPOINTS.items() if config.incremental_fields
}
