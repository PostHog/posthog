from dataclasses import field
from enum import StrEnum
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Codecov returns only the top level of the tree unless `depth` asks for more, and no real
# repository nests source files deeper than this.
REPORT_TREE_DEPTH = 100


class CodecovResponseShape(StrEnum):
    """How an endpoint's response body maps onto warehouse rows."""

    PAGINATED_LIST = "paginated_list"  # DRF envelope: {count, next, previous, results}
    BARE_LIST = "bare_list"  # plain JSON array, one row per entry
    TOTALS = "totals"  # coverage report object, flattened to a single totals row
    REPORT_FILES = "report_files"  # coverage report object, one row per entry in `files`
    TREE = "tree"  # nested directory tree, one row per node at any depth


@frozen
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
    response_shape: CodecovResponseShape = CodecovResponseShape.PAGINATED_LIST
    # The repository allow-list has no server-side equivalent, so the endpoint that lists
    # repositories applies it client-side. Endpoints that fan out already only visit the
    # allowed repositories, and owner-level endpoints are not repository-scoped at all.
    filtered_by_repository_allow_list: bool = False
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
        filtered_by_repository_allow_list=True,
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
        response_shape=CodecovResponseShape.BARE_LIST,
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
    "repo_totals": CodecovEndpointConfig(
        name="repo_totals",
        path="/repos/{repo}/totals",
        # Coverage of the default branch head as it stands right now; the response carries no
        # timestamp to filter or order on.
        incremental_fields=[],
        primary_keys=["repo"],
        fan_out_over_repos=True,
        response_shape=CodecovResponseShape.TOTALS,
    ),
    "report_files": CodecovEndpointConfig(
        name="report_files",
        path="/repos/{repo}/report",
        incremental_fields=[],  # Same point-in-time report as repo_totals, at file grain.
        primary_keys=["repo", "name"],
        fan_out_over_repos=True,
        response_shape=CodecovResponseShape.REPORT_FILES,
    ),
    "report_tree": CodecovEndpointConfig(
        name="report_tree",
        path="/repos/{repo}/report/tree",
        incremental_fields=[],  # Same point-in-time report as repo_totals, at directory grain.
        primary_keys=["repo", "full_path"],
        fan_out_over_repos=True,
        response_shape=CodecovResponseShape.TREE,
        extra_params={"depth": str(REPORT_TREE_DEPTH)},
    ),
    "test_results": CodecovEndpointConfig(
        name="test_results",
        path="/repos/{repo}/test-results",
        # `timestamp` never moves, but the endpoint filters only on branch, commit and
        # duration and exposes no ordering param, so there is nothing to sync incrementally
        # against.
        incremental_fields=[],
        primary_keys=["repo", "test_id", "commit_sha", "timestamp"],
        partition_key="timestamp",
        fan_out_over_repos=True,
    ),
    "users": CodecovEndpointConfig(
        name="users",
        path="/users",
        incremental_fields=[],  # Membership state only; no timestamps at all.
        primary_keys=["username"],
    ),
}

ENDPOINTS = tuple(CODECOV_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CODECOV_ENDPOINTS.items()
}
