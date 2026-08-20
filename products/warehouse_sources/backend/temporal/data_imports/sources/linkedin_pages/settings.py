from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Synthesised on every statistics row from the element's `timeRange.start`. LinkedIn returns the
# bucket as an epoch-millisecond range rather than a date column, and the range is what the
# `timeIntervals` filter windows on — so this is the only field that can act as a cursor.
STATS_DATE_FIELD = "date"
# Synthesised on every row: the organization URN the row was fetched for. LinkedIn's statistics
# finders don't echo the queried entity back, so without it rows from different pages collide.
ORGANIZATION_FIELD = "organization"
POSTS_CREATED_AT_FIELD = "created_at"


class EndpointKind(StrEnum):
    # Entity lookup, one GET per administered organization.
    ORGANIZATION = "organization"
    # `timeIntervals`-windowed statistics finder — one element per day per organization.
    TIME_SERIES = "time_series"
    # Paginated Rest.li finder (start/count, or a pageToken on newer versions).
    FINDER = "finder"


@dataclass(frozen=True)
class LinkedinPagesEndpointConfig:
    name: str
    kind: EndpointKind
    path: str
    primary_key: list[str]
    # Rest.li finder name, sent as `q=`.
    finder: Optional[str] = None
    # Query param the organization URN is passed as. Rest.li names it after the entity, so it
    # differs per resource (`organization` vs `organizationalEntity` vs `author`).
    urn_param: Optional[str] = None
    partition_key: Optional[str] = None

    def urn_query(self, urn: str) -> dict[str, str]:
        """Finder plus the URN param this resource addresses its organization through."""
        if self.finder is None or self.urn_param is None:
            raise ValueError(f"The {self.name} endpoint is not addressed by an organization URN")
        return {"q": self.finder, self.urn_param: urn}

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        # Only the statistics finders accept a server-side `timeIntervals` filter. Organizations
        # and posts have no updated-since parameter, so they stay full refresh.
        if self.kind is not EndpointKind.TIME_SERIES:
            return []
        return [incremental_field(STATS_DATE_FIELD, IncrementalFieldType.Date)]


LINKEDIN_PAGES_ENDPOINTS: dict[str, LinkedinPagesEndpointConfig] = {
    "organizations": LinkedinPagesEndpointConfig(
        name="organizations",
        kind=EndpointKind.ORGANIZATION,
        path="/organizations",
        primary_key=["id"],
    ),
    "page_statistics": LinkedinPagesEndpointConfig(
        name="page_statistics",
        kind=EndpointKind.TIME_SERIES,
        path="/organizationPageStatistics",
        # One element per (organization, day), so the queried entity has to be part of the key.
        primary_key=[ORGANIZATION_FIELD, STATS_DATE_FIELD],
        finder="organization",
        urn_param="organization",
        partition_key=STATS_DATE_FIELD,
    ),
    "follower_statistics": LinkedinPagesEndpointConfig(
        name="follower_statistics",
        kind=EndpointKind.TIME_SERIES,
        path="/organizationalEntityFollowerStatistics",
        primary_key=[ORGANIZATION_FIELD, STATS_DATE_FIELD],
        finder="organizationalEntity",
        urn_param="organizationalEntity",
        partition_key=STATS_DATE_FIELD,
    ),
    "share_statistics": LinkedinPagesEndpointConfig(
        name="share_statistics",
        kind=EndpointKind.TIME_SERIES,
        path="/organizationalEntityShareStatistics",
        primary_key=[ORGANIZATION_FIELD, STATS_DATE_FIELD],
        finder="organizationalEntity",
        urn_param="organizationalEntity",
        partition_key=STATS_DATE_FIELD,
    ),
    "posts": LinkedinPagesEndpointConfig(
        name="posts",
        kind=EndpointKind.FINDER,
        path="/posts",
        # Post URNs (`urn:li:share:…` / `urn:li:ugcPost:…`) are globally unique.
        primary_key=["id"],
        finder="author",
        urn_param="author",
        partition_key=POSTS_CREATED_AT_FIELD,
    ),
}

ENDPOINTS = tuple(LINKEDIN_PAGES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LINKEDIN_PAGES_ENDPOINTS.items()
}
