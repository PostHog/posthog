from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import re2

from products.logs.backend.models import LogsExclusionRule

# Three-valued logic for evaluating a drop rule against a *partial* log record at query time. When
# faceting we know exactly one field of the record (the facet's column or resource attribute); every
# other predicate (body, arbitrary attributes, request path) varies per line. A leaf/group resolves to
# _TRUE (provably matches some log with this value), _FALSE (provably cannot), or _INDETERMINATE.
#
# Two evaluations sit on top of this, with different thresholds:
#   - rule_could_apply_to_service / filter_group_result (Services tab): "could this rule match any log
#     from this service?" — true unless provably FALSE; an unscoped rule applies to everything.
#   - matching_drop_rule_names (facet rail): "does this rule *explicitly target* this facet value?" —
#     true only when a predicate on this facet's own dimension matches. A rule scoped solely on another
#     dimension (e.g. a body match) is deliberately NOT surfaced, so it doesn't light up every facet.
# The Node ingestion worker (nodejs/src/logs/sampling/) remains the source of truth for actual drops.
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


def rule_could_apply_to_service(filter_group: Any, service_name: str) -> bool:
    """Return True iff the rule's `config.filter_group` could match some log line with this
    `service_name`. True for an absent/empty filter_group (no scoping → applies to everything);
    False only when the group provably cannot match. Backs the Services tab's `active_rules` list."""
    return filter_group_result(filter_group, FacetDimension(field="service_name"), service_name) != _FALSE


def _rule_applies_to_value(rule: LogsExclusionRule, dimension: FacetDimension, value: str) -> bool:
    """True only when the rule *explicitly targets* this facet value — i.e. it carries a predicate on
    this facet's own dimension that the value satisfies. A rule scoped purely on another dimension (a
    body/message match, a path pattern, a different attribute) is NOT surfaced here, even though it
    could drop some of these logs: it doesn't single this value out, so flagging it on every facet is
    noise. Predicates on other dimensions are ignored (treated as the group's identity), so a compound
    rule like `service=envoy AND status=422` still surfaces on the `envoy` service value."""
    config = rule.config or {}

    if rule.rule_type == LogsExclusionRule.RuleType.SEVERITY_SAMPLING:
        # The worker evaluates severity_sampling purely on per-severity action; only the severity facet
        # is explicitly targeted, and only on the levels the rule actually drops or samples.
        return dimension.field == "severity_text" and _severity_drops_value(config, value)

    # path_drop / rate_limit. The legacy scope_service column is an exact service-name predicate.
    if dimension.field == "service_name" and rule.scope_service:
        return rule.scope_service == value

    # Otherwise the rule must name this dimension in its filter_group and the value must match it.
    return _evaluate_dimension(config.get("filter_group"), dimension, value) == _TRUE


def _severity_drops_value(config: dict, value: str) -> bool:
    bucket = _SEVERITY_BUCKET.get(value.strip().lower())
    if bucket is None:
        return False
    actions = config.get("actions")
    if not isinstance(actions, dict):
        return False
    action = actions.get(bucket)
    return isinstance(action, dict) and action.get("type") in ("drop", "sample")


def _evaluate_dimension(node: Any, dimension: FacetDimension, value: str) -> int | None:
    """Three-valued evaluation restricted to leaves that target `dimension`. Returns None when the
    subtree carries no predicate on this dimension at all (so it neither confirms nor blocks a match).
    Children that return None are dropped from their parent group, which makes a non-dimension predicate
    act as the group's identity — AND ignores it, OR ignores it — leaving only this dimension's verdict."""
    if node is None or not isinstance(node, dict):
        return None
    if _is_group(node):
        results = [
            r
            for r in (_evaluate_dimension(child, dimension, value) for child in node.get("values") or [])
            if r is not None
        ]
        if not results:
            return None
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
        return None
    return _evaluate_leaf(node, value)


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
