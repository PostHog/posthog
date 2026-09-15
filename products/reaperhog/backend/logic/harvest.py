import re
import logging
from collections.abc import Sequence
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.reaperhog.backend.facade.enums import ClusterRank, ClusterStatus, RootKind
from products.reaperhog.backend.logic.artefacts import Note, Verdict, VerdictRecord
from products.reaperhog.backend.logic.constants import (
    HARVEST_LABEL,
    HARVEST_NOTE_AUTHOR,
    MAX_FILES_PER_PR,
    MAX_OPEN_REAPER_PRS,
)
from products.reaperhog.backend.logic.github import parse_pr_number, pull_request_state
from products.reaperhog.backend.logic.verification import ClusterView, cluster_view
from products.reaperhog.backend.models import ReaperArtefact, ReaperCluster, ReaperInventory
from products.tasks.backend.facade import api as tasks_facade

logger = logging.getLogger(__name__)

_OPEN_STATUSES = (ClusterStatus.HARVESTING, ClusterStatus.REAPED)
_SLUG = re.compile(r"[^a-z0-9]+")


@frozen
class HarvestPrompt:
    title: str
    description: str


@frozen
class HarvestCandidate:
    view: ClusterView
    verdict: Verdict
    verified_sha: str


@frozen
class HarvestRequest:
    team_id: int
    user_id: int
    repository: str
    scope: str
    max_prs: int = MAX_OPEN_REAPER_PRS


@frozen(frozen=False)
class HarvestResult:
    dispatched: int = 0
    skipped_budget: int = 0
    skipped_size: int = 0
    open_before: int = 0


@frozen(frozen=False)
class SyncResult:
    reaped: int = 0
    buried: int = 0
    declined: int = 0
    returned: int = 0


@frozen
class Selection:
    selected: tuple[HarvestCandidate, ...]
    skipped_budget: int
    skipped_size: int


def pr_size(candidate: HarvestCandidate) -> int:
    return len(candidate.verdict.files_to_delete) + len(candidate.verdict.files_to_edit)


def select_harvest(
    candidates: Sequence[HarvestCandidate], *, open_count: int, max_prs: int = MAX_OPEN_REAPER_PRS
) -> Selection:
    budget = max(0, max_prs - open_count)
    ordered = sorted(candidates, key=lambda c: (c.view.rank != ClusterRank.STRONG, c.view.root))
    selected: list[HarvestCandidate] = []
    skipped_size = 0
    for candidate in ordered:
        if pr_size(candidate) > MAX_FILES_PER_PR:
            skipped_size += 1
            continue
        if len(selected) < budget:
            selected.append(candidate)
    skipped_budget = len(ordered) - skipped_size - len(selected)
    return Selection(selected=tuple(selected), skipped_budget=skipped_budget, skipped_size=skipped_size)


def branch_name(view: ClusterView) -> str:
    return f"reaper/{_SLUG.sub('-', view.root.lower()).strip('-')[:60]}"


def pr_title(view: ClusterView) -> str:
    return f"chore(reaper): remove {view.root_kind.value} {view.root}"


def render_pr_body(candidate: HarvestCandidate) -> str:
    view, verdict = candidate.view, candidate.verdict
    lines = [
        "## Problem",
        "",
        f"`{view.root}` ({view.root_kind.value}) is dead code. Production data says nobody reaches it:",
        "",
    ]
    for hit in view.hits:
        lines.append(f"- **{hit.scout.value}**: {hit.summary}")
        detail = ", ".join(f"{key}={value}" for key, value in hit.evidence.items() if value not in (None, ""))
        if detail:
            lines.append(f"  - {detail}")
    if view.owner:
        lines += ["", f"Owner per CODEOWNERS: {view.owner}"]
    lines += [
        "",
        "## Evidence",
        "",
        f"Verified at `{candidate.verified_sha[:12]}`, confidence `{verdict.confidence.value}`.",
        "",
    ]
    lines.append(verdict.argumentation.strip())
    if verdict.searches:
        lines += ["", "| Search | Command | Hits |", "| --- | --- | --- |"]
        for search in verdict.searches:
            lines.append(f"| {search.purpose} | `{search.command}` | {search.hits} |")
    if verdict.could_not_prove:
        lines += ["", "Open questions for the reviewer:", ""]
        lines += [f"- {item}" for item in verdict.could_not_prove]
    lines += ["", "## Changes", "", verdict.deletion_plan.strip(), ""]
    if verdict.files_to_delete:
        lines.append("Deleted: " + ", ".join(f"`{path}`" for path in verdict.files_to_delete))
    if verdict.files_to_edit:
        lines.append("Edited: " + ", ".join(f"`{path}`" for path in verdict.files_to_edit))
    lines += ["", "## After merge", ""]
    if view.root_kind == RootKind.FLAG:
        lines.append(
            f"- [ ] Archive the flag `{view.root}` in PostHog (archive, do not delete; the evaluation history stays)"
        )
    else:
        lines.append("- [ ] Nothing. The directory is gone.")
    lines += ["", "Opened by ReaperHog. Humans do the burying: this PR is never merged automatically.", ""]
    return "\n".join(lines)


def build_harvest_prompt(candidate: HarvestCandidate) -> HarvestPrompt:
    view, verdict = candidate.view, candidate.verdict
    title = pr_title(view)
    body = render_pr_body(candidate)
    deleted = "\n".join(f"- {path}" for path in verdict.files_to_delete) or "- (none)"
    edited = "\n".join(f"- {path}" for path in verdict.files_to_edit) or "- (none)"
    description = "\n".join(
        [
            f'Remove the dead code behind the {view.root_kind.value} "{view.root}" and open a DRAFT pull request.',
            "Never merge it, never mark it ready for review, never add the stamphog label.",
            "",
            "## Deletion plan (already verified against the codebase)",
            "",
            verdict.deletion_plan.strip(),
            "",
            "Files to delete:",
            deleted,
            "",
            "Files to edit:",
            edited,
            "",
            "## Rules",
            "",
            f"- Work on a new branch named `{branch_name(view)}` off the default branch.",
            "- Apply exactly the plan above. Delete tests that exist only for this root. Remove imports and exports the deletion orphans.",
            "- Do not touch migrations, anything under .github/, CODEOWNERS, dependency manifests or lockfiles, generated files, or public API serializers and URL confs, beyond removing a single reference the plan names.",
            "- Run the checks for every workspace you touched. Python: `hogli test --changed` and `ruff check`. Main frontend: `pnpm --filter=@posthog/frontend typescript:check` and `pnpm --filter=@posthog/frontend lint`. products/desktop: `pnpm typecheck`, `pnpm test:vitest` and `pnpm lint` from that directory. Nested workspaces: the nearest package.json scripts.",
            "- If a check fails for a reason the plan did not anticipate, revert everything, do not open a pull request, and end with a note that names the failing command and why. Do not fix tests to make the deletion pass.",
            f'- Commit with the subject "Remove {view.root}".',
            f'- Open a DRAFT pull request titled exactly "{title}" with the label "{HARVEST_LABEL}".',
            "- Use the pull request body below verbatim. If the repository has a pull request template, keep its section headings, put this body under the first section, and fill the other sections with N/A. Append a `## Checks` section listing every command you ran and its result.",
            "",
            "## Pull request body",
            "",
            body,
        ]
    )
    return HarvestPrompt(title=title, description=description)


def load_dead_clusters(*, team_id: int, repository: str, scope: str) -> list[HarvestCandidate]:
    with team_scope(team_id):
        inventory = ReaperInventory.objects.get(team_id=team_id, repository=repository, scope=scope)
        clusters = ReaperCluster.objects.filter(
            inventory=inventory, status=ClusterStatus.DEAD, blocked_reason__isnull=True
        ).order_by("rank", "root")
        candidates: list[HarvestCandidate] = []
        for cluster in clusters:
            latest = cluster.artefacts.filter(type="verdict").order_by("-created_at").first()
            if latest is None:
                continue
            record = VerdictRecord.model_validate_json(latest.content)
            candidates.append(
                HarvestCandidate(view=cluster_view(cluster), verdict=record.verdict, verified_sha=record.head_sha)
            )
        return candidates


def open_pr_count(*, team_id: int, repository: str) -> int:
    with team_scope(team_id):
        return ReaperCluster.objects.filter(
            inventory__repository=repository, status__in=[status.value for status in _OPEN_STATUSES]
        ).count()


def dispatch_harvest(request: HarvestRequest) -> HarvestResult:
    candidates = load_dead_clusters(team_id=request.team_id, repository=request.repository, scope=request.scope)
    open_before = open_pr_count(team_id=request.team_id, repository=request.repository)
    selection = select_harvest(candidates, open_count=open_before, max_prs=request.max_prs)
    result = HarvestResult(
        skipped_budget=selection.skipped_budget, skipped_size=selection.skipped_size, open_before=open_before
    )
    if not selection.selected:
        return result
    team = Team.objects.get(id=request.team_id)
    for candidate in selection.selected:
        prompt = build_harvest_prompt(candidate)
        created = tasks_facade.create_and_run_task(
            team=team,
            title=prompt.title,
            description=prompt.description,
            origin_product=tasks_facade.TaskOriginProduct.REAPERHOG,
            user_id=request.user_id,
            repository=request.repository,
            create_pr=True,
            interaction_origin="reaperhog",
            ai_stage="harvest",
        )
        _mark_harvesting(request.team_id, candidate.view.id, created.task_id)
        result.dispatched += 1
    return result


def _mark_harvesting(team_id: int, cluster_id: UUID, task_id: UUID) -> None:
    with team_scope(team_id):
        cluster = ReaperCluster.objects.get(id=cluster_id, team_id=team_id)
        cluster.task_id = task_id
        cluster.status = ClusterStatus.HARVESTING
        cluster.save(update_fields=["task_id", "status", "updated_at"])
        _note(cluster, f"Harvest task {task_id} dispatched")


def sync_harvest(*, team_id: int, repository: str, scope: str) -> SyncResult:
    result = SyncResult()
    with team_scope(team_id):
        inventory = ReaperInventory.objects.get(team_id=team_id, repository=repository, scope=scope)
        harvesting = list(ReaperCluster.objects.filter(inventory=inventory, status=ClusterStatus.HARVESTING))
        runs = tasks_facade.get_latest_run_by_task([c.task_id for c in harvesting if c.task_id])
        for cluster in harvesting:
            run = runs.get(str(cluster.task_id)) if cluster.task_id else None
            if run is None:
                continue
            if run.pr_url and run.pr_url.startswith("https://github.com/"):
                cluster.pr_url = run.pr_url
                cluster.pr_number = parse_pr_number(run.pr_url)
                cluster.status = ClusterStatus.REAPED
                cluster.save(update_fields=["pr_url", "pr_number", "status", "updated_at"])
                _note(cluster, f"Pull request opened: {run.pr_url}")
                result.reaped += 1
            elif run.is_terminal:
                cluster.status = ClusterStatus.UNDECIDED
                cluster.save(update_fields=["status", "updated_at"])
                _note(cluster, f"Harvest run ended without a pull request (status {run.status})")
                result.returned += 1
        for cluster in ReaperCluster.objects.filter(inventory=inventory, status=ClusterStatus.REAPED):
            if cluster.pr_number is None:
                continue
            state = pull_request_state(team_id=team_id, repository=repository, number=cluster.pr_number)
            if state.state == "merged":
                cluster.status = ClusterStatus.BURIED
                result.buried += 1
            elif state.state == "closed":
                cluster.status = ClusterStatus.DECLINED
                result.declined += 1
            else:
                continue
            cluster.save(update_fields=["status", "updated_at"])
            _note(cluster, f"Pull request #{cluster.pr_number} {state.state}")
    return result


def _note(cluster: ReaperCluster, body: str) -> None:
    ReaperArtefact.append(
        team_id=cluster.team_id,
        inventory_id=cluster.inventory_id,
        cluster_id=cluster.id,
        content=Note(author=HARVEST_NOTE_AUTHOR, body=body),
    )


def render_harvest_summary(result: HarvestResult) -> str:
    return (
        f"Harvest: {result.dispatched} pull request task(s) dispatched "
        f"({result.open_before} already open, {result.skipped_budget} held for budget, {result.skipped_size} too big).\n"
    )


def render_sync_summary(result: SyncResult) -> str:
    return (
        f"Sync: {result.reaped} opened, {result.buried} merged, {result.declined} closed, "
        f"{result.returned} ended without a pull request.\n"
    )
