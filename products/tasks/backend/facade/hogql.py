"""Tasks' federated HogQL visibility predicates for `system.tasks` and `system.task_runs`.

Owned here rather than in core so the HogQL schema mirrors the exact read gate the Tasks
REST API enforces (`task_visibility_q` in ``visibility.py``): personal-channel ("#me") tasks
stay creator-only, while team-readable origins and public-channel tasks are visible to the
whole team. Core `schema/system.py` imports these builders instead of hardcoding the
product's origin-product list, channel semantics, or the internal-task exclusion.
"""

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.parser import parse_expr

from products.tasks.backend.models import Channel
from products.tasks.backend.visibility import TEAM_READABLE_ORIGIN_PRODUCTS


def task_visibility_predicates(user_id: int | None) -> list[Expr]:
    """HogQL predicates for `system.tasks`, mirroring ``task_visibility_q(user_id)``.

    A task is readable when the querying user created it, it is unowned (legacy tasks),
    its origin is team-readable (signals/onboarding/experiments/…), or it lives in a
    public, non-deleted channel. The public-channel term scopes through
    ``system.task_channels``, which the printer re-applies its own team_id guard to.

    ``internal != true`` stays a separate predicate so it AND-combines with visibility,
    keeping internal pipeline tasks out entirely.
    """
    visible_terms: list[Expr] = [
        # Legacy unowned tasks stay team-visible (they can't be executed — oauth needs a creator).
        parse_expr("created_by_id IS NULL"),
        ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["origin_product"]),
            right=ast.Constant(value=[str(product) for product in TEAM_READABLE_ORIGIN_PRODUCTS]),
        ),
        # `NOT deleted` rather than `deleted = 0`: the predicate is pushed into the federated
        # PostgreSQL query, where comparing a boolean column to an integer literal is a type error.
        parse_expr(
            "channel_id IN (SELECT id FROM system.task_channels WHERE channel_type = {public} AND NOT deleted)",
            placeholders={"public": ast.Constant(value=str(Channel.ChannelType.PUBLIC))},
        ),
    ]
    if user_id is not None:
        visible_terms.insert(
            0,
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["created_by_id"]),
                right=ast.Constant(value=user_id),
            ),
        )

    return [parse_expr("internal != true"), ast.Or(exprs=visible_terms)]


def task_run_visibility_predicates() -> list[Expr]:
    """HogQL predicate for `system.task_runs`, mirroring ``task_run_visibility_q``.

    A run is readable iff its parent task is. Scoping through ``system.tasks`` inherits both
    its visibility gate and its internal-task exclusion, so internal pipeline runs never
    surface either — no separate ``internal`` predicate is needed here.
    """
    return [parse_expr("task_id IN (SELECT id FROM system.tasks)")]
