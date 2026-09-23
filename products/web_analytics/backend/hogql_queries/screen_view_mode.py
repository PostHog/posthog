from typing import TYPE_CHECKING, Optional, TypeVar

from posthog.schema import HogQLQueryModifiers, WebAnalyticsScreenViewMode

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

if TYPE_CHECKING:
    from posthog.models import Team

PAGEVIEW_EVENT = "$pageview"
SCREEN_EVENT = "$screen"

QueryT = TypeVar("QueryT", bound=ast.Expr)


def effective_screen_view_mode(
    team: "Team", modifiers: Optional[HogQLQueryModifiers]
) -> Optional[WebAnalyticsScreenViewMode]:
    # Some precompute gates only receive the request modifiers, which do not carry the team setting yet.
    value = modifiers.webAnalyticsScreenViewMode if modifiers else None
    if value is None and isinstance(team.modifiers, dict):
        value = team.modifiers.get("webAnalyticsScreenViewMode")
    if not value:
        return None
    try:
        return WebAnalyticsScreenViewMode(value)
    except ValueError:
        # Team modifiers are stored without validation, and a bad value must not fail every web analytics query.
        return None


def view_event_names(mode: Optional[WebAnalyticsScreenViewMode]) -> tuple[str, ...]:
    if mode == WebAnalyticsScreenViewMode.PAGEVIEWS:
        return (PAGEVIEW_EVENT,)
    if mode == WebAnalyticsScreenViewMode.SCREENS:
        return (SCREEN_EVENT,)
    return (PAGEVIEW_EVENT, SCREEN_EVENT)


def view_event_exprs(mode: Optional[WebAnalyticsScreenViewMode]) -> list[ast.Expr]:
    return [
        ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value=e))
        for e in view_event_names(mode)
    ]


def view_event_expr(mode: Optional[WebAnalyticsScreenViewMode]) -> ast.Expr:
    return ast.Or(exprs=view_event_exprs(mode))


def sessions_view_count_expr(mode: Optional[WebAnalyticsScreenViewMode]) -> ast.Expr:
    count_fields = {PAGEVIEW_EVENT: "$pageview_count", SCREEN_EVENT: "$screen_count"}
    return ast.Or(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["sessions", count_fields[e]]),
                right=ast.Constant(value=0),
            )
            for e in view_event_names(mode)
        ]
    )


def uses_screen_name_as_path(mode: Optional[WebAnalyticsScreenViewMode]) -> bool:
    return mode in (WebAnalyticsScreenViewMode.SCREENS, WebAnalyticsScreenViewMode.PAGEVIEWS_AND_SCREENS)


class _PathnameFallbackVisitor(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        chain = node.chain
        if chain in (["properties", "$pathname"], ["events", "properties", "$pathname"]):
            screen_name = ast.Field(chain=[*chain[:-1], "$screen_name"])
            return ast.Call(
                name="coalesce",
                args=[
                    ast.Call(name="nullIf", args=[ast.Field(chain=list(chain)), ast.Constant(value="")]),
                    screen_name,
                ],
            )
        return super().visit_field(node)


def with_screen_name_path_fallback(query: QueryT, mode: Optional[WebAnalyticsScreenViewMode]) -> QueryT:
    """Read `$screen_name` wherever the query reads an event's `$pathname` and the event has none.

    The rewrite covers the path breakdown, `$pathname` filters and path cleaning together, so a
    screen row in the Paths tile still matches the filter it adds when someone clicks it.
    Session entry and exit paths come from the sessions table and keep using `$pathname` only.
    """
    if not uses_screen_name_as_path(mode):
        return query
    return _PathnameFallbackVisitor().visit(query)
