import sys
import logging
from pathlib import Path

from asgiref.sync import sync_to_async

from products.review_hog.backend.reviewer.constants import PUBLISH_REVIEW_ENABLED
from products.review_hog.backend.reviewer.models import generate_all_schemas
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
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
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import prepare_validation_markdown
from products.review_hog.backend.reviewer.tools.publish_review import publish_review
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import split_pr_into_chunks

logger = logging.getLogger(__name__)
# Configure logging to output to console
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Review output directory relative to the review_hog product
_REVIEW_HOG_DIR = Path(__file__).parent.parent.parent

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


# TODO: Make it a parent workflow and spawn steps as child workflows for better visualization
async def main(pr_url: str, *, team_id: int, user_id: int) -> None:
    """Main entry point for running PR review tools.

    ``team_id`` / ``user_id`` are explicit inputs from the trigger (the `run_review` CLI today, the
    Temporal trigger later): the team the review runs and persists under, and the user the sandbox
    tasks run as.
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

    # 2. Create output directory (if doesn't exist)
    review_dir = _REVIEW_HOG_DIR / "reviews" / str(pr_number)
    review_dir.mkdir(parents=True, exist_ok=True)

    # 3. Fetch PR data from GitHub
    _stage(1, "Fetch PR data")
    try:
        pr_metadata, pr_comments, pr_files = PRFetcher(
            owner=owner, repo=repo, pr_number=pr_number, review_dir=str(review_dir)
        ).fetch_pr_data()
    except Exception as e:
        logger.exception(f"Unexpected error while fetching PR data: {e}")
        raise

    branch = pr_metadata.head_branch

    # Bind the explicit team/user for this run's sandboxes (validates the team's GitHub integration),
    # then open the living report for this PR. A re-run reuses the report keyed by
    # (team, repository, pr_number).
    await bind_sandbox_identity(team_id=team_id, user_id=user_id)
    report_id = await sync_to_async(upsert_review_report)(
        team_id=team_id, repository=repository, pr_url=pr_url, pr_metadata=pr_metadata
    )

    # Snapshot the point-in-time diff this turn reviews, in the same fetch boundary that produced it
    # (idempotent on the PR's head_sha — a re-run with no new commits records nothing).
    snapshotted = await sync_to_async(persist_commit_snapshot)(
        team_id=team_id,
        report_id=report_id,
        repository=repository,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        review_dir=review_dir,
    )
    _emit("Captured point-in-time diff snapshot" if snapshotted else "No new diff snapshot this turn")

    # 4. Generate schemas
    logger.info("Generating schemas...")
    generate_all_schemas()

    # 5. Split PR into chunks
    _stage(2, "Split into chunks")
    await split_pr_into_chunks(
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
        repository=repository,
    )

    # 6. Load chunks
    chunks_path = review_dir / "chunks.json"
    with chunks_path.open() as f:
        chunks_data = ChunksList.model_validate_json(f.read())

    # 7. Analyze chunks to better understand their logic/architecture
    _stage(3, "Analyze chunks")
    await analyze_chunks(
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
        repository=repository,
    )

    # 8. Find issues in each chunk in multiple passes
    _stage(4, "Review chunks (3 passes)")
    await review_chunks(
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
        repository=repository,
    )
    logger.info("Issues review completed successfully!")

    # 9. Combine issues found in all passes
    _stage(5, "Combine & scope-clean issues")
    combine_issues(review_dir=review_dir)

    # 10. Clean issues based on PR scope
    logger.info("Cleaning issues based on PR scope...")
    clean_issues(review_dir=review_dir)

    # 11. Deduplicate issues found in all passes
    _stage(6, "Deduplicate issues")
    await deduplicate_issues(
        pr_metadata=pr_metadata,
        review_dir=review_dir,
        branch=branch,
        repository=repository,
    )
    logger.info("Issue deduplication completed successfully!")

    findings_count = await sync_to_async(persist_findings)(team_id=team_id, report_id=report_id, review_dir=review_dir)
    _emit(f"Persisted {findings_count} finding(s) to the review report")

    # 12. Validate issues found in all passes
    _stage(7, "Validate issues")
    await validate_issues(
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
        repository=repository,
    )
    logger.info("Issue validation completed successfully!")

    verdicts_count = await sync_to_async(persist_verdicts)(team_id=team_id, report_id=report_id, review_dir=review_dir)
    _emit(f"Persisted {verdicts_count} validation verdict(s) to the review report")

    # 13. Prepare validation markdown documents
    _stage(8, "Build report")
    await prepare_validation_markdown(
        chunks_data=chunks_data,
        review_dir=review_dir,
        pr_metadata=pr_metadata.model_dump(),
    )
    logger.info("Validation markdown preparation completed successfully!")

    # Turn complete: store the rendered markdown and bump the report's run watermark.
    await sync_to_async(finalize_review_report)(team_id=team_id, report_id=report_id, review_dir=review_dir)

    # 14. Publish review to GitHub
    _stage(9, "Publish review")
    if PUBLISH_REVIEW_ENABLED:
        logger.info("Publishing review to GitHub...")
        publish_review(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            review_dir=review_dir,
        )
        logger.info("Review published successfully!")
    else:
        logger.info("Publishing disabled (PUBLISH_REVIEW_ENABLED=False)")

    _emit(f"═════ ReviewHog complete · report: {review_dir / 'review_report.md'} ═════")
