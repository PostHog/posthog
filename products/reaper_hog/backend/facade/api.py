from pathlib import Path

from products.reaper_hog.backend.facade import contracts
from products.reaper_hog.backend.logic import scan


def run_scan(request: contracts.ScanRequest) -> contracts.ScanSummary:
    result = scan.run_scan(
        scan.ScanRequest(
            team_id=request.team_id,
            repository=request.repository,
            scope=request.scope,
            repo_path=Path(request.repo_path),
        )
    )
    return contracts.ScanSummary(
        inventory_id=result.inventory_id,
        head_sha=result.head_sha,
        hit_count=result.hit_count,
        cluster_count=len(result.drafts),
        strong_count=sum(1 for draft in result.drafts if draft.strong),
        note=result.note,
    )
