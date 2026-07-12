import pytest
from unittest import TestCase

from parameterized import parameterized
from rest_framework import serializers

from products.workflows.backend.api.graph_operations import apply_graph_operations
from products.workflows.backend.api.graph_validation import validate_graph

TRIGGER = {"id": "t", "name": "trigger", "type": "trigger", "config": {"type": "event"}}
EXIT = {"id": "x", "name": "exit", "type": "exit", "config": {}}


def _fn(action_id: str) -> dict:
    return {"id": action_id, "name": action_id, "type": "function", "config": {}}


def _cond(action_id: str, n_conditions: int) -> dict:
    return {
        "id": action_id,
        "name": action_id,
        "type": "conditional_branch",
        "config": {"conditions": [{"filters": {}} for _ in range(n_conditions)]},
    }


def _edge(frm: str, to: str, edge_type: str = "continue", index: int | None = None) -> dict:
    edge: dict = {"from": frm, "to": to, "type": edge_type}
    if index is not None:
        edge["index"] = index
    return edge


def _graph_errors(actions, edges, abort_action=None) -> str:
    with pytest.raises(serializers.ValidationError) as exc:
        validate_graph(actions, edges, abort_action=abort_action)
    return str(exc.value.detail)


class TestValidateGraph(TestCase):
    def test_valid_linear_graph_passes_with_no_warnings(self):
        actions = [TRIGGER, _fn("a"), EXIT]
        edges = [_edge("t", "a"), _edge("a", "x")]
        assert validate_graph(actions, edges) == []

    def test_duplicate_action_id_raises(self):
        actions = [TRIGGER, _fn("a"), _fn("a"), EXIT]
        assert "Duplicate action id" in _graph_errors(actions, [])

    @parameterized.expand([("zero", []), ("two", [TRIGGER, dict(TRIGGER, id="t2")])])
    def test_trigger_count_must_be_one(self, _name, trigger_actions):
        actions = [*trigger_actions, _fn("a")] if trigger_actions else [_fn("a")]
        assert "Exactly one trigger action is required" in _graph_errors(actions, [])

    def test_edge_with_unknown_source_raises(self):
        actions = [TRIGGER, _fn("a")]
        assert "unknown source action 'ghost'" in _graph_errors(actions, [_edge("ghost", "a")])

    def test_edge_with_unknown_target_raises(self):
        actions = [TRIGGER, _fn("a")]
        assert "unknown target action 'ghost'" in _graph_errors(actions, [_edge("a", "ghost")])

    def test_branch_edge_on_non_branching_action_raises(self):
        actions = [TRIGGER, _fn("a"), EXIT]
        assert "does not support branch edges" in _graph_errors(actions, [_edge("a", "x", "branch", index=0)])

    def test_branch_edge_missing_index_raises(self):
        actions = [TRIGGER, _cond("c", 2), EXIT]
        assert "missing 'index'" in _graph_errors(actions, [_edge("c", "x", "branch")])

    def test_branch_edge_index_out_of_range_raises(self):
        actions = [TRIGGER, _cond("c", 2), EXIT]
        assert "out of range [0, 2)" in _graph_errors(actions, [_edge("c", "x", "branch", index=2)])

    def test_duplicate_branch_index_raises(self):
        actions = [TRIGGER, _cond("c", 2), _fn("a"), EXIT]
        edges = [_edge("c", "a", "branch", index=0), _edge("c", "x", "branch", index=0)]
        assert "Duplicate branch edge" in _graph_errors(actions, edges)

    def test_abort_action_unknown_raises(self):
        actions = [TRIGGER, _fn("a")]
        assert "abort_action references unknown action 'ghost'" in _graph_errors(actions, [], abort_action="ghost")

    def test_abort_action_known_passes(self):
        actions = [TRIGGER, _fn("a")]
        edges = [_edge("t", "a")]
        assert validate_graph(actions, edges, abort_action="a") == []

    def test_valid_branch_graph_passes(self):
        actions = [TRIGGER, _cond("c", 2), _fn("a"), _fn("b"), EXIT]
        edges = [
            _edge("t", "c"),
            _edge("c", "a", "branch", index=0),
            _edge("c", "b", "branch", index=1),
            _edge("c", "x"),  # no-match fall-through
            _edge("a", "x"),
            _edge("b", "x"),
        ]
        assert validate_graph(actions, edges) == []

    def test_wait_until_condition_allows_index_zero_only(self):
        wait = {"id": "w", "name": "w", "type": "wait_until_condition", "config": {"condition": {"filters": {}}}}
        actions = [TRIGGER, wait, EXIT]
        edges = [_edge("t", "w"), _edge("w", "x", "branch", index=0), _edge("w", "x")]
        assert validate_graph(actions, edges) == []
        assert "out of range [0, 1)" in _graph_errors(actions, [_edge("t", "w"), _edge("w", "x", "branch", index=1)])

    def test_agent_task_requires_success_edge_at_index_zero(self):
        agent = {"id": "a", "name": "a", "type": "agent_task", "config": {"prompt": "fix it"}}
        actions = [TRIGGER, agent, EXIT]
        # The success (branch index 0) + failure/timeout (continue) shape the palette produces is valid.
        valid = [_edge("t", "a"), _edge("a", "x", "branch", index=0), _edge("a", "x")]
        assert validate_graph(actions, valid) == []
        # Missing the branch edge is rejected so a success-blind step can't ship via the graph API.
        missing = _graph_errors(actions, [_edge("t", "a"), _edge("a", "x")])
        assert "missing its resolution edge" in missing
        assert "taken when the task completes" in missing
        # index 1 is out of range (only the completed path exists).
        assert "out of range [0, 1)" in _graph_errors(actions, [_edge("t", "a"), _edge("a", "x", "branch", index=1)])

    def test_unreachable_node_returns_warning_not_error(self):
        actions = [TRIGGER, _fn("a"), _fn("orphan"), EXIT]
        edges = [_edge("t", "a"), _edge("a", "x")]
        warnings = validate_graph(actions, edges)
        assert len(warnings) == 1
        assert "not reachable from the trigger" in warnings[0]
        assert "orphan" in warnings[0]


class TestApplyGraphOperations(TestCase):
    def test_update_action_deep_merges_config(self):
        actions = [
            TRIGGER,
            {
                "id": "a",
                "name": "a",
                "type": "function",
                "config": {"inputs": {"url": {"value": "old"}, "keep": {"value": "v"}}},
            },
        ]
        ops = [{"op": "update_action", "id": "a", "patch": {"config": {"inputs": {"url": {"value": "new"}}}}}]
        new_actions, _ = apply_graph_operations(actions, [], ops)
        a = next(x for x in new_actions if x["id"] == "a")
        assert a["config"]["inputs"]["url"]["value"] == "new"
        assert a["config"]["inputs"]["keep"]["value"] == "v"  # untouched sibling preserved

    def test_update_action_null_leaf_deletes_key(self):
        actions = [TRIGGER, {"id": "a", "name": "a", "type": "function", "config": {"x": 1, "y": 2}}]
        ops = [{"op": "update_action", "id": "a", "patch": {"config": {"x": None}}}]
        new_actions, _ = apply_graph_operations(actions, [], ops)
        a = next(x for x in new_actions if x["id"] == "a")
        assert a["config"] == {"y": 2}

    def test_update_action_not_found_raises(self):
        with pytest.raises(serializers.ValidationError) as exc:
            apply_graph_operations([TRIGGER], [], [{"op": "update_action", "id": "ghost", "patch": {}}])
        assert "not found" in str(exc.value.detail)

    def test_add_action_appends(self):
        new_actions, _ = apply_graph_operations([TRIGGER], [], [{"op": "add_action", "action": _fn("a")}])
        assert [x["id"] for x in new_actions] == ["t", "a"]

    def test_add_action_duplicate_id_raises(self):
        with pytest.raises(serializers.ValidationError) as exc:
            apply_graph_operations([TRIGGER, _fn("a")], [], [{"op": "add_action", "action": _fn("a")}])
        assert "already exists" in str(exc.value.detail)

    def test_add_action_missing_id_raises(self):
        with pytest.raises(serializers.ValidationError) as exc:
            apply_graph_operations(
                [TRIGGER], [], [{"op": "add_action", "action": {"name": "x", "type": "function", "config": {}}}]
            )
        assert "missing an 'id'" in str(exc.value.detail)

    def test_remove_action_reroutes_incoming_to_first_outgoer(self):
        # t -> a -> x ; removing a should reconnect t -> x
        actions = [TRIGGER, _fn("a"), EXIT]
        edges = [_edge("t", "a"), _edge("a", "x")]
        new_actions, new_edges = apply_graph_operations(actions, edges, [{"op": "remove_action", "id": "a"}])
        assert [x["id"] for x in new_actions] == ["t", "x"]
        assert new_edges == [_edge("t", "x")]

    def test_remove_action_not_found_raises(self):
        with pytest.raises(serializers.ValidationError) as exc:
            apply_graph_operations([TRIGGER], [], [{"op": "remove_action", "id": "ghost"}])
        assert "not found" in str(exc.value.detail)

    def test_add_edge_appends(self):
        _, new_edges = apply_graph_operations([TRIGGER, _fn("a")], [], [{"op": "add_edge", "edge": _edge("t", "a")}])
        assert new_edges == [_edge("t", "a")]

    def test_remove_edge_removes_matching(self):
        edges = [_edge("t", "a"), _edge("a", "x")]
        _, new_edges = apply_graph_operations(
            [TRIGGER, _fn("a"), EXIT], edges, [{"op": "remove_edge", "edge": _edge("t", "a")}]
        )
        assert new_edges == [_edge("a", "x")]

    def test_remove_edge_no_match_raises(self):
        with pytest.raises(serializers.ValidationError) as exc:
            apply_graph_operations([TRIGGER, _fn("a")], [], [{"op": "remove_edge", "edge": _edge("t", "a")}])
        assert "no matching edge" in str(exc.value.detail)

    def test_replace_action_edges_swaps_outgoing_and_preserves_incoming(self):
        # c has old outgoing branch edges; replace with a fresh set. The incoming t->c edge is left intact
        # so editing a node's branches can't orphan it when the caller only sends outgoing edges.
        actions = [TRIGGER, _cond("c", 2), _fn("a"), _fn("b"), EXIT]
        edges = [_edge("t", "c"), _edge("c", "a", "branch", index=0), _edge("c", "x")]
        ops = [
            {
                "op": "replace_action_edges",
                "id": "c",
                "edges": [_edge("c", "a", "branch", index=0), _edge("c", "b", "branch", index=1)],
            }
        ]
        _, new_edges = apply_graph_operations(actions, edges, ops)
        # incoming edge preserved
        assert _edge("t", "c") in new_edges
        # old outgoing replaced by the new set
        assert _edge("c", "x") not in new_edges
        assert _edge("c", "b", "branch", index=1) in new_edges

    def test_replace_action_edges_unknown_id_raises(self):
        with pytest.raises(serializers.ValidationError) as exc:
            apply_graph_operations([TRIGGER], [], [{"op": "replace_action_edges", "id": "ghost", "edges": []}])
        assert "not found" in str(exc.value.detail)

    def test_operations_apply_in_order(self):
        # add an action, then update it in the same batch
        ops = [
            {"op": "add_action", "action": _fn("a")},
            {"op": "update_action", "id": "a", "patch": {"name": "renamed"}},
        ]
        new_actions, _ = apply_graph_operations([TRIGGER], [], ops)
        assert next(x for x in new_actions if x["id"] == "a")["name"] == "renamed"

    def test_does_not_mutate_input(self):
        actions = [TRIGGER, _fn("a")]
        edges = [_edge("t", "a")]
        apply_graph_operations(actions, edges, [{"op": "update_action", "id": "a", "patch": {"name": "x"}}])
        assert actions[1]["name"] == "a"  # original untouched
