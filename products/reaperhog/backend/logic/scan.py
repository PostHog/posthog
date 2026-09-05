import logging
from datetime import UTC, datetime
from pathlib import Path

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope

from products.reaperhog.backend.logic.artefacts import Hit, Note
from products.reaperhog.backend.logic.constants import SUMMARY_NOTE_AUTHOR
from products.reaperhog.backend.logic.converge import ClusterDraft, converge
from products.reaperhog.backend.logic.inventory import (
    ScanOutcome,
    abandon_scan,
    begin_scan,
    record_scan,
    upsert_inventory,
)
from products.reaperhog.backend.logic.owners import CODEOWNERS_PATH, OwnerRule, parse_codeowners
from products.reaperhog.backend.logic.repo import RepoIndex
from products.reaperhog.backend.logic.scouts.archaeology import ArchaeologyScout
from products.reaperhog.backend.logic.scouts.base import Scout, ScoutContext
from products.reaperhog.backend.logic.scouts.experiments import ExperimentsScout
from products.reaperhog.backend.logic.scouts.flags import FlagsScout
from products.reaperhog.backend.logic.scouts.scenes import ScenesScout
from products.reaperhog.backend.logic.scouts.static import StaticScout
from products.reaperhog.backend.logic.summary import render_summary
from products.reaperhog.backend.models import ReaperArtefact

logger = logging.getLogger(__name__)

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
    failed_scouts: tuple[str, ...] = ()


def run_scan(request: ScanRequest, *, scouts: tuple[Scout, ...] = SCOUTS) -> ScanResult:
    now = datetime.now(UTC)
    repo = RepoIndex(request.repo_path)
    head_sha = repo.head_sha()
    context = ScoutContext(team_id=request.team_id, repo=repo, scope=request.scope, now=now)

    with team_scope(request.team_id):
        inventory = upsert_inventory(team_id=request.team_id, repository=request.repository, scope=request.scope)
        begin_scan(inventory)

    hits, failed = _run_scouts(scouts, context)
    if failed and len(failed) == len([s for s in scouts if s.applies_to(request.scope)]):
        with team_scope(request.team_id):
            abandon_scan(inventory)
        raise RuntimeError(f"Every scout failed: {', '.join(failed)}")
    drafts = converge(hits, owner_rules=_owner_rules(repo))

    with team_scope(request.team_id):
        outcome = record_scan(inventory, drafts, head_sha=head_sha, now=now)
        note = render_summary(
            repository=request.repository,
            scope=request.scope,
            head_sha=head_sha,
            drafts=drafts,
            outcome=outcome,
            failed_scouts=failed,
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
        failed_scouts=failed,
    )


def _run_scouts(scouts: tuple[Scout, ...], context: ScoutContext) -> tuple[list[Hit], tuple[str, ...]]:
    hits: list[Hit] = []
    failed: list[str] = []
    for scout in scouts:
        if not scout.applies_to(context.scope):
            continue
        try:
            hits += scout.run(context)
        except Exception:
            logger.exception("Scout %s failed; continuing with the others", scout.name)
            failed.append(scout.name.value)
    return hits, tuple(failed)


def _owner_rules(repo: RepoIndex) -> tuple[OwnerRule, ...]:
    path = repo.root / CODEOWNERS_PATH
    if not path.is_file():
        return ()
    return parse_codeowners(path.read_text())
