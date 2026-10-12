from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField


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
# The other four endpoints expose no date filter and no pagination, so they full-refresh in a single
# request each regardless.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in OCTOLENS_ENDPOINTS}
