"""Project-wide erasure of derived MCP intent data.

The coordinator owns the write barrier, the durable erasure record and reopening. Physical drain and
purge live in provider modules owned by the layers that write the data. A provider that is absent is
acceptable only while no derived state exists; otherwise erasure stays pending and the project stays frozen.
"""

import importlib
import importlib.util
from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid5

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.clickhouse.workload import Workload
from posthog.models.deletion_targets import DeletionTarget, placement_for
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
    MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
)
from products.mcp_analytics.backend.facade.contracts import (
    IntentErasure,
    IntentErasurePending,
    IntentInvalidationConflict,
)
from products.mcp_analytics.backend.intent_topics.invalidation import _freeze, _locked_barrier
from products.mcp_analytics.backend.models import (
    MCPIntentClusteringRun,
    MCPIntentClusterSnapshot,
    MCPIntentEmbeddingCache,
    MCPIntentErasure,
    MCPIntentTopic,
    MCPSession,
)

ASSIGNMENTS = DeletionTarget(
    data_table=MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
    read_table=MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
    optional=True,
)

_PROVIDER_PACKAGE = "products.mcp_analytics.backend"
# (module, function): each is owned by the layer that writes the data it covers.
WRITERS_DRAINED = ("intent_erasure_writers", "assert_writers_drained")
STORAGE_PURGE = ("intent_erasure_storage", "purge_intent_storage")
ROLLUPS_PURGE = ("intent_erasure_rollups", "purge_rollups_and_caches")


def _handle(operation: MCPIntentErasure) -> IntentErasure:
    return IntentErasure(
        project_id=operation.team_id,
        invalidation_id=operation.pk,
        source_team_ids=tuple(operation.source_team_ids),
        verify_sources=operation.verify_sources,
        completed=operation.completed_at is not None,
    )


def _provider(spec: tuple[str, str]) -> Callable[..., None] | None:
    module_name, function = spec
    qualified = f"{_PROVIDER_PACKAGE}.{module_name}"
    # Only a missing module means "not in this layer". A module that exists but fails to import raises.
    if importlib.util.find_spec(qualified) is None:
        return None
    return getattr(importlib.import_module(qualified), function)


def _run_provider(
    spec: tuple[str, str], *, erasure: IntentErasure, cluster: ClickhouseCluster, has_state: bool
) -> None:
    provider = _provider(spec)
    if provider is None:
        if has_state:
            raise IntentErasurePending(f"{spec[1]} is unavailable while derived intent data exists")
        return
    provider(erasure=erasure, cluster=cluster)


def _assert_writers_drained(*, erasure: IntentErasure, cluster: ClickhouseCluster) -> None:
    # Legacy writers read source intents and write copies later without consulting the barrier, so empty
    # stores prove nothing about them. Drain proof is required even when no derived data exists yet.
    provider = _provider(WRITERS_DRAINED)
    if provider is None:
        raise IntentErasurePending("Intent writer drain cannot be proved in this layer")
    provider(erasure=erasure, cluster=cluster)


def _pg_state_exists(team_id: int) -> bool:
    with team_scope(team_id, canonical=True):
        return (
            MCPIntentClusteringRun.objects.filter(team_id=team_id).exists()
            or MCPIntentTopic.objects.filter(team_id=team_id).exists()
            # Sessions exist for ordinary MCP traffic; only the copied intent text is derived data.
            or MCPSession.objects.filter(team_id=team_id).exclude(intent__isnull=True).exclude(intent="").exists()
            or MCPIntentClusterSnapshot.objects.filter(team_id=team_id).exclude(clusters={}).exists()
            or MCPIntentEmbeddingCache.objects.filter(team_id=team_id).exists()
        )


def _replica_rows_exist(target: DeletionTarget, *, cluster: ClickhouseCluster, where: str, params: dict) -> bool:
    placement = placement_for(cluster, target)
    if placement is None:
        return False
    query = Query(f"SELECT 1 FROM {settings.CLICKHOUSE_DATABASE}.{target.data_table} WHERE {where} LIMIT 1", params)
    # The cluster workload selector filters hosts; proof must include online and offline replicas.
    results = placement.cluster.map_hosts_by_role(
        query, placement.cluster.shard_role, workload=Workload.DEFAULT
    ).result()
    if not results:
        raise IntentErasurePending(f"No replica could verify {target.data_table}")
    return any(results.values())


def has_state(*, erasure: IntentErasure, cluster: ClickhouseCluster) -> bool:
    """Read-only probe for derived intent data in the stores this layer owns. Never a drain proof.

    Document embeddings belong to the pipeline layer, whose storage provider purges and verifies them.
    """
    if any(_pg_state_exists(team_id) for team_id in erasure.source_team_ids):
        return True
    return _replica_rows_exist(
        ASSIGNMENTS, cluster=cluster, where="team_id IN %(team_ids)s", params={"team_ids": erasure.source_team_ids}
    )


def prepare(
    *,
    source_team_id: int,
    invalidation_id: UUID,
    cluster: ClickhouseCluster,
    scope_fingerprint: str,
    operation_kind: Literal["request", "deletes_job"],
) -> IntentErasure:
    source = Team.objects.select_related("parent_team").filter(pk=source_team_id).first()
    if source is None:
        # The team row is gone, so no barrier can be taken; the writers provider alone must prove it.
        erasure = IntentErasure(
            project_id=source_team_id, invalidation_id=invalidation_id, source_team_ids=(source_team_id,)
        )
        _assert_writers_drained(erasure=erasure, cluster=cluster)
        return erasure
    project = source.parent_team or source
    invalidation_id = uuid5(invalidation_id, str(project.pk))
    with _locked_barrier(project) as barrier:
        if barrier.invalidation_id is not None and barrier.invalidation_id != invalidation_id:
            raise IntentInvalidationConflict("Another intent erasure owns this project")

        operation, _ = MCPIntentErasure.objects.get_or_create(
            pk=invalidation_id,
            team_id=project.pk,
            defaults={
                "source_team_ids": list(
                    Team.objects.filter(Q(pk=project.pk) | Q(parent_team_id=project.pk))
                    .order_by("pk")
                    .values_list("pk", flat=True)
                ),
                "operation_kind": operation_kind,
                "scope_fingerprint": scope_fingerprint,
            },
        )
        if operation.operation_kind != operation_kind:
            raise IntentInvalidationConflict("This token belongs to a different deletion operation")
        if operation.scope_fingerprint != scope_fingerprint:
            raise IntentInvalidationConflict("The deletion scope changed; retry the original operation")
        if operation.completed_at is not None:
            return _handle(operation)
        if barrier.invalidation_id is None:
            _freeze(barrier, invalidation_id)
        erasure = _handle(operation)

    # The freeze is committed before any remote proof or source mutation, including on failure.
    state = has_state(erasure=erasure, cluster=cluster)
    if state:
        _require_source_verification(project, erasure)
    try:
        _assert_writers_drained(erasure=erasure, cluster=cluster)
    except IntentErasurePending:
        _require_source_verification(project, erasure)
        raise
    with _locked_barrier(project) as barrier:
        if barrier.invalidation_id != erasure.invalidation_id:
            raise IntentInvalidationConflict("The erasure no longer owns the project's write barrier")
        MCPIntentErasure.objects.filter(pk=erasure.invalidation_id, team_id=project.pk).update(
            prepared_at=timezone.now()
        )
        return _handle(MCPIntentErasure.objects.get(pk=erasure.invalidation_id, team_id=project.pk))


def _require_source_verification(project: Team, erasure: IntentErasure) -> None:
    with _locked_barrier(project):
        MCPIntentErasure.objects.filter(
            pk=erasure.invalidation_id, team_id=project.pk, completed_at__isnull=True
        ).update(verify_sources=True)


def complete(*, erasure: IntentErasure, cluster: ClickhouseCluster) -> None:
    project = Team.objects.filter(pk=erasure.project_id).first()
    if project is None:
        _assert_writers_drained(erasure=erasure, cluster=cluster)
        return
    failure: Exception | None = None
    with _locked_barrier(project) as barrier:
        operation = MCPIntentErasure.objects.get(pk=erasure.invalidation_id, team_id=project.pk)
        if operation.completed_at is not None:
            return
        if barrier.invalidation_id != erasure.invalidation_id or operation.prepared_at is None:
            raise IntentInvalidationConflict("The erasure has not prepared this project's write barrier")
        if tuple(operation.source_team_ids) != erasure.source_team_ids:
            raise IntentInvalidationConflict("The erasure scope does not match its stored project scope")
        if operation.verify_sources and not erasure.verify_sources:
            raise IntentInvalidationConflict("Prepare this erasure again and verify source deletion before completing")

        # Serialize retries through the purge, so none can delete data after another reopens admission.
        # The freeze was committed by prepare; a remote failure rolls back to that frozen state.
        try:
            with transaction.atomic():
                state = has_state(erasure=erasure, cluster=cluster)
                _assert_writers_drained(erasure=erasure, cluster=cluster)
                _run_provider(STORAGE_PURGE, erasure=erasure, cluster=cluster, has_state=state)
                _run_provider(ROLLUPS_PURGE, erasure=erasure, cluster=cluster, has_state=state)
                for team_id in erasure.source_team_ids:
                    with team_scope(team_id, canonical=True):
                        MCPIntentTopic.objects.filter(team_id=team_id).delete()
                        MCPIntentClusteringRun.objects.filter(team_id=team_id).delete()
                # Trust the providers only after an independent read finds nothing left.
                if has_state(erasure=erasure, cluster=cluster):
                    raise IntentErasurePending("Derived intent copies survived the purge")
                MCPIntentErasure.objects.filter(pk=erasure.invalidation_id, team_id=project.pk).update(
                    completed_at=timezone.now()
                )
                # Reopen without resetting `generation`: stale readers must still see the change.
                barrier.invalidation_id = None
                barrier.frozen_at = None
                barrier.save(update_fields=["invalidation_id", "frozen_at"])
        except Exception as exc:
            # Keep the lock through rollback and latch persistence, so another completion cannot slip between them.
            MCPIntentErasure.objects.filter(pk=erasure.invalidation_id, team_id=project.pk).update(verify_sources=True)
            failure = exc
    if failure is not None:
        raise failure
