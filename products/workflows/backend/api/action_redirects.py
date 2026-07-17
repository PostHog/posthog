# Skip-forward map for deleted steps: {deleted_action_id: next surviving action_id}, persisted on
# HogFlow.action_redirects. When a live graph edit deletes a step that in-flight runs are parked on,
# the worker resolves the run's dead position with one dict lookup and continues at the surviving
# successor instead of exiting the run. Pure functions here — no DB — so they're cheap to unit-test
# exhaustively, like graph_operations.
#
# The walk follows only `continue` edges: that's the graph's declared unconditional default (the
# no-match fall-through of conditional_branch, the timeout path of wait_until_condition). Branch
# edges encode a qualification decided by the deleted node's config, which no longer exists — routing
# a run down one would put it on a targeted path it never qualified for. This deliberately diverges
# from graph_operations.remove_action's edit-time reroute (first outgoer of any edge type): that
# patches the stored graph's shape; this decides where a *person* goes.

# The map self-prunes on re-adds, but entries whose targets stay live persist — so an editor churning
# uniquely-named steps could grow it without bound. Cap it well above any real flow's step count;
# on overflow keep the newest entries (dict order: prior-edit entries first, this edit's last), and
# runs parked on a dropped one take the pre-existing graceful exit.
MAX_ACTION_REDIRECTS = 512


def compute_action_redirects(
    old_actions: list[dict],
    old_edges: list[dict],
    new_actions: list[dict],
    existing: dict[str, str] | None,
) -> dict[str, str] | None:
    """Diff the old graph against the new one and return the merged redirect map, or None when empty.

    For each action id deleted by this edit, walk the old graph's continue edges (skipping through
    other deleted nodes) to the first id that survives in the new graph. Dead ends — no continue
    edge, a cycle, or everything downstream deleted too — are omitted, so the worker's graceful-exit
    fallback keeps handling them and `exited_workflow_changed` keeps measuring true dead ends.

    The result is normalized against the new graph, folding in `existing` (the map from prior
    edits): entries whose key was re-added are pruned, entries whose target was deleted by this edit
    are rewritten through this edit's redirects (or dropped when the target has no survivor). The
    invariant this maintains: every value references an action present in the same row's `actions`,
    so a run any number of edits behind resolves in exactly one lookup.
    """
    old_ids = {action["id"] for action in old_actions if action.get("id")}
    new_ids = {action["id"] for action in new_actions if action.get("id")}

    # First continue edge per node, matching the worker's findNextAction (first match wins).
    continue_targets: dict[str, str] = {}
    for edge in old_edges:
        source, target = edge.get("from"), edge.get("to")
        if edge.get("type") == "continue" and source and target and source not in continue_targets:
            continue_targets[source] = target

    fresh: dict[str, str] = {}
    for deleted_id in old_ids - new_ids:
        cursor = continue_targets.get(deleted_id)
        visited = {deleted_id}
        while cursor is not None and cursor not in new_ids and cursor not in visited:
            visited.add(cursor)
            cursor = continue_targets.get(cursor)
        if cursor is not None and cursor in new_ids:
            fresh[deleted_id] = cursor

    merged: dict[str, str] = {}
    for key, target in (existing or {}).items():
        if key in new_ids:
            continue  # Step re-added: runs standing on it execute it normally again.
        if target in new_ids:
            merged[key] = target
        elif target in fresh:
            merged[key] = fresh[target]
        # else: target deleted with no survivor — drop the entry; those runs exit gracefully.
    # Fresh entries win over stale ones: they're computed from the graph as it is right now.
    merged.update(fresh)

    if len(merged) > MAX_ACTION_REDIRECTS:
        merged = dict(list(merged.items())[-MAX_ACTION_REDIRECTS:])

    return merged or None
