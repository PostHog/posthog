"""
Detects `wait_until_condition` conditions that nothing can ever wake.

A wait is woken by the subscription matcher when a message arrives on one of its streams: an event,
a person change, an internal event, a distinct_id repoint. A condition that compares against the
clock produces no message at all, so such a wait sits until its max_wait_duration and then takes the
timeout edge, whatever the condition says by then.

Rejecting these at save time is what makes the matcher sufficient: express the same intent with a
delay step and a condition that guards it, and the wait is woken by something that actually
happens.
"""

import re
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


# The matcher keys its streams on person and distinct_id only, so a group change carries nothing it
# can look a parked job up by.
GROUP_FIELD_RE = re.compile(r"^group_\d+$")


class _GroupFieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found: Optional[str] = None
        # A lambda argument can shadow a group name, as in arrayExists(group_0 -> group_0 = 'pro', xs).
        self.bound: set[str] = set()

    def visit_lambda(self, node: ast.Lambda) -> None:
        added = {arg for arg in node.args if arg not in self.bound}
        self.bound |= added
        try:
            super().visit_lambda(node)
        finally:
            self.bound -= added

    def visit_field(self, node: ast.Field) -> None:
        if self.found is None and self._reads_group_property(node):
            self.found = str(node.chain[0])
        super().visit_field(node)

    def visit_array_access(self, node: ast.ArrayAccess) -> None:
        # Bracket notation reaches the same property as the dotted form: group_0['properties'] parses
        # as an ArrayAccess around a bare group_0 field, which visit_field alone would let through.
        if (
            self.found is None
            and isinstance(node.array, ast.Field)
            and len(node.array.chain) == 1
            and isinstance(node.property, ast.Constant)
            and node.property.value == "properties"
            and self._is_group_root(str(node.array.chain[0]))
        ):
            self.found = str(node.array.chain[0])
        super().visit_array_access(node)

    def _is_group_root(self, root: str) -> bool:
        return root not in self.bound and bool(GROUP_FIELD_RE.match(root))

    def _reads_group_property(self, node: ast.Field) -> bool:
        # A group property is always read as group_<index>.properties.<key>, so a bare name is a
        # local or an unrelated identifier rather than the group the matcher cannot observe.
        if len(node.chain) < 2 or str(node.chain[1]) != "properties":
            return False
        return self._is_group_root(str(node.chain[0]))


def find_group_field(condition_expr: ast.Expr) -> Optional[str]:
    """Name of the first group field the expression reads, or None if it reads none."""
    finder = _GroupFieldFinder()
    finder.visit(condition_expr)
    return finder.found
