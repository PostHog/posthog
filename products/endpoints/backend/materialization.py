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


@dataclass
class VariableUsageInWhere:
    """Details of how a variable is used in a WHERE clause"""

    column_chain: list[str]
    column_expression: str
    operator: ast.CompareOperationOp
    column_ast: Optional[ast.Expr] = None


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
            variable_usage = find_variable_in_where(ast_node, placeholder)
        except VariableInHavingClauseError:
            return False, "Variable used in HAVING clause are not supported for materialization.", []
        except ValueError as e:
            capture_exception(e)
            return False, "Invalid variable usage in WHERE clause.", []

        if not variable_usage:
            return False, "Variable not used in WHERE clause", []

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
            )
        )

    return True, "OK", result_vars


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


class VariableInWhereFinder(TraversingVisitor):
    """Find how a variable is used in WHERE clause"""

    def __init__(self, target_placeholder: ast.Placeholder):
        super().__init__()
        self.target = target_placeholder
        self.result: Optional[VariableUsageInWhere] = None
        self.in_where = False

    def visit_select_query(self, node: ast.SelectQuery):
        if node.having:
            finder = VariablePlaceholderFinder()
            finder.visit(node.having)
            if any(p.chain == self.target.chain for p in finder.variable_placeholders):
                raise VariableInHavingClauseError()

        if node.where:
            self.in_where = True
            self.visit(node.where)
            self.in_where = False

    def visit_compare_operation(self, node: ast.CompareOperation):
        if not self.in_where:
            return

        field_side = None
        if isinstance(node.right, ast.Placeholder) and node.right.chain == self.target.chain:
            field_side = node.left
        elif isinstance(node.left, ast.Placeholder) and node.left.chain == self.target.chain:
            field_side = node.right

        if not field_side:
            return

        if isinstance(field_side, ast.Field):
            column_chain = [str(item) for item in field_side.chain]
            self.result = VariableUsageInWhere(
                column_chain=column_chain,
                column_expression=".".join(column_chain),
                operator=node.op,
            )
        elif isinstance(field_side, ast.Call):
            column_chain = self._extract_column_chain_from_call(field_side)
            self.result = VariableUsageInWhere(
                column_chain=column_chain,
                column_expression=".".join(column_chain) if column_chain else str(field_side),
                operator=node.op,
                column_ast=field_side if not column_chain else None,
            )

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
    """

    def __init__(self, variable_infos: list[MaterializableVariable]):
        super().__init__()
        self.variable_infos = variable_infos

    def visit_select_query(self, node: ast.SelectQuery):
        new_node = super().visit_select_query(node)

        # Add aliased column per variable to SELECT
        select_additions = [self._create_column_field(var) for var in self.variable_infos]
        if new_node.select:
            new_node.select = [*list(new_node.select), *select_additions]
        else:
            new_node.select = select_additions

        # Add unique columns to GROUP BY (deduplicated by column_chain or expression string)
        # Also skip columns that already exist in the GROUP BY from the original query
        existing_keys: set[str] = set()
        if new_node.group_by:
            for expr in new_node.group_by:
                if isinstance(expr, ast.Field):
                    existing_keys.add(".".join(str(c) for c in expr.chain))

        seen_keys: set[str] = set()
        group_by_additions: list[ast.Expr] = []
        for var in self.variable_infos:
            dedup_key = ".".join(var.column_chain) if var.column_chain else var.column_expression
            if dedup_key not in seen_keys and dedup_key not in existing_keys:
                seen_keys.add(dedup_key)
                group_by_additions.append(self._variable_expr(var))

        if new_node.group_by:
            new_node.group_by = [*list(new_node.group_by), *group_by_additions]
        else:
            new_node.group_by = group_by_additions

        if new_node.where:
            new_node.where = self._remove_variable_from_where(new_node.where)

        return new_node

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

        chain = var.column_chain

        if len(chain) >= 2 and chain[0] == "properties":
            properties_chain: list[str | int] = ["properties"]
            return ast.Call(
                name="JSONExtractString",
                args=[
                    ast.Field(chain=properties_chain),
                    ast.Constant(value=chain[1]),
                ],
            )
        elif len(chain) >= 3 and chain[1] == "properties":
            field_chain: list[str | int] = list(chain[:2])
            return ast.Call(
                name="JSONExtractString",
                args=[ast.Field(chain=field_chain), ast.Constant(value=chain[2])],
            )
        else:
            simple_chain: list[str | int] = list(chain)
            return ast.Field(chain=simple_chain)

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
        return any(
            isinstance(side, ast.Placeholder) and side.chain and side.chain[0] == "variables"
            for side in (node.left, node.right)
        )
