from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class CodecovEndpointConfig:
    name: str
    path: str  # Path template relative to /{service}/{owner_username}; "{repo}" is filled per repository during fan-out
    incremental_fields: list[IncrementalField]
    primary_keys: list[str]
    default_incremental_field: Optional[str] = None
    # Query param for Codecov's server-side time filter (e.g. `start_date` on the coverage
    # report). None means no server-side filter: incremental endpoints without one scroll
    # newest-first and stop client-side at the watermark instead.
    incremental_server_param: Optional[str] = None
    partition_key: Optional[str] = None  # Stable datetime field (never one that mutates)
    fan_out_over_repos: bool = False
    # Most endpoints are DRF-paginated ({count, next, previous, results}); components
    # returns a bare, unpaginated JSON array.
    paginated: bool = True
    extra_params: dict[str, str] = field(default_factory=dict)


_TIMESTAMP_INCREMENTAL_FIELD: IncrementalField = {
    "label": "timestamp",
    "type": IncrementalFieldType.DateTime,
    "field": "timestamp",
    "field_type": IncrementalFieldType.DateTime,
}


CODECOV_ENDPOINTS: dict[str, CodecovEndpointConfig] = {
    "repos": CodecovEndpointConfig(
        name="repos",
        path="/repos",
        # No server-side time filter and `updatestamp` mutates, so full refresh only.
        incremental_fields=[],
        primary_keys=["name"],
    ),
    "branches": CodecovEndpointConfig(
        name="branches",
        path="/repos/{repo}/branches",
        incremental_fields=[],  # Only name + a mutating updatestamp; full refresh only.
        primary_keys=["repo", "name"],
        fan_out_over_repos=True,
    ),
    "commits": CodecovEndpointConfig(
        name="commits",
        path="/repos/{repo}/commits",
        # The list is returned newest-first with no server-side time filter, so incremental
        # sync scrolls descending and stops once a page predates the watermark.
        incremental_fields=[_TIMESTAMP_INCREMENTAL_FIELD],
        default_incremental_field="timestamp",
        primary_keys=["repo", "commitid"],
        partition_key="timestamp",  # Commit timestamps are immutable.
        fan_out_over_repos=True,
    ),
    "pulls": CodecovEndpointConfig(
        name="pulls",
        path="/repos/{repo}/pulls",
        # `updatestamp` is null on pulls without coverage data and the default order is by
        # pullid, so there is no reliable cursor; state also mutates (open -> merged).
        incremental_fields=[],
        primary_keys=["repo", "pullid"],
        fan_out_over_repos=True,
    ),
    "flags": CodecovEndpointConfig(
        name="flags",
        path="/repos/{repo}/flags",
        incremental_fields=[],  # Point-in-time coverage per flag; no timestamps at all.
        primary_keys=["repo", "flag_name"],
        fan_out_over_repos=True,
    ),
    "components": CodecovEndpointConfig(
        name="components",
        path="/repos/{repo}/components",
        incremental_fields=[],  # Point-in-time coverage per component; no timestamps at all.
        primary_keys=["repo", "component_id"],
        fan_out_over_repos=True,
        paginated=False,
    ),
    "coverage_trend": CodecovEndpointConfig(
        name="coverage_trend",
        path="/repos/{repo}/coverage",
        # Genuine server-side filter: `start_date` bounds the time series (verified: a
        # future cutoff drops all but the carried-forward latest point).
        incremental_fields=[_TIMESTAMP_INCREMENTAL_FIELD],
        default_incremental_field="timestamp",
        incremental_server_param="start_date",
        primary_keys=["repo", "timestamp"],
        fan_out_over_repos=True,
        extra_params={"interval": "1d"},
    ),
}

ENDPOINTS = tuple(CODECOV_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CODECOV_ENDPOINTS.items()
}
