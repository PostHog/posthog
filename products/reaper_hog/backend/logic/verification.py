import json
import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.reaper_hog.backend.facade.enums import ClusterRank, ClusterStatus, Confidence, RootKind
from products.reaper_hog.backend.logic.artefacts import Hit, Verdict, VerdictRecord
from products.reaper_hog.backend.logic.constants import (
    MAX_VERIFICATIONS_PER_RUN,
    VERIFICATION_INITIAL_PERMISSION_MODE,
    VERIFICATION_MODEL,
    VERIFICATION_REASONING_EFFORT,
    VERIFICATION_RUNTIME_ADAPTER,
)
from products.reaper_hog.backend.logic.sandbox import MultiTurnSession, continue_session, end_session, start_session
from products.reaper_hog.backend.logic.skill import PinnedSkill, sync_verification_skill
from products.reaper_hog.backend.models import ReaperArtefact, ReaperCluster, ReaperInventory

logger = logging.getLogger(__name__)

VERIFICATION_SYSTEM_PROMPT = """You are verifying whether a candidate root in this repository is dead code.
Investigate the codebase with rg and by reading files. DO NOT delete or edit anything, ONLY assess.
Return ONLY valid JSON output that conforms to the provided schema."""

_HARD_FLOORS = (
    "migrations, anything under .github/, CODEOWNERS, dependency manifests and lockfiles, generated files, "
    "and public API serializers or URL confs must never appear in files_to_delete"
)


@frozen
class ClusterView:
    id: UUID
    hash: str
    root_kind: RootKind
    root: str
    rank: ClusterRank
    files: tuple[str, ...]
    hits: tuple[Hit, ...]


@frozen
class VerifyRequest:
    team_id: int
    user_id: int
    repository: str
    scope: str
    branch: str = "master"
    max_clusters: int = MAX_VERIFICATIONS_PER_RUN


@frozen(frozen=False)
class VerifyResult:
    verified: int = 0
    dead: int = 0
    alive: int = 0
    undecided: int = 0
    failed: int = 0
    skipped_reason: str | None = None


def status_for(verdict: Verdict) -> ClusterStatus:
    if not verdict.is_dead:
        return ClusterStatus.ALIVE
    if verdict.confidence == Confidence.HIGH:
        return ClusterStatus.DEAD
    return ClusterStatus.UNDECIDED


def build_verification_prompt(view: ClusterView, skill: PinnedSkill) -> str:
    return "\n\n".join(
        [
            _cluster_block(view),
            "<instructions>\n"
            "Decide whether this root is dead. Verification is always repository-wide: the scouts may have "
            "scanned one directory, but a reference anywhere in the repository keeps the root alive.\n\n"
            "The scout evidence above comes from production data (flag evaluations, experiment outcomes, commit "
            "history). Treat it as the reason this root is a candidate, not as proof. Your job is the code side: "
            "prove that nothing reachable at runtime still depends on the root, or show what does.\n\n"
            "Run every search the criteria skill requires with rg from the repository root and record each one in "
            f"`searches`. {_HARD_FLOORS}. DO NOT implement the deletion, ONLY assess.\n"
            "</instructions>",
            _skill_block(skill),
            _schema_block(),
        ]
    )


def build_verification_followup_prompt(view: ClusterView) -> str:
    return "\n\n".join(
        [
            _cluster_block(view),
            "Now verify the NEXT candidate root above. Apply the exact same criteria you already loaded (do not "
            "re-fetch the skill), run the required searches again for this root, and DO NOT implement anything.",
            _schema_block(),
        ]
    )


def _cluster_block(view: ClusterView) -> str:
    hits = [
        {"scout": hit.scout.value, "summary": hit.summary, "decisive": hit.decisive, "evidence": hit.evidence}
        for hit in view.hits
    ]
    payload = {
        "root_kind": view.root_kind.value,
        "root": view.root,
        "rank": view.rank.value,
        "files_with_references": list(view.files),
        "scout_hits": hits,
    }
    return f"<candidate_root>\n{json.dumps(payload, indent=2)}\n</candidate_root>"


def _skill_block(skill: PinnedSkill) -> str:
    return (
        "<your_verification_criteria>\n"
        "The bar for calling a root dead lives in a skill you MUST read before judging. As your first step, call "
        "this over the PostHog MCP:\n\n"
        f'    skill-get(skill_name="{skill.name}", version={skill.version})\n\n'
        f"Pin to version {skill.version} explicitly. Apply it as the standard for `is_dead` and `confidence`. "
        "Do not decide before you have read it.\n"
        "</your_verification_criteria>"
    )


def _schema_block() -> str:
    schema = json.dumps(Verdict.model_json_schema(), indent=2)
    return (
        "<output_format>\nReturn ONLY a JSON object conforming to this schema (no markdown fences, no prose):\n\n"
        f"{schema}\n</output_format>"
    )


def load_candidates(
    *, team_id: int, repository: str, scope: str, limit: int
) -> tuple[ReaperInventory, list[ClusterView]]:
    with team_scope(team_id):
        inventory = ReaperInventory.objects.get(team_id=team_id, repository=repository, scope=scope)
        clusters = list(
            ReaperCluster.objects.filter(
                inventory=inventory, status=ClusterStatus.CANDIDATE, blocked_reason__isnull=True
            ).order_by("rank", "root")[:limit]
        )
        views = [cluster_view(cluster) for cluster in clusters]
    return inventory, views


def cluster_view(cluster: ReaperCluster) -> ClusterView:
    latest_by_scout: dict[str, Hit] = {}
    for artefact in cluster.artefacts.filter(type="hit").order_by("created_at"):
        hit = Hit.model_validate_json(artefact.content)
        latest_by_scout[hit.scout.value] = hit
    return ClusterView(
        id=cluster.id,
        hash=cluster.hash,
        root_kind=RootKind(cluster.root_kind),
        root=cluster.root,
        rank=ClusterRank(cluster.rank),
        files=tuple(cluster.files),
        hits=tuple(latest_by_scout[scout] for scout in sorted(latest_by_scout)),
    )


def persist_verdict(*, team_id: int, cluster_id: UUID, head_sha: str, verdict: Verdict) -> ClusterStatus:
    with team_scope(team_id):
        cluster = ReaperCluster.objects.get(id=cluster_id)
        ReaperArtefact.append(
            team_id=team_id,
            inventory_id=cluster.inventory_id,
            cluster_id=cluster.id,
            content=VerdictRecord(head_sha=head_sha, model=VERIFICATION_MODEL, verdict=verdict),
        )
        cluster.status = status_for(verdict)
        cluster.verified_at = datetime.now(UTC)
        cluster.verified_sha = head_sha
        cluster.save(update_fields=["status", "verified_at", "verified_sha", "updated_at"])
        return ClusterStatus(cluster.status)


def _pin_skill(team_id: int) -> PinnedSkill:
    with team_scope(team_id):
        return sync_verification_skill(team_id)


async def verify_inventory(request: VerifyRequest) -> VerifyResult:
    inventory, views = await database_sync_to_async(load_candidates, thread_sensitive=False)(
        team_id=request.team_id, repository=request.repository, scope=request.scope, limit=request.max_clusters
    )
    if not views:
        return VerifyResult(skipped_reason="no_candidates")
    head_sha = inventory.last_scan_sha or ""
    skill = await database_sync_to_async(_pin_skill, thread_sensitive=False)(request.team_id)
    result = VerifyResult()
    session: MultiTurnSession | None = None
    clean = False
    try:
        for view in views:
            try:
                if session is None:
                    session, verdict = await start_session(
                        team_id=request.team_id,
                        user_id=request.user_id,
                        repository=request.repository,
                        branch=request.branch,
                        prompt=build_verification_prompt(view, skill),
                        system_prompt=VERIFICATION_SYSTEM_PROMPT,
                        model_to_validate=Verdict,
                        step_name="reaper-verify",
                        runtime_adapter=VERIFICATION_RUNTIME_ADAPTER,
                        model=VERIFICATION_MODEL,
                        reasoning_effort=VERIFICATION_REASONING_EFFORT,
                        initial_permission_mode=VERIFICATION_INITIAL_PERMISSION_MODE,
                    )
                else:
                    verdict = await continue_session(
                        session,
                        prompt=build_verification_followup_prompt(view),
                        model_to_validate=Verdict,
                        label=view.root,
                    )
            except Exception:
                logger.exception("Verification turn failed for %s; continuing with a fresh session", view.root)
                result.failed += 1
                if session is not None:
                    await end_session(session, status="failed", error=f"verification turn failed for {view.root}")
                    session = None
                continue
            status = await database_sync_to_async(persist_verdict, thread_sensitive=False)(
                team_id=request.team_id, cluster_id=view.id, head_sha=head_sha, verdict=verdict
            )
            result.verified += 1
            _count(result, status)
        clean = True
    finally:
        if session is not None:
            await end_session(
                session,
                status="completed" if clean else "failed",
                error=None if clean else "verification run failed mid-session",
            )
    return result


def _count(result: VerifyResult, status: ClusterStatus) -> None:
    if status == ClusterStatus.DEAD:
        result.dead += 1
    elif status == ClusterStatus.ALIVE:
        result.alive += 1
    else:
        result.undecided += 1


def run_verification(request: VerifyRequest) -> VerifyResult:
    return asyncio.run(verify_inventory(request))


def render_verification_summary(request: VerifyRequest, result: VerifyResult) -> str:
    if result.skipped_reason:
        return f"Verification skipped: {result.skipped_reason}\n"
    return (
        f"Verified {result.verified} cluster(s) in {request.repository} (scope `{request.scope}`): "
        f"{result.dead} dead, {result.alive} alive, {result.undecided} undecided, {result.failed} failed.\n"
    )
