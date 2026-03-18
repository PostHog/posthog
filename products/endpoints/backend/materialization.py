from dataclasses import dataclass
from typing import Any, Optional

from posthog.schema import HogQLQuery, HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team import Team


class VariableInHavingClauseError(ValueError):
    """Raised when a variable is used in a HAVING clause, which is not supported for materialization."""


def convert_insight_query_to_hogql(query: dict[str, Any], team: Team) -> dict[str, Any]:
    query_kind = query.get("kind")

    if query_kind == "HogQLQuery":
        return query

    query_runner = get_query_runner(
        query=query,
        team=team,
        timings=HogQLTimings(),
        modifiers=HogQLQueryModifiers(),
    )

    combined_query_ast = query_runner.to_query()

    hogql_string = to_printed_hogql(combined_query_ast, team=team, modifiers=query_runner.modifiers)

    result = HogQLQuery(query=hogql_string, modifiers=query_runner.modifiers).model_dump()
    if "variables" in query:
        result["variables"] = query["variables"]
    return result


@dataclass
class MaterializableVariable:
    """Info about a variable that can be materialized"""

    variable_id: str
    code_name: str
    column_chain: list[str]
    column_expression: str
    operator: ast.CompareOperationOp = ast.CompareOperationOp.Eq
    column_ast: Optional[ast.Expr] = None
    value_wrapper_fns: Optional[list[str]] = None
    cte_name: Optional[str] = None  # CTE containing the variable; None = top-level query


@dataclass
class VariableUsageInWhere:
    """Details of how a variable is used in a WHERE clause"""

    column_chain: list[str]
    column_expression: str
    operator: ast.CompareOperationOp
    column_ast: Optional[ast.Expr] = None
    value_wrapper_fns: Optional[list[str]] = None


SUPPORTED_MATERIALIZATION_OPS = frozenset(
    {
        ast.CompareOperationOp.Eq,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
        ast.CompareOperationOp.Like,
        ast.CompareOperationOp.ILike,
        ast.CompareOperationOp.NotLike,
        ast.CompareOperationOp.NotILike,
    }
)


def analyze_variables_for_materialization(
    hogql_query: dict[str, Any],
) -> tuple[bool, str, list[MaterializableVariable]]:
    """
    Check if query variables can be materialized.

    Each variable must be used in a WHERE clause with a supported operator
    (=, >=, >, <, <=). Multiple variables are supported.

    Returns:
        (can_materialize, reason, variable_infos)
    """
    query_str = hogql_query.get("query")
    if not query_str:
        return False, "No query string found", []

    try:
        ast_node = parse_select(query_str)
    except Exception as e:
        capture_exception(e)
        return False, "Failed to parse query.", []

    finder = VariablePlaceholderFinder()
    finder.visit(ast_node)

    if not finder.variable_placeholders:
        return False, "No variables found", []

    variables_dict = hogql_query.get("variables", {})
    result_vars: list[MaterializableVariable] = []
    seen_code_names: set[str] = set()

    for placeholder in finder.variable_placeholders:
        if not placeholder.chain or len(placeholder.chain) < 2:
            return False, "Invalid variable placeholder format", []

        code_name = str(placeholder.chain[1])
        if code_name in seen_code_names:
            continue
        seen_code_names.add(code_name)

        try:
            all_usages = find_all_variable_usages(ast_node, placeholder)
        except VariableInHavingClauseError:
            return False, "Variable used in HAVING clause are not supported for materialization.", []
        except ValueError as e:
            capture_exception(e)
            return False, "Invalid variable usage in WHERE clause.", []

        if not all_usages:
            return False, "Variable not used in WHERE clause", []

        # Determine CTE context for this variable
        cte_names = {cte_name for cte_name, _ in all_usages}
        if len(cte_names) > 1:
            # Variable used in multiple different locations (e.g. two CTEs, or CTE + top-level)
            has_top_level = None in cte_names
            has_cte = any(n is not None for n in cte_names)
            if has_top_level and has_cte:
                return False, "Variable used in both CTE and top-level query is not yet supported", []
            return False, "Variable used in multiple CTEs is not yet supported", []

        cte_name = next(iter(cte_names))
        # Use the first usage for column info (all usages of the same variable should be consistent)
        variable_usage = all_usages[0][1]

        if variable_usage.operator not in SUPPORTED_MATERIALIZATION_OPS:
            return (
                False,
                f"Unsupported operator {variable_usage.operator}, supported: =, >=, >, <, <=",
                [],
            )

        variable_id = next(
            (var_id for var_id, var_data in variables_dict.items() if var_data.get("code_name") == code_name),
            None,
        )

        if not variable_id:
            return False, "Variable metadata not found", []

        result_vars.append(
            MaterializableVariable(
                variable_id=variable_id,
                code_name=code_name,
                column_chain=variable_usage.column_chain,
                column_expression=variable_usage.column_expression,
                operator=variable_usage.operator,
                column_ast=variable_usage.column_ast,
                value_wrapper_fns=variable_usage.value_wrapper_fns,
                cte_name=cte_name,
            )
        )

    # Safety check: CTE variables + top-level JOINs produce wrong results.
    # Removing a CTE's WHERE changes its row cardinality, which changes JOIN
    # output. Filtering after materialization can't recover the original semantics
    # (e.g. LEFT JOIN non-matches get NULL for the variable column and are lost).
    has_cte_vars = any(v.cte_name is not None for v in result_vars)
    if has_cte_vars and isinstance(ast_node, ast.SelectQuery) and _has_joins(ast_node):
        return False, "CTE variables with JOINs in the top-level query are not supported for materialization", []

    return True, "OK", result_vars


def _has_joins(node: ast.SelectQuery) -> bool:
    """Check if a SelectQuery has any JOINs (next_join on select_from)."""
    return node.select_from is not None and node.select_from.next_join is not None


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


def transform_select_for_materialized_table(select_exprs: list[ast.Expr], team: Team) -> list[ast.Expr]:
    """
    Transform SELECT expressions to reference pre-computed columns in materialized table.

    The materialized table has pre-aggregated data, so we need to select the
    column names directly instead of re-computing expressions.

    Examples:
    - count() -> Field(chain=["count()"])
    - count() as total -> Field(chain=["total"])
    - toStartOfDay(timestamp) as date -> Field(chain=["date"])
    """
    transformed: list[ast.Expr] = []
    for expr in select_exprs:
        if isinstance(expr, ast.Alias):
            transformed.append(ast.Field(chain=[expr.alias]))
        else:
            expr_str = expr.to_hogql()
            transformed.append(ast.Field(chain=[expr_str]))

    return transformed


def transform_query_for_materialization(
    hogql_query: dict[str, Any],
    variable_infos: MaterializableVariable | list[MaterializableVariable],
    team: Team,
) -> dict[str, Any]:
    """
    Transform query by:
    1. Removing WHERE clauses with variables
    2. Adding variable columns to SELECT (aliased by code_name) and GROUP BY (deduplicated)

    Example (single):
        Before: SELECT count(), date FROM events WHERE event = {variables.event_name} GROUP BY date
        After:  SELECT count(), date, event AS event_name FROM events GROUP BY date, event

    Example (multi, same column):
        Before: SELECT count() FROM events WHERE hour >= {variables.start} AND hour < {variables.end}
        After:  SELECT count(), hour AS start, hour AS end FROM events GROUP BY hour
    """
    if isinstance(variable_infos, MaterializableVariable):
        variable_infos = [variable_infos]

    query_str = hogql_query.get("query")
    if not query_str:
        raise ValueError("No query string found")
    parsed_ast = parse_select(query_str)

    transformer = MaterializationTransformer(variable_infos)
    transformed_ast = transformer.visit(parsed_ast)

    transformed_query_str = to_printed_hogql(transformed_ast, team=team)

    return {
        **hogql_query,
        "query": transformed_query_str,
        "variables": {},
    }


class MaterializationTransformer(CloningVisitor):
    """AST transformer that removes variable WHERE clauses and adds columns to SELECT and GROUP BY.

    Each variable gets an aliased column in SELECT (aliased by code_name).
    GROUP BY is deduplicated by column_chain to handle same-column range variables
    (e.g., hour >= start AND hour < end → GROUP BY hour, not GROUP BY hour, hour).

    CTE-aware: when variables live in a CTE, the CTE gets the column addition + WHERE removal,
    and the top-level query gets a passthrough column from the CTE.
    """

    def __init__(self, variable_infos: list[MaterializableVariable]):
        super().__init__()
        self.variable_infos = variable_infos
        self._current_cte_name: Optional[str] = None

    def visit_select_query(self, node: ast.SelectQuery):
        new_ctes = self._process_ctes(node)

        # Visit the select query itself (without re-visiting CTEs)
        original_ctes = node.ctes
        node.ctes = None
        new_node = super().visit_select_query(node)
        node.ctes = original_ctes  # Restore original
        new_node.ctes = new_ctes

        # Add variable columns + remove variable WHERE clauses for current context
        vars_for_context = self._vars_for_current_context()
        if vars_for_context:
            self._add_variable_columns(new_node, vars_for_context)

        # Top-level query: add passthrough columns for CTE variables
        cte_vars = [v for v in self.variable_infos if v.cte_name is not None]
        if self._current_cte_name is None and cte_vars:
            self._add_cte_passthrough_columns(new_node, cte_vars)

        return new_node

    def _process_ctes(self, node: ast.SelectQuery) -> Optional[dict[str, ast.CTE]]:
        """Process CTEs with proper context tracking, returning transformed CTE dict."""
        if not node.ctes:
            return None
        new_ctes: dict[str, ast.CTE] = {}
        for cte_name, cte in node.ctes.items():
            prev_cte = self._current_cte_name
            self._current_cte_name = cte_name
            new_expr = self.visit(cte.expr)
            self._current_cte_name = prev_cte
            new_ctes[cte_name] = ast.CTE(name=cte_name, expr=new_expr, cte_type=cte.cte_type)
        return new_ctes

    def _add_variable_columns(self, node: ast.SelectQuery, vars_for_context: list[MaterializableVariable]) -> None:
        """Add aliased variable columns to SELECT, update GROUP BY, and remove variable WHERE clauses."""
        select_additions = [self._create_column_field(var) for var in vars_for_context]
        if node.select:
            node.select = [*list(node.select), *select_additions]
        else:
            node.select = select_additions

        if node.group_by is not None or self._current_cte_name is None:
            self._add_group_by(node, vars_for_context)

        if node.where:
            node.where = self._remove_variable_from_where(node.where)

    def _add_cte_passthrough_columns(self, node: ast.SelectQuery, cte_vars: list[MaterializableVariable]) -> None:
        """Add passthrough columns + GROUP BY at top level for CTE-resident variables."""
        passthrough_additions: list[ast.Expr] = [ast.Field(chain=[var.code_name]) for var in cte_vars]
        if node.select:
            node.select = [*list(node.select), *passthrough_additions]
        else:
            node.select = passthrough_additions

        if node.group_by is not None or self._has_aggregate_functions(node):
            self._add_group_by(node, cte_vars, use_field_ref=True)

    @staticmethod
    def _has_aggregate_functions(node: ast.SelectQuery) -> bool:
        """Check if any SELECT expression uses an aggregate function (sum, count, avg, etc.)."""
        from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS

        agg_names = set(HOGQL_AGGREGATIONS.keys())

        class AggFinder(TraversingVisitor):
            def __init__(self):
                super().__init__()
                self.found = False

            def visit_call(self, node: ast.Call):
                if node.name in agg_names:
                    self.found = True
                else:
                    super().visit_call(node)

        finder = AggFinder()
        for expr in node.select or []:
            finder.visit(expr)
            if finder.found:
                return True
        return False

    def _vars_for_current_context(self) -> list[MaterializableVariable]:
        """Return variables that apply to the current CTE/top-level context."""
        return [v for v in self.variable_infos if v.cte_name == self._current_cte_name]

    def _add_group_by(
        self,
        node: ast.SelectQuery,
        vars_to_add: list[MaterializableVariable],
        use_field_ref: bool = False,
    ) -> None:
        """Add unique columns to GROUP BY, deduplicating by column_chain."""
        existing_keys: set[str] = set()
        if node.group_by:
            for expr in node.group_by:
                if isinstance(expr, ast.Field):
                    existing_keys.add(".".join(str(c) for c in expr.chain))

        seen_keys: set[str] = set()
        group_by_additions: list[ast.Expr] = []
        for var in vars_to_add:
            dedup_key = ".".join(var.column_chain) if var.column_chain else var.column_expression
            if use_field_ref:
                dedup_key = var.code_name
            if dedup_key not in seen_keys and dedup_key not in existing_keys:
                seen_keys.add(dedup_key)
                if use_field_ref:
                    group_by_additions.append(ast.Field(chain=[var.code_name]))
                else:
                    group_by_additions.append(self._variable_expr(var))

        if node.group_by:
            node.group_by = [*list(node.group_by), *group_by_additions]
        elif group_by_additions:
            node.group_by = group_by_additions

    def _create_column_field(self, var: MaterializableVariable) -> ast.Expr:
        return ast.Alias(
            alias=var.code_name,
            expr=self._variable_expr(var),
        )

    @staticmethod
    def _variable_expr(var: MaterializableVariable) -> ast.Expr:
        """Expression used for the variable column without aliasing.

        Uses the original AST expression when available (e.g. for function calls
        like toDate(timestamp) that can't be reconstructed from column_chain).
        Always returns a fresh copy to avoid sharing AST nodes between SELECT and GROUP BY.
        """
        if var.column_ast is not None:
            return CloningVisitor().visit(var.column_ast)
        return ast.Field(chain=list(var.column_chain))

    def _remove_variable_from_where(self, where_node: Optional[ast.Expr]) -> Optional[ast.Expr]:
        if where_node is None:
            return None

        if isinstance(where_node, ast.CompareOperation):
            return None if self._is_variable_comparison(where_node) else where_node

        if isinstance(where_node, ast.And):
            filtered_exprs = [
                expr
                for expr in where_node.exprs
                if not (isinstance(expr, ast.CompareOperation) and self._is_variable_comparison(expr))
            ]
            if not filtered_exprs:
                return None
            if len(filtered_exprs) == 1:
                return filtered_exprs[0]
            return ast.And(exprs=filtered_exprs)

        if isinstance(where_node, ast.Or):
            raise ValueError("Variables in OR conditions not supported")

        return where_node

    def _is_variable_comparison(self, node: ast.CompareOperation) -> bool:
        return any(self._expr_contains_variable(side) for side in (node.left, node.right))

    def _expr_contains_variable(self, node: ast.Expr) -> bool:
        if isinstance(node, ast.Placeholder) and node.chain and node.chain[0] == "variables":
            return True
        if isinstance(node, ast.Call):
            return any(self._expr_contains_variable(arg) for arg in node.args)
        return False
