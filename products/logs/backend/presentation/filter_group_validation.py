from __future__ import annotations

from typing import Any

# Keep aligned with `MAX_FILTER_GROUP_DEPTH` / `MAX_FILTER_GROUP_NODES` in
# `nodejs/src/logs-ingestion/sampling/filter-group-match.ts` and
# `compile-rules.ts`. Both depth and breadth are bounded so an adversarially
# deep or wide filter_group cannot stack-overflow or CPU-burn the per-record
# evaluator in the Node ingestion worker. The breadth cap is the more
# realistic abuse vector — depth 1 with 10k sibling leaves passes the depth
# check but costs O(leaves) per log record.
MAX_FILTER_GROUP_DEPTH = 16
MAX_FILTER_GROUP_NODES = 256


def filter_group_depth(node: Any, depth: int = 0) -> int:
    # Short-circuit once we've crossed the cap — we don't need the true depth,
    # just that it exceeds MAX_FILTER_GROUP_DEPTH. Prevents Python RecursionError
    # on adversarial payloads that pass pydantic-core (Rust) validation, which
    # has a more generous recursion limit than ours.
    if depth > MAX_FILTER_GROUP_DEPTH:
        return depth
    if not isinstance(node, dict):
        return depth
    values = node.get("values")
    if not isinstance(values, list) or node.get("type") not in ("AND", "OR"):
        return depth
    max_child = depth
    for child in values:
        d = filter_group_depth(child, depth + 1)
        if d > max_child:
            max_child = d
    return max_child


def filter_group_node_count(node: Any) -> int:
    """Total node count across the filter group (groups + leaves). Short-circuits
    once the cap is exceeded so adversarial payloads don't get fully traversed."""
    if not isinstance(node, dict):
        return 1
    total = 1
    values = node.get("values")
    if not isinstance(values, list) or node.get("type") not in ("AND", "OR"):
        return total
    for child in values:
        total += filter_group_node_count(child)
        if total > MAX_FILTER_GROUP_NODES:
            return total
    return total


def filter_group_has_empty_group(node: Any) -> bool:
    """True when any group node in the tree has an empty `values` list. The worker's
    matchFilterGroup treats empty groups as no-match (dropping is irreversible, so
    vacuous filters fail closed), which makes a rule carrying one silently inert —
    worst on rate_limit, where `{"type": "AND", "values": []}` reads like "cap
    everything" but caps nothing.

    Recurses without a depth short-circuit of its own — callers must run the
    MAX_FILTER_GROUP_DEPTH check first so the tree is already bounded."""
    if not isinstance(node, dict):
        return False
    values = node.get("values")
    if not isinstance(values, list) or node.get("type") not in ("AND", "OR"):
        return False
    if len(values) == 0:
        return True
    return any(filter_group_has_empty_group(child) for child in values)
