from collections.abc import Collection

from posthog.schema import ErrorTrackingIssueTagFilter

from posthog.hogql import ast
from posthog.hogql.database.argmax import argmax_select

ISSUE_TAGS_TABLE = "raw_error_tracking_issue_tags"


def applied_issue_tags_query(keys: Collection[str], issue_ids: Collection[str] | None = None) -> ast.SelectQuery:
    """The tags in `keys` that are applied to each issue, as rows of latest_value, issue_id and key.

    A tag is applied while its latest row is not deleted and has the value 1. The query checks the value in HAVING,
    after the argMax, because a filter on `value` in WHERE would let an older row win.
    """
    query = argmax_select(
        table_name=ISSUE_TAGS_TABLE,
        select_fields={"issue_id": ["issue_id"], "key": ["key"], "latest_value": ["value"]},
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
    assert query.having is not None
    query.having = ast.And(
        exprs=[
            query.having,
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["latest_value"]), right=ast.Constant(value=1)
            ),
        ]
    )
    return query


def issue_tag_filter_expr(issue_id: ast.Expr, tag_filter: ErrorTrackingIssueTagFilter) -> ast.Expr:
    """Keep the issues the tag is applied to, or every other issue when `applied` is false."""
    tagged_issues = ast.SelectQuery(
        select=[ast.Field(chain=["issue_id"])],
        select_from=ast.JoinExpr(table=applied_issue_tags_query([tag_filter.key])),
    )
    # An issue the tag is not applied to can have no row to select, so `applied` false excludes the tagged issues.
    # GLOBAL builds the set once on the initiator. The tags table is on another cluster, so a plain IN in the
    # legacy shape, which filters events on each shard, would make every shard read the tags table again.
    return ast.CompareOperation(
        op=ast.CompareOperationOp.GlobalIn if tag_filter.applied else ast.CompareOperationOp.GlobalNotIn,
        left=issue_id,
        right=tagged_issues,
    )
