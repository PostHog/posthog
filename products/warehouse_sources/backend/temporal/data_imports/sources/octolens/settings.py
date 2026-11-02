from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Documented maximum page size on the cursor-paginated feeds (1-100, default 20).
PAGE_SIZE = 100


@dataclass(frozen=True)
class OctolensEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Path under `/api/<version>`, e.g. `/mentions`."""
    primary_key: Optional[list[str]]
    """`None` for single-object endpoints, which have no identifier to key on."""
    method: Literal["get", "post"] = "get"
    data_selector: str = "data"
    paginated: bool = False
    """True only for the cursor-paginated feeds (mentions, searches). The other list endpoints document
    no pagination parameters and return the full collection in one response."""
    partition_key: Optional[str] = None
    """A STABLE creation-time field to partition on. `None` disables partitioning."""
    fanout: Optional[DependentEndpointConfig] = None
    """Set for child tables fetched once per row of a parent table."""
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


OCTOLENS_ENDPOINTS: dict[str, OctolensEndpointConfig] = {
    "mentions": OctolensEndpointConfig(
        name="mentions",
        path="/mentions",
        primary_key=["sourceId"],
        method="post",
        paginated=True,
        partition_key="timestamp",
    ),
    "keywords": OctolensEndpointConfig(name="keywords", path="/keywords", primary_key=["id"]),
    "feeds": OctolensEndpointConfig(name="feeds", path="/feeds", primary_key=["id"]),
    "notifications": OctolensEndpointConfig(name="notifications", path="/notifications", primary_key=["id"]),
    "org_members": OctolensEndpointConfig(name="org_members", path="/org/members", primary_key=["id"]),
    "usage": OctolensEndpointConfig(name="usage", path="/org/usage", primary_key=None, data_selector="$"),
    "searches": OctolensEndpointConfig(
        name="searches",
        path="/search",
        primary_key=["searchId"],
        paginated=True,
        partition_key="createdAt",
    ),
    # The list endpoint carries no results, so each search is fetched on its own. A `sourceId` can
    # appear in several searches, so the key includes the search.
    "search_results": OctolensEndpointConfig(
        name="search_results",
        path="/search/{searchId}",
        primary_key=["searchId", "sourceId"],
        data_selector="mentions",
        partition_key="timestamp",
        fanout=DependentEndpointConfig(
            parent_name="searches",
            resolve_param="searchId",
            resolve_field="searchId",
            include_from_parent=["searchId"],
            parent_field_renames={"searchId": "searchId"},
            parent_params={"limit": PAGE_SIZE},
        ),
    ),
}

ENDPOINTS = tuple(OCTOLENS_ENDPOINTS.keys())

# Every table is full refresh.
#
# The only date filter Octolens offers is `filters.startDate` on the mentions feed, and it filters on
# `timestamp` — the time the mention was *posted*, not the time Octolens collected or last changed the
# row. Mention rows are mutable after that post time: `sentiment` is null until scoring finishes, and
# `engaged`/`feedbackRelevant` change as people act on a mention. Octolens also backfills historical
# mentions for a keyword long after the fact. Watermarking on `timestamp` would therefore permanently
# exclude both late-collected old mentions and every later edit to a row already synced, so the feed is
# resynced in full until Octolens exposes an update-aware cursor (an `updatedAt` field or a
# collected-at filter) we can safely watermark on.
#
# The searches feed pages by cursor but has no date filter, and the other endpoints expose neither, so
# they full-refresh regardless.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in OCTOLENS_ENDPOINTS}
