from collections.abc import Collection

from posthog.schema import ErrorTrackingIssueTagsFilter

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


def issue_tags_filter_exprs(issue_id: ast.Expr, tags_filter: ErrorTrackingIssueTagsFilter) -> list[ast.Expr]:
    """Keep the issues that have every tag in `has` and no tag in `hasNot`."""
    # GLOBAL builds each set once on the initiator. The tags table is on another cluster, so a plain IN in the
    # legacy shape, which filters events on each shard, would make every shard read the tags table again.
    exprs: list[ast.Expr] = []
    if tags_filter.has:
        issues_with_every_tag = _tagged_issues(tags_filter.has)
        # applied_issue_tags_query gives one row for each issue and applied tag, so an issue with every tag in `has`
        # has one row for each distinct key.
        issues_with_every_tag.group_by = [ast.Field(chain=["issue_id"])]
        issues_with_every_tag.having = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Call(name="count", args=[]),
            right=ast.Constant(value=len(set(tags_filter.has))),
        )
        exprs.append(
            ast.CompareOperation(op=ast.CompareOperationOp.GlobalIn, left=issue_id, right=issues_with_every_tag)
        )
    if tags_filter.hasNot:
        # An issue without a tag has no row to select, so `hasNot` uses NOT IN against the tagged issues.
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GlobalNotIn, left=issue_id, right=_tagged_issues(tags_filter.hasNot)
            )
        )
    return exprs


def _tagged_issues(keys: Collection[str]) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Field(chain=["issue_id"])],
        select_from=ast.JoinExpr(table=applied_issue_tags_query(keys)),
    )
