from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.llm.system_one import ChoiceAnswer, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult

from products.workflows.backend.services.data_suggestions.brand import BrandKit, parse_brand_kit
from products.workflows.backend.services.data_suggestions.branded_email import EmailCopy, render_branded_email
from products.workflows.backend.services.data_suggestions.builder import BuildContext, build_workflow
from products.workflows.backend.services.data_suggestions.planner import (
    PlannedBranch,
    PlannedStep,
    PlannedWorkflow,
    WorkflowIdea,
    _strict_schema,
)
from products.workflows.backend.services.data_suggestions.ranking import (
    LifecycleStage,
    select_prompt_events,
    suggestion_score,
)
from products.workflows.backend.services.data_suggestions.stages import StageClassificationFailed, classify_event_stages

IDEA = WorkflowIdea(
    name="Trial started upgrade nudge",
    description="Nudge people to upgrade while their trial is running.",
    reason="trial_started fires every day.",
    trigger_event="trial_started",
    stage="trial",
    step_outline=["email", "delay", "email"],
)


def step(step_id: str = "email_1", **overrides: Any) -> PlannedStep:
    values: dict[str, Any] = {
        "id": step_id,
        "type": "email",
        "name": "Email",
        "setup_note": "",
        "next": None,
        "branches": None,
        "template_id": None,
        "wait_event": None,
        "wait_event_next": None,
        "duration": None,
        "email_template_id": None,
        "email_subject": "Your trial started",
        "email_heading": "Welcome to your trial",
        "email_paragraphs": ["Here is how to get started."],
        "email_button_label": "Open the app",
        "slack_message": None,
    }
    values.update(overrides)
    return PlannedStep(**values)


def plan(*steps: PlannedStep, first_step: str | None = None) -> PlannedWorkflow:
    return PlannedWorkflow(first_step=first_step or (steps[0].id if steps else "email_1"), steps=list(steps))


def branch(label: str, next_id: str | None, percentage: int | None = None) -> PlannedBranch:
    return PlannedBranch(label=label, percentage=percentage, next=next_id)


def context(**overrides: Any) -> BuildContext:
    values: dict[str, Any] = {
        "allowed_events": frozenset({"trial_started", "onboarding_completed"}),
        "step_template_ids": frozenset({"template-webhook", "template-slack"}),
        "channels": frozenset(),
        "email_templates": {},
        "sender": None,
        "slack_integration_id": None,
        "brand": None,
    }
    values.update(overrides)
    return BuildContext(**values)


def edges(built: Any) -> list[tuple]:
    return [(edge["from"], edge["to"], edge["type"], edge.get("index")) for edge in built.workflow["edges"]]


class TestDataSuggestions(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "meta tags",
                '<meta property="og:site_name" content="Acme"><meta name="theme-color" content="#1D4AFF">'
                '<link rel="apple-touch-icon" href="/touch.png"><link rel="icon" href="/favicon.ico">',
                BrandKit(
                    domain="example.com",
                    site_name="Acme",
                    primary_color="#1d4aff",
                    logo_url="https://example.com/touch.png",
                ),
            ),
            (
                "title fallback, bad color, insecure logo",
                '<title>Acme | Ship faster</title><meta name="theme-color" content="red">'
                '<link rel="icon" href="http://cdn.example.com/icon.png">',
                BrandKit(domain="example.com", site_name="Acme", primary_color=None, logo_url=None),
            ),
            (
                "nothing",
                "<p>hi</p>",
                BrandKit(domain="example.com", site_name="example.com", primary_color=None, logo_url=None),
            ),
        ]
    )
    def test_parse_brand_kit(self, _name: str, html: str, expected: BrandKit) -> None:
        assert parse_brand_kit(domain="example.com", html=html, base_url="https://example.com/") == expected

    def test_branded_email_escapes_copy_and_keeps_light_brand_colors_readable(self) -> None:
        email = render_branded_email(
            EmailCopy(subject="Hi", heading="<script>x</script>", paragraphs=("a & b",), button_label="Go"),
            BrandKit(domain="example.com", site_name="Acme", primary_color="#ffffff", logo_url=None),
        )
        assert "<script>" not in email.html
        assert "a &amp; b" in email.html
        assert "background:#1d1f27" in email.html
        assert 'href="https://example.com"' in email.html
        assert email.design["body"]["rows"]

    def test_branded_email_without_a_brand_has_no_button(self) -> None:
        email = render_branded_email(
            EmailCopy(subject="Hi", heading="Hello", paragraphs=("Body",), button_label="Go"), None
        )
        assert ">Go</a>" not in email.html
        assert "Go:" not in email.text

    @parameterized.expand(
        [
            ("event the project does not send", {"trigger_event": "made_up_event"}, plan(step())),
            ("unknown saved template", {}, plan(step(email_template_id="not-a-template"))),
            ("email without copy", {}, plan(step(email_heading=None))),
            ("delay without a duration", {}, plan(step("wait", type="delay"))),
            ("no steps", {}, plan()),
            ("sms without an sms provider", {}, plan(step("text", type="sms"))),
            ("push without a push provider", {}, plan(step("notify", type="push"))),
            ("first step that does not exist", {}, plan(step(), first_step="missing")),
            ("next that does not exist", {}, plan(step(next="missing"))),
            ("duplicate step ids", {}, plan(step(), step())),
            ("template outside the catalog", {}, plan(step("hook", type="function", template_id="template-made-up"))),
            (
                "loop back to an earlier step",
                {},
                plan(step("a", next="b"), step("b", type="delay", duration="1d", next="a")),
            ),
            ("step no path reaches", {}, plan(step("a"), step("b", type="delay", duration="1d"))),
            ("branch without paths", {}, plan(step("check", type="conditional_branch"))),
            (
                "split that does not add up to 100",
                {},
                plan(step("ab", type="random_split", branches=[branch("A", None, 50), branch("B", None, 40)])),
            ),
            (
                "more than 20 steps",
                {},
                plan(
                    *[step(f"s{index}", type="delay", duration="1d", next=f"s{index + 1}") for index in range(20)],
                    step("s20"),
                ),
            ),
        ]
    )
    def test_build_workflow_rejects_plans_that_do_not_hold_up(
        self, _name: str, idea_overrides: dict, planned: PlannedWorkflow
    ) -> None:
        assert build_workflow(IDEA.model_copy(update=idea_overrides), planned, context()) is None

    def test_build_workflow_wires_waits_branches_and_blank_integration_steps(self) -> None:
        built = build_workflow(
            IDEA,
            plan(
                step("welcome", next="wait"),
                step(
                    "wait",
                    type="wait_until_event",
                    wait_event="onboarding_completed",
                    wait_event_next="notify",
                    duration="2d",
                    next="split",
                ),
                step("notify", type="function", template_id="template-webhook", setup_note="Add the endpoint URL"),
                step("split", type="random_split", branches=[branch("A", "nudge", 50), branch("B", None, 50)]),
                step("nudge", type="slack", slack_message="Trial user needs help"),
            ),
            context(),
        )
        assert built is not None
        assert edges(built) == [
            ("trigger_node", "action_0_email", "continue", None),
            ("action_0_email", "action_1_wait_until_event", "continue", None),
            ("action_1_wait_until_event", "action_2_function", "branch", 0),
            ("action_1_wait_until_event", "action_3_random_split", "continue", None),
            ("action_2_function", "exit_node", "continue", None),
            ("action_3_random_split", "action_4_slack", "branch", 0),
            ("action_3_random_split", "exit_node", "branch", 1),
            ("action_3_random_split", "exit_node", "continue", None),
            ("action_4_slack", "exit_node", "continue", None),
        ]
        actions = {action["id"]: action for action in built.workflow["actions"]}
        wait_config = actions["action_1_wait_until_event"]["config"]
        assert wait_config["events"][0]["filters"]["events"][0]["id"] == "onboarding_completed"
        assert wait_config["max_wait_duration"] == "2d"
        assert actions["action_2_function"]["config"] == {"template_id": "template-webhook", "inputs": {}}
        assert actions["action_2_function"]["description"] == "Add the endpoint URL"
        assert actions["action_3_random_split"]["config"]["cohorts"] == [
            {"percentage": 50, "name": "A"},
            {"percentage": 50, "name": "B"},
        ]
        slack_inputs = actions["action_4_slack"]["config"]["inputs"]
        assert "slack_workspace" not in slack_inputs
        assert slack_inputs["text"]["value"] == "Trial user needs help"

    def test_plan_schema_only_offers_connected_channels(self) -> None:
        schema = _strict_schema(PlannedWorkflow, frozenset({"sms", "push"}))
        step_types = schema["$defs"]["PlannedStep"]["properties"]["type"]["enum"]
        assert "email" in step_types
        assert "sms" not in step_types
        assert "push" not in step_types
        assert schema["$defs"]["PlannedStep"]["additionalProperties"] is False

    def test_build_workflow_leaves_a_wait_on_an_unknown_event_blank(self) -> None:
        built = build_workflow(
            IDEA,
            plan(step("wait", type="wait_until_event", wait_event="made_up_event", wait_event_next=None)),
            context(),
        )
        assert built is not None
        assert built.workflow["actions"][1]["config"]["events"] == []

    def test_build_workflow_reuses_a_saved_template(self) -> None:
        saved = {"subject": "Saved subject", "html": "<p>saved</p>", "text": "saved", "design": {"body": {}}}
        built = build_workflow(IDEA, plan(step(email_template_id="tpl-1")), context(email_templates={"tpl-1": saved}))
        assert built is not None
        assert built.uses_saved_template
        email = built.workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        assert email["subject"] == "Saved subject"
        assert email["html"] == "<p>saved</p>"

    def test_build_workflow_puts_a_wait_between_back_to_back_emails(self) -> None:
        built = build_workflow(
            IDEA, plan(step("first", next="second"), step("second", email_subject="Second")), context()
        )
        assert built is not None
        assert built.step_types == ("email", "delay", "email")
        assert built.workflow["actions"][2]["config"] == {"delay_duration": "1d"}
        assert edges(built)[1:3] == [
            ("action_0_email", "action_1_delay", "continue", None),
            ("action_1_delay", "action_2_email", "continue", None),
        ]

    def test_build_workflow_strips_template_tags_from_model_copy(self) -> None:
        built = build_workflow(
            IDEA, plan(step(email_paragraphs=["Hi {{ person.properties.secret }} there {% if x %}"])), context()
        )
        assert built is not None
        html = built.workflow["actions"][1]["config"]["inputs"]["email"]["value"]["html"]
        assert "person.properties.secret" not in html
        assert "{%" not in html

    def test_build_workflow_starts_model_copy_with_a_capital(self) -> None:
        built = build_workflow(IDEA.model_copy(update={"name": "welcome new trial users"}), plan(step()), context())
        assert built is not None
        assert built.name == "Welcome new trial users"

    def test_select_prompt_events_keeps_quiet_lifecycle_events_and_drops_noise(self) -> None:
        counts = {"query executed": 9000, "page scrolled": 5000, "user_signed_up": 40, "rare_click": 2}
        assert select_prompt_events(counts, limit=2) == [("user_signed_up", 40), ("query executed", 9000)]

    @parameterized.expand(
        [
            ("quiet sign-up beats busy usage", ("signup", 40), ("other", 10_000)),
            ("onboarding beats a busier failure", ("onboarding", 20), ("failure", 500)),
            ("volume decides within a stage", ("trial", 300), ("trial", 30)),
        ]
    )
    def test_suggestion_score_prefers_welcome_flows(self, _name: str, higher: tuple, lower: tuple) -> None:
        assert suggestion_score(*higher) > suggestion_score(*lower)

    def test_select_prompt_events_ranks_by_jev_stage_when_known(self) -> None:
        counts = {"query executed": 9000, "account_opened": 40, "report_viewed": 300}
        stages: dict[str, LifecycleStage] = {
            "account_opened": "signup",
            "query executed": "other",
            "report_viewed": "other",
        }
        assert [name for name, _ in select_prompt_events(counts, limit=2, stages=stages)] == [
            "account_opened",
            "query executed",
        ]

    @patch("products.workflows.backend.services.data_suggestions.stages.build_system_one_client")
    def test_classify_event_stages_keeps_confident_answers_only(self, build_client: MagicMock) -> None:
        build_client.return_value.decide.return_value = SystemOneResult(
            model="jev-test",
            answers={
                "e0": ChoiceAnswer(choice="signup", confidence=0.9, probabilities={"signup": 0.9}),
                "e1": ChoiceAnswer(choice="purchase", confidence=0.3, probabilities={"purchase": 0.3}),
            },
            input_tokens=10,
        )
        assert classify_event_stages(team_id=1, event_names=["account_opened", "thing_happened"]) == {
            "account_opened": "signup",
            "thing_happened": "other",
        }

    @patch("products.workflows.backend.services.data_suggestions.stages.build_system_one_client")
    def test_classify_event_stages_falls_back_when_jev_is_not_configured(self, build_client: MagicMock) -> None:
        build_client.side_effect = SystemOneNotConfigured("no gateway")
        assert classify_event_stages(team_id=1, event_names=["signed_up"]) == {}

    @patch("products.workflows.backend.services.data_suggestions.stages.build_system_one_client")
    def test_classify_event_stages_fails_when_a_configured_jev_does_not_answer(self, build_client: MagicMock) -> None:
        build_client.return_value.decide.side_effect = SystemOneRequestFailed("boom", status_code=529)
        with self.assertRaises(StageClassificationFailed):
            classify_event_stages(team_id=1, event_names=["signed_up"])

    @parameterized.expand(
        [
            ("workspace creation is a sign-up moment", "workspace_created", True),
            ("account deletion is churn", "account_deleted", True),
            ("deleting a product object is not churn", "hog_flow_deleted", False),
            ("plain usage is not a lifecycle moment", "dashboard_viewed", False),
        ]
    )
    def test_fallback_patterns_put_lifecycle_events_first(self, _name: str, event: str, first: bool) -> None:
        selected = select_prompt_events({"busy_usage": 5000, event: 10}, limit=2)
        assert (selected[0][0] == event) is first
