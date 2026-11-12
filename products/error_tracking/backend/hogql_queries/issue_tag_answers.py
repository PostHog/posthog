from collections.abc import Collection
from typing import cast

from posthog.schema import ErrorTrackingIssueTagFilter, ErrorTrackingIssueTagFilterValue

from posthog.hogql import ast
from posthog.hogql.parser import parse_select


def latest_issue_tag_answers(keys: Collection[str], issue_ids: Collection[str] | None = None) -> ast.SelectQuery:
    """The current answer of each issue to each tag in `keys`, as rows of issue_id, key and answer.

    Every write of a tag adds a row, so the row with the highest version is the current answer. The query filters
    rows only on the columns it groups by: a filter on `value` before the argMax would let an older answer win.
    `tuple(value)` keeps a null answer, which a bare argMax skips. An answer whose newest row is deleted is left out.
    """
    conditions: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.In, left=ast.Field(chain=["key"]), right=ast.Constant(value=list(keys))
        )
    ]
    if issue_ids is not None:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["issue_id"]),
                right=ast.Constant(value=list(issue_ids)),
            )
        )
    return cast(
        ast.SelectQuery,
        parse_select(
            """
            SELECT issue_id, key, argMax(tuple(value), version).1 AS answer
            FROM posthog.raw_error_tracking_issue_tags
            WHERE {conditions}
            GROUP BY issue_id, key
            HAVING argMax(is_deleted, version) = 0
            """,
            placeholders={"conditions": ast.And(exprs=conditions)},
        ),
    )


def issue_tag_filter_expr(issue_id: ast.Expr, tag_filter: ErrorTrackingIssueTagFilter) -> ast.Expr:
    """Keep the issues whose current answer to the tag is the one the filter wants."""
    # Unknown is a null answer or no answer at all, and an issue without an answer has no row to select,
    # so unknown keeps every issue outside the yes and no answers.
    unknown = tag_filter.value == ErrorTrackingIssueTagFilterValue.UNKNOWN
    answer = ast.Field(chain=["answer"])
    condition: ast.Expr = (
        ast.Call(name="isNotNull", args=[answer])
        if unknown
        else ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=answer,
            right=ast.Constant(value=tag_filter.value == ErrorTrackingIssueTagFilterValue.YES),
        )
    )
    answered_issues = ast.SelectQuery(
        select=[ast.Field(chain=["issue_id"])],
        select_from=ast.JoinExpr(table=latest_issue_tag_answers([tag_filter.key])),
        where=condition,
    )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn if unknown else ast.CompareOperationOp.In, left=issue_id, right=answered_issues
    )
