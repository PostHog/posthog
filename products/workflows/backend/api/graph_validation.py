from collections import deque
from typing import Optional

from rest_framework import serializers

# Action types that fan out via `branch` edges, and the config array each branch `index` points into.
# A branch edge's `index` must fall in [0, branch_count). Types not listed support no branch edges.
# Mirrors the frontend branch-edge model (getBranchLabel / StepConditionalBranch / StepRandomCohortBranch
# in products/workflows/frontend/Workflows/hogflows): conditional_branch has one branch per condition,
# random_cohort_branch one per cohort, wait_until_condition exactly one (the condition-met path, index 0),
# each alongside a single `continue` fall-through/timeout edge.


# Step types whose branch edge at index 0 is a required resolution edge (the non-timeout path).
# Value describes when that edge is taken, for the error message.
_RESOLUTION_EDGE_STEP_TYPES = {
    "wait_until_condition": "taken when the condition matches or an events entry fires",
    "agent_task": "taken when the task completes",
}


def _branch_slot_count(action: dict) -> int:
    config = action.get("config") or {}
    action_type = action.get("type")
    if action_type == "conditional_branch":
        return len(config.get("conditions") or [])
    if action_type == "random_cohort_branch":
        return len(config.get("cohorts") or [])
    if action_type in _RESOLUTION_EDGE_STEP_TYPES:
        return 1
    return 0


def validate_graph(actions: list[dict], edges: list[dict], abort_action: Optional[str] = None) -> list[str]:
    """Structural validation of the workflow graph. Raises ValidationError on hard errors that would
    break execution at runtime ('No next action found' and friends); returns a list of non-fatal
    warnings (e.g. unreachable nodes) for the caller to surface. Complements the per-action and
    whole-flow checks in HogFlowSerializer — those validate config; this validates the graph wiring."""
    errors: list[str] = []

    action_ids = [a.get("id") for a in actions]
    actions_by_id = {a.get("id"): a for a in actions}

    # Unique action ids — surgical edits reference nodes by id, so collisions are ambiguous.
    duplicate_ids = sorted({aid for aid in action_ids if action_ids.count(aid) > 1 and aid is not None})
    if duplicate_ids:
        errors.append(f"Duplicate action id(s): {', '.join(duplicate_ids)}. Action ids must be unique.")

    # Exactly one trigger.
    trigger_ids = [a.get("id") for a in actions if a.get("type") == "trigger"]
    if len(trigger_ids) != 1:
        errors.append(f"Exactly one trigger action is required (found {len(trigger_ids)}).")

    # Every edge endpoint references a real action.
    seen_branch_keys: set[tuple] = set()
    for edge in edges:
        src, dst, edge_type = edge.get("from"), edge.get("to"), edge.get("type")
        if src not in actions_by_id:
            errors.append(f"Edge references unknown source action '{src}'.")
        if dst not in actions_by_id:
            errors.append(f"Edge references unknown target action '{dst}'.")

        if edge_type == "branch":
            index = edge.get("index")
            if index is None:
                errors.append(f"Branch edge from '{src}' is missing 'index'.")
            elif src in actions_by_id:
                slot_count = _branch_slot_count(actions_by_id[src])
                if slot_count == 0:
                    errors.append(
                        f"Action '{src}' (type {actions_by_id[src].get('type')}) does not support branch edges."
                    )
                elif not (0 <= index < slot_count):
                    errors.append(f"Branch edge from '{src}' has index {index} out of range [0, {slot_count}).")
                else:
                    key = (src, index)
                    if key in seen_branch_keys:
                        errors.append(f"Duplicate branch edge from '{src}' with index {index}.")
                    seen_branch_keys.add(key)

    # abort_action, when set, must point at a real action.
    if abort_action and abort_action not in actions_by_id:
        errors.append(f"abort_action references unknown action '{abort_action}'.")

    # Every wait_until_condition needs its single resolution edge: a `branch` edge at index 0, taken when
    # the condition matches or an events entry fires. Without it the node only advances on the
    # max_wait_duration timeout (the `continue` edge) and silently ignores resolution — a footgun the
    # frontend never produces (it always wires this edge). seen_branch_keys holds only valid branch edges.
    # agent_task has the same shape: branch index 0 is the task-completed path, continue is failure/timeout.
    for action in actions:
        action_type = action.get("type")
        if not action_type:
            continue
        resolution = _RESOLUTION_EDGE_STEP_TYPES.get(action_type)
        if resolution and (action.get("id"), 0) not in seen_branch_keys:
            errors.append(
                f"{action_type} '{action.get('id')}' is missing its resolution edge: add a 'branch' edge with "
                f"index 0 ({resolution}). Without it the step only ever advances on the max_wait_duration timeout, "
                f"never on resolution."
            )

    if errors:
        raise serializers.ValidationError({"graph": errors})

    return _reachability_warnings(action_ids, actions_by_id, edges, trigger_ids)


def _reachability_warnings(
    action_ids: list[Optional[str]], actions_by_id: dict, edges: list[dict], trigger_ids: list[Optional[str]]
) -> list[str]:
    # A workflow always runs from its single trigger, so any action you can't reach by following edges
    # from the trigger is dead — it'll never execute. We surface that as a warning (not an error: a
    # half-wired draft is legitimate mid-build). Needs exactly one trigger to have a well-defined start.
    if len(trigger_ids) != 1:
        return []

    # Adjacency list: action id -> list of action ids its outgoing edges point to.
    adjacency: dict[Optional[str], list[Optional[str]]] = {aid: [] for aid in action_ids}
    for edge in edges:
        src = edge.get("from")
        if src in adjacency:
            adjacency[src].append(edge.get("to"))

    # Breadth-first walk from the trigger, collecting every node we can get to. The `reachable` set
    # both records the answer and prevents us from re-processing a node (so cycles terminate).
    reachable: set[Optional[str]] = set()
    queue: deque = deque([trigger_ids[0]])
    while queue:
        node = queue.popleft()
        if node in reachable:
            continue
        reachable.add(node)
        queue.extend(adjacency.get(node, []))

    # Anything defined in the graph but never visited by the walk is unreachable.
    unreachable = sorted(str(aid) for aid in actions_by_id if aid not in reachable)
    if unreachable:
        return [f"Action(s) not reachable from the trigger: {', '.join(unreachable)}."]
    return []
