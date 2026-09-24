import json
from dataclasses import asdict
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services.code_renderer import (
    MAX_ACTIONS,
    MAX_BRANCH_ARMS,
    MAX_EDGES,
    WorkflowTooLargeToRender,
    render_workflow_code,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "code_renderer"

# The warnings each fixture must report, in order. A fixture absent here renders with none.
EXPECTED_WARNINGS: dict[str, list[dict[str, str | None]]] = {
    "crm_follow_up": [
        {
            "action_id": "tell_the_crm",
            "message": 'The input "signing_secret" of "Tell the CRM" is a secret. PostHog does not return its value, so set TELL_THE_CRM_SIGNING_SECRET before you push.',
        },
    ],
    "passthrough_actions": [
        {
            "action_id": "split",
            "message": 'The arm "1" of "Split traffic" has no edge. Add a step to it before you push.',
        },
    ],
    "re_engagement": [
        {
            "action_id": "exit_node",
            "message": 'The path after "Nudge by email" does not rejoin the workflow. The steps it leads to are dropped.',
        },
        {
            "action_id": "nudge_by_email",
            "message": 'The path after "Text them" does not rejoin the workflow. The steps it leads to are dropped.',
        },
    ],
    "trial_nudge": [
        {
            "action_id": None,
            "message": "This workflow has no key, so the copied file invents one from its name. The first push creates a new draft workflow. Turn the original workflow off or delete it after that push.",
        },
        {
            "action_id": "exit_node",
            "message": 'The exit condition "exit_on_conversion" is not one @posthog/workflows can declare, so the file declares "exit_only_at_end" and the first push stores it. With no conversion goal, the two run the same.',
        },
    ],
    "ui_built": [
        {
            "action_id": None,
            "message": "This workflow has no key, so the copied file invents one from its name. The first push creates a new draft workflow. Turn the original workflow off or delete it after that push.",
        },
    ],
}


def _cases() -> list[str]:
    return sorted(path.stem for path in FIXTURES.glob("*.json") if not path.name.endswith(".roundtrip.json"))


def _person_condition(name: str) -> dict:
    return {
        "name": name,
        "filters": {"properties": [{"key": "plan", "operator": "exact", "value": ["pro"], "type": "person"}]},
    }


def _cohort_condition(name: str) -> dict:
    return {"name": name, "filters": {"properties": [{"key": "id", "type": "cohort", "value": 5, "operator": "in"}]}}


def _basic_workflow(**overrides: object) -> dict:
    workflow: dict[str, object] = {
        "key": "basic-workflow",
        "name": "Basic workflow",
        "status": "draft",
        "exit_condition": "exit_only_at_end",
        "actions": [
            {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "schedule"}},
            {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}},
        ],
        "edges": [{"from": "trigger_node", "to": "exit_node", "type": "continue"}],
    }
    workflow.update(overrides)
    return workflow


def _branch_workflow(
    conditions: list[dict], arm_targets: dict[int, str], branch_name: str = "Which", extra_edges: tuple[dict, ...] = ()
) -> dict:
    return {
        "key": "branchy",
        "name": "Branchy",
        "status": "draft",
        "exit_condition": "exit_only_at_end",
        "actions": [
            {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "schedule"}},
            {"id": "which", "name": branch_name, "type": "conditional_branch", "config": {"conditions": conditions}},
            {"id": "inside", "name": "Inside", "type": "delay", "config": {"delay_duration": "1d"}},
            {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}},
        ],
        "edges": [
            {"from": "trigger_node", "to": "which", "type": "continue"},
            {"from": "which", "to": "exit_node", "type": "continue"},
            {"from": "inside", "to": "exit_node", "type": "continue"},
            *[
                {"from": "which", "to": arm_targets.get(index, "exit_node"), "type": "branch", "index": index}
                for index in range(len(conditions))
            ],
            *extra_edges,
        ],
    }


class TestCodeRenderer(SimpleTestCase):
    @parameterized.expand(_cases())
    def test_renders_fixture_byte_for_byte(self, case: str) -> None:
        definition = json.loads((FIXTURES / f"{case}.json").read_text())

        rendered = render_workflow_code(definition)

        assert rendered.code == (FIXTURES / f"{case}.ts").read_text()
        assert [asdict(warning) for warning in rendered.warnings] == EXPECTED_WARNINGS.get(case, [])

    def test_renders_non_default_trigger_and_exit_ids_like_default_ids(self) -> None:
        default_definition = json.loads((FIXTURES / "welcome_series.json").read_text())
        custom_definition = json.loads((FIXTURES / "welcome_series.json").read_text())
        trigger_id = "custom_trigger"
        exit_id = "custom_exit"
        custom_definition["actions"][0]["id"] = trigger_id
        custom_definition["actions"][-1]["id"] = exit_id
        for edge in custom_definition["edges"]:
            if edge["from"] == "trigger_node":
                edge["from"] = trigger_id
            if edge["to"] == "exit_node":
                edge["to"] = exit_id

        default_rendered = render_workflow_code(default_definition)
        custom_rendered = render_workflow_code(custom_definition)

        assert custom_rendered == default_rendered

    @parameterized.expand(
        [
            (
                "empty_arm_is_dropped_with_a_warning",
                _branch_workflow(
                    conditions=[_person_condition("Paid"), _person_condition("Free")], arm_targets={0: "inside"}
                ),
                ["then: path(delay('1d', { name: 'Inside' }))"],
                ["then: path()"],
                [
                    {
                        "action_id": "which",
                        "message": 'The arm "Free" of "Which" has no steps, so it is dropped. A person who matches it continues after the branch either way.',
                    }
                ],
            ),
            (
                "early_empty_arm_keeps_its_place_in_the_order",
                _branch_workflow(
                    conditions=[_person_condition("Suppressed"), _person_condition("Subscribed")],
                    arm_targets={1: "inside"},
                ),
                [
                    "{ name: 'Suppressed', when: [person('plan', 'exact', ['pro'])], then: path() },\n"
                    "                {\n"
                    "                    name: 'Subscribed',"
                ],
                [],
                [
                    {
                        "action_id": "which",
                        "message": 'The arm "Suppressed" of "Which" has no steps. @posthog/workflows cannot declare an empty arm, and leaving it out would send a person who matches it and a later arm down the later arm. The file keeps it as an empty path(), which does not push. Add a step to the arm or remove it in PostHog first.',
                    }
                ],
            ),
            (
                "branch_edge_past_the_arms_is_dropped",
                _branch_workflow(
                    conditions=[_person_condition("Paid")],
                    arm_targets={0: "inside"},
                    extra_edges=({"from": "which", "to": "exit_node", "type": "branch", "index": 2147483647},),
                ),
                ["then: path(delay('1d', { name: 'Inside' }))"],
                [],
                [
                    {
                        "action_id": "which",
                        "message": '"Which" has 1 branch edge(s) that match no arm of the step. They are dropped.',
                    }
                ],
            ),
            (
                "unsupported_condition_uses_passthrough_and_keeps_arm_steps",
                _branch_workflow(conditions=[_cohort_condition("In cohort")], arm_targets={0: "inside"}),
                ["step({", "type: 'conditional_branch'", "delay('1d', { name: 'Inside' })"],
                ['// The conditional_branch step "Which" is kept as JSON.'],
                None,
            ),
            (
                "line_terminators_in_a_step_name_stay_inside_the_comment",
                _branch_workflow(
                    conditions=[_cohort_condition("In cohort")],
                    arm_targets={0: "inside"},
                    branch_name="Which\u2028import x from 'y'",
                ),
                ["// - Pass-through steps: which (Which\\u2028import x from 'y')."],
                ["\u2028"],
                None,
            ),
            (
                "trailing_newlines_are_not_read_as_a_key_or_a_duration",
                _basic_workflow(
                    actions=[
                        {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "schedule"}},
                        {"id": "wait", "name": "Wait", "type": "delay", "config": {"delay_duration": "1d\n"}},
                        {
                            "id": "hook",
                            "name": "Hook",
                            "type": "function",
                            "config": {
                                "template_id": "template-webhook",
                                "inputs": {
                                    "url": {"value": "https://example.com/hook"},
                                    "body": {"value": {"line\n": "x"}},
                                },
                            },
                        },
                        {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}},
                    ],
                    edges=[
                        {"from": "trigger_node", "to": "wait", "type": "continue"},
                        {"from": "wait", "to": "hook", "type": "continue"},
                        {"from": "hook", "to": "exit_node", "type": "continue"},
                    ],
                ),
                ["'line\\n': 'x'", "delay_duration: '1d\\n'"],
                ["delay('1d"],
                None,
            ),
            (
                "malformed_trigger_filters_stay_in_a_raw_trigger",
                _basic_workflow(
                    actions=[
                        {
                            "id": "trigger_node",
                            "name": "Trigger",
                            "type": "trigger",
                            "config": {"type": "event", "filters": {"events": 5}},
                        },
                        {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}},
                    ]
                ),
                ["on: trigger({ type: 'event', filters: { events: 5 } })"],
                ["onEvent("],
                None,
            ),
            (
                "malformed_trigger_event_properties_stay_in_a_raw_trigger",
                _basic_workflow(
                    actions=[
                        {
                            "id": "trigger_node",
                            "name": "Trigger",
                            "type": "trigger",
                            "config": {
                                "type": "event",
                                "filters": {"events": [{"id": "$pageview", "type": "events", "properties": 5}]},
                            },
                        },
                        {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}},
                    ]
                ),
                ["properties: 5"],
                ["onEvent("],
                None,
            ),
        ]
    )
    def test_keeps_every_loss_visible(
        self, _name: str, definition: dict, present: list[str], absent: list[str], warnings: list[dict] | None
    ) -> None:
        rendered = render_workflow_code(definition)

        for text in present:
            assert text in rendered.code, rendered.code
        for text in absent:
            assert text not in rendered.code, rendered.code
        if warnings is not None:
            assert [asdict(warning) for warning in rendered.warnings] == warnings

    @parameterized.expand(
        [
            (
                "missing_key",
                _basic_workflow(key=""),
                [
                    {
                        "action_id": None,
                        "message": "This workflow has no key, so the copied file invents one from its name. The first push creates a new draft workflow. Turn the original workflow off or delete it after that push.",
                    },
                    {
                        "action_id": "trigger_node",
                        "message": "The trigger leads to no step. The workflow has no steps.",
                    },
                    {
                        "action_id": None,
                        "message": "The workflow has no steps. A no-operation step is added so the file loads, but remove it before you push.",
                    },
                ],
                ["key: 'basic-workflow'"],
                [],
            ),
            (
                "liquid_input",
                _basic_workflow(
                    actions=[
                        {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "schedule"}},
                        {
                            "id": "liquid_webhook",
                            "name": "Liquid webhook",
                            "type": "function",
                            "config": {
                                "template_id": "template-webhook",
                                "inputs": {
                                    "url": {"value": "https://example.com/hook"},
                                    "body": {"value": "{{ person.name }}", "templating": "liquid"},
                                },
                            },
                        },
                        {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}},
                    ],
                    edges=[
                        {"from": "trigger_node", "to": "liquid_webhook", "type": "continue"},
                        {"from": "liquid_webhook", "to": "exit_node", "type": "continue"},
                    ],
                ),
                [
                    {
                        "action_id": "liquid_webhook",
                        "message": 'The input "body" of "Liquid webhook" uses liquid templating. @posthog/workflows uses Hog templating, so rewrite the input before you push.',
                    }
                ],
                ["body: {", "templating: 'liquid'"],
                ["body: '{{ person.name }}'"],
            ),
            (
                "workflow_level_settings",
                _basic_workflow(
                    email_sending_rate_limit={"count": 100, "period": "minute"},
                    schedules=[{"rrule": "FREQ=DAILY"}],
                    abort_action={"type": "function"},
                ),
                [
                    {
                        "action_id": "trigger_node",
                        "message": "The trigger leads to no step. The workflow has no steps.",
                    },
                    {
                        "action_id": None,
                        "message": 'The workflow setting "email_sending_rate_limit" is dropped. @posthog/workflows cannot declare it.',
                    },
                    {
                        "action_id": None,
                        "message": 'The workflow setting "schedules" is dropped. @posthog/workflows cannot declare it.',
                    },
                    {
                        "action_id": None,
                        "message": 'The workflow setting "abort_action" is dropped. @posthog/workflows cannot declare it.',
                    },
                    {
                        "action_id": None,
                        "message": "The workflow has no steps. A no-operation step is added so the file loads, but remove it before you push.",
                    },
                ],
                [],
                [],
            ),
            (
                "non_text_webhook_method",
                _basic_workflow(
                    actions=[
                        {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "schedule"}},
                        {
                            "id": "bad_webhook",
                            "name": "Bad webhook",
                            "type": "function",
                            "config": {
                                "template_id": "template-webhook",
                                "inputs": {
                                    "url": {"value": "https://example.com/hook"},
                                    "method": {"value": ["POST"]},
                                },
                            },
                        },
                        {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}},
                    ],
                    edges=[
                        {"from": "trigger_node", "to": "bad_webhook", "type": "continue"},
                        {"from": "bad_webhook", "to": "exit_node", "type": "continue"},
                    ],
                ),
                [
                    {
                        "action_id": "bad_webhook",
                        "message": 'The webhook method of "Bad webhook" is not text. @posthog/workflows cannot declare it as webhook(...), so the function template is kept instead.',
                    }
                ],
                ["fn({", "method: ['POST']"],
                ["webhook({"],
            ),
            (
                "exit_on_conversion_without_goal",
                _basic_workflow(
                    exit_condition="exit_on_conversion", conversion={"window_minutes": None, "filters": []}
                ),
                [
                    {
                        "action_id": "trigger_node",
                        "message": "The trigger leads to no step. The workflow has no steps.",
                    },
                    {
                        "action_id": "exit_node",
                        "message": 'The exit condition "exit_on_conversion" is not one @posthog/workflows can declare, so the file declares "exit_only_at_end" and the first push stores it. With no conversion goal, the two run the same.',
                    },
                    {
                        "action_id": None,
                        "message": "The workflow has no steps. A no-operation step is added so the file loads, but remove it before you push.",
                    },
                ],
                ["key: 'basic-workflow'"],
                ["exitCondition"],
            ),
            (
                "exit_on_trigger_or_conversion_keeps_the_trigger_exit",
                _basic_workflow(
                    exit_condition="exit_on_trigger_not_matched_or_conversion",
                    conversion={"window_minutes": None, "filters": [{"key": "plan", "type": "person"}]},
                ),
                [
                    {
                        "action_id": "trigger_node",
                        "message": "The trigger leads to no step. The workflow has no steps.",
                    },
                    {
                        "action_id": "exit_node",
                        "message": 'The exit condition "exit_on_trigger_not_matched_or_conversion" needs a conversion goal, which @posthog/workflows cannot declare. The file declares "exit_on_trigger_not_matched", so a person who converts no longer leaves early.',
                    },
                    {
                        "action_id": None,
                        "message": "The conversion goal is dropped. @posthog/workflows cannot declare one.",
                    },
                    {
                        "action_id": None,
                        "message": "The workflow has no steps. A no-operation step is added so the file loads, but remove it before you push.",
                    },
                ],
                ["exitCondition: 'exit_on_trigger_not_matched'"],
                [],
            ),
        ]
    )
    def test_warns_for_workflow_conversion_gaps(
        self, _name: str, definition: dict, warnings: list[dict], present: list[str], absent: list[str]
    ) -> None:
        rendered = render_workflow_code(definition)

        assert [asdict(warning) for warning in rendered.warnings] == warnings
        for text in present:
            assert text in rendered.code, rendered.code
        for text in absent:
            assert text not in rendered.code, rendered.code

    @parameterized.expand(
        [
            ("actions", {"actions": [{"id": f"step_{index}", "type": "delay"} for index in range(MAX_ACTIONS + 1)]}),
            ("edges", {"edges": [{"from": "a", "to": "b", "type": "continue"}] * (MAX_EDGES + 1)}),
            (
                "arms",
                {
                    "actions": [
                        {
                            "id": "which",
                            "type": "conditional_branch",
                            "config": {"conditions": [{}] * (MAX_BRANCH_ARMS + 1)},
                        }
                    ]
                },
            ),
        ]
    )
    def test_refuses_a_graph_over_the_render_bounds(self, _name: str, overrides: dict) -> None:
        with self.assertRaises(WorkflowTooLargeToRender):
            render_workflow_code(_basic_workflow(**overrides))

    def test_renders_condition_shapes_the_sdk_supports(self) -> None:
        definition = _branch_workflow(
            conditions=[
                {
                    "name": "Modern operators",
                    "filters": {
                        "properties": [
                            {"key": "plan", "operator": "exact", "value": "pro", "type": "person"},
                            {"key": "email", "operator": "is_set", "type": "person", "value": "is_set"},
                            {
                                "key": "tier",
                                "operator": "semver_gte",
                                "value": "1.2.0",
                                "type": "group",
                                "group_type_index": 0,
                            },
                        ]
                    },
                }
            ],
            arm_targets={0: "inside"},
        )

        rendered = render_workflow_code(definition)

        assert "person('plan', 'exact', 'pro')" in rendered.code
        assert "person('email', 'is_set')" in rendered.code
        assert "group(0, 'tier', 'semver_gte', '1.2.0')" in rendered.code
        assert [asdict(warning) for warning in rendered.warnings] == []
