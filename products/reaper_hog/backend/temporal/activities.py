from pathlib import Path

from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.reaper_hog.backend.logic.harvest import (
    HarvestRequest,
    HarvestResult,
    SyncResult,
    dispatch_harvest,
    sync_harvest,
)
from products.reaper_hog.backend.logic.scan import ScanRequest, run_scan
from products.reaper_hog.backend.logic.verification import VerifyRequest, VerifyResult, verify_inventory
from products.reaper_hog.backend.temporal.types import ReapScopeInputs, ScanActivityResult


@activity.defn
@scoped_temporal()
@close_db_connections
async def scan_activity(inputs: ReapScopeInputs) -> ScanActivityResult:
    request = ScanRequest(
        team_id=inputs.team_id, repository=inputs.repository, scope=inputs.scope, repo_path=Path(inputs.repo_path)
    )
    async with Heartbeater():
        result = await database_sync_to_async(run_scan, thread_sensitive=False)(request)
    return ScanActivityResult(
        inventory_id=result.inventory_id,
        head_sha=result.head_sha,
        hit_count=result.hit_count,
        cluster_count=len(result.drafts),
        strong_count=sum(1 for draft in result.drafts if draft.strong),
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def verify_activity(inputs: ReapScopeInputs) -> VerifyResult:
    request = VerifyRequest(
        team_id=inputs.team_id,
        user_id=inputs.user_id,
        repository=inputs.repository,
        scope=inputs.scope,
        branch=inputs.branch,
        max_clusters=inputs.max_clusters,
    )
    async with Heartbeater():
        return await verify_inventory(request)


@activity.defn
@scoped_temporal()
@close_db_connections
async def sync_activity(inputs: ReapScopeInputs) -> SyncResult:
    return await database_sync_to_async(sync_harvest, thread_sensitive=False)(
        team_id=inputs.team_id, repository=inputs.repository, scope=inputs.scope
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def harvest_activity(inputs: ReapScopeInputs) -> HarvestResult:
    request = HarvestRequest(
        team_id=inputs.team_id,
        user_id=inputs.user_id,
        repository=inputs.repository,
        scope=inputs.scope,
        max_prs=inputs.max_prs,
    )
    return await database_sync_to_async(dispatch_harvest, thread_sensitive=False)(request)
