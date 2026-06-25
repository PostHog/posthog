import sys
import logging

from asgiref.sync import sync_to_async

from posthog.models.team.team import Team

from products.review_hog.backend.reviewer.constants import PUBLISH_REVIEW_ENABLED
from products.review_hog.backend.reviewer.lazy_seed import sync_canonical_perspectives
from products.review_hog.backend.reviewer.models import generate_all_schemas
from products.review_hog.backend.reviewer.persistence import (
    finalize_review_report,
    persist_commit_snapshot,
    persist_findings,
    persist_verdicts,
    upsert_review_report,
)
from products.review_hog.backend.reviewer.sandbox.executor import bind_sandbox_identity
from products.review_hog.backend.reviewer.tools.chunk_analysis import analyze_chunks
from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher, PRParser
from products.review_hog.backend.reviewer.tools.issue_cleaner import clean_issues
from products.review_hog.backend.reviewer.tools.issue_combination import combine_issues
from products.review_hog.backend.reviewer.tools.issue_deduplicator import deduplicate_issues
from products.review_hog.backend.reviewer.tools.issue_validation import validate_issues
from products.review_hog.backend.reviewer.tools.issues_review import review_chunks
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import build_review_body
from products.review_hog.backend.reviewer.tools.publish_review import publish_review
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import split_pr_into_chunks

logger = logging.getLogger(__name__)

_TOTAL_STAGES = 9


def _emit(message: str) -> None:
    """Write a user-facing progress line straight to stdout.

    The reviewer's INFO logs are not surfaced by the Django/structlog console config, so stage
    progress goes to stdout directly; the flush makes each line appear before its (slow) work runs.
    """
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def _stage(number: int, label: str) -> None:
    """Emit a one-line, numbered banner so the current pipeline stage is obvious in the console."""
    _emit(f"━━━━━ STAGE {number}/{_TOTAL_STAGES} · {label} ━━━━━")


def _sync_perspectives_for_team(team_id: int) -> None:
    """Cold-start sync the team's canonical review perspectives before the review pulls them.

    Mirrors the Signals scout runner's lazy sync (prune off — an ad-hoc run only ensures its own
    perspectives are seeded and current). Log-and-continue: a sync failure shouldn't crash the run;
    the review proceeds with whatever perspective skills the team already has, and surfaces a clear
    error later if one is genuinely missing.
    """
    try:
        sync_canonical_perspectives(Team.objects.get(id=team_id))
    except Exception:
        logger.exception("Perspective skill sync failed; continuing with existing team perspectives")


# TODO: Make it a parent workflow and spawn steps as child workflows for better visualization
async def main(pr_url: str, *, team_id: int, user_id: int) -> None:
    """Main entry point for running PR review tools.

    ``team_id`` / ``user_id`` are explicit inputs from the trigger (the `run_review` CLI today, the
    Temporal trigger later): the team the review runs and persists under, and the user the sandbox
    tasks run as. Inter-stage state lives in Postgres (`ReviewReport` + `ReviewReportArtefact`),
    passed in-process within this run and persisted per stage — there is no on-disk store. A re-run
    on the same ``head_sha`` reuses the expensive, turn-stable sandbox stages (chunk / analyze /
    perspective review) from rows; dedup and validation recompute, since their post-dedup issue set
    isn't stable across re-runs.
    """

    # 1. Parse PR URL into PR metadata
    try:
        pr_info = PRParser().parse_github_pr_url(pr_url)
    except ValueError as e:
        logger.exception(f"Error: {e}")
        raise
    owner = str(pr_info["owner"])
    repo = str(pr_info["repo"])
    pr_number = int(pr_info["pr_number"])
    repository = f"{owner}/{repo}"
    _emit(f"═════ ReviewHog · reviewing PR #{pr_number} · {repository} ═════")

    # 2. Fetch PR data from GitHub (everything in-process; the reviewed diff comes back too)
    _stage(1, "Fetch PR data")
    try:
        pr_metadata, pr_comments, pr_files, diff = PRFetcher(
            owner=owner, repo=repo, pr_number=pr_number
        ).fetch_pr_data()
    except Exception as e:
        logger.exception(f"Unexpected error while fetching PR data: {e}")
        raise

    branch = pr_metadata.head_branch
    head_sha = pr_metadata.head_sha or ""

    # Bind the explicit team/user for this run's sandboxes (validates the team's GitHub integration),
    # then open the living report for this PR. A re-run reuses the report keyed by
    # (team, repository, pr_number).
    await bind_sandbox_identity(team_id=team_id, user_id=user_id)
    report_id = await sync_to_async(upsert_review_report)(
        team_id=team_id, repository=repository, pr_url=pr_url, pr_metadata=pr_metadata
    )

    # Snapshot the point-in-time diff this turn reviews (idempotent on the PR's head_sha — a re-run
    # with no new commits records nothing).
    snapshotted = await sync_to_async(persist_commit_snapshot)(
        team_id=team_id,
        report_id=report_id,
        repository=repository,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        diff=diff,
    )
    _emit("Captured point-in-time diff snapshot" if snapshotted else "No new diff snapshot this turn")

    # Cold-start: seed/update this team's canonical review perspectives so the parallel review can
    # pull each one over MCP (skill-get). Mirrors the Signals scout runner's lazy sync.
    await sync_to_async(_sync_perspectives_for_team)(team_id)

    # 3. Generate prompt schemas (static package assets the prompt templates embed)
    logger.info("Generating schemas...")
    generate_all_schemas()

    # 4. Split PR into chunks
    _stage(2, "Split into chunks")
    chunks_data = await split_pr_into_chunks(
        team_id=team_id,
        report_id=report_id,
        head_sha=head_sha,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        branch=branch,
        repository=repository,
    )

    # 5. Analyze chunks to better understand their logic/architecture
    _stage(3, "Analyze chunks")
    analyses = await analyze_chunks(
        team_id=team_id,
        report_id=report_id,
        head_sha=head_sha,
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        branch=branch,
        repository=repository,
    )

    # 6. Find issues in each chunk across the parallel perspectives
    _stage(4, "Review chunks (3 perspectives)")
    perspective_results = await review_chunks(
        team_id=team_id,
        report_id=report_id,
        head_sha=head_sha,
        chunks_data=chunks_data,
        analyses=analyses,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        branch=branch,
        repository=repository,
    )
    logger.info("Issues review completed successfully!")

    # 7. Combine + scope-clean the issues (local, in-process)
    _stage(5, "Combine & scope-clean issues")
    raw_issues = combine_issues(perspective_results)
    cleaned_issues = clean_issues(raw_issues, pr_files)

    # 8. Deduplicate issues
    _stage(6, "Deduplicate issues")
    issues = await deduplicate_issues(
        issues=cleaned_issues,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        branch=branch,
        repository=repository,
    )
    logger.info("Issue deduplication completed successfully!")

    findings_count = await sync_to_async(persist_findings)(team_id=team_id, report_id=report_id, issues=issues)
    _emit(f"Persisted {findings_count} finding(s) to the review report")

    # 9. Validate issues
    _stage(7, "Validate issues")
    validations = await validate_issues(
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_files=pr_files,
        issues=issues,
        branch=branch,
        repository=repository,
    )
    logger.info("Issue validation completed successfully!")

    verdicts_count = await sync_to_async(persist_verdicts)(
        team_id=team_id, report_id=report_id, issues=issues, validations=validations
    )
    _emit(f"Persisted {verdicts_count} validation verdict(s) to the review report")

    # 10. Build the review body and finalize the turn (store the body, bump the run watermark)
    _stage(8, "Build report")
    body = build_review_body(chunks_data=chunks_data, analyses=analyses, issues=issues, validations=validations)
    await sync_to_async(finalize_review_report)(team_id=team_id, report_id=report_id, body_markdown=body)
    logger.info("Review report finalized successfully!")

    # 11. Publish review to GitHub (DB-driven: body from the report, inline comments from the rows)
    _stage(9, "Publish review")
    if PUBLISH_REVIEW_ENABLED:
        logger.info("Publishing review to GitHub...")
        await sync_to_async(publish_review)(
            owner=owner, repo=repo, pr_number=pr_number, team_id=team_id, report_id=report_id, pr_files=pr_files
        )
        logger.info("Review published successfully!")
    else:
        logger.info("Publishing disabled (PUBLISH_REVIEW_ENABLED=False)")

    _emit(f"═════ ReviewHog complete · report stored on ReviewReport {report_id} ═════")
