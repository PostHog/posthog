import logging
from pathlib import Path

from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuesReview, PassType

logger = logging.getLogger(__name__)


def combine_issues(review_dir: Path) -> None:
    """Combine issues found in all passes into a single list."""
    passes_count = len(PassType)
    all_issues: list[Issue] = []
    # Process each pass to collect issues
    for pass_number in range(1, passes_count + 1):
        # The lens that produced this pass's issues (passes 1..3 map to PassType members in order)
        lens_name = list(PassType)[pass_number - 1].value
        # Directory paths for this pass
        pass_results_dir = review_dir / f"pass{pass_number}_results"
        # Find all chunk summary files for this pass
        summary_files = sorted(pass_results_dir.glob("chunk-*-issues-review.json"))
        if not summary_files:
            logger.warning(f"No code summary files found for Pass {pass_number}")
            continue
        for summary_file in summary_files:
            # Extract chunk index from filename
            chunk_index = int(summary_file.stem.split("-")[1])
            # Load the issues review
            try:
                with summary_file.open() as f:
                    issues_review = IssuesReview.model_validate_json(f.read())
            except Exception as e:
                raise Exception(f"Failed to load issues review from {summary_file}: {e}") from e
            # Stamp the originating lens on each issue, then combine
            for issue in issues_review.issues:
                issue.source_lens = lens_name
            all_issues += issues_review.issues
            logger.info(
                f"Added {len(issues_review.issues)} issues from chunk {chunk_index} to the combined list of issues"
            )
    # Create IssueCombination model and write to file
    issue_combination = IssueCombination(issues=all_issues)
    with (review_dir / "issues_found_raw.json").open("w") as f:
        f.write(issue_combination.model_dump_json(indent=2))
