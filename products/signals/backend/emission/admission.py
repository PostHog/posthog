from collections.abc import Mapping
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.signals.backend.contracts import (
    ADMISSION_RULE_FIELDS,
    ADMISSION_RULES_KEY,
    AdmissionRule,
    AdmissionRuleGroup,
    parse_admission_rules,
)
from products.signals.backend.emission.registry import SignalSourceTableConfig


class InvalidAdmissionRulesError(ValueError):
    """The stored admission rules do not parse. The fetcher raises this instead of reading every
    record, so a broken filter fails the run and admits nothing."""


def admission_filter_from_source_config(config: SignalSourceTableConfig, source_config: Any) -> ast.Expr | None:
    """The HogQL filter for the team's admission rules, or None when no rule narrows the read."""
    if not config.admission_fields or not isinstance(source_config, dict):
        return None
    raw = source_config.get(ADMISSION_RULES_KEY)
    if raw is None:
        return None
    group, problem = parse_admission_rules(raw, ADMISSION_RULE_FIELDS[(config.source_product, config.source_type)])
    if group is None:
        raise InvalidAdmissionRulesError(f"{ADMISSION_RULES_KEY} {problem}")
    field_exprs = {field: parse_expr(expr) for field, expr in config.admission_fields.items()}
    return compile_admission_rules(group, field_exprs)


def compile_admission_rules(group: AdmissionRuleGroup, field_exprs: Mapping[str, ast.Expr]) -> ast.Expr | None:
    """Compile a validated rule tree to a HogQL expression. None means the tree admits every record:
    an empty group puts no constraint on its parent."""
    compiled = [
        compile_admission_rules(rule, field_exprs)
        if isinstance(rule, AdmissionRuleGroup)
        else _compile_rule(rule, field_exprs[rule.field])
        for rule in group.rules
    ]
    if group.operator == "OR" and any(expr is None for expr in compiled):
        return None
    exprs = [expr for expr in compiled if expr is not None]
    if not exprs:
        return None
    if len(exprs) == 1:
        return exprs[0]
    return ast.And(exprs=exprs) if group.operator == "AND" else ast.Or(exprs=exprs)


def _compile_rule(rule: AdmissionRule, field: ast.Expr) -> ast.Expr:
    values = rule.value if isinstance(rule.value, list) else [rule.value]
    constants: list[ast.Expr] = [ast.Constant(value=value) for value in values]
    match rule.operator:
        case "any":
            return ast.Call(name="hasAny", args=[field, ast.Array(exprs=constants)])
        case "all":
            return ast.Call(name="hasAll", args=[field, ast.Array(exprs=constants)])
        case "none":
            return ast.Not(expr=ast.Call(name="hasAny", args=[field, ast.Array(exprs=constants)]))
        case "eq":
            return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=field, right=constants[0])
        case "neq":
            return ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=field, right=constants[0])
        case "in":
            return ast.CompareOperation(op=ast.CompareOperationOp.In, left=field, right=ast.Tuple(exprs=constants))
        case "not_in":
            return ast.CompareOperation(op=ast.CompareOperationOp.NotIn, left=field, right=ast.Tuple(exprs=constants))
