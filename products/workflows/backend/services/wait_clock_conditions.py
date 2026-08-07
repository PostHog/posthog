"""
Detects `wait_until_condition` conditions that only the polling re-check could ever satisfy.

A wait is woken by the subscription matcher when a message arrives on one of its streams: an event,
a person change, an internal event, a distinct_id repoint. A condition that compares against the
clock produces no message at all, so nothing wakes it. The 10-minute polling re-check is what has
been covering that gap, and it re-parks every wait in the fleet to do it.

Rejecting these at save time is what lets the poll go: express the same intent with a delay step and
a condition that guards it, and the wait is woken by something that actually happens.
"""

from typing import Optional

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

# Zero-argument functions whose value advances with wall-clock time. A condition built on one of
# these changes truth value without anything happening, which is exactly what no stream can report.
CLOCK_FUNCTIONS = {"now", "today"}


class _ClockCallFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found: Optional[str] = None

    def visit_call(self, node: ast.Call) -> None:
        if self.found is None and node.name in CLOCK_FUNCTIONS:
            self.found = node.name
        super().visit_call(node)


def find_clock_function(condition_expr: ast.Expr) -> Optional[str]:
    """Name of the first clock function the expression calls, or None if it calls none."""
    finder = _ClockCallFinder()
    finder.visit(condition_expr)
    return finder.found
