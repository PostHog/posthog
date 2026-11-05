from posthog.hogql import ast

ENVIRONMENT_KEYS: tuple[str, ...] = ("deployment.environment.name", "deployment.environment", "env")
UNLABELED_ENVIRONMENT = "(none)"


def _resource_attribute(key: str) -> ast.Expr:
    return ast.Call(name="arrayElement", args=[ast.Field(chain=["resource_attributes"]), ast.Constant(value=key)])


def environment_expr() -> ast.Expr:
    expr = _resource_attribute(ENVIRONMENT_KEYS[-1])
    for key in reversed(ENVIRONMENT_KEYS[:-1]):
        is_set = ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq, left=_resource_attribute(key), right=ast.Constant(value="")
        )
        expr = ast.Call(name="if", args=[is_set, _resource_attribute(key), expr])
    return expr


def _matches(column: ast.Expr, environment: str) -> ast.Expr:
    value = "" if environment.strip() == UNLABELED_ENVIRONMENT else environment.strip().lower()
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq, left=ast.Call(name="lower", args=[column]), right=ast.Constant(value=value)
    )


def environment_filter_expr(environment: str) -> ast.Expr:
    return _matches(environment_expr(), environment)


def rollup_environment_filter_expr(environment: str) -> ast.Expr:
    return _matches(ast.Field(chain=["environment"]), environment)
