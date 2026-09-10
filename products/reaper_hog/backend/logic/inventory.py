from collections.abc import Sequence
from datetime import datetime

from posthog.dataclasses import frozen

from products.reaper_hog.backend.facade.enums import ClusterStatus, InventoryStatus
from products.reaper_hog.backend.logic.converge import ClusterDraft
from products.reaper_hog.backend.models import ReaperArtefact, ReaperCluster, ReaperInventory

_VANISHABLE = frozenset(
    {
        ClusterStatus.CANDIDATE,
        ClusterStatus.DEAD,
        ClusterStatus.ALIVE,
        ClusterStatus.UNDECIDED,
        ClusterStatus.DECLINED,
    }
)
_REOPENABLE = frozenset({ClusterStatus.VANISHED})


@frozen
class ScanOutcome:
    created: int
    refreshed: int
    reopened: int
    vanished: int


def upsert_inventory(*, team_id: int, repository: str, scope: str) -> ReaperInventory:
    inventory, _ = ReaperInventory.objects.for_team(team_id).get_or_create(
        team_id=team_id, repository=repository, scope=scope
    )
    return inventory


def begin_scan(inventory: ReaperInventory) -> None:
    inventory.status = InventoryStatus.ACTIVE
    inventory.save(update_fields=["status", "updated_at"])


def abandon_scan(inventory: ReaperInventory) -> None:
    inventory.status = InventoryStatus.IDLE
    inventory.save(update_fields=["status", "updated_at"])


def record_scan(
    inventory: ReaperInventory, drafts: Sequence[ClusterDraft], *, head_sha: str, now: datetime
) -> ScanOutcome:
    team_id = inventory.team_id
    existing = {
        cluster.hash: cluster for cluster in ReaperCluster.objects.for_team(team_id).filter(inventory=inventory)
    }
    created = refreshed = reopened = 0
    seen: set[str] = set()
    for draft in drafts:
        seen.add(draft.hash)
        cluster = existing.get(draft.hash)
        if cluster is None:
            cluster = ReaperCluster.objects.for_team(team_id).create(
                team_id=team_id,
                inventory=inventory,
                hash=draft.hash,
                root_kind=draft.root_kind,
                root=draft.root,
                rank=draft.rank,
                blocked_reason=draft.blocked_reason,
                scouts=list(draft.scouts),
                files=list(draft.files),
                reference_count=draft.reference_count,
                line_count=draft.line_count,
                owner=draft.owner,
                first_seen_at=now,
                last_seen_at=now,
            )
            created += 1
        else:
            files_changed = list(draft.files) != cluster.files
            if cluster.status in _REOPENABLE or (cluster.status == ClusterStatus.DECLINED and files_changed):
                cluster.status = ClusterStatus.CANDIDATE
                reopened += 1
            else:
                refreshed += 1
            cluster.rank = draft.rank
            cluster.blocked_reason = draft.blocked_reason
            cluster.scouts = list(draft.scouts)
            cluster.files = list(draft.files)
            cluster.reference_count = draft.reference_count
            cluster.line_count = draft.line_count
            cluster.owner = draft.owner
            cluster.last_seen_at = now
            cluster.save()
        for hit in draft.hits:
            ReaperArtefact.append(team_id=team_id, inventory_id=inventory.id, cluster_id=cluster.id, content=hit)

    vanished = 0
    for cluster in existing.values():
        if cluster.hash in seen or cluster.status not in _VANISHABLE:
            continue
        cluster.status = ClusterStatus.VANISHED
        cluster.save(update_fields=["status", "updated_at"])
        vanished += 1

    inventory.run_count += 1
    inventory.last_scan_sha = head_sha
    inventory.last_scan_at = now
    inventory.status = InventoryStatus.IDLE
    inventory.save(update_fields=["run_count", "last_scan_sha", "last_scan_at", "status", "updated_at"])
    return ScanOutcome(created=created, refreshed=refreshed, reopened=reopened, vanished=vanished)
