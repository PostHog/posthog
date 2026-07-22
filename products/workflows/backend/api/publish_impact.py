import re
from typing import Any, Optional

from products.workflows.backend.api.action_redirects import compute_action_redirects

# Publish-time impact summary: what applying a staged draft will do to people already in the flow.
# Pure functions over the two graphs plus externally-fetched counts, so the matrix is unit-testable
# without a DB — mirrors the worker's runtime variable scan (hogflow-variable-usage.ts), which
# observes the same misses per-run at execution time.

# Both templating modes reference workflow variables textually: `{variables.foo}` (hog) and
# `{{ variables.foo }}` (liquid), plus the bracket form `variables['my-var']`.
_DOT_REFERENCE_REGEX = re.compile(r"\bvariables\.([A-Za-z_$][A-Za-z0-9_$]*)")
_BRACKET_REFERENCE_REGEX = re.compile(r"\bvariables\s*\[\s*['\"]([^'\"\]]+)['\"]\s*\]")

# Compiled hog output carried alongside the template strings — never scanned, matching the worker:
# references there are separate string constants, and a template embedded verbatim as a bytecode
# constant would be a false positive.
_SKIPPED_KEYS = {"bytecode", "transpiled"}

# Draft configs are user-controlled JSON: a ~6 KB payload nested ~1000 deep parses fine at write
# time but would RecursionError this scan. Legitimate configs nest a handful of levels; anything
# deeper is ignored rather than crashing the preview (same posture as integration_usage.py).
_MAX_CONFIG_DEPTH = 20


def find_variable_references(value: Any) -> set[str]:
    """Names of workflow variables referenced anywhere in a config blob's template strings."""
    found: set[str] = set()
    _collect_references(value, found, _MAX_CONFIG_DEPTH)
    return found


def _collect_references(value: Any, into: set[str], depth_left: int) -> None:
    if depth_left <= 0:
        return
    if isinstance(value, str):
        for regex in (_DOT_REFERENCE_REGEX, _BRACKET_REFERENCE_REGEX):
            into.update(regex.findall(value))
        return
    if isinstance(value, list):
        for item in value:
            _collect_references(item, into, depth_left - 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in _SKIPPED_KEYS:
                _collect_references(item, into, depth_left - 1)


def _output_variable_keys(action: dict) -> list[str]:
    output_variable = action.get("output_variable")
    if not output_variable:
        return []
    entries = output_variable if isinstance(output_variable, list) else [output_variable]
    return [entry["key"] for entry in entries if isinstance(entry, dict) and entry.get("key")]


def build_publish_impact(
    *,
    live_actions: list[dict],
    live_edges: list[dict],
    live_variables: list[dict],
    draft_actions: list[dict],
    draft_variables: list[dict],
    existing_redirects: Optional[dict[str, str]],
    by_action_counts: Optional[dict[str, int]],
    position_unknown: Optional[int],
    schedule_overrides: dict[str, dict],
) -> dict:
    """What publishing the draft does to people in-flight. Counts are point-in-time approximations
    (jobs transition during the read); None means the counting service was unavailable, never 0."""
    draft_ids = {action["id"] for action in draft_actions if action.get("id")}
    draft_names = {action["id"]: action.get("name") or action["id"] for action in draft_actions if action.get("id")}

    redirects = compute_action_redirects(live_actions, live_edges, draft_actions, existing_redirects) or {}
    deleted_steps = []
    for action in live_actions:
        action_id = action.get("id")
        if not action_id or action_id in draft_ids:
            continue
        target = redirects.get(action_id)
        deleted_steps.append(
            {
                "action_id": action_id,
                "name": action.get("name") or action_id,
                "runs": by_action_counts.get(action_id, 0) if by_action_counts is not None else None,
                "moves_to": {"action_id": target, "name": draft_names[target]} if target else None,
                "exits": target is None,
            }
        )

    # A variable produced only by something new in the draft may render empty for runs already past
    # its producer: an output_variable key this draft adds (on a new action, or newly added to a
    # surviving one), or a workflow variable declared by this draft (declared variables are seeded
    # at run start, so pre-existing runs never had it).
    producers: dict[str, Optional[str]] = {}
    live_variable_keys = {variable.get("key") for variable in live_variables}
    for variable in draft_variables:
        key = variable.get("key")
        if key and key not in live_variable_keys:
            producers[key] = None
    live_output_keys = {action["id"]: set(_output_variable_keys(action)) for action in live_actions if action.get("id")}
    for action in draft_actions:
        action_id = action.get("id")
        if not action_id:
            continue
        for key in _output_variable_keys(action):
            if key not in live_output_keys.get(action_id, set()):
                producers[key] = action_id

    empty_variables = []
    if producers:
        references: dict[str, list[str]] = {key: [] for key in producers}
        for action in draft_actions:
            action_id = action.get("id")
            if not action_id:
                continue
            config = action.get("config") or {}
            # Only inputs/mappings — the worker renders templates from those two fields alone, so a
            # variables-shaped string anywhere else in the config never renders and must not warn.
            for key in find_variable_references([config.get("inputs"), config.get("mappings")]):
                if key in references and action_id != producers[key]:
                    references[key].append(action_id)
        empty_variables = [
            {"variable": key, "set_by": producers[key], "referenced_by": referenced_by}
            for key, referenced_by in sorted(references.items())
            if referenced_by
        ]

    declared_keys = {variable.get("key") for variable in draft_variables}
    schedule_conflicts = [
        {"schedule_id": schedule_id, "variables": orphaned}
        for schedule_id, overrides in schedule_overrides.items()
        if (orphaned := sorted(set(overrides) - declared_keys))
    ]

    return {
        "deleted_steps": deleted_steps,
        "position_unknown": position_unknown,
        "empty_variables": empty_variables,
        "schedule_conflicts": schedule_conflicts,
    }
