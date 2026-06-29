"""Temporal activities for the single-turn ReviewHog PR review.

Each activity wraps one stage of the former `run.py main()` pipeline. Inputs carry only small,
serializable values — `(team_id, user_id, report_id, head_sha, repository, branch)` plus unit keys
or JSON-encoded issue slices — and every activity that needs the PR's metadata / comments / files
reloads them from the `pr_snapshot` artefact by `(report_id, head_sha)`. Nothing big (pr_files, the
diff, perspective results) ever crosses the workflow boundary, so the Temporal ~2 MiB payload cap is
respected and the sandbox fan-out stays by-reference.

Sandbox-turn activities (chunk / analyze / review / validate / dedup) call `run_sandbox_review`,
which spins a single-turn agent (minutes), so they declare a `heartbeat_timeout` on dispatch and
heartbeat via `Heartbeater()`. ORM access goes through `database_sync_to_async(..., thread_sensitive=
False)`; `@scoped_temporal()` + `@close_db_connections` mirror the Signals report activities.
"""

import logging
from dataclasses import dataclass

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.lazy_seed import sync_canonical_perspectives, sync_canonical_validation
from products.review_hog.backend.reviewer.models import generate_all_schemas
from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuesReview
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.persistence import (
    finalize_review_report,
    load_chunk_analyses,
    load_chunk_set,
    load_perspective_results,
    load_pr_snapshot,
    load_prior_findings,
    persist_chunk_analyses,
    persist_chunk_set,
    persist_commit_snapshot,
    persist_findings,
    persist_perspective_results,
    persist_pr_snapshot,
    persist_verdict,
    upsert_review_report,
)
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review
from products.review_hog.backend.reviewer.skill_loader import load_perspectives_for_run, load_validation_skill_for_run
from products.review_hog.backend.reviewer.tools.chunk_analysis import ANALYSIS_SYSTEM_PROMPT, build_analysis_prompt
from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher
from products.review_hog.backend.reviewer.tools.issue_cleaner import clean_issues
from products.review_hog.backend.reviewer.tools.issue_combination import combine_issues
from products.review_hog.backend.reviewer.tools.issue_deduplicator import deduplicate_issues
from products.review_hog.backend.reviewer.tools.issue_validation import (
    VALIDATION_SYSTEM_PROMPT,
    build_validation_prompt,
)
from products.review_hog.backend.reviewer.tools.issues_review import REVIEW_SYSTEM_PROMPT, build_review_prompt
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import build_review_body
from products.review_hog.backend.reviewer.tools.publish_review import publish_persisted_review
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import (
    CHUNKING_SYSTEM_PROMPT,
    generate_chunking_prompt,
    plan_deterministic_chunks,
)
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = logging.getLogger(__name__)


# --- Inputs / outputs ------------------------------------------------------------------------------


@dataclass
class ValidateIntegrationInput:
    team_id: int


@dataclass
class FetchPRDataInput:
    team_id: int
    user_id: int
    repository: str
    owner: str
    repo: str
    pr_number: int
    pr_url: str


@dataclass
class ReviewMeta:
    """Small fetch result the parent threads through the rest of the run (no big payloads)."""

    report_id: str
    head_sha: str
    branch: str
    repository: str
    # This turn's 1-based index; stamped on each finding so publishing scopes to one turn.
    run_index: int
    snapshotted: bool
    # Already reviewed AND posted this exact head (published_head_sha == head_sha): the parent's
    # early-exit gate skips a dead re-trigger turn. Distinct from `snapshotted` (head moved) because a
    # head can be unchanged yet not-yet-published (a prior no-publish turn) and must still publish.
    already_published: bool
    # New inline comments since the last turn's watermark — logged only for now (they don't force a
    # turn yet; see ARCHITECTURE.md). Will gate the early-exit once ReviewHog reacts to comments.
    new_comment_count: int
    # The PR author's GitHub login (`pr_metadata.author`), so the parent can resolve the acting user
    # whose enabled perspectives this review applies.
    author_login: str


@dataclass
class ResolveActingUserInput:
    team_id: int
    author_login: str
    # CLI/eval override: when set, perspective selection uses this user directly instead of resolving
    # the PR author — the local eval tests a specific user's perspectives against any PR.
    override_user_id: int | None


@dataclass
class ResolveActingUserResult:
    # The user whose enabled perspectives drive this review; None when the PR author maps to no PostHog
    # org user — we apply PostHog-stored skills, so the parent then skips the review.
    acting_user_id: int | None


@dataclass
class LoadPerspectivesInput:
    team_id: int
    acting_user_id: int


@dataclass
class LoadValidationInput:
    team_id: int
    acting_user_id: int


@dataclass
class SyncReviewSkillsInput:
    team_id: int


@dataclass
class GenerateSchemasInput:
    pass


@dataclass
class SandboxStageInput:
    """Shared identity + turn scope for a sandbox-turn activity."""

    team_id: int
    user_id: int
    report_id: str
    head_sha: str
    repository: str
    branch: str
    run_index: int


@dataclass
class AnalyzeChunkInput(SandboxStageInput):
    chunk_id: int


@dataclass
class ReviewChunkInput(SandboxStageInput):
    chunk_id: int
    pass_number: int
    skill_name: str
    skill_version: int


@dataclass
class ValidateIssueInput(SandboxStageInput):
    issue_json: str
    skill_name: str
    skill_version: int


@dataclass
class ValidateIssueResult:
    issue_id: str
    validation_json: str | None


@dataclass
class LoadedPerspectiveDTO:
    pass_number: int
    skill_name: str
    version: int


@dataclass
class LoadedValidationSkillDTO:
    skill_name: str
    version: int


@dataclass
class CombineCleanInput:
    team_id: int
    report_id: str
    head_sha: str


@dataclass
class DedupInput(SandboxStageInput):
    issues_json: list[str]


@dataclass
class DedupResult:
    issues_json: list[str]
    findings_count: int


@dataclass
class BuildBodyInput:
    team_id: int
    report_id: str
    head_sha: str
    issues_json: list[str]
    validations_json: dict[str, str]


@dataclass
class PublishInput:
    team_id: int
    report_id: str
    head_sha: str
    run_index: int
    owner: str
    repo: str
    pr_number: int


# --- Setup activities ------------------------------------------------------------------------------


def _github_integration_exists(team_id: int) -> bool:
    return Integration.objects.filter(team_id=team_id, kind="github").exists()


def _installation_token(team_id: int, repository: str) -> str:
    """Resolve the team's GitHub App installation token for `repository` (`owner/repo`).

    Picks the installation that can actually access the repo and auto-refreshes an expired token.
    This replaces the worker's old `GITHUB_TOKEN` env dependency — the credential is the team's
    integration, resolved server-side.

    `first_for_team_repository` probes the GitHub API, so a transient 5xx/rate-limit looks the same
    as "no installation". The error is therefore left **retryable** (the activity's retry rides out
    the blip); the genuinely-missing-integration case is already caught non-retryably up front by
    `validate_github_integration_activity`, so a real misconfig still fails fast there.
    """
    github = GitHubIntegration.first_for_team_repository(team_id, repository)
    if github is None:
        raise ApplicationError(
            f"Could not resolve a GitHub App installation for team {team_id} that can access {repository} "
            "(no installation, or a transient GitHub API failure)."
        )
    return github.get_access_token()


@activity.defn
@scoped_temporal()
@close_db_connections
async def validate_github_integration_activity(input: ValidateIntegrationInput) -> None:
    """Fail fast (non-retryably) if the team has no GitHub integration the sandbox tasks need."""
    exists = await database_sync_to_async(_github_integration_exists, thread_sensitive=False)(input.team_id)
    if not exists:
        raise ApplicationError(
            f"No GitHub integration found for team {input.team_id}. "
            "Set up a GitHub App installation first (Settings → Integrations).",
            non_retryable=True,
        )


def _fetch_and_persist(input: FetchPRDataInput) -> ReviewMeta:
    """Fetch the PR from GitHub, open/refresh the report, and snapshot this turn's inputs + diff."""
    token = _installation_token(input.team_id, input.repository)
    pr_metadata, pr_comments, pr_files, diff = PRFetcher(
        owner=input.owner, repo=input.repo, pr_number=input.pr_number, token=token
    ).fetch_pr_data()
    if pr_metadata.is_fork:
        raise ApplicationError(
            f"Refusing to review fork PR #{input.pr_number} in {input.repository}: a fork's head ref is "
            "attacker-influenced and its branch isn't on the base origin (the sandbox checkout would fail).",
            non_retryable=True,
        )
    head_sha = pr_metadata.head_sha or ""
    report_id = upsert_review_report(
        team_id=input.team_id, repository=input.repository, pr_url=input.pr_url, pr_metadata=pr_metadata
    )
    # Read the report's watermark BEFORE persist_commit_snapshot advances it, so the parent can decide
    # whether this turn has anything to do. `published_head_sha == head_sha` means we already reviewed
    # and posted this exact head; new comments are surfaced for visibility but don't gate yet.
    report = ReviewReport.objects.for_team(input.team_id).get(id=report_id)
    already_published = bool(head_sha) and report.published_head_sha == head_sha
    # This turn's index. run_count (completed turns) only bumps at finalize, so a turn that fails and
    # resumes reuses the same index while a fresh turn gets a new one.
    run_index = report.run_count + 1
    max_comment_id = max((c.id for c in pr_comments if c.id is not None), default=None)
    new_comment_count = sum(
        1
        for c in pr_comments
        if c.id is not None and (report.last_seen_comment_id is None or c.id > report.last_seen_comment_id)
    )
    if new_comment_count:
        logger.info(
            "PR #%s: %s new inline comment(s) since the last turn (watermark %s, latest %s)",
            pr_metadata.number,
            new_comment_count,
            report.last_seen_comment_id,
            max_comment_id,
        )
    snapshotted = persist_commit_snapshot(
        team_id=input.team_id,
        report_id=report_id,
        repository=input.repository,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        diff=diff,
    )
    persist_pr_snapshot(
        team_id=input.team_id,
        report_id=report_id,
        head_sha=head_sha,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
    )
    return ReviewMeta(
        report_id=report_id,
        head_sha=head_sha,
        branch=pr_metadata.head_branch,
        repository=input.repository,
        run_index=run_index,
        snapshotted=snapshotted,
        already_published=already_published,
        new_comment_count=new_comment_count,
        author_login=pr_metadata.author,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def fetch_pr_data_activity(input: FetchPRDataInput) -> ReviewMeta:
    """Fetch PR data and persist the per-turn `commit` + `pr_snapshot` artefacts; return a small meta.

    The big `pr_files` payload stays in the DB (`pr_snapshot`); downstream stages reload it by
    `(report_id, head_sha)` so it never crosses the workflow boundary.
    """
    return await database_sync_to_async(_fetch_and_persist, thread_sensitive=False)(input)


def _resolve_acting_user(team_id: int, author_login: str, override_user_id: int | None) -> int | None:
    if override_user_id is not None:
        return override_user_id
    matches = resolve_org_github_login_to_users(team_id, [author_login])
    user = matches.get(author_login.strip().lower()) if author_login else None
    return user.id if user is not None else None


@activity.defn
@scoped_temporal()
@close_db_connections
async def resolve_acting_user_activity(input: ResolveActingUserInput) -> ResolveActingUserResult:
    """Resolve the user whose enabled perspectives drive this review.

    Production: the PR author, mapped GitHub-login → PostHog org user (`resolve_org_github_login_to_users`).
    Returns None when the author isn't a PostHog org user — the parent then skips the review (no
    fallback: we apply the author's PostHog-stored perspectives, so the author must be a PostHog user).
    The CLI/eval passes an explicit `override_user_id` to test a known user's perspectives on any PR.
    """
    acting_user_id = await database_sync_to_async(_resolve_acting_user, thread_sensitive=False)(
        input.team_id, input.author_login, input.override_user_id
    )
    return ResolveActingUserResult(acting_user_id=acting_user_id)


def _sync_review_skills(team_id: int) -> None:
    team = Team.objects.get(id=team_id)
    sync_canonical_perspectives(team)
    sync_canonical_validation(team)


@activity.defn
@scoped_temporal()
@close_db_connections
async def sync_review_skills_activity(input: SyncReviewSkillsInput) -> None:
    """Cold-start sync the team's canonical review skills (perspectives + validation criteria).

    Best-effort: a sync failure shouldn't crash the run — the review proceeds with the team's
    existing skills, and the loaders raise a clear error later if one is genuinely missing.
    """
    try:
        await database_sync_to_async(_sync_review_skills, thread_sensitive=False)(input.team_id)
    except Exception:
        logger.exception("Review skill sync failed; continuing with the team's existing review skills")


@activity.defn
@scoped_temporal()
async def generate_schemas_activity(input: GenerateSchemasInput) -> None:
    """Regenerate the prompt output schemas (committed static assets the templates embed).

    Best-effort: on a read-only worker FS the committed schemas are already correct, so a failed
    rewrite shouldn't fail the review.
    """
    try:
        generate_all_schemas()
    except OSError:
        logger.exception("Schema generation failed; using the committed schemas")


# --- Chunking --------------------------------------------------------------------------------------


@activity.defn
@scoped_temporal()
@close_db_connections
async def split_chunks_activity(input: SandboxStageInput) -> list[int]:
    """Split the PR into reviewable chunks (resume-aware); return the chunk ids."""
    existing = await database_sync_to_async(load_chunk_set, thread_sensitive=False)(
        team_id=input.team_id, report_id=input.report_id, head_sha=input.head_sha
    )
    if existing is not None:
        logger.info("Reusing persisted chunk set for this turn")
        return [chunk.chunk_id for chunk in existing.chunks]

    snapshot = await database_sync_to_async(load_pr_snapshot, thread_sensitive=False)(
        team_id=input.team_id, report_id=input.report_id, head_sha=input.head_sha
    )
    if snapshot is None:
        raise ApplicationError("PR snapshot missing for chunking", non_retryable=True)

    # Small PRs are one coherent review unit: skip the chunking LLM turn (and the per-chunk fan-out it
    # would multiply) and use a single deterministic chunk. Only larger PRs reach the semantic chunker.
    planned = plan_deterministic_chunks(snapshot.pr_files)
    if planned is not None:
        logger.info("PR within the single-chunk size; one deterministic chunk, skipping the chunking LLM turn")
        await database_sync_to_async(persist_chunk_set, thread_sensitive=False)(
            team_id=input.team_id, report_id=input.report_id, head_sha=input.head_sha, chunks=planned
        )
        return [chunk.chunk_id for chunk in planned.chunks]

    prompt = generate_chunking_prompt(snapshot.pr_metadata, snapshot.pr_comments, snapshot.pr_files)
    async with Heartbeater():
        chunks = await run_sandbox_review(
            team_id=input.team_id,
            user_id=input.user_id,
            repository=input.repository,
            branch=input.branch,
            prompt=prompt,
            system_prompt=CHUNKING_SYSTEM_PROMPT,
            model_to_validate=ChunksList,
            step_name="chunking",
        )
    await database_sync_to_async(persist_chunk_set, thread_sensitive=False)(
        team_id=input.team_id, report_id=input.report_id, head_sha=input.head_sha, chunks=chunks
    )
    return [chunk.chunk_id for chunk in chunks.chunks]


# --- Analyze (per-chunk fan-out) -------------------------------------------------------------------


def _prepare_analysis_prompt(team_id: int, report_id: str, head_sha: str, chunk_id: int) -> str | None:
    """Build the analysis prompt for one chunk, or None if it's already analysed this turn."""
    if chunk_id in load_chunk_analyses(team_id=team_id, report_id=report_id, head_sha=head_sha):
        return None
    snapshot = load_pr_snapshot(team_id=team_id, report_id=report_id, head_sha=head_sha)
    chunks = load_chunk_set(team_id=team_id, report_id=report_id, head_sha=head_sha)
    if snapshot is None or chunks is None:
        raise ApplicationError("PR snapshot or chunk set missing for analysis", non_retryable=True)
    chunk = next((c for c in chunks.chunks if c.chunk_id == chunk_id), None)
    if chunk is None:
        raise ApplicationError(f"Chunk {chunk_id} not found in chunk set", non_retryable=True)
    return build_analysis_prompt(
        chunk=chunk, pr_metadata=snapshot.pr_metadata, pr_comments=snapshot.pr_comments, pr_files=snapshot.pr_files
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def analyze_chunk_activity(input: AnalyzeChunkInput) -> bool:
    """Analyze one chunk through a sandbox agent and persist it (idempotent; raises on failure so it retries)."""
    prompt = await database_sync_to_async(_prepare_analysis_prompt, thread_sensitive=False)(
        input.team_id, input.report_id, input.head_sha, input.chunk_id
    )
    if prompt is None:
        return True
    async with Heartbeater():
        analysis = await run_sandbox_review(
            team_id=input.team_id,
            user_id=input.user_id,
            repository=input.repository,
            branch=input.branch,
            prompt=prompt,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            model_to_validate=ChunkAnalysis,
            step_name=f"chunk-analysis-{input.chunk_id}",
        )
    await database_sync_to_async(persist_chunk_analyses, thread_sensitive=False)(
        team_id=input.team_id, report_id=input.report_id, head_sha=input.head_sha, analyses={input.chunk_id: analysis}
    )
    return True


# --- Review (perspective × chunk fan-out) ----------------------------------------------------------


def _load_perspectives(team_id: int, acting_user_id: int) -> list[LoadedPerspectiveDTO]:
    return [
        LoadedPerspectiveDTO(pass_number=p.pass_number, skill_name=p.skill_name, version=p.version)
        for p in load_perspectives_for_run(team_id, acting_user_id)
    ]


@activity.defn
@scoped_temporal()
@close_db_connections
async def load_perspectives_activity(input: LoadPerspectivesInput) -> list[LoadedPerspectiveDTO]:
    """Resolve the acting user's enabled perspectives, pinned to their current versions, for this run."""
    return await database_sync_to_async(_load_perspectives, thread_sensitive=False)(input.team_id, input.acting_user_id)


def _prepare_review_prompt(
    team_id: int,
    report_id: str,
    head_sha: str,
    chunk_id: int,
    pass_number: int,
    skill_name: str,
    skill_version: int,
    run_index: int,
) -> str | None:
    """Build the review prompt for one (perspective, chunk), or None if already reviewed this turn."""
    done = load_perspective_results(team_id=team_id, report_id=report_id, head_sha=head_sha)
    if (pass_number, chunk_id) in done:
        return None
    snapshot = load_pr_snapshot(team_id=team_id, report_id=report_id, head_sha=head_sha)
    chunks = load_chunk_set(team_id=team_id, report_id=report_id, head_sha=head_sha)
    if snapshot is None or chunks is None:
        raise ApplicationError("PR snapshot or chunk set missing for review", non_retryable=True)
    chunk = next((c for c in chunks.chunks if c.chunk_id == chunk_id), None)
    if chunk is None:
        raise ApplicationError(f"Chunk {chunk_id} not found in chunk set", non_retryable=True)
    analysis = load_chunk_analyses(team_id=team_id, report_id=report_id, head_sha=head_sha).get(chunk_id)
    prior_findings = load_prior_findings(team_id=team_id, report_id=report_id, before_run_index=run_index)
    return build_review_prompt(
        skill_name=skill_name,
        skill_version=skill_version,
        chunk=chunk,
        analysis=analysis,
        pr_metadata=snapshot.pr_metadata,
        pr_comments=snapshot.pr_comments,
        pr_files=snapshot.pr_files,
        prior_findings=prior_findings,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def review_chunk_activity(input: ReviewChunkInput) -> bool:
    """Review one chunk through one perspective in a sandbox agent and persist it (idempotent)."""
    prompt = await database_sync_to_async(_prepare_review_prompt, thread_sensitive=False)(
        input.team_id,
        input.report_id,
        input.head_sha,
        input.chunk_id,
        input.pass_number,
        input.skill_name,
        input.skill_version,
        input.run_index,
    )
    if prompt is None:
        return True
    async with Heartbeater():
        review = await run_sandbox_review(
            team_id=input.team_id,
            user_id=input.user_id,
            repository=input.repository,
            branch=input.branch,
            prompt=prompt,
            system_prompt=REVIEW_SYSTEM_PROMPT,
            model_to_validate=IssuesReview,
            step_name=f"issues-review-p{input.pass_number}-c{input.chunk_id}",
        )
    # Stamp each issue's perspective (the skill that ran) here, not in combine — it survives the
    # persisted result + resume, and keeps `source_perspective` = skill_name, decoupled from the enum.
    for issue in review.issues:
        issue.source_perspective = input.skill_name
    await database_sync_to_async(persist_perspective_results, thread_sensitive=False)(
        team_id=input.team_id,
        report_id=input.report_id,
        head_sha=input.head_sha,
        results={(input.pass_number, input.chunk_id): review},
    )
    return True


# --- Combine + scope-clean + dedup -----------------------------------------------------------------


def _combine_and_clean(team_id: int, report_id: str, head_sha: str) -> list[str]:
    perspective_results = load_perspective_results(team_id=team_id, report_id=report_id, head_sha=head_sha)
    snapshot = load_pr_snapshot(team_id=team_id, report_id=report_id, head_sha=head_sha)
    pr_files = snapshot.pr_files if snapshot is not None else []
    raw_issues = combine_issues(perspective_results)
    cleaned = clean_issues(raw_issues, pr_files)
    return [issue.model_dump_json() for issue in cleaned]


@activity.defn
@scoped_temporal()
@close_db_connections
async def combine_and_clean_activity(input: CombineCleanInput) -> list[str]:
    """Flatten every perspective's findings and scope-clean to the diff (local, no sandbox)."""
    return await database_sync_to_async(_combine_and_clean, thread_sensitive=False)(
        input.team_id, input.report_id, input.head_sha
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def dedup_activity(input: DedupInput) -> DedupResult:
    """Deduplicate the in-scope issues (conditional single sandbox call) and persist the findings."""
    issues = [Issue.model_validate_json(j) for j in input.issues_json]
    snapshot = await database_sync_to_async(load_pr_snapshot, thread_sensitive=False)(
        team_id=input.team_id, report_id=input.report_id, head_sha=input.head_sha
    )
    if snapshot is None:
        raise ApplicationError("PR snapshot missing for deduplication", non_retryable=True)
    async with Heartbeater():
        survivors = await deduplicate_issues(
            team_id=input.team_id,
            user_id=input.user_id,
            issues=issues,
            pr_metadata=snapshot.pr_metadata,
            pr_comments=snapshot.pr_comments,
            branch=input.branch,
            repository=input.repository,
        )
    findings_count = await database_sync_to_async(persist_findings, thread_sensitive=False)(
        team_id=input.team_id, report_id=input.report_id, issues=survivors, run_index=input.run_index
    )
    return DedupResult(issues_json=[issue.model_dump_json() for issue in survivors], findings_count=findings_count)


# --- Validate (per-issue fan-out) ------------------------------------------------------------------


def _load_validation_skill(team_id: int, acting_user_id: int) -> LoadedValidationSkillDTO:
    skill = load_validation_skill_for_run(team_id, acting_user_id)
    return LoadedValidationSkillDTO(skill_name=skill.skill_name, version=skill.version)


@activity.defn
@scoped_temporal()
@close_db_connections
async def load_validation_skill_activity(input: LoadValidationInput) -> LoadedValidationSkillDTO:
    """Resolve the acting user's selected validator, pinned to its current version, for this run."""
    return await database_sync_to_async(_load_validation_skill, thread_sensitive=False)(
        input.team_id, input.acting_user_id
    )


def _prepare_validation_prompt(
    team_id: int, report_id: str, head_sha: str, issue: Issue, skill_name: str, skill_version: int
) -> str | None:
    """Build the validation prompt for one issue, or None if its chunk can't be resolved."""
    parts = issue.id.split("-")
    if len(parts) != 3:
        logger.warning(f"Skipping validation for issue with malformed id: {issue.id}")
        return None
    chunks = load_chunk_set(team_id=team_id, report_id=report_id, head_sha=head_sha)
    snapshot = load_pr_snapshot(team_id=team_id, report_id=report_id, head_sha=head_sha)
    if chunks is None or snapshot is None:
        raise ApplicationError("PR snapshot or chunk set missing for validation", non_retryable=True)
    chunk = next((c for c in chunks.chunks if c.chunk_id == int(parts[1])), None)
    if chunk is None:
        logger.warning(f"Skipping validation for issue {issue.id}: chunk {parts[1]} not found")
        return None
    # Narrow pr_files to the issue's own file before building the prompt (first-match semantics).
    issue_files = [f for f in snapshot.pr_files if f.filename == issue.file]
    return build_validation_prompt(
        issue=issue,
        chunk=chunk,
        skill_name=skill_name,
        skill_version=skill_version,
        pr_metadata=snapshot.pr_metadata,
        pr_files=issue_files,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def validate_issue_activity(input: ValidateIssueInput) -> ValidateIssueResult:
    """Validate one issue against the live codebase, persist its verdict, return the ruling.

    The verdict is also persisted (`validation_verdict` artefact) so publishing is DB-driven; the
    returned `validation_json` lets the parent render the body without another DB read.
    """
    issue = Issue.model_validate_json(input.issue_json)
    prompt = await database_sync_to_async(_prepare_validation_prompt, thread_sensitive=False)(
        input.team_id, input.report_id, input.head_sha, issue, input.skill_name, input.skill_version
    )
    if prompt is None:
        return ValidateIssueResult(issue_id=issue.id, validation_json=None)
    async with Heartbeater():
        validation = await run_sandbox_review(
            team_id=input.team_id,
            user_id=input.user_id,
            repository=input.repository,
            branch=input.branch,
            prompt=prompt,
            system_prompt=VALIDATION_SYSTEM_PROMPT,
            model_to_validate=IssueValidation,
            step_name=f"validation-{issue.id}",
        )
    await database_sync_to_async(persist_verdict, thread_sensitive=False)(
        team_id=input.team_id, report_id=input.report_id, issue=issue, validation=validation, run_index=input.run_index
    )
    return ValidateIssueResult(issue_id=issue.id, validation_json=validation.model_dump_json())


# --- Build body + finalize + publish ---------------------------------------------------------------


def _build_and_finalize(
    team_id: int, report_id: str, head_sha: str, issues_json: list[str], validations_json: dict[str, str]
) -> None:
    issues = [Issue.model_validate_json(j) for j in issues_json]
    validations = {issue_id: IssueValidation.model_validate_json(j) for issue_id, j in validations_json.items()}
    chunks_data = load_chunk_set(team_id=team_id, report_id=report_id, head_sha=head_sha) or ChunksList(chunks=[])
    analyses = load_chunk_analyses(team_id=team_id, report_id=report_id, head_sha=head_sha)
    body = build_review_body(chunks_data=chunks_data, analyses=analyses, issues=issues, validations=validations)
    finalize_review_report(team_id=team_id, report_id=report_id, body_markdown=body)


@activity.defn
@scoped_temporal()
@close_db_connections
async def build_body_activity(input: BuildBodyInput) -> None:
    """Render the review body and finalize the turn (store the body, bump the run watermark)."""
    await database_sync_to_async(_build_and_finalize, thread_sensitive=False)(
        input.team_id, input.report_id, input.head_sha, input.issues_json, input.validations_json
    )


def _publish(
    team_id: int, report_id: str, head_sha: str, run_index: int, owner: str, repo: str, pr_number: int
) -> None:
    token = _installation_token(team_id, f"{owner}/{repo}")
    publish_persisted_review(
        team_id=team_id,
        report_id=report_id,
        head_sha=head_sha,
        run_index=run_index,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        token=token,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def publish_review_activity(input: PublishInput) -> None:
    """Publish the review to GitHub (DB-driven).

    The per-run publish gate lives in the workflow (`inputs.publish`): this activity is dispatched
    only when publishing is enabled, so reaching here means publish.
    """
    await database_sync_to_async(_publish, thread_sensitive=False)(
        input.team_id, input.report_id, input.head_sha, input.run_index, input.owner, input.repo, input.pr_number
    )
