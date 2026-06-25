import logging

from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuesReview, PerspectiveType

logger = logging.getLogger(__name__)


def combine_issues(perspective_results: dict[tuple[int, int], IssuesReview]) -> list[Issue]:
    """Flatten every (perspective, chunk) review into one issue list, stamping each issue's source.

    `perspective_results` is keyed by `(pass_number, chunk_id)`; passes 1..3 map to `PerspectiveType`
    members in order, so the pass number recovers which perspective found each issue.
    """
    all_issues: list[Issue] = []
    for (pass_number, chunk_id), review in sorted(perspective_results.items()):
        perspective_name = list(PerspectiveType)[pass_number - 1].value
        for issue in review.issues:
            issue.source_perspective = perspective_name
        all_issues += review.issues
        logger.info(
            f"Added {len(review.issues)} issues from chunk {chunk_id} (perspective {pass_number}) to the combined list"
        )
    return all_issues
