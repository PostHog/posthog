from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class VercelEndpointConfig:
    name: str
    # Versioned path on https://api.vercel.com (Vercel pins each resource to its own API version).
    path: str
    # Key in the JSON response body that holds the list of rows (e.g. {"deployments": [...]}).
    response_data_key: str
    primary_key: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param that lower-bounds results by creation time (Unix ms). Only set where Vercel
    # documents a genuine server-side time filter — None means full refresh for this endpoint.
    since_param: Optional[str] = None
    # Team-owned resources require ?teamId=<id> on each request. Endpoints that list resources
    # visible to the token itself (e.g. /v2/teams) are not team-scoped.
    team_scoped: bool = True


# Vercel list endpoints share one pagination model: the response carries a `pagination` object
# with `count`, `next`, and `prev` Unix-ms timestamps; the next page is requested by passing the
# `next` value back as the `until` query param. Rows arrive newest-first (descending by creation
# time), so every SourceResponse here is sort_mode="desc".
VERCEL_ENDPOINTS: dict[str, VercelEndpointConfig] = {
    "deployments": VercelEndpointConfig(
        name="deployments",
        path="/v6/deployments",
        response_data_key="deployments",
        primary_key="uid",
        # /v6/deployments documents `since`/`until` (Unix ms) as a server-side filter on the
        # deployment creation time. `created` is an immutable epoch-ms integer, so it is both the
        # incremental cursor and a stable ordering key.
        since_param="since",
        incremental_fields=[
            {
                "label": "created",
                "type": IncrementalFieldType.Integer,
                "field": "created",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    # The endpoints below are full refresh only: Vercel's public docs describe the `pagination`
    # cursor for them but do not document a server-side creation-time filter, and we have no API
    # credentials to curl-verify one. Marking them incremental would re-page the whole resource
    # every sync at the same API cost as a full refresh, so we ship full refresh until a filter is
    # confirmed against the live API.
    "projects": VercelEndpointConfig(
        name="projects",
        path="/v9/projects",
        response_data_key="projects",
        primary_key="id",
    ),
    "teams": VercelEndpointConfig(
        name="teams",
        path="/v2/teams",
        response_data_key="teams",
        primary_key="id",
        team_scoped=False,
    ),
    "domains": VercelEndpointConfig(
        name="domains",
        path="/v5/domains",
        response_data_key="domains",
        primary_key="id",
    ),
    "aliases": VercelEndpointConfig(
        name="aliases",
        path="/v4/aliases",
        response_data_key="aliases",
        primary_key="uid",
    ),
}

ENDPOINTS = tuple(VERCEL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VERCEL_ENDPOINTS.items()
}
