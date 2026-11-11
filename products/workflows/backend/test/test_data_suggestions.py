import uuid
from typing import Any, get_args

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.llm.system_one import ChoiceAnswer, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult

from products.messaging.backend.facade.api import EmailTemplateContent
from products.workflows.backend.facade.contracts import DataSuggestionsStatus, LifecycleStage, OutlineKind
from products.workflows.backend.presentation.views.workflow_data_suggestions import (
    DataSuggestionsStatus as DataSuggestionsStatusChoices,
    DataSuggestionStage,
    DataSuggestionStepKind,
    EventWorkflowsBuildRequestSerializer,
)
from products.workflows.backend.services.data_suggestions.builder import (
    PUSH_SETUP_NOTE,
    BuildContext,
    build_workflow,
    missing_inputs,
)
from products.workflows.backend.services.data_suggestions.email_design import EmailCopy, render_email
from products.workflows.backend.services.data_suggestions.llm import invoke_structured, strict_schema
from products.workflows.backend.services.data_suggestions.planner import (
    PlannedBranch,
    PlannedStep,
    PlannedWorkflow,
    WorkflowIdea,
)
from products.workflows.backend.services.data_suggestions.premade import with_push_channels
from products.workflows.backend.services.data_suggestions.ranking import select_prompt_events, suggestion_score
from products.workflows.backend.services.data_suggestions.stages import StageClassificationFailed, classify_event_stages

IDEA = WorkflowIdea(
    name="Trial started upgrade nudge",
    description="Nudge people to upgrade while their trial is running.",
    reason="trial_started fires every day.",
    trigger_event="trial_started",
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
        "push_title": None,
        "push_body": None,
        "slack_message": None,
    }
    values.update(overrides)
    return PlannedStep(**values)


def plan(*steps: PlannedStep, first_step: str | None = None) -> PlannedWorkflow:
    return PlannedWorkflow(first_step=first_step or (steps[0].id if steps else "email_1"), steps=list(steps))


def branch(
    label: str,
    next_id: str | None,
    percentage: int | None = None,
    person_property: str | None = None,
    property_value: str | None = None,
) -> PlannedBranch:
    return PlannedBranch(
        label=label,
        percentage=percentage,
        next=next_id,
        person_property=person_property,
        property_value=property_value,
    )


def context(**overrides: Any) -> BuildContext:
    values: dict[str, Any] = {
        "allowed_events": frozenset({"trial_started", "onboarding_completed"}),
        "step_template_ids": frozenset({"template-webhook", "template-slack"}),
        "channels": frozenset(),
        "email_templates": {},
        "sender": None,
        "slack_integration_id": None,
    }
    values.update(overrides)
    return BuildContext(**values)


def edges(built: Any) -> list[tuple]:
    return [(edge["from"], edge["to"], edge["type"], edge.get("index")) for edge in built.workflow["edges"]]


class TestDataSuggestions(SimpleTestCase):
    def test_picked_event_names_keep_their_whitespace(self) -> None:
        payload = EventWorkflowsBuildRequestSerializer(data={"events": [" signed up "]})

        assert payload.is_valid(), payload.errors
        assert payload.validated_data["events"] == [" signed up "]

    def test_email_escapes_copy_and_carries_an_editor_design(self) -> None:
        email = render_email(EmailCopy(subject="Hi", heading="<script>x</script>", paragraphs=("a & b",)))
        assert "<script>" not in email.html
        assert "a &amp; b" in email.html
        assert email.design["body"]["rows"]

    @parameterized.expand(
        [
            ("event the project does not send", {"trigger_event": "made_up_event"}, plan(step())),
            ("unknown saved template", {}, plan(step(email_template_id="not-a-template"))),
            ("email without copy", {}, plan(step(email_heading=None))),
            ("delay without a duration", {}, plan(step("wait", type="delay"))),
            ("no steps", {}, plan()),
            ("sms without an sms provider", {}, plan(step("text", type="sms"))),
            ("push the project cannot use", {}, plan(step("notify", type="push", push_title="Your trial started"))),
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
            ("wait with no event", {}, plan(step("wait", type="wait_until_event"))),
            (
                "wait on an event the project does not send",
                {},
                plan(step("wait", type="wait_until_event", wait_event="made_up_event")),
            ),
            (
                "step reachable only through a split's continue edge",
                {},
                plan(
                    step("ab", type="random_split", branches=[branch("A", None, 50), branch("B", None, 50)], next="x"),
                    step("x", type="delay", duration="1d"),
                ),
            ),
            (
                "split with a share outside 1 to 100",
                {},
                plan(step("ab", type="random_split", branches=[branch("A", None, -50), branch("B", None, 150)])),
            ),
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
                step("nudge", type="slack", slack_message="Trial user needs help", next="window"),
                step("window", type="wait_until_time_window"),
            ),
            context(once_per_person=True),
        )
        assert built is not None
        assert built.workflow["trigger_masking"] == {"hash": "{person.id}", "ttl": None, "threshold": None}
        assert edges(built) == [
            ("trigger_node", "action_0_email", "continue", None),
            ("action_0_email", "action_1_wait_until_event", "continue", None),
            ("action_1_wait_until_event", "action_2_function", "branch", 0),
            ("action_1_wait_until_event", "action_3_random_split", "continue", None),
            ("action_2_function", "exit_node", "continue", None),
            ("action_3_random_split", "action_4_slack", "branch", 0),
            ("action_3_random_split", "exit_node", "branch", 1),
            ("action_3_random_split", "exit_node", "continue", None),
            ("action_4_slack", "action_5_wait_until_time_window", "continue", None),
            ("action_5_wait_until_time_window", "exit_node", "continue", None),
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
        assert actions["action_5_wait_until_time_window"]["config"]["day"] == "weekday"
        webhook_schema = {"template-webhook": [{"key": "url", "label": "Webhook URL", "required": True}]}
        assert {(item.step_id, item.field) for item in missing_inputs(built.workflow, webhook_schema)} == {
            ("action_0_email", "Email sender"),
            ("action_2_function", "Webhook URL"),
        }

    @parameterized.expand([("provider connected", (7, 9)), ("no provider yet", ())])
    def test_build_workflow_writes_push_copy_and_asks_for_a_provider_only_when_missing(
        self, _name: str, integration_ids: tuple[int, ...]
    ) -> None:
        built = build_workflow(
            IDEA,
            plan(
                step(
                    "notify",
                    type="push",
                    setup_note="Check the copy",
                    push_title="your {{ person.name }}trial started",
                    push_body="See what [[plan|your plan]] includes.",
                )
            ),
            context(
                channels=frozenset({"push"}),
                push_integration_ids=integration_ids,
                event_properties=frozenset({"plan"}),
            ),
        )
        assert built is not None
        push = built.workflow["actions"][1]
        assert push["type"] == "function_push"
        assert push["config"]["inputs"] == {
            "distinctId": {"value": "{event.distinct_id}", "templating": "hog"},
            "channels": {"value": list(integration_ids)},
            "title": {"value": "Your trial started", "templating": "hog"},
            "body": {
                "value": "See what {{ event.properties.plan | default: 'your plan' | raw }} includes.",
                "templating": "liquid",
            },
        }
        push_schema = {
            "template-native-push": [
                {"key": "distinctId", "label": "Distinct ID", "required": True},
                {"key": "channels", "label": "Push channels", "required": True},
                {"key": "title", "label": "Notification title", "required": True},
            ]
        }
        missing = [item.field for item in missing_inputs(built.workflow, push_schema)]
        if integration_ids:
            assert push["description"] == "Check the copy"
            assert missing == []
        else:
            assert push["description"] == f"{PUSH_SETUP_NOTE} Check the copy"
            assert missing == ["Push channels"]
            connected_later = with_push_channels(built.workflow, [7])["actions"][1]
            assert connected_later["config"]["inputs"]["channels"] == {"value": [7]}
            assert connected_later["description"] == "Check the copy"

    def test_build_workflow_drops_push_without_a_title(self) -> None:
        planned = plan(step("notify", type="push", push_body="Only a body"))
        assert build_workflow(IDEA, planned, context(channels=frozenset({"push"}))) is None

    @patch("products.workflows.backend.services.data_suggestions.llm.logger")
    @patch("products.workflows.backend.services.data_suggestions.llm.is_privacy_mode_enabled", return_value=True)
    @patch("products.workflows.backend.services.data_suggestions.llm.MaxChatAnthropic")
    def test_a_malformed_answer_is_logged_without_its_content(
        self, chat: MagicMock, _privacy: MagicMock, logger: MagicMock
    ) -> None:
        chat.return_value.invoke.return_value.content = '{"first_step": "secret_signup_event"}'

        result = invoke_structured(
            team=MagicMock(id=1),
            user=MagicMock(distinct_id="user-1"),
            model="claude-test",
            effort="low",
            feature="test",
            schema=PlannedWorkflow,
            system="",
            human="",
            excluded_values=frozenset(),
        )

        assert result is None
        assert "secret_signup_event" not in str(logger.warning.call_args)
        assert "exc_info" not in logger.warning.call_args.kwargs

    def test_plan_schema_only_offers_connected_channels_and_project_events(self) -> None:
        schema = strict_schema(PlannedWorkflow, frozenset({"sms", "push"}), {"wait_event": ["trial_started", "sms"]})
        wait_event = schema["$defs"]["PlannedStep"]["properties"]["wait_event"]["anyOf"]
        assert {"type": "string", "enum": ["trial_started", "sms"]} in wait_event
        assert {"type": "null"} in wait_event
        step_types = schema["$defs"]["PlannedStep"]["properties"]["type"]["enum"]
        assert "email" in step_types
        assert "sms" not in step_types
        assert "push" not in step_types
        assert schema["$defs"]["PlannedStep"]["additionalProperties"] is False

    def test_build_workflow_reuses_a_saved_template(self) -> None:
        saved = EmailTemplateContent(
            id=uuid.uuid4(),
            name="Trial welcome",
            email={"subject": "Saved subject", "html": "<p>saved</p>", "text": None, "design": {"body": {}}},
        )
        built = build_workflow(IDEA, plan(step(email_template_id="tpl-1")), context(email_templates={"tpl-1": saved}))
        assert built is not None
        assert built.uses_saved_template
        email = built.workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        assert email["subject"] == "Saved subject"
        assert email["html"] == "<p>saved</p>"
        assert "text" not in email

    def test_build_workflow_spaces_out_emails_for_a_person(self) -> None:
        built = build_workflow(
            IDEA, plan(step("first", next="second"), step("second", email_subject="Second")), context()
        )
        assert built is not None
        assert [action["type"] for action in built.workflow["actions"][1:4]] == [
            "function_email",
            "delay",
            "function_email",
        ]
        assert built.workflow["actions"][2]["config"] == {"delay_duration": "1d"}
        assert built.workflow["trigger_masking"] == {"hash": "{person.id}", "ttl": 7 * 24 * 60 * 60, "threshold": None}
        assert edges(built)[1:3] == [
            ("action_0_email", "action_1_delay", "continue", None),
            ("action_1_delay", "action_2_email", "continue", None),
        ]

    @parameterized.expand(
        [
            (
                "a sent property and value",
                "plan",
                "pro",
                [{"key": "plan", "value": ["pro"], "operator": "exact", "type": "person"}],
            ),
            ("a value the project does not send", "plan", "enterprise", None),
            ("a property the project does not send", "secret", "pro", None),
        ]
    )
    def test_build_workflow_fills_branch_conditions_from_sent_person_properties(
        self, _name: str, person_property: str, property_value: str, expected: list | None
    ) -> None:
        built = build_workflow(
            IDEA,
            plan(
                step(
                    "check",
                    type="conditional_branch",
                    branches=[
                        branch("Pro plan", "nudge", person_property=person_property, property_value=property_value)
                    ],
                ),
                step("nudge"),
            ),
            context(person_properties={"plan": ("free", "pro")}),
        )
        assert built is not None
        condition = built.workflow["actions"][1]["config"]["conditions"][0]
        assert condition["filters"] == ({"properties": expected} if expected else {})
        unset = {item.field for item in missing_inputs(built.workflow, {})}
        assert ("Condition: Pro plan" in unset) is (expected is None)

    @parameterized.expand([("quiet trigger", 50_000, None), ("busy trigger", 1_000_000, 5), ("flood", 9_000_000, 1)])
    def test_build_workflow_starts_a_busy_trigger_on_a_sample(
        self, _name: str, weekly_count: int, share: int | None
    ) -> None:
        built = build_workflow(IDEA, plan(step("welcome")), context(weekly_count=weekly_count))
        assert built is not None
        if share is None:
            assert edges(built)[0] == ("trigger_node", "action_0_email", "continue", None)
            return
        assert edges(built)[:4] == [
            ("trigger_node", "action_sample", "continue", None),
            ("action_sample", "action_0_email", "branch", 0),
            ("action_sample", "exit_node", "branch", 1),
            ("action_sample", "exit_node", "continue", None),
        ]
        sample = next(action for action in built.workflow["actions"] if action["id"] == "action_sample")
        assert [cohort["percentage"] for cohort in sample["config"]["cohorts"]] == [share, 100 - share]

    @parameterized.expand(
        [
            (
                "liquid in an email",
                step(email_paragraphs=["Hi {{ person.properties.secret }} there {% if x %}"]),
                lambda inputs: inputs["email"]["value"]["html"],
                "person.properties.secret",
            ),
            (
                "hog in a slack message",
                step("ping", type="slack", slack_message="New sign-up {person.properties.secret} here"),
                lambda inputs: inputs["text"]["value"],
                "{person",
            ),
            (
                "nested braces in a slack message",
                step("ping", type="slack", slack_message="New sign-up {{x}person.properties.secret} here"),
                lambda inputs: inputs["text"]["value"],
                "{person",
            ),
            (
                "a placeholder for a property the trigger event does not carry",
                step(email_paragraphs=["You left [[secret|an item]] behind"]),
                lambda inputs: inputs["email"]["value"]["html"],
                "secret",
            ),
        ]
    )
    def test_build_workflow_strips_template_tags_from_model_copy(
        self, _name: str, planned: PlannedStep, copy_of: Any, leftover: str
    ) -> None:
        built = build_workflow(IDEA, plan(planned), context())
        assert built is not None
        copy = copy_of(built.workflow["actions"][1]["config"]["inputs"])
        assert leftover not in copy
        assert "{%" not in copy

    def test_build_workflow_shows_trigger_event_properties_through_liquid(self) -> None:
        planned = step(
            email_subject="You left [[product_name|something]] behind",
            email_paragraphs=[
                "Your [[product_name|items]] cost [[price|less than you think]].",
                "Pick [[product_name|your team's choice]] or [[price|Tom's deal]].",
                "See [[product_name|Tom&#x27;s plan\\]] today.",
            ],
        )

        built = build_workflow(IDEA, plan(planned), context(event_properties=frozenset({"product_name"})))

        assert built is not None
        email = built.workflow["actions"][1]
        assert email["config"]["inputs"]["email"]["value"]["subject"] == (
            "You left {{ event.properties.product_name | default: 'something' | raw }} behind"
        )
        assert (
            "See {{ event.properties.product_name | default: 'Toms plan' | raw }} today."
            in (email["config"]["inputs"]["email"]["value"]["text"])
        )
        assert (
            "Your {{ event.properties.product_name | default: 'items' }} cost less than you think."
            in (email["config"]["inputs"]["email"]["value"]["html"])
        )
        assert (
            "Pick {{ event.properties.product_name | default: 'your teams choice' }} or Toms deal."
            in (email["config"]["inputs"]["email"]["value"]["html"])
        )
        assert email["name"] == "You left something behind"

    @parameterized.expand(
        [
            ("starts with a capital", "welcome new trial users", "Welcome new trial users"),
            ("an em dash becomes a comma", "Welcome — let's get started", "Welcome, let's get started"),
        ]
    )
    def test_build_workflow_cleans_model_copy(self, _name: str, written: str, expected: str) -> None:
        built = build_workflow(IDEA.model_copy(update={"name": written}), plan(step()), context())
        assert built is not None
        assert built.workflow["name"] == expected

    @parameterized.expand(
        [
            ("stage", DataSuggestionStage, LifecycleStage),
            ("step kind", DataSuggestionStepKind, OutlineKind),
            ("status", DataSuggestionsStatusChoices, DataSuggestionsStatus),
        ]
    )
    def test_api_choices_match_the_values_the_service_returns(self, _name: str, choices: Any, literal: Any) -> None:
        assert set(choices.values) == set(get_args(literal))

    def test_select_prompt_events_keeps_quiet_lifecycle_events_and_drops_noise(self) -> None:
        counts = {"query executed": 9000, "page scrolled": 5000, "user_signed_up": 40, "rare_click": 2}
        assert select_prompt_events(counts, limit=2) == [("user_signed_up", 40), ("query executed", 9000)]

    def test_select_prompt_events_does_not_let_one_name_pattern_fill_the_list(self) -> None:
        counts = {f"upload_{index}_failed": 1000 + index for index in range(40)}
        counts |= {"user_signed_up": 10, "first_event_ingested": 500}

        selected = [name for name, _ in select_prompt_events(counts, limit=20)]

        assert "user_signed_up" in selected
        assert "first_event_ingested" in selected

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
                "e2": ChoiceAnswer(choice="signup", confidence=0.6, probabilities={"signup": 0.6}),
                "e3": ChoiceAnswer(choice="failure", confidence=0.6, probabilities={"failure": 0.6}),
                "e4": ChoiceAnswer(choice="signup", confidence=0.9, probabilities={"signup": 0.9}),
                "e5": ChoiceAnswer(choice="signup", confidence=0.1, probabilities={"signup": 0.1}),
                "e6": ChoiceAnswer(choice="churn_risk", confidence=0.3, probabilities={"churn_risk": 0.3}),
            },
            input_tokens=10,
        )
        assert classify_event_stages(
            team_id=1,
            event_names=[
                "account_created",
                "thing_happened",
                "summary_generated",
                "upload_failed",
                "query executed",
                "workspace created",
                "subscription paused",
            ],
        ) == {
            "account_created": "signup",
            "thing_happened": "other",
            "summary_generated": "other",
            "upload_failed": "failure",
            "query executed": "other",
            "workspace created": "signup",
            "subscription paused": "churn_risk",
        }

    @parameterized.expand([("jev is not configured", True), ("jev does not answer", False)])
    @patch("products.workflows.backend.services.data_suggestions.stages.build_system_one_client")
    def test_classify_event_stages_fails_without_a_working_jev(
        self, _name: str, not_configured: bool, build_client: MagicMock
    ) -> None:
        if not_configured:
            build_client.side_effect = SystemOneNotConfigured("no gateway")
        else:
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
