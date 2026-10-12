from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services.workflow_outline import EmailStep, outline_workflow

INDENT = " "


def _email(action_id: str, name: str, subject: str) -> dict[str, Any]:
    return {
        "id": action_id,
        "name": name,
        "type": "function_email",
        "config": {"inputs": {"email": {"value": {"subject": subject, "html": f"<p>{subject}</p>"}}}},
    }


def _trigger(config: dict[str, Any]) -> dict[str, Any]:
    return {"id": "trigger", "name": "Trigger", "type": "trigger", "config": config}


SIGNED_UP_TRIGGER = _trigger({"type": "event", "filters": {"events": [{"id": "signed up", "name": "signed up"}]}})

AB_TEST_ACTIONS = [
    SIGNED_UP_TRIGGER,
    {
        "id": "split",
        "name": "Split audience",
        "type": "random_cohort_branch",
        "config": {"cohorts": [{"percentage": 50, "name": "Folders first"}, {"percentage": 50}]},
    },
    _email("folders_1", "Welcome", "Welcome to Hedgebox"),
    {"id": "wait", "name": "Wait", "type": "delay", "config": {"delay_duration": "2d"}},
    _email("folders_2", "Follow up", "Your files, on every device"),
    _email("sharing_1", "Welcome", "Share your first folder"),
    {"id": "exit", "name": "Exit", "type": "exit", "config": {}},
]

AB_TEST_EDGES = [
    {"from": "trigger", "to": "split", "type": "continue"},
    {"from": "split", "to": "folders_1", "type": "branch", "index": 0},
    {"from": "split", "to": "sharing_1", "type": "branch", "index": 1},
    {"from": "split", "to": "exit", "type": "continue"},
    {"from": "folders_1", "to": "wait", "type": "continue"},
    {"from": "wait", "to": "folders_2", "type": "continue"},
    {"from": "folders_2", "to": "exit", "type": "continue"},
    {"from": "sharing_1", "to": "exit", "type": "continue"},
]


class TestWorkflowOutline(SimpleTestCase):
    def test_outlines_each_branch_of_a_split_and_lists_its_emails_in_order(self) -> None:
        outline = outline_workflow(AB_TEST_ACTIONS, AB_TEST_EDGES)

        assert outline.lines == (
            "• Trigger: signed up",
            "• Split audience",
            f"{INDENT}↳ Folders first (50%)",
            f'{INDENT}{INDENT}• Welcome: email "Welcome to Hedgebox"',
            f"{INDENT}{INDENT}• Wait: 2d",
            f'{INDENT}{INDENT}• Follow up: email "Your files, on every device"',
            f"{INDENT}↳ If cohort #2 matches (50%)",
            f'{INDENT}{INDENT}• Welcome: email "Share your first folder"',
        )
        assert outline.email_steps == (
            EmailStep(action_id="folders_1", title="Welcome to Hedgebox"),
            EmailStep(action_id="folders_2", title="Your files, on every device"),
            EmailStep(action_id="sharing_1", title="Share your first folder"),
        )

    def test_points_at_a_step_an_earlier_branch_already_listed(self) -> None:
        merging_edges = [{**edge, "to": "wait"} if edge["from"] == "sharing_1" else edge for edge in AB_TEST_EDGES]

        outline = outline_workflow(AB_TEST_ACTIONS, merging_edges)

        assert outline.lines[-2:] == (
            f'{INDENT}{INDENT}• Welcome: email "Share your first folder"',
            f'{INDENT}{INDENT}• Continues at "Wait"',
        )

    def test_lists_unmatched_contacts_when_a_condition_continues_to_a_step(self) -> None:
        actions = [
            SIGNED_UP_TRIGGER,
            {
                "id": "check",
                "name": "Is on a paid plan",
                "type": "conditional_branch",
                "config": {"conditions": [{"name": "Paid plan"}]},
            },
            _email("upsell", "Upsell", ""),
            _email("thanks", "Thanks", "Thanks for paying"),
        ]
        edges = [
            {"from": "trigger", "to": "check", "type": "continue"},
            {"from": "check", "to": "thanks", "type": "branch", "index": 0},
            {"from": "check", "to": "upsell", "type": "continue"},
        ]

        outline = outline_workflow(actions, edges)

        assert outline.lines[2:] == (
            f"{INDENT}↳ Paid plan",
            f'{INDENT}{INDENT}• Thanks: email "Thanks for paying"',
            f"{INDENT}↳ No match",
            f"{INDENT}{INDENT}• Upsell: email",
        )
        assert outline.email_steps[-1] == EmailStep(action_id="upsell", title="Upsell")

    @parameterized.expand(
        [
            ("named_condition", {"condition": {"name": "Opened the app"}}, "Opened the app"),
            (
                "property_condition_only",
                {"condition": {"filters": {"properties": [{"key": "plan"}]}}},
                "Condition matched",
            ),
            ("event_only", {"events": [{"filters": {"events": [{"id": "uploaded file"}]}}]}, "Event received"),
            (
                "event_or_property_condition",
                {
                    "condition": {"filters": {"properties": [{"key": "plan"}]}},
                    "events": [{"filters": {"events": [{"id": "uploaded file"}]}}],
                },
                "Condition or event matched",
            ),
        ]
    )
    def test_labels_how_a_wait_resolves_like_the_editor(
        self, _name: str, config: dict[str, Any], expected_match: str
    ) -> None:
        actions = [
            SIGNED_UP_TRIGGER,
            {"id": "wait", "name": "Wait for upload", "type": "wait_until_condition", "config": config},
            _email("nudge", "Nudge", "Need a hand?"),
            _email("thanks", "Thanks", "Nice upload"),
        ]
        edges = [
            {"from": "trigger", "to": "wait", "type": "continue"},
            {"from": "wait", "to": "thanks", "type": "branch", "index": 0},
            {"from": "wait", "to": "nudge", "type": "continue"},
        ]

        outline = outline_workflow(actions, edges)

        assert outline.lines[1:] == (
            "• Wait for upload",
            f"{INDENT}↳ {expected_match}",
            f'{INDENT}{INDENT}• Thanks: email "Nice upload"',
            f"{INDENT}↳ No match",
            f'{INDENT}{INDENT}• Nudge: email "Need a hand?"',
        )

    def test_labels_a_wait_timeout_and_a_split_fallback(self) -> None:
        actions = [
            SIGNED_UP_TRIGGER,
            {"id": "wait", "name": "Wait", "type": "wait_until_condition", "config": {"max_wait_duration": "3d"}},
            {
                "id": "split",
                "name": "Split",
                "type": "random_cohort_branch",
                "config": {"cohorts": [{"percentage": 100}]},
            },
            {"id": "first", "name": "First cohort", "type": "delay", "config": {"delay_duration": "1h"}},
            {"id": "unnamed", "name": "", "type": "delay", "config": {"delay_duration": "1h"}},
        ]
        edges = [
            {"from": "trigger", "to": "wait", "type": "continue"},
            {"from": "wait", "to": "split", "type": "branch", "index": 0},
            {"from": "wait", "to": "unnamed", "type": "continue"},
            {"from": "split", "to": "first", "type": "branch", "index": 0},
            {"from": "split", "to": "unnamed", "type": "continue"},
        ]

        outline = outline_workflow(actions, edges)

        assert outline.lines[1:] == (
            "• Wait: up to 3d",
            f"{INDENT}↳ Condition matched",
            f"{INDENT}{INDENT}• Split",
            f"{INDENT}{INDENT}{INDENT}↳ If cohort #1 matches (100%)",
            f"{INDENT}{INDENT}{INDENT}{INDENT}• First cohort: 1h",
            f"{INDENT}{INDENT}{INDENT}↳ Fallback if no cohort has traffic",
            f"{INDENT}{INDENT}{INDENT}{INDENT}• 1h",
            f"{INDENT}↳ No match within 3d",
            f"{INDENT}{INDENT}• Continues at an earlier step",
        )

    @parameterized.expand(
        [
            ("event_without_display_name", {"type": "event", "filters": {"events": [{"id": "purchase"}]}}, "purchase"),
            ("event_without_filters", {"type": "event"}, "any event"),
            ("schedule", {"type": "schedule"}, "on a schedule"),
            ("unknown_trigger_type", {"type": "new-trigger"}, "new-trigger"),
        ]
    )
    def test_describes_the_trigger(self, _name: str, config: dict[str, Any], expected: str) -> None:
        outline = outline_workflow([_trigger(config)], [])

        assert outline.lines == (f"• Trigger: {expected}",)

    def test_reads_a_workflow_saved_without_actions_or_edges(self) -> None:
        outline = outline_workflow({}, {})

        assert outline.lines == ()
        assert outline.email_steps == ()
