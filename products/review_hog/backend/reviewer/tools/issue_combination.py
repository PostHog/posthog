import logging

from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuesReview

logger = logging.getLogger(__name__)


def combine_issues(perspective_results: dict[tuple[int, int], IssuesReview]) -> list[Issue]:
    """Flatten every (perspective, chunk) review into one issue list, re-stamping each issue's id.

    `perspective_results` is keyed by `(pass_number, chunk_id)`. Each issue's `id` is re-stamped to
    `{pass}-{chunk}-{n}` from the loop position: the review prompt is perspective-agnostic, so the
    agent doesn't know its pass and every perspective self-assigns colliding `1-...` ids; re-stamping
    yields a unique id that downstream stages depend on (validation keys verdicts by `issue.id`, and
    the persisted `issue_key` embeds it). `source_perspective` is already stamped to the skill name
    by the review activity that ran the perspective, so it is preserved here, not recomputed.
    """
    all_issues: list[Issue] = []
    for (pass_number, chunk_id), review in sorted(perspective_results.items()):
        for issue_number, issue in enumerate(review.issues, start=1):
            issue.id = f"{pass_number}-{chunk_id}-{issue_number}"
        all_issues += review.issues
        logger.info(
            f"Added {len(review.issues)} issues from chunk {chunk_id} (perspective {pass_number}) to the combined list"
        )
    return all_issues
