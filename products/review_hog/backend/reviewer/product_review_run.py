import json
import logging
from pathlib import Path

import aiohttp

from products.review_hog.backend.reviewer.models import generate_all_schemas
from products.review_hog.backend.reviewer.tools.analyze_pr import analyze_pr
from products.review_hog.backend.reviewer.tools.fetch_posthog_context import fetch_posthog_context
from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher, PRParser
from products.review_hog.backend.reviewer.tools.rewrite_product_review import rewrite_product_review
from products.review_hog.backend.reviewer.tools.write_product_review import publish_product_review, write_product_review

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

_REVIEW_HOG_DIR = Path(__file__).parent.parent.parent
_CLOUDFLARE_WEBHOOK_URL = "https://example.workers.dev/review"  # TODO: replace with real URL


async def main(pr_url: str) -> None:
    """Main entry point for running a product review."""

    # 1. Parse PR URL
    try:
        pr_info = PRParser().parse_github_pr_url(pr_url)
    except ValueError as e:
        logger.exception(f"Error: {e}")
        raise
    owner = str(pr_info["owner"])
    repo = str(pr_info["repo"])
    pr_number = int(pr_info["pr_number"])
    logger.info(f"Processing PR #{pr_number} from {owner}/{repo}")

    # 2. Create output directory (separate from code review output)
    review_dir = _REVIEW_HOG_DIR / "reviews" / "product_review" / str(pr_number)
    review_dir.mkdir(parents=True, exist_ok=True)

    # 3. Fetch PR data from GitHub
    try:
        pr_metadata, pr_comments, pr_files = PRFetcher(
            owner=owner, repo=repo, pr_number=pr_number, review_dir=str(review_dir)
        ).fetch_pr_data()
    except Exception as e:
        logger.exception(f"Unexpected error while fetching PR data: {e}")
        raise

    branch = pr_metadata.head_branch

    # 4. Generate schemas for product review models
    logger.info("Generating schemas...")
    generate_all_schemas()

    # 5. Step 1: Analyze the PR (sandbox)
    logger.info("Step 1: Analyzing PR in sandbox...")
    await analyze_pr(
        pr_metadata=pr_metadata,
        pr_files=pr_files,
        review_dir=review_dir,
        branch=branch,
    )

    # 6. Step 2: Fetch PostHog context (sandbox with MCP)
    logger.info("Step 2: Fetching PostHog usage context...")
    await fetch_posthog_context(
        review_dir=review_dir,
        branch=branch,
    )

    # # 7. Step 3: Record video of the feature (Browserbase)
    # this is borked right now
    # logger.info("Step 3: Recording feature video...")
    # await record_feature(
    #     review_dir=review_dir,
    #     base_url=os.environ.get("POSTHOG_REVIEW_BASE_URL", "http://localhost:8010"),
    # )

    # 8. Step 4: Write raw product review (sandbox with repo access)
    logger.info("Step 4: Writing raw product review...")
    pr_comments_str = json.dumps([c.model_dump(mode="json") for c in pr_comments], indent=2) if pr_comments else None
    await write_product_review(
        pr_metadata=pr_metadata,
        review_dir=review_dir,
        branch=branch,
        pr_comments=pr_comments_str,
    )

    # 9. Step 5: Rewrite review in product language (sandbox, no repo knowledge)
    logger.info("Step 5: Rewriting review in product language...")
    await rewrite_product_review(
        pr_metadata=pr_metadata,
        review_dir=review_dir,
        branch=branch,
    )

    # 10. Assemble and publish
    logger.info("Step 6: Publishing review...")
    publish_product_review(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        review_dir=review_dir,
    )
    logger.info("Product review published successfully!")

    # 11. Notify Cloudflare worker with the review
    logger.info("Step 7: Sending review to Cloudflare...")
    try:
        review_md = (review_dir / "product-review.md").read_text()
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                _CLOUDFLARE_WEBHOOK_URL,
                json={"pr_url": pr_url, "review": review_md},
            )
            if resp.status == 200:
                logger.info("Review sent to Cloudflare successfully.")
            else:
                logger.warning(f"Cloudflare returned status {resp.status}")
    except Exception:
        logger.exception("Failed to send review to Cloudflare, skipping.")
