from typing import Any

import pytest

from posthog.hogql import ast

from products.signals.backend.contracts import AdmissionRuleGroup
from products.signals.backend.emission.admission import compile_admission_rules

FIELDS: dict[str, ast.Expr] = {
    "labels": ast.Field(chain=["labels"]),
    "priority": ast.Field(chain=["priority"]),
    "state_name": ast.Field(chain=["state_name"]),
}


def _rule(field: str, operator: str, value: Any) -> dict[str, Any]:
    return {"field": field, "operator": operator, "value": value}


def _compile(group: dict[str, Any]) -> str | None:
    expr = compile_admission_rules(AdmissionRuleGroup.model_validate(group), FIELDS)
    return None if expr is None else expr.to_hogql()


@pytest.mark.parametrize(
    "rule,expected",
    [
        (_rule("labels", "any", ["bug", "ux"]), "hasAny(labels, ['bug', 'ux'])"),
        (_rule("labels", "all", ["bug", "ux"]), "hasAll(labels, ['bug', 'ux'])"),
        (_rule("labels", "none", ["chore"]), "not(hasAny(labels, ['chore']))"),
        (_rule("priority", "eq", 1), "equals(priority, 1)"),
        (_rule("state_name", "neq", "Done"), "notEquals(state_name, 'Done')"),
        (_rule("priority", "in", [1, 2]), "in(priority, tuple(1, 2))"),
        (_rule("state_name", "not_in", ["Done", "Backlog"]), "notIn(state_name, tuple('Done', 'Backlog'))"),
    ],
)
def test_compiles_each_operator(rule, expected):
    assert _compile({"operator": "AND", "rules": [rule]}) == expected


@pytest.mark.parametrize(
    "group,expected",
    [
        ({"operator": "AND", "rules": []}, None),
        (
            {"operator": "OR", "rules": [_rule("priority", "eq", 1), {"operator": "AND", "rules": []}]},
            None,
        ),
        (
            {"operator": "AND", "rules": [_rule("priority", "eq", 1), {"operator": "OR", "rules": []}]},
            "equals(priority, 1)",
        ),
        (
            {
                "operator": "AND",
                "rules": [
                    _rule("labels", "any", ["bug"]),
                    {"operator": "OR", "rules": [_rule("priority", "eq", 1), _rule("state_name", "eq", "Triage")]},
                ],
            },
            "and(hasAny(labels, ['bug']), or(equals(priority, 1), equals(state_name, 'Triage')))",
        ),
    ],
)
def test_empty_groups_admit_everything(group, expected):
    assert _compile(group) == expected
