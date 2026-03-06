import logging
from pathlib import Path

from products.review_hog.backend.reviewer.models import generate_all_schemas
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tools.chunk_analysis import analyze_chunks
from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher, PRParser
from products.review_hog.backend.reviewer.tools.issue_cleaner import clean_issues
from products.review_hog.backend.reviewer.tools.issue_combination import combine_issues
from products.review_hog.backend.reviewer.tools.issue_deduplicator import deduplicate_issues
from products.review_hog.backend.reviewer.tools.issue_validation import validate_issues
from products.review_hog.backend.reviewer.tools.issues_review import review_chunks
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import prepare_validation_markdown
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import split_pr_into_chunks

logger = logging.getLogger(__name__)
# Configure logging to output to console
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Review output directory relative to the review_hog product
_REVIEW_HOG_DIR = Path(__file__).parent.parent.parent


async def main(pr_url: str) -> None:
    """Main entry point for running PR review tools."""

    # Parse PR URL into PR metadata
    try:
        pr_info = PRParser().parse_github_pr_url(pr_url)
    except ValueError as e:
        logger.exception(f"Error: {e}")
        raise
    owner = str(pr_info["owner"])
    repo = str(pr_info["repo"])
    pr_number = int(pr_info["pr_number"])
    logger.info(f"Processing PR #{pr_number} from {owner}/{repo}")

    # Create output directory (if doesn't exist)
    review_dir = _REVIEW_HOG_DIR / "reviews" / str(pr_number)
    review_dir.mkdir(parents=True, exist_ok=True)

    # Fetch PR data from GitHub
    try:
        pr_metadata, pr_comments, pr_files = PRFetcher(
            owner=owner, repo=repo, pr_number=pr_number, review_dir=str(review_dir)
        ).fetch_pr_data()
    except Exception as e:
        logger.exception(f"Unexpected error while fetching PR data: {e}")
        raise

    branch = pr_metadata.head_branch

    # Generate schemas
    logger.info("Generating schemas...")
    generate_all_schemas()

    # Split PR into chunks
    logger.info("Splitting PR into chunks...")
    await split_pr_into_chunks(
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
    )

    # Load chunks
    chunks_path = review_dir / "chunks.json"
    with chunks_path.open() as f:
        chunks_data = ChunksList.model_validate_json(f.read())

    # Analyze chunks to better understand their logic/architecture
    logger.info("Starting chunk analysis process...")
    await analyze_chunks(
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
    )

    # Find issues in each chunk in multiple passes
    logger.info("Starting issues review process...")
    await review_chunks(
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
    )
    logger.info("Issues review completed successfully!")

    # Combine issues found in all passes
    logger.info("Combining issues found in all passes...")
    combine_issues(review_dir=review_dir)

    # Clean issues based on PR scope
    logger.info("Cleaning issues based on PR scope...")
    clean_issues(review_dir=review_dir)

    # Deduplicate issues found in all passes
    logger.info("Starting issue deduplication process...")
    await deduplicate_issues(
        pr_metadata=pr_metadata,
        review_dir=review_dir,
        branch=branch,
    )
    logger.info("Issue deduplication completed successfully!")

    # Validate issues found in all passes
    logger.info("Starting issue validation process...")
    await validate_issues(
        chunks_data=chunks_data,
        pr_metadata=pr_metadata,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
    )
    logger.info("Issue validation completed successfully!")

    # Prepare validation markdown documents
    logger.info("Preparing validation markdown documents...")
    await prepare_validation_markdown(
        chunks_data=chunks_data,
        review_dir=review_dir,
        pr_metadata=pr_metadata.model_dump(),
    )
    logger.info("Validation markdown preparation completed successfully!")
