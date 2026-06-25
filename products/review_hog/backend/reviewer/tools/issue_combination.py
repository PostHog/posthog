import logging

from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuesReview, PerspectiveType

logger = logging.getLogger(__name__)


def combine_issues(perspective_results: dict[tuple[int, int], IssuesReview]) -> list[Issue]:
    """Flatten every (perspective, chunk) review into one issue list, stamping each issue's source.

    `perspective_results` is keyed by `(pass_number, chunk_id)`; passes 1..3 map to `PerspectiveType`
    members in order, so the pass number recovers which perspective found each issue.

    Each issue's `id` is re-stamped to `{pass}-{chunk}-{n}` from the loop position. The review prompt is
    perspective-agnostic, so the agent doesn't know its ordinal and every perspective self-assigns
    colliding `1-...` ids; re-stamping yields a unique, correctly-attributed id that downstream stages
    depend on (validation keys verdicts by `issue.id`, and the persisted `issue_key` embeds it).
    """
    all_issues: list[Issue] = []
    for (pass_number, chunk_id), review in sorted(perspective_results.items()):
        perspective_name = list(PerspectiveType)[pass_number - 1].value
        for issue_number, issue in enumerate(review.issues, start=1):
            issue.source_perspective = perspective_name
            issue.id = f"{pass_number}-{chunk_id}-{issue_number}"
        all_issues += review.issues
        logger.info(
            f"Added {len(review.issues)} issues from chunk {chunk_id} (perspective {pass_number}) to the combined list"
        )
    return all_issues
