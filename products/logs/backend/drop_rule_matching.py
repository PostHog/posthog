from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import re2

from products.logs.backend.models import LogsExclusionRule

# Three-valued logic for evaluating a drop rule against a *partial* log record at query time.
# When faceting we know exactly one field of the record (the facet's column or resource attribute);
# every other predicate (severity, arbitrary attributes, request path) varies per log line and is
# INDETERMINATE. A leaf or group resolves to:
#   _TRUE          — provably matches some log with this facet value
#   _FALSE         — provably cannot match any log with this facet value
#   _INDETERMINATE — depends on fields we don't know yet
# The Node ingestion worker (nodejs/src/logs/sampling/) is the source of truth for per-record drop
# decisions; this only decides whether a rule *could* drop logs carrying a given facet value, mirroring
# the established Services-tab logic (rule_could_apply_to_service) generalized to every facet dimension.
_FALSE, _INDETERMINATE, _TRUE = -1, 0, 1

# Keys the ingestion worker treats as the service name / severity (see lookupRecordValue in
# nodejs/src/logs/sampling/filter-group-match.ts). The drop-rule builder writes `severity_level`.
_SERVICE_NAME_KEYS = {"service_name", "service.name"}
_SEVERITY_KEYS = {"severity_text", "severity_level", "level", "severity"}

# severity_text values bucketed onto the four ordinals severity_sampling rules act on
# (matches severityOrdinalFromRecord + parseSeverityActions in the ingestion worker).
_SEVERITY_BUCKET = {
    "trace": "DEBUG",
    "debug": "DEBUG",
    "info": "INFO",
    "warn": "WARN",
    "warning": "WARN",
    "error": "ERROR",
    "fatal": "ERROR",
}

# Names returned to the UI per facet value are capped so a value swept by many broad rules doesn't
# bloat the response or the tooltip — the icon's job is "this value is affected", not an exhaustive list.
MAX_DROP_RULE_NAMES = 10


@dataclass(frozen=True)
class FacetDimension:
    """The single known field of a partial log record. Exactly one attribute is set, matching the
    facet_values endpoint inputs (a top-level column or a resource-attribute map key)."""

    field: str | None = None
    resource_attribute: str | None = None

    def leaf_targets_dimension(self, leaf: dict) -> bool:
        key = str(leaf.get("key") or "")
        key_lower = key.lower()
        if self.field == "service_name":
            return key_lower in _SERVICE_NAME_KEYS
        if self.field == "severity_text":
            return key_lower in _SEVERITY_KEYS
        if self.resource_attribute is not None:
            return str(leaf.get("type") or "") == "log_resource_attribute" and key == self.resource_attribute
        return False


def filter_group_result(filter_group: Any, dimension: FacetDimension, value: str) -> int:
    """Evaluate a rule's `config.filter_group` against a facet value. An absent/empty group has no
    scoping, so it's INDETERMINATE (could apply) rather than FALSE."""
    if filter_group is None or not isinstance(filter_group, dict):
        return _INDETERMINATE
    return _evaluate_node(filter_group, dimension, value)


def matching_drop_rule_names(
    enabled_rules: list[LogsExclusionRule],
    dimension: FacetDimension,
    value: str,
) -> list[str]:
    """Names of the enabled drop rules that could drop or rate-limit logs carrying this facet value,
    in evaluation order, capped at MAX_DROP_RULE_NAMES."""
    names: list[str] = []
    for rule in enabled_rules:
        if _rule_applies_to_value(rule, dimension, value):
            names.append(rule.name)
            if len(names) >= MAX_DROP_RULE_NAMES:
                break
    return names


def annotate_facet_values_with_drop_rules(
    results: list[dict],
    *,
    team_id: int,
    facet_field: str | None,
    facet_resource_attribute: str | None,
) -> list[dict]:
    """Attach a `dropRules` list (matching enabled drop-rule names) to each facet value dict.

    One indexed query loads the team's enabled rules in evaluation order; with no enabled rules every
    value gets an empty list without any per-value work.
    """
    enabled_rules = list(
        LogsExclusionRule.objects.filter(team_id=team_id, enabled=True).order_by("priority", "created_at")
    )
    if not enabled_rules:
        return [{**row, "dropRules": []} for row in results]
    dimension = FacetDimension(field=facet_field, resource_attribute=facet_resource_attribute)
    return [
        {**row, "dropRules": matching_drop_rule_names(enabled_rules, dimension, str(row.get("value") or ""))}
        for row in results
    ]


def rule_could_apply_to_service(filter_group: Any, service_name: str) -> bool:
    """Return True iff the rule's `config.filter_group` could match some log line with this
    `service_name`. True for an absent/empty filter_group (no scoping → applies to everything);
    False only when the group provably cannot match. Backs the Services tab's `active_rules` list."""
    return filter_group_result(filter_group, FacetDimension(field="service_name"), service_name) != _FALSE


def _rule_applies_to_value(rule: LogsExclusionRule, dimension: FacetDimension, value: str) -> bool:
    # Legacy scope_service column: an exact service-name match in the worker (matchesScope).
    if rule.scope_service and dimension.field == "service_name" and rule.scope_service != value:
        return False

    config = rule.config or {}

    if rule.rule_type == LogsExclusionRule.RuleType.SEVERITY_SAMPLING:
        # The worker evaluates severity_sampling purely on scope + per-severity action — filter_group
        # is not consulted. On the severity facet we know the exact level, so we can be precise; on any
        # other facet the rule could drop whichever lines fall into a dropped/sampled severity bucket.
        if dimension.field == "severity_text":
            return _severity_drops_value(config, value)
        return _has_any_drop_or_sample(config)

    # path_drop / rate_limit are scoped via config.filter_group; a provably-FALSE group means no log
    # carrying this facet value can match. Legacy path_drop `patterns` match the request path, which is
    # INDETERMINATE for every facet dimension, so they neither confirm nor exclude on their own.
    return filter_group_result(config.get("filter_group"), dimension, value) != _FALSE


def _severity_drops_value(config: dict, value: str) -> bool:
    bucket = _SEVERITY_BUCKET.get(value.strip().lower())
    if bucket is None:
        return False
    actions = config.get("actions")
    if not isinstance(actions, dict):
        return False
    action = actions.get(bucket)
    return isinstance(action, dict) and action.get("type") in ("drop", "sample")


def _has_any_drop_or_sample(config: dict) -> bool:
    actions = config.get("actions")
    if not isinstance(actions, dict):
        return False
    return any(isinstance(a, dict) and a.get("type") in ("drop", "sample") for a in actions.values())


def _evaluate_node(node: Any, dimension: FacetDimension, value: str) -> int:
    if not isinstance(node, dict):
        return _INDETERMINATE
    if _is_group(node):
        children = node.get("values") or []
        if not children:
            return _INDETERMINATE
        results = [_evaluate_node(child, dimension, value) for child in children]
        if str(node.get("type", "")).upper() == "OR":
            if _TRUE in results:
                return _TRUE
            if _INDETERMINATE in results:
                return _INDETERMINATE
            return _FALSE
        # AND (default for any unrecognised operator).
        if _FALSE in results:
            return _FALSE
        if _INDETERMINATE in results:
            return _INDETERMINATE
        return _TRUE
    if not dimension.leaf_targets_dimension(node):
        # A predicate on a field we don't know at facet time.
        return _INDETERMINATE
    return _evaluate_leaf(node, value)


def _is_group(node: dict) -> bool:
    return str(node.get("type", "")).upper() in ("AND", "OR") and isinstance(node.get("values"), list)


def _evaluate_leaf(leaf: dict, actual: str) -> int:
    operator = str(leaf.get("operator") or "exact").lower()
    value = leaf.get("value")

    if operator == "is_set":
        return _TRUE if actual else _FALSE
    if operator == "is_not_set":
        return _TRUE if not actual else _FALSE

    if value is None:
        return _INDETERMINATE
    if not actual:
        if operator in ("is_not", "not_in", "not_icontains", "not_regex"):
            return _TRUE
        return _FALSE

    if operator in ("exact", "in"):
        return _TRUE if _matches_any(value, actual) else _FALSE
    if operator in ("is_not", "not_in"):
        return _FALSE if _matches_any(value, actual) else _TRUE
    if operator == "icontains":
        return _TRUE if str(value).lower() in actual.lower() else _FALSE
    if operator == "not_icontains":
        return _FALSE if str(value).lower() in actual.lower() else _TRUE
    if operator in ("regex", "not_regex"):
        # RE2 (linear-time) — same engine the worker uses. A member can pick the regex operator, so a
        # pathological pattern through Python's backtracking `re` would be a ReDoS vector on every request.
        matched = _regex_search(str(value), actual)
        if matched is None:
            # Invalid regex: `regex` can never match → FALSE; `not_regex` is trivially satisfied →
            # INDETERMINATE (conservative — only a provably-FALSE result excludes the rule).
            return _FALSE if operator == "regex" else _INDETERMINATE
        if operator == "regex":
            return _TRUE if matched else _FALSE
        return _FALSE if matched else _TRUE
    # Numeric / semver / date operators don't apply to these string dimensions — be conservative.
    return _INDETERMINATE


def _matches_any(value: Any, actual: str) -> bool:
    actual_lower = actual.lower()
    if isinstance(value, list):
        return any(str(v).lower() == actual_lower for v in value)
    return str(value).lower() == actual_lower


@lru_cache(maxsize=512)
def _compile_regex(pattern: str) -> Any | None:
    # `(?is)` = case-insensitive + DOTALL, matching the worker's compileLeafRegex flags.
    try:
        return re2.compile(f"(?is){pattern}")
    except re2.error:
        return None


def _regex_search(pattern: str, actual: str) -> bool | None:
    compiled = _compile_regex(pattern)
    if compiled is None:
        return None
    return compiled.search(actual) is not None
