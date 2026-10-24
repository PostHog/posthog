"""Find and repair materialized endpoint versions whose node cadence differs from their declared freshness."""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

from products.data_modeling.backend.facade.api import (
    UnsatisfiableFrequencyError,
    UnsupportedFrequencyTargetError,
    apply_saved_query_frequency_target,
    declared_targets_by_saved_query,
)
from products.endpoints.backend.models import EndpointVersion


@dataclass(frozen=True, kw_only=True)
class FreshnessTargetMismatch:
    version: EndpointVersion
    declared: timedelta
    node_target: timedelta | None  # None when the node carries no target at all


@dataclass(frozen=True, kw_only=True)
class RepairOutcome:
    mismatch: FreshnessTargetMismatch
    nodes_written: int = 0
    refused_reason: str | None = None  # set when the data modeling bounds refuse the declared freshness


def find_freshness_target_mismatches(team_id: int | None = None) -> Iterator[FreshnessTargetMismatch]:
    versions = (
        EndpointVersion.objects.filter(
            endpoint__is_active=True,
            is_active=True,
            saved_query__isnull=False,
            saved_query__is_materialized=True,
        )
        .exclude(saved_query__deleted=True)
        .select_related("saved_query", "endpoint")
        .order_by("endpoint__team_id", "id")
    )
    if team_id is not None:
        versions = versions.filter(endpoint__team_id=team_id)

    by_team: dict[int, list[EndpointVersion]] = defaultdict(list)
    for version in versions:
        by_team[version.endpoint.team_id].append(version)

    for version_team_id, team_versions in by_team.items():
        targets = declared_targets_by_saved_query(version_team_id, [v.saved_query_id for v in team_versions])
        for version in team_versions:
            declared = timedelta(seconds=version.data_freshness_seconds)
            node_target = targets.get(str(version.saved_query_id))
            if node_target != declared:
                yield FreshnessTargetMismatch(version=version, declared=declared, node_target=node_target)


def repair_freshness_target(mismatch: FreshnessTargetMismatch) -> RepairOutcome:
    """Write the declared freshness to the node through the path the endpoint enable uses, then reconcile its DAG."""
    saved_query = mismatch.version.saved_query
    assert saved_query is not None
    try:
        written = apply_saved_query_frequency_target(saved_query, mismatch.declared)
    except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as e:
        return RepairOutcome(mismatch=mismatch, refused_reason=str(e))
    return RepairOutcome(mismatch=mismatch, nodes_written=written)
