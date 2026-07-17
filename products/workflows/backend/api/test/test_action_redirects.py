from unittest import TestCase

from parameterized import parameterized

from products.workflows.backend.api.action_redirects import compute_action_redirects


def _actions(*ids: str) -> list[dict]:
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
            # (name, old_ids, old_edges, new_ids, existing, expected)
            (
                "deleted_step_redirects_to_surviving_successor",
                ["t", "a", "b", "c", "x"],
                LINEAR_EDGES,
                ["t", "a", "c", "x"],
                None,
                {"b": "c"},
            ),
            (
                "chain_of_steps_deleted_in_one_edit_walks_to_first_survivor",
                ["t", "a", "b", "c", "x"],
                LINEAR_EDGES,
                ["t", "x"],
                None,
                {"a": "x", "b": "x", "c": "x"},
            ),
            (
                "dead_end_with_no_continue_edge_is_omitted",
                ["t", "a", "b"],
                [_edge("t", "a"), _edge("a", "b")],
                ["t", "a"],
                None,
                None,
            ),
            (
                "everything_downstream_also_deleted_is_omitted",
                ["t", "a", "b", "x"],
                [_edge("t", "a"), _edge("a", "b"), _edge("b", "x")],
                ["t", "a"],
                None,
                None,
            ),
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
            (
                "cycle_of_deleted_nodes_terminates_and_is_omitted",
                ["t", "a", "b"],
                [_edge("t", "a"), _edge("a", "b"), _edge("b", "a")],
                ["t"],
                None,
                None,
            ),
            (
                "existing_entry_with_deleted_target_is_rewritten_through_this_edit",
                ["t", "b", "c", "x"],
                [_edge("t", "b"), _edge("b", "c"), _edge("c", "x")],
                ["t", "c", "x"],
                {"a": "b"},
                {"a": "c", "b": "c"},
            ),
            (
                "existing_entry_whose_key_was_readded_is_pruned",
                ["t", "a", "x"],
                [_edge("t", "a"), _edge("a", "x")],
                ["t", "a", "b", "x"],
                {"b": "x"},
                None,
            ),
            (
                "existing_entry_whose_target_died_with_no_survivor_is_dropped",
                ["t", "b"],
                [_edge("t", "b")],
                ["t"],
                {"a": "b"},
                None,
            ),
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
