from unittest import TestCase

from parameterized import parameterized

from products.workflows.backend.api.action_redirects import MAX_ACTION_REDIRECTS, compute_action_redirects


def _actions(*ids: str) -> list[dict]:
    # The type is arbitrary: compute_action_redirects only ever reads ids and edges. What kind of
    # step was deleted can't matter - it was removed before the parked run executed it.
    return [{"id": action_id, "type": "function", "config": {}} for action_id in ids]


def _edge(frm: str, to: str, edge_type: str = "continue", index: int | None = None) -> dict:
    edge: dict = {"from": frm, "to": to, "type": edge_type}
    if index is not None:
        edge["index"] = index
    return edge


# A linear graph: t -> a -> b -> c -> x
LINEAR_EDGES = [_edge("t", "a"), _edge("a", "b"), _edge("b", "c"), _edge("c", "x")]


class TestComputeActionRedirects(TestCase):
    @parameterized.expand(
        [
            # Each case: (name, old_ids, old_edges, new_ids, existing_map, expected_map).
            # The sketch above each case draws the OLD graph with the steps this edit deletes
            # in [brackets]; the expected map is where runs parked on a deleted step go.
            #
            # t -> a -> [b] -> c -> x
            (
                "deleted_step_redirects_to_surviving_successor",
                ["t", "a", "b", "c", "x"],
                LINEAR_EDGES,
                ["t", "a", "c", "x"],
                None,
                {"b": "c"},
            ),
            # t -> [a] -> [b] -> [c] -> x        every deleted step walks to the first survivor
            (
                "chain_of_steps_deleted_in_one_edit_walks_to_first_survivor",
                ["t", "a", "b", "c", "x"],
                LINEAR_EDGES,
                ["t", "x"],
                None,
                {"a": "x", "b": "x", "c": "x"},
            ),
            # t -> a -> [b]        b was the last step: nothing after it, so no entry
            # (runs parked on b take the graceful exit)
            (
                "dead_end_with_no_continue_edge_is_omitted",
                ["t", "a", "b"],
                [_edge("t", "a"), _edge("a", "b")],
                ["t", "a"],
                None,
                None,
            ),
            # t -> a -> [b] -> [x]        everything after b died too: no survivor, no entry
            (
                "everything_downstream_also_deleted_is_omitted",
                ["t", "a", "b", "x"],
                [_edge("t", "a"), _edge("a", "b"), _edge("b", "x")],
                ["t", "a"],
                None,
                None,
            ),
            # t -> [cond] -branch-> targeted
            #         \---continue-> fallthrough
            # the walk takes cond's continue fall-through, never a branch edge: the config
            # that decided who qualifies for `targeted` died with the node
            (
                "deleted_branch_node_follows_continue_fallthrough_not_branch_edges",
                ["t", "cond", "targeted", "fallthrough"],
                [
                    _edge("t", "cond"),
                    _edge("cond", "targeted", edge_type="branch", index=0),
                    _edge("cond", "fallthrough"),
                ],
                ["t", "targeted", "fallthrough"],
                None,
                {"cond": "fallthrough"},
            ),
            # t -> [a] <-> [b]        a and b point at each other: the walk detects the loop
            # of deleted nodes, finds no survivor, and omits both
            (
                "cycle_of_deleted_nodes_terminates_and_is_omitted",
                ["t", "a", "b"],
                [_edge("t", "a"), _edge("a", "b"), _edge("b", "a")],
                ["t"],
                None,
                None,
            ),
            # t -> [b] -> c -> x        with prior map {a: b} from an earlier edit:
            # b resolves to c, and the stale a->b entry is rewritten to a->c so a run
            # parked two edits back still resolves in one lookup
            (
                "existing_entry_with_deleted_target_is_rewritten_through_this_edit",
                ["t", "b", "c", "x"],
                [_edge("t", "b"), _edge("b", "c"), _edge("c", "x")],
                ["t", "c", "x"],
                {"a": "b"},
                {"a": "c", "b": "c"},
            ),
            # t -> a -> x        with prior map {b: x}, and this edit re-adds a step named b:
            # runs parked on b can execute it normally again, so the entry is pruned
            (
                "existing_entry_whose_key_was_readded_is_pruned",
                ["t", "a", "x"],
                [_edge("t", "a"), _edge("a", "x")],
                ["t", "a", "b", "x"],
                {"b": "x"},
                None,
            ),
            # t -> [b]        with prior map {a: b}: b dies as a dead end, so the a->b entry
            # has nowhere to be rewritten and is dropped (those runs exit gracefully)
            (
                "existing_entry_whose_target_died_with_no_survivor_is_dropped",
                ["t", "b"],
                [_edge("t", "b")],
                ["t"],
                {"a": "b"},
                None,
            ),
            # t -> b -> x        nothing deleted: the prior {a: b} entry still points at a
            # live step and is kept as-is
            (
                "no_deletions_preserves_existing_entries_with_live_targets",
                ["t", "b", "x"],
                [_edge("t", "b"), _edge("b", "x")],
                ["t", "b", "x"],
                {"a": "b"},
                {"a": "b"},
            ),
        ]
    )
    def test_compute(self, _name, old_ids, old_edges, new_ids, existing, expected):
        assert compute_action_redirects(_actions(*old_ids), old_edges, _actions(*new_ids), existing) == expected

    def test_two_successive_edits_leave_a_run_two_edits_behind_one_lookup_away(self):
        # A run parks on `a`. Edit 2 deletes `a` (map: a -> b). Edit 3 deletes `b`. The stored map
        # must resolve `a` directly to `c` — the worker does exactly one lookup, never a chain.
        after_edit_2 = compute_action_redirects(
            _actions("t", "a", "b", "c", "x"), LINEAR_EDGES, _actions("t", "b", "c", "x"), None
        )
        assert after_edit_2 == {"a": "b"}

        edges_after_edit_2 = [_edge("t", "b"), _edge("b", "c"), _edge("c", "x")]
        after_edit_3 = compute_action_redirects(
            _actions("t", "b", "c", "x"), edges_after_edit_2, _actions("t", "c", "x"), after_edit_2
        )
        assert after_edit_3 == {"a": "c", "b": "c"}

    def test_map_is_capped_keeping_the_newest_entries(self):
        # Churning uniquely-named steps can't grow the map without bound: over the cap, the oldest
        # entries (prior edits) drop first and runs parked on them take the graceful exit.
        existing = {f"old_{i}": "x" for i in range(MAX_ACTION_REDIRECTS)}
        result = compute_action_redirects(
            _actions("t", "a", "x"), [_edge("t", "a"), _edge("a", "x")], _actions("t", "x"), existing
        )
        assert result is not None
        assert len(result) == MAX_ACTION_REDIRECTS
        assert result["a"] == "x"  # this edit's entry survives
        assert "old_0" not in result  # the oldest prior entry is the one dropped
