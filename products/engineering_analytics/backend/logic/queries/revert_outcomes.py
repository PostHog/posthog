from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    ApprovalRevertOutcome,
    AuthorshipRevertOutcome,
    PullRequestApproval,
    PullRequestAuthorship,
    RevertedPullRequest,
    RevertOutcomes,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.views.reviews import APPROVED_STATE

REVERTED_PULL_REQUEST_LIMIT = 200

_APPROVED_BEFORE_MERGE = f"r.state = '{APPROVED_STATE}' AND r.submitted_at <= pr.merged_at"

_APPROVAL_FROM_REVIEWS = f"""multiIf(
                countIf({_APPROVED_BEFORE_MERGE} AND NOT r.reviewer_is_bot) > 0, '{PullRequestApproval.HUMAN.value}',
                countIf({_APPROVED_BEFORE_MERGE}) > 0, '{PullRequestApproval.AUTOMATED_ONLY.value}',
                '{PullRequestApproval.NONE.value}'
            )"""

_OUTCOMES_CTES = f"""
    WITH reverted AS (
        SELECT
            reverted_pr_number AS target_number,
            min(merged_at) AS reverted_at,
            argMin(number, merged_at) AS reverting_pr_number
        FROM __PR_SOURCE__
        WHERE merged_at IS NOT NULL AND reverted_pr_number IS NOT NULL AND merged_at >= {{date_from}}
        GROUP BY reverted_pr_number
    ),
    merged AS (
        SELECT
            pr.number AS number,
            pr.title AS title,
            pr.merged_at AS merged_at,
            multiIf(
                pr.is_bot, '{PullRequestAuthorship.BOT.value}',
                pr.has_agent_context, '{PullRequestAuthorship.AGENT_CONTEXT.value}',
                '{PullRequestAuthorship.NO_AGENT_CONTEXT.value}'
            ) AS authorship,
            __APPROVAL__ AS approval
        FROM __PR_SOURCE__ AS pr
        __REVIEWS_JOIN__
        WHERE pr.merged_at IS NOT NULL AND pr.merged_at >= {{date_from}} __DATE_TO__ AND NOT pr.is_revert
        GROUP BY pr.number, pr.title, pr.merged_at, pr.is_bot, pr.has_agent_context
    )
"""

_WAS_REVERTED = "rv.reverting_pr_number > 0 AND rv.reverted_at >= m.merged_at"

_COHORTS_SELECT = f"""
    SELECT m.authorship AS authorship, m.approval AS approval, count() AS merged, countIf({_WAS_REVERTED}) AS reverted
    FROM merged AS m
    LEFT JOIN reverted AS rv ON rv.target_number = m.number
    GROUP BY authorship, approval
"""

_REVERTED_SELECT = f"""
    SELECT m.number, m.title, m.merged_at, m.authorship, m.approval, rv.reverting_pr_number, rv.reverted_at
    FROM merged AS m
    INNER JOIN reverted AS rv ON rv.target_number = m.number
    WHERE {_WAS_REVERTED}
    ORDER BY rv.reverted_at DESC, m.number DESC
    LIMIT {REVERTED_PULL_REQUEST_LIMIT + 1}
"""


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def query_revert_outcomes(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> RevertOutcomes:
    reviews = curated.reviews_source()
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    ctes = (
        _OUTCOMES_CTES.replace("__PR_SOURCE__", curated.pr_source())
        .replace("__APPROVAL__", _APPROVAL_FROM_REVIEWS if reviews else "''")
        .replace("__REVIEWS_JOIN__", f"LEFT JOIN {reviews} AS r ON r.pr_number = pr.number" if reviews else "")
        .replace("__DATE_TO__", "AND pr.merged_at <= {date_to}" if date_to is not None else "")
    )
    cohort_response = curated.run(
        ctes + _COHORTS_SELECT,
        query_type="engineering_analytics.revert_outcome_cohorts",
        placeholders=placeholders,
    )
    cohorts = [
        (str(authorship), str(approval), int(merged or 0), int(reverted or 0))
        for authorship, approval, merged, reverted in cohort_response.results or []
    ]
    merged_pr_count = sum(merged for _, _, merged, _ in cohorts)
    if not curated.pull_requests_have_body:
        return RevertOutcomes(
            merged_pr_count=merged_pr_count,
            reverted_pr_count=None,
            reverted_share=None,
            body_data_available=False,
            review_data_available=reviews is not None,
            by_authorship=[],
            by_approval=[],
            reverted_pull_requests=[],
            truncated=False,
            limit=REVERTED_PULL_REQUEST_LIMIT,
        )
    reverted_response = curated.run(
        ctes + _REVERTED_SELECT,
        query_type="engineering_analytics.reverted_pull_requests",
        placeholders=placeholders,
    )
    reverted_rows = reverted_response.results or []
    reverted_pr_count = sum(reverted for _, _, _, reverted in cohorts)
    by_authorship: list[AuthorshipRevertOutcome] = []
    for authorship in PullRequestAuthorship:
        merged = sum(row[2] for row in cohorts if row[0] == authorship.value)
        reverted = sum(row[3] for row in cohorts if row[0] == authorship.value)
        by_authorship.append(
            AuthorshipRevertOutcome(
                authorship=authorship,
                merged_pr_count=merged,
                reverted_pr_count=reverted,
                reverted_share=_share(reverted, merged),
            )
        )
    by_approval: list[ApprovalRevertOutcome] = []
    for approval in PullRequestApproval if reviews else ():
        merged = sum(row[2] for row in cohorts if row[1] == approval.value)
        reverted = sum(row[3] for row in cohorts if row[1] == approval.value)
        by_approval.append(
            ApprovalRevertOutcome(
                approval=approval,
                merged_pr_count=merged,
                reverted_pr_count=reverted,
                reverted_share=_share(reverted, merged),
            )
        )
    return RevertOutcomes(
        merged_pr_count=merged_pr_count,
        reverted_pr_count=reverted_pr_count,
        reverted_share=_share(reverted_pr_count, merged_pr_count),
        body_data_available=True,
        review_data_available=reviews is not None,
        by_authorship=by_authorship,
        by_approval=by_approval,
        reverted_pull_requests=[_to_reverted_pull_request(row) for row in reverted_rows[:REVERTED_PULL_REQUEST_LIMIT]],
        truncated=len(reverted_rows) > REVERTED_PULL_REQUEST_LIMIT,
        limit=REVERTED_PULL_REQUEST_LIMIT,
    )


def _to_reverted_pull_request(row: tuple) -> RevertedPullRequest:
    number, title, merged_at, authorship, approval, reverting_pr_number, reverted_at = row
    return RevertedPullRequest(
        number=int(number),
        title=title or "",
        merged_at=merged_at,
        authorship=PullRequestAuthorship(authorship),
        approval=PullRequestApproval(approval) if approval else None,
        reverting_pr_number=int(reverting_pr_number),
        reverted_at=reverted_at,
        merge_to_revert_seconds=int((reverted_at - merged_at).total_seconds()),
    )
