import logging

from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuesReview, PassType

logger = logging.getLogger(__name__)


def combine_issues(lens_results: dict[tuple[int, int], IssuesReview]) -> list[Issue]:
    """Flatten every (lens, chunk) review into one issue list, stamping each issue's source lens.

    `lens_results` is keyed by `(pass_number, chunk_id)`; passes 1..3 map to `PassType` members in
    order, so the pass number recovers which lens found each issue.
    """
    all_issues: list[Issue] = []
    for (pass_number, chunk_id), review in sorted(lens_results.items()):
        lens_name = list(PassType)[pass_number - 1].value
        for issue in review.issues:
            issue.source_lens = lens_name
        all_issues += review.issues
        logger.info(
            f"Added {len(review.issues)} issues from chunk {chunk_id} (lens {pass_number}) to the combined list"
        )
    return all_issues
