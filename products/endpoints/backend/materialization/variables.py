from typing import Optional

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from products.endpoints.backend.materialization.types import VariableInHavingClauseError, VariableUsageInWhere


class VariablePlaceholderFinder(TraversingVisitor):
    """Find all variable placeholders in the AST"""

    def __init__(self):
        super().__init__()
        self.variable_placeholders: list[ast.Placeholder] = []

    def visit_placeholder(self, node: ast.Placeholder):
        if node.chain and node.chain[0] == "variables":
            self.variable_placeholders.append(node)


def find_variable_in_where(
    ast_node: ast.SelectQuery | ast.SelectSetQuery, placeholder: ast.Placeholder
) -> Optional[VariableUsageInWhere]:
    """
    Walk AST to find where the placeholder is used in WHERE clause.
    Returns column being compared and operator.
    """
    if not isinstance(ast_node, ast.SelectQuery):
        return None
    finder = VariableInWhereFinder(placeholder)
    finder.visit(ast_node)
    return finder.result


def find_all_variable_usages(
    ast_node: ast.SelectQuery | ast.SelectSetQuery, placeholder: ast.Placeholder
) -> list[tuple[Optional[str], VariableUsageInWhere]]:
    """Find all usages of a variable in WHERE clauses, including inside CTEs.

    Returns list of (cte_name, usage) tuples. cte_name is None for top-level query.
    """
    if not isinstance(ast_node, ast.SelectQuery):
        return []
    finder = VariableInWhereFinder(placeholder)
    finder.visit(ast_node)
    return finder.all_results


class VariableInWhereFinder(TraversingVisitor):
    """Find how a variable is used in WHERE clause, including inside CTEs."""

    def __init__(self, target_placeholder: ast.Placeholder):
        super().__init__()
        self.target = target_placeholder
        self.all_results: list[tuple[Optional[str], VariableUsageInWhere]] = []
        self.in_where = False
        self._current_cte_name: Optional[str] = None

    @property
    def result(self) -> Optional[VariableUsageInWhere]:
        """Backward-compat: return first match's usage."""
        return self.all_results[0][1] if self.all_results else None

    def visit_select_query(self, node: ast.SelectQuery):
        if node.having:
            finder = VariablePlaceholderFinder()
            finder.visit(node.having)
            if any(p.chain == self.target.chain for p in finder.variable_placeholders):
                raise VariableInHavingClauseError()

        # Visit CTEs first (they're part of this SelectQuery)
        if node.ctes:
            for cte_name, cte in node.ctes.items():
                prev_cte = self._current_cte_name
                self._current_cte_name = cte_name
                self.visit(cte.expr)
                self._current_cte_name = prev_cte

        if node.where:
            self.in_where = True
            self.visit(node.where)
            self.in_where = False

    def visit_compare_operation(self, node: ast.CompareOperation):
        if not self.in_where:
            return

        field_side = None
        variable_side = None
        if self._contains_target_placeholder(node.right):
            field_side = node.left
            variable_side = node.right
        elif self._contains_target_placeholder(node.left):
            field_side = node.right
            variable_side = node.left

        if not field_side:
            return

        wrapper_fns = self._extract_wrapper_fns(variable_side)

        if isinstance(field_side, ast.Field):
            column_chain = [str(item) for item in field_side.chain]
            self.all_results.append(
                (
                    self._current_cte_name,
                    VariableUsageInWhere(
                        column_chain=column_chain,
                        column_expression=".".join(column_chain),
                        operator=node.op,
                        value_wrapper_fns=wrapper_fns,
                    ),
                )
            )
        elif isinstance(field_side, ast.Call):
            column_chain = self._extract_column_chain_from_call(field_side)
            self.all_results.append(
                (
                    self._current_cte_name,
                    VariableUsageInWhere(
                        column_chain=column_chain,
                        column_expression=".".join(column_chain) if column_chain else str(field_side),
                        operator=node.op,
                        column_ast=field_side if not column_chain else None,
                        value_wrapper_fns=wrapper_fns,
                    ),
                )
            )

    def _contains_target_placeholder(self, node: ast.Expr) -> bool:
        """Check if an expression is or contains the target placeholder (e.g. inside toDate(...))."""
        if isinstance(node, ast.Placeholder) and node.chain == self.target.chain:
            return True
        if isinstance(node, ast.Call):
            return any(self._contains_target_placeholder(arg) for arg in node.args)
        return False

    @staticmethod
    def _extract_wrapper_fns(node: Optional[ast.Expr]) -> Optional[list[str]]:
        """Extract the chain of wrapping function names from outermost to innermost.

        For toDate(toStartOfMonth({variables.x})), returns ["toDate", "toStartOfMonth"].
        """
        fns: list[str] = []
        current = node
        while isinstance(current, ast.Call) and len(current.args) == 1:
            fns.append(current.name)
            current = current.args[0]
        return fns or None

    def _extract_column_chain_from_call(self, call: ast.Call) -> list[str]:
        if call.name == "JSONExtractString" and len(call.args) >= 2:
            if isinstance(call.args[0], ast.Field) and isinstance(call.args[1], ast.Constant):
                field_chain = [str(item) for item in call.args[0].chain]
                return [*field_chain, str(call.args[1].value)]
        return []
