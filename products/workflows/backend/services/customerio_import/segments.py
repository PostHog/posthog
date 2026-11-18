"""Customer.io segment rules as realtime cohort filters.

Only rules a cohort matches exactly are translated: person attribute comparisons. A segment with any other rule
is not translated at all, because a cohort built from part of its rules would hold a different audience.
"""

import sys
import json
import functools
from typing import Any

from products.workflows.backend.facade.contracts import SegmentCohortFilters
from products.workflows.backend.services.customerio_import import conditions

# The person attribute operators a realtime cohort evaluates the same way. Relative dates, like "in the last 30
# days", are left out: a realtime cohort only re-checks a person when their properties change, so it would keep
# people who aged out.
_COHORT_OPERATORS = {"eq", "!eq", "contains", "!contains", "gt", "lt", "exists", "!exists", "bw"}
_ABSOLUTE_DATE_OPERATORS = {"timestamp_gta", "timestamp_lta", "timestamp_bw"}
_GROUP_TYPES = {"and": "AND", "or": "OR"}
_REGEX_SYNTAX = set("\\.^$|?*+()[]{}")


def segment_cohort_filters(segment_conditions: Any) -> SegmentCohortFilters:
    """The cohort filters for a segment's `conditions` tree, or the rules that stop it from translating."""
    if not isinstance(segment_conditions, dict) or not segment_conditions:
        return SegmentCohortFilters(filters=None, untranslated=("the segment has no rules",))
    translation = _Translation()
    groups, root_type = translation.root(segment_conditions)
    if translation.untranslated:
        return SegmentCohortFilters(filters=None, untranslated=tuple(dict.fromkeys(translation.untranslated)))
    if not groups:
        return SegmentCohortFilters(filters=None, untranslated=("the segment has no rules",))
    return SegmentCohortFilters(filters={"properties": {"type": root_type, "values": groups}})


class _Translation:
    """Cohort filters hold two levels: groups, each a list of property filters. Deeper trees don't translate."""

    def __init__(self) -> None:
        self.untranslated: list[str] = []

    def root(self, tree: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        operator = _group_operator(tree)
        if operator is None:
            # One rule on its own.
            leaf = self.leaf(tree, "AND")
            return ([{"type": "AND", "values": leaf}] if leaf else []), "AND"
        root_type = _GROUP_TYPES[operator]
        children = tree[operator] if isinstance(tree[operator], list) else []
        groups: list[dict[str, Any]] = []
        loose: list[dict[str, Any]] = []
        for child in children:
            child_operator = _group_operator(child) if isinstance(child, dict) else None
            if child_operator is None:
                loose.extend(self.leaf(child, root_type))
                continue
            group_type = _GROUP_TYPES[child_operator]
            values: list[dict[str, Any]] = []
            for grandchild in child[child_operator] if isinstance(child[child_operator], list) else []:
                if isinstance(grandchild, dict) and _group_operator(grandchild) is not None:
                    self.untranslated.append("rules grouped more than two levels deep")
                    continue
                values.extend(self.leaf(grandchild, group_type))
            if values:
                groups.append({"type": group_type, "values": values})
        if loose:
            groups.insert(0, {"type": root_type, "values": loose})
        return groups, root_type

    def leaf(self, node: Any, group_type: str) -> list[dict[str, Any]]:
        if not isinstance(node, dict):
            self.untranslated.append(conditions.describe(node))
            return []
        negate = bool(node.get("inverse"))
        if isinstance(node.get("not"), dict):
            negate, node = not negate, node["not"]
            if _group_operator(node) is not None:
                self.untranslated.append("a negated group of rules")
                return []
        attribute = node.get("attribute") if isinstance(node.get("attribute"), dict) else None
        if attribute is None and node.get("type") in (None, "attribute") and "field" in node:
            attribute = node
        if attribute is None:
            attribute = _current_attribute(node)
        if attribute is None:
            self.untranslated.append(describe_rule(node))
            return []
        if attribute is not node and attribute.get("inverse"):
            negate = not negate
        operator = attribute.get("operator") or "eq"
        if not isinstance(operator, str):
            self.untranslated.append(f"{attribute.get('field') or 'an attribute'} (an unsupported operator)")
            return []
        description = conditions.describe({**attribute, "operator": operator, "inverse": negate})
        if operator not in _COHORT_OPERATORS | _ABSOLUTE_DATE_OPERATORS:
            reason = "a relative date" if operator in ("timestamp_gt", "timestamp_lt") else "an unsupported operator"
            self.untranslated.append(f"{description} ({reason})")
            return []
        filters = conditions.property_filters({**attribute, "operator": operator}, "person", negate=negate)
        # A range is two filters that must both match, which an "any of" group can't hold.
        if filters is None or (len(filters) > 1 and group_type == "OR"):
            self.untranslated.append(description)
            return []
        return [_with_set_value(_ignoring_case(item)) for item in filters]


def _current_attribute(node: dict[str, Any]) -> dict[str, Any] | None:
    """The attribute check in an `attribute_change` rule, which is how Customer.io stores "attribute is X".

    Its `to` filter is the check on the current value, and its `from` filter repeats it, inverted. A rule with any
    other filters, a time window or a count above one is a rule this can't read as a plain attribute check.
    """
    event = node.get("event")
    if not isinstance(event, dict) or event.get("type") != "attribute_change":
        return None
    field = event.get("name")
    filters = event.get("filters")
    leaves = filters.get("and") if isinstance(filters, dict) else None
    if not isinstance(field, str) or not field or not isinstance(leaves, list):
        return None
    if node.get("within") not in (0, None) or node.get("times") not in (1, None):
        return None
    to = [leaf for leaf in leaves if isinstance(leaf, dict) and leaf.get("field") == "to"]
    # Without the mirrored `from` it may be a change rule, so both must be there.
    if len(to) != 1 or len(leaves) != 2:
        return None

    def check(leaf: dict[str, Any]) -> tuple[Any, ...]:
        return (leaf.get("operator"), leaf.get("value"), leaf.get("value2"))

    for leaf in leaves:
        if leaf is to[0]:
            continue
        mirrors_to = (
            isinstance(leaf, dict)
            and leaf.get("field") == "from"
            and check(leaf) == check(to[0])
            and bool(leaf.get("inverse")) != bool(to[0].get("inverse"))
        )
        if not mirrors_to:
            return None
    return {
        "field": field,
        "operator": to[0].get("operator"),
        "value": to[0].get("value"),
        "value2": to[0].get("value2"),
        "inverse": bool(to[0].get("inverse")),
    }


def describe_rule(node: dict[str, Any]) -> str:
    """A short, readable name for a segment rule that has no cohort equivalent."""
    event = node.get("event")
    if isinstance(event, dict):
        name = event.get("name") or "an event"
        if event.get("type") == "attribute_change":
            return f"{name} changed{_change_detail(event.get('filters'))}"
        count = node.get("times")
        within = node.get("within")
        detail = f" at least {count} times" if isinstance(count, int) and count > 1 else ""
        if isinstance(within, int) and within > 0:
            detail += f" within {_days(within)}"
        verb = "did not perform" if node.get("inverse") else "performed"
        return f"{verb} {name}{detail}"
    labels = {
        "segment": "in another segment",
        "message": "message activity, such as opened or clicked",
        "device": "a device rule",
        "relationship": "a relationship rule",
        "object": "an object rule",
    }
    for key, label in labels.items():
        if key in node:
            if key == "segment" and isinstance(node[key], dict) and node[key].get("id") is not None:
                return f"in segment {node[key]['id']}"
            return label
    return json.dumps(node, sort_keys=True, default=str)[:200]


def _group_operator(node: dict[str, Any]) -> str | None:
    for operator in _GROUP_TYPES:
        if isinstance(node.get(operator), list):
            return operator
    return None


def _change_detail(filters: Any) -> str:
    leaves = [
        leaf
        for leaf in (filters.get("and") if isinstance(filters, dict) else None) or []
        if isinstance(leaf, dict) and leaf.get("field") in ("to", "from") and not leaf.get("inverse")
    ]
    return "".join(f" {leaf['field']} {leaf.get('value')}" for leaf in leaves)


def _days(seconds: int) -> str:
    days = seconds / 86400
    return f"{days:g} days" if days >= 1 else f"{seconds // 3600 or 1} hours"


def _ignoring_case(item: dict[str, Any]) -> dict[str, Any]:
    # Customer.io compares segment values without case: it saves "DE" as "de" and still matches "DE".
    if item["operator"] not in ("exact", "is_not") or not isinstance(item.get("value"), str):
        return item
    pattern = "".join(_any_case(character) for character in item["value"])
    return {**item, "operator": "regex" if item["operator"] == "exact" else "not_regex", "value": f"^{pattern}$"}


def _any_case(character: str) -> str:
    # A character class rather than an (?i) flag, which the JavaScript HogVM can't read.
    lower = character.lower()
    variants = _case_variants().get(lower) if len(lower) == 1 else None
    if variants:
        return f"[{lower}{variants}]"
    # Only the characters every engine reads as syntax: Rust's regex rejects some escapes Python's re.escape adds.
    return f"\\{character}" if character in _REGEX_SYNTAX else character


@functools.cache
def _case_variants() -> dict[str, str]:
    """Each lowercase character to the other characters that lowercase to it, such as "ß" to "ẞ"."""
    # Built from lower() rather than upper(), which turns "ß" into the two characters "SS".
    variants: dict[str, set[str]] = {}
    for code_point in range(sys.maxunicode + 1):
        character = chr(code_point)
        lower = character.lower()
        if len(lower) == 1 and lower != character:
            variants.setdefault(lower, set()).add(character)
    return {lower: "".join(sorted(characters)) for lower, characters in variants.items()}


def _with_set_value(item: dict[str, Any]) -> dict[str, Any]:
    # Cohort property filters carry the operator as the value of is_set / is_not_set, the way the cohort editor saves them.
    if item["operator"] in ("is_set", "is_not_set") and "value" not in item:
        return {**item, "value": item["operator"]}
    return item
