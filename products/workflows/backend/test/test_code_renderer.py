import json
from dataclasses import asdict
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services.code_renderer import render_workflow_code

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "code_renderer"

# The warnings each fixture must report, in order. A fixture absent here renders with none.
EXPECTED_WARNINGS: dict[str, list[dict[str, str | None]]] = {
    "crm_follow_up": [
        {
            "action_id": "tell_the_crm",
            "message": 'The input "signing_secret" of "Tell the CRM" is a secret. PostHog does not return its value, so set TELL_THE_CRM_SIGNING_SECRET before you push.',
        },
    ],
    "re_engagement": [
        {
            "action_id": "wait_for_a_click",
            "message": 'The branch edges out of "Wait for a click" are dropped. Only its next step is kept.',
        },
        {
            "action_id": "wait_for_a_click",
            "message": 'The wait_until_condition step "Wait for a click" has no constructor in @posthog/workflows. It is kept in place as a comment.',
        },
        {
            "action_id": "text_them",
            "message": 'The function_sms step "Text them" has no constructor in @posthog/workflows. It is kept in place as a comment.',
        },
        {
            "action_id": "nudge_by_email",
            "message": 'The email design of "Nudge by email" was edited in the visual editor. @posthog/workflows rebuilds the design from html, so that layout is dropped.',
        },
    ],
    "trial_nudge": [
        {
            "action_id": None,
            "message": "This workflow has no key, so the copied file invents one from its name. The first push creates a new draft workflow. Turn the original workflow off or delete it after that push.",
        },
        {
            "action_id": "trigger_node",
            "message": "The trigger filters out test accounts. @posthog/workflows cannot set that, so a push turns it off.",
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


def _branch_workflow(conditions: list[dict], arm_targets: dict[int, str], branch_name: str = "Which") -> dict:
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
                "unsupported_condition_drops_the_arm_steps_out_loud",
                _branch_workflow(conditions=[_cohort_condition("In cohort")], arm_targets={0: "inside"}),
                ['// The conditional_branch step "Which" is kept as JSON.'],
                ["delay('1d', { name: 'Inside' })"],
                [
                    {
                        "action_id": "which",
                        "message": 'The conditional_branch step "Which" has no constructor in @posthog/workflows. It is kept in place as a comment.',
                    },
                    {
                        "action_id": "inside",
                        "message": '"Inside" sits inside "Which", which is kept as a comment, so it is dropped.',
                    },
                ],
            ),
            (
                "line_terminators_in_a_step_name_stay_inside_the_comment",
                _branch_workflow(
                    conditions=[_cohort_condition("In cohort")],
                    arm_targets={0: "inside"},
                    branch_name="Which\u2028import x from 'y'",
                ),
                ["// - which: The conditional_branch step \"Which\\u2028import x from 'y'\" has no constructor"],
                ["\u2028"],
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
                    }
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
                [],
                ["key: 'basic-workflow'"],
                ["exitCondition", "conversion goal"],
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
