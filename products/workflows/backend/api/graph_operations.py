from copy import deepcopy
from typing import NoReturn

from rest_framework import serializers

# Surgical, id-addressed edits to a workflow graph (actions + edges). The caller sends a small,
# ordered list of operations instead of re-transmitting the whole graph; these are applied to the
# stored actions/edges and the result is validated + saved by the serializer. Pure functions here —
# no DB, no validation of config (that's HogFlowSerializer's job) and no structural validation
# (that's validate_graph) — so they're cheap to unit-test exhaustively.


def _deep_merge(target: dict, patch: dict) -> dict:
    """Recursively merge `patch` into `target`. A null leaf deletes the key; a dict merges into a
    dict; anything else replaces. Lets a caller change config.inputs.subject without resending the
    rest of config."""
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _edges_match(a: dict, b: dict) -> bool:
    return (
        a.get("from") == b.get("from")
        and a.get("to") == b.get("to")
        and a.get("type") == b.get("type")
        and a.get("index") == b.get("index")
    )


def _fail(message: str) -> NoReturn:
    raise serializers.ValidationError({"operations": message})


def apply_graph_operations(
    actions: list[dict], edges: list[dict], operations: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Apply the ordered operations to copies of `actions`/`edges` and return the new graph. Does not
    mutate the inputs. Raises ValidationError on operations that can't be applied (unknown id, missing
    edge, duplicate id). Structural validity of the result is the caller's responsibility."""
    actions = deepcopy(actions)
    edges = deepcopy(edges)
    actions_by_id = {a.get("id"): a for a in actions}

    for op in operations:
        kind = op["op"]

        if kind == "update_action":
            action = actions_by_id.get(op["id"])
            if action is None:
                _fail(f"update_action: action '{op['id']}' not found")
            _deep_merge(action, op["patch"])

        elif kind == "add_action":
            new_action = op["action"]
            new_id = new_action.get("id")
            if not new_id:
                _fail("add_action: action is missing an 'id'")
            if new_id in actions_by_id:
                _fail(f"add_action: action id '{new_id}' already exists")
            actions.append(new_action)
            actions_by_id[new_id] = new_action

        elif kind == "remove_action":
            target_id = op["id"]
            if target_id not in actions_by_id:
                _fail(f"remove_action: action '{target_id}' not found")
            # Reroute incoming edges to the removed node's first outgoer, then drop edges touching it
            # — mirrors the web builder's onNodesDelete so a removed middle node doesn't orphan its tail.
            outgoers = [e["to"] for e in edges if e.get("from") == target_id]
            first_outgoer = outgoers[0] if outgoers else None
            if first_outgoer is not None:
                for edge in edges:
                    if edge.get("to") == target_id:
                        edge["to"] = first_outgoer
            edges = [e for e in edges if e.get("from") != target_id and e.get("to") != target_id]
            actions = [a for a in actions if a.get("id") != target_id]
            del actions_by_id[target_id]

        elif kind == "add_edge":
            edges.append(dict(op["edge"]))

        elif kind == "remove_edge":
            target_edge = op["edge"]
            remaining = [e for e in edges if not _edges_match(e, target_edge)]
            if len(remaining) == len(edges):
                _fail("remove_edge: no matching edge found")
            edges = remaining

        elif kind == "replace_action_edges":
            target_id = op["id"]
            if target_id not in actions_by_id:
                _fail(f"replace_action_edges: action '{target_id}' not found")
            # Replace only the node's *outgoing* edges (the rewire-branches use case). Incoming edges are
            # left intact so a caller who sends just the new branches can't accidentally orphan the node.
            edges = [e for e in edges if e.get("from") != target_id]
            edges.extend(dict(e) for e in op["edges"])

    return actions, edges
