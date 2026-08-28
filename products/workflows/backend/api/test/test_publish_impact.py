from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.api.publish_impact import build_publish_impact, find_variable_references


def _action(action_id: str, name: str | None = None, output_variable: dict | list | None = None, **config) -> dict:
    return {
        "id": action_id,
        "name": name or action_id,
        "type": "function",
        "output_variable": output_variable,
        "config": config or {"inputs": {}},
    }


def _continue_edge(source: str, target: str) -> dict:
    return {"from": source, "to": target, "type": "continue"}


class TestFindVariableReferences(SimpleTestCase):
    @parameterized.expand(
        [
            ("hog_dot", {"inputs": {"url": {"value": "{variables.foo}"}}}, {"foo"}),
            ("liquid_dot", {"inputs": {"body": {"value": "Hi {{ variables.name }}!"}}}, {"name"}),
            ("bracket", {"inputs": {"body": {"value": "{{ variables['my-var'] }}"}}}, {"my-var"}),
            ("bracket_spaced", {"inputs": {"x": {"value": "variables[ 'y' ]"}}}, {"y"}),
            ("nested_and_lists", {"mappings": [{"v": ["{variables.a}", {"w": "{variables.b}"}]}]}, {"a", "b"}),
            ("bytecode_skipped", {"inputs": {"url": {"bytecode": ["{variables.foo}"], "value": "plain"}}}, set()),
            ("transpiled_skipped", {"inputs": {"url": {"transpiled": "{variables.foo}"}}}, set()),
            ("no_references", {"inputs": {"url": {"value": "https://example.com"}}}, set()),
        ]
    )
    def test_reference_extraction(self, _name, config, expected):
        assert find_variable_references(config) == expected

    def test_pathological_nesting_is_ignored_not_crashed(self):
        deep: dict = {"value": "{variables.too_deep}"}
        for _ in range(2000):
            deep = {"nested": deep}
        assert find_variable_references({"inputs": {"shallow": "{variables.ok}", "deep": deep}}) == {"ok"}


class TestBuildPublishImpact(SimpleTestCase):
    def _base(self, **overrides: Any) -> dict:
        kwargs: dict[str, Any] = {
            "live_actions": [_action("trigger"), _action("a"), _action("b"), _action("c")],
            "live_edges": [_continue_edge("trigger", "a"), _continue_edge("a", "b"), _continue_edge("b", "c")],
            "live_variables": [],
            "draft_actions": [_action("trigger"), _action("a"), _action("b"), _action("c")],
            "draft_variables": [],
            "existing_redirects": None,
            "by_action_counts": {},
            "position_unknown": 0,
            "schedule_overrides": {},
        }
        kwargs.update(overrides)
        return build_publish_impact(**kwargs)

    def test_content_only_edit_produces_empty_impact(self):
        impact = self._base()
        assert impact == {
            "deleted_steps": [],
            "position_unknown": 0,
            "empty_variables": [],
            "schedule_conflicts": [],
        }

    def test_deleted_step_with_survivor_reports_move(self):
        impact = self._base(
            draft_actions=[_action("trigger"), _action("a"), _action("c", name="Step C")],
            by_action_counts={"b": 312, "a": 5},
        )
        assert impact["deleted_steps"] == [
            {
                "action_id": "b",
                "name": "b",
                "runs": 312,
                "moves_to": {"action_id": "c", "name": "Step C"},
                "exits": False,
            }
        ]

    def test_deleted_dead_end_reports_exit(self):
        impact = self._base(
            draft_actions=[_action("trigger"), _action("a"), _action("b")],
            by_action_counts={"c": 45},
        )
        assert impact["deleted_steps"] == [{"action_id": "c", "name": "c", "runs": 45, "moves_to": None, "exits": True}]

    def test_counts_unavailable_reports_unknown_runs_not_zero(self):
        impact = self._base(
            draft_actions=[_action("trigger"), _action("a"), _action("c")],
            by_action_counts=None,
            position_unknown=None,
        )
        assert impact["deleted_steps"][0]["runs"] is None
        assert impact["deleted_steps"][0]["moves_to"] == {"action_id": "c", "name": "c"}
        assert impact["position_unknown"] is None

    def test_prior_edit_redirect_entries_are_not_reported_again(self):
        # `old_deleted` was removed by an earlier edit; only this edit's deletions ("b") are impact.
        impact = self._base(
            draft_actions=[_action("trigger"), _action("a"), _action("c")],
            existing_redirects={"old_deleted": "a"},
            by_action_counts={"b": 1},
        )
        assert [step["action_id"] for step in impact["deleted_steps"]] == ["b"]

    @parameterized.expand(
        [
            ("single", {"key": "discount_code"}),
            ("list", [{"key": "discount_code"}, {"key": "unreferenced"}]),
        ]
    )
    def test_new_action_output_variable_referenced_downstream_is_flagged(self, _name, output_variable):
        impact = self._base(
            draft_actions=[
                _action("trigger"),
                _action("assign", output_variable=output_variable),
                _action("email", inputs={"body": {"value": "Use {{ variables.discount_code }}"}}),
            ],
        )
        assert impact["empty_variables"] == [
            {"variable": "discount_code", "set_by": "assign", "referenced_by": ["email"]}
        ]

    def test_existing_action_output_variable_is_not_flagged(self):
        actions = [
            _action("trigger"),
            _action("a", output_variable={"key": "score"}),
            _action("b", inputs={"body": {"value": "{variables.score}"}}),
        ]
        impact = self._base(live_actions=actions, draft_actions=actions)
        assert impact["empty_variables"] == []

    def test_output_variable_added_to_existing_action_is_flagged(self):
        # Runs already past "a" never executed the version that stores its output
        impact = self._base(
            draft_actions=[
                _action("trigger"),
                _action("a", output_variable={"key": "score"}),
                _action("b", inputs={"body": {"value": "{variables.score}"}}),
                _action("c"),
            ],
        )
        assert impact["empty_variables"] == [{"variable": "score", "set_by": "a", "referenced_by": ["b"]}]

    def test_reference_outside_inputs_and_mappings_is_not_flagged(self):
        # The worker renders templates only from config.inputs/config.mappings — a variables-shaped
        # string elsewhere in the config never renders, so it must not warn
        impact = self._base(
            draft_actions=[_action("trigger"), _action("a", metadata={"note": "{variables.plan}"})],
            draft_variables=[{"key": "plan", "type": "string", "default": ""}],
        )
        assert impact["empty_variables"] == []

    def test_newly_declared_variable_referenced_in_draft_is_flagged(self):
        impact = self._base(
            draft_actions=[_action("trigger"), _action("a", inputs={"body": {"value": "{variables.plan}"}})],
            draft_variables=[{"key": "plan", "type": "string", "default": ""}],
        )
        assert impact["empty_variables"] == [{"variable": "plan", "set_by": None, "referenced_by": ["a"]}]

    def test_produced_but_unreferenced_variable_is_not_flagged(self):
        impact = self._base(
            draft_actions=[_action("trigger"), _action("assign", output_variable={"key": "orphan"})],
        )
        assert impact["empty_variables"] == []

    def test_schedule_override_of_deleted_variable_is_flagged(self):
        impact = self._base(
            live_variables=[{"key": "kept"}, {"key": "removed"}],
            draft_variables=[{"key": "kept"}],
            schedule_overrides={"sched-1": {"kept": "x", "removed": "y"}, "sched-2": {"kept": "z"}},
        )
        assert impact["schedule_conflicts"] == [{"schedule_id": "sched-1", "variables": ["removed"]}]
