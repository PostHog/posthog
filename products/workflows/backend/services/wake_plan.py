"""
Derives how a `wait_until_condition` can be woken, so the executor never has to poll to find out.

A wait's condition becomes true for one of two reasons: a message arrived (an event, a person
change) or the clock passed a threshold. The first is observable on a stream. The second produces
no message at all, which is the only reason the 10-minute polling re-check exists.

This analyzes the same compiled expression the runtime evaluates and answers both questions up
front: which streams could carry a satisfying signal, and at which instants the clock alone could
satisfy it. The executor parks to the earliest of those instants still in the future instead of
re-checking on a timer.

Fails closed. If any clock reference isn't provably an invertible threshold, `unsupported_reason`
is set and the caller must keep the wait on the polling path (or reject it at save time) rather
than assume a stream will cover it.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor

# Zero-argument functions whose value advances with wall-clock time.
CLOCK_FUNCTIONS = {"now", "today"}

# Monotonic wrappers we can invert around a clock call, mapped to the function that converts the
# other side of the comparison back into a datetime. `None` means the other side already is one.
# Monotonicity is what makes the inversion valid: if f is increasing, `f(now()) >= f(x)` first
# holds at the same instant `now() >= x` does. Every value here must exist in the HogVM stdlib
# (common/hogvm/typescript/src/stl/stl.ts), since that is what evaluates the emitted bytecode -
# the ClickHouse-only function mapping is not available at runtime.
_INVERTIBLE_WRAPPERS: dict[str, Optional[str]] = {
    "toUnixTimestamp": "fromUnixTimestamp",
}

_GT_OPS = {ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq}
_LT_OPS = {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq}


@dataclass
class WakePlan:
    """How the executor should arrange to be woken for one wait_until_condition."""

    streams: list[str] = field(default_factory=list)
    # Bytecode expressions, each returning an instant at which some clock threshold in the
    # condition flips. The executor evaluates them against the invocation globals and parks to the
    # earliest result still in the future, falling back to max_wait when none is.
    #
    # Deliberately a flat list rather than a combined greatest()/least() expression: waking early
    # is harmless (the condition is re-evaluated and re-parked), whereas waking late means a missed
    # wake. Parking to the earliest future threshold can never sleep through a flip, and it avoids
    # emitting stdlib functions the HogVM may not implement.
    timers: list[list[Any]] = field(default_factory=list)
    unsupported_reason: Optional[str] = None

    @property
    def needs_polling(self) -> bool:
        """True when neither a stream nor a timer can be relied on to wake this wait."""
        return self.unsupported_reason is not None


class _ClockCallCounter(TraversingVisitor):
    def __init__(self) -> None:
        self.count = 0

    def visit_call(self, node: ast.Call) -> None:
        if node.name in CLOCK_FUNCTIONS:
            self.count += 1
        super().visit_call(node)


def _clock_refs(node: ast.Expr) -> int:
    counter = _ClockCallCounter()
    counter.visit(node)
    return counter.count


class _FieldChainCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.chains: list[list[str | int]] = []

    def visit_field(self, node: ast.Field) -> None:
        self.chains.append(node.chain)
        super().visit_field(node)


def _streams_for(node: ast.Expr) -> set[str]:
    collector = _FieldChainCollector()
    collector.visit(node)

    streams: set[str] = set()
    for chain in collector.chains:
        if not chain:
            continue
        root = chain[0]
        if root == "person":
            streams.add("person")
        elif root in ("event", "properties", "elements_chain", "distinct_id", "timestamp"):
            streams.add("event")
    return streams


@dataclass(frozen=True)
class _ClockExpr:
    """
    A sub-expression whose value moves monotonically with the clock.

    `increasing` says which way it moves; `invert` maps the other side of a comparison to the
    instant at which the two sides meet, which is when the comparison flips.
    """

    increasing: bool
    invert: Callable[[ast.Expr], ast.Expr]


def _is_bare_clock(node: ast.Expr) -> bool:
    return isinstance(node, ast.Call) and node.name in CLOCK_FUNCTIONS and not node.args


def _negated(node: ast.Expr) -> ast.Expr:
    # There is no dateSub in the HogVM stdlib, so subtracting an interval means adding a negative one.
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return ast.Constant(value=-node.value)
    return ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Sub, left=ast.Constant(value=0), right=node)


def _clock_expr(node: ast.Expr) -> Optional[_ClockExpr]:
    """Recognize the clock-dependent side of a comparison, or None if this isn't one."""
    if _is_bare_clock(node):
        return _ClockExpr(increasing=True, invert=lambda threshold: threshold)

    if not isinstance(node, ast.Call):
        return None

    # A monotonic wrapper directly around a clock call, e.g. toUnixTimestamp(now()). Nested wrappers
    # would need the composed inverse, which isn't worth guessing.
    if node.name in _INVERTIBLE_WRAPPERS and len(node.args) == 1 and _is_bare_clock(node.args[0]):
        inverse = _INVERTIBLE_WRAPPERS[node.name]
        return _ClockExpr(
            increasing=True,
            invert=lambda threshold: ast.Call(name=inverse, args=[threshold]) if inverse else threshold,
        )

    # dateDiff(unit, start, end) with the clock at one end. "N units since X" grows with time and
    # flips at X + N; "N units until Y" shrinks and flips at Y - N.
    if node.name == "dateDiff" and len(node.args) == 3:
        unit, start, end = node.args
        if _clock_refs(unit):
            return None
        if _is_bare_clock(end) and not _clock_refs(start):
            return _ClockExpr(
                increasing=True,
                invert=lambda amount: ast.Call(name="dateAdd", args=[unit, amount, start]),
            )
        if _is_bare_clock(start) and not _clock_refs(end):
            return _ClockExpr(
                increasing=False,
                invert=lambda amount: ast.Call(name="dateAdd", args=[unit, _negated(amount), end]),
            )

    return None


def _threshold_from_comparison(node: ast.CompareOperation) -> Optional[ast.Expr]:
    """
    Invert a clock comparison into the instant it starts holding.

    Returns None when the comparison isn't a clock threshold we can invert.
    """
    left = _clock_expr(node.left)
    right = _clock_expr(node.right)

    if left is not None and right is None:
        if _clock_refs(node.right):
            return None
        # On the left, an increasing side flips as it climbs past the threshold; a decreasing one as
        # it falls below. On the right the roles swap.
        wanted = _GT_OPS if left.increasing else _LT_OPS
        return left.invert(node.right) if node.op in wanted else None

    if right is not None and left is None:
        if _clock_refs(node.left):
            return None
        wanted = _LT_OPS if right.increasing else _GT_OPS
        return right.invert(node.left) if node.op in wanted else None

    return None


def _collect_thresholds(node: ast.Expr) -> tuple[list[ast.Expr], Optional[str]]:
    """
    Find every clock threshold in the expression.

    Returns (thresholds, unsupported_reason). Descends only through boolean structure: a clock
    reference anywhere else can't be turned into an instant, so it fails closed. Every clock
    reference must be accounted for, which is what makes a clean result trustworthy.
    """
    if not _clock_refs(node):
        return [], None

    if isinstance(node, ast.CompareOperation):
        threshold = _threshold_from_comparison(node)
        if threshold is None:
            return [], "clock comparison is not an invertible threshold"
        return [threshold], None

    if isinstance(node, ast.And | ast.Or):
        thresholds: list[ast.Expr] = []
        for child in node.exprs:
            child_thresholds, reason = _collect_thresholds(child)
            if reason is not None:
                return [], reason
            thresholds.extend(child_thresholds)
        return thresholds, None

    # A clock reference under Not, arithmetic, a function call, or anything else: we can't say when
    # it flips, so don't pretend to.
    return [], f"clock reference in unsupported position ({type(node).__name__})"


def analyze_wait_condition(condition_expr: ast.Expr, team_id: int) -> WakePlan:
    """
    Build the wake plan for one wait_until_condition.

    `condition_expr` is the compiled filter expression, the same AST that becomes the bytecode the
    matcher and executor evaluate, so the plan can't drift from what actually runs.
    """
    plan = WakePlan(streams=sorted(_streams_for(condition_expr)))

    thresholds, reason = _collect_thresholds(condition_expr)
    if reason is not None:
        plan.unsupported_reason = reason
        return plan

    context = HogQLContext(team_id=team_id)
    plan.timers = [create_bytecode(threshold, context=context).bytecode for threshold in thresholds]
    return plan
