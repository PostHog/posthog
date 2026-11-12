from collections.abc import Collection

from posthog.schema import ErrorTrackingIssueTagFilter, ErrorTrackingIssueTagFilterValue

from posthog.hogql import ast
from posthog.hogql.database.argmax import argmax_select

ISSUE_TAGS_TABLE = "raw_error_tracking_issue_tags"


def latest_issue_tag_answers_query(keys: Collection[str], issue_ids: Collection[str] | None = None) -> ast.SelectQuery:
    """The current answer of each issue to each tag in `keys`, as rows of answer, issue_id and key.

    The query filters rows only on the columns it groups by, because a filter on `value` before the argMax would let
    an older answer win.
    """
    query = argmax_select(
        table_name=ISSUE_TAGS_TABLE,
        select_fields={"issue_id": ["issue_id"], "key": ["key"], "answer": ["value"]},
        group_fields=["issue_id", "key"],
        argmax_field="version",
        deleted_field="is_deleted",
    )
    # argmax_select names the table without a namespace, and HogQL registers this table only under `posthog`.
    query.select_from = ast.JoinExpr(table=ast.Field(chain=["posthog", ISSUE_TAGS_TABLE]), alias=ISSUE_TAGS_TABLE)
    conditions: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=[ISSUE_TAGS_TABLE, "key"]),
            right=ast.Constant(value=list(keys)),
        )
    ]
    if issue_ids is not None:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=[ISSUE_TAGS_TABLE, "issue_id"]),
                right=ast.Constant(value=list(issue_ids)),
            )
        )
        # Without an explicit limit, execute_hogql_query returns at most 100 rows and drops the rest.
        query.limit = ast.Constant(value=len(keys) * len(issue_ids))
    query.where = ast.And(exprs=conditions)
    return query


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
        select_from=ast.JoinExpr(table=latest_issue_tag_answers_query([tag_filter.key])),
        where=condition,
    )
    # GLOBAL builds the set once on the initiator. The tags table is on another cluster, so a plain IN in the
    # legacy shape, which filters events on each shard, would make every shard read the tags table again.
    return ast.CompareOperation(
        op=ast.CompareOperationOp.GlobalNotIn if unknown else ast.CompareOperationOp.GlobalIn,
        left=issue_id,
        right=answered_issues,
    )
