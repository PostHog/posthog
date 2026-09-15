from datetime import UTC, datetime
from pathlib import Path

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope

from products.reaper_hog.backend.logic.artefacts import Note
from products.reaper_hog.backend.logic.constants import SUMMARY_NOTE_AUTHOR
from products.reaper_hog.backend.logic.converge import ClusterDraft, converge
from products.reaper_hog.backend.logic.inventory import (
    ScanOutcome,
    abandon_scan,
    begin_scan,
    record_scan,
    upsert_inventory,
)
from products.reaper_hog.backend.logic.owners import CODEOWNERS_PATH, OwnerRule, parse_codeowners
from products.reaper_hog.backend.logic.repo import RepoIndex
from products.reaper_hog.backend.logic.scouts.archaeology import ArchaeologyScout
from products.reaper_hog.backend.logic.scouts.base import Scout, ScoutContext
from products.reaper_hog.backend.logic.scouts.experiments import ExperimentsScout
from products.reaper_hog.backend.logic.scouts.flags import FlagsScout
from products.reaper_hog.backend.logic.scouts.scenes import ScenesScout
from products.reaper_hog.backend.logic.scouts.static import StaticScout
from products.reaper_hog.backend.logic.summary import render_summary
from products.reaper_hog.backend.models import ReaperArtefact

SCOUTS: tuple[Scout, ...] = (FlagsScout(), ExperimentsScout(), ArchaeologyScout(), ScenesScout(), StaticScout())


@frozen
class ScanRequest:
    team_id: int
    repository: str
    scope: str
    repo_path: Path


@frozen
class ScanResult:
    inventory_id: str
    head_sha: str
    hit_count: int
    drafts: tuple[ClusterDraft, ...]
    outcome: ScanOutcome
    note: str


def run_scan(request: ScanRequest, *, scouts: tuple[Scout, ...] = SCOUTS) -> ScanResult:
    now = datetime.now(UTC)
    repo = RepoIndex(request.repo_path)
    head_sha = repo.head_sha()
    context = ScoutContext(team_id=request.team_id, repo=repo, scope=request.scope, now=now)

    with team_scope(request.team_id):
        inventory = upsert_inventory(team_id=request.team_id, repository=request.repository, scope=request.scope)
        begin_scan(inventory)

    try:
        hits = [hit for scout in scouts if scout.applies_to(request.scope) for hit in scout.run(context)]
    except Exception:
        with team_scope(request.team_id):
            abandon_scan(inventory)
        raise
    drafts = converge(hits, owner_rules=_owner_rules(repo))

    with team_scope(request.team_id):
        outcome = record_scan(inventory, drafts, head_sha=head_sha, now=now)
        note = render_summary(
            repository=request.repository, scope=request.scope, head_sha=head_sha, drafts=drafts, outcome=outcome
        )
        ReaperArtefact.append(
            team_id=request.team_id, inventory_id=inventory.id, content=Note(author=SUMMARY_NOTE_AUTHOR, body=note)
        )
    return ScanResult(
        inventory_id=str(inventory.id),
        head_sha=head_sha,
        hit_count=len(hits),
        drafts=tuple(drafts),
        outcome=outcome,
        note=note,
    )


def _owner_rules(repo: RepoIndex) -> tuple[OwnerRule, ...]:
    path = repo.root / CODEOWNERS_PATH
    if not path.is_file():
        return ()
    return parse_codeowners(path.read_text())
