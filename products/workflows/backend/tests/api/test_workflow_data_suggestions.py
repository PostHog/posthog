from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models import EventDefinition

from products.workflows.backend.services.data_suggestions.planner import (
    PlannedBranch,
    PlannedStep,
    PlannedWorkflow,
    WorkflowIdea,
)
from products.workflows.backend.services.data_suggestions.ranking import LifecycleStage
from products.workflows.backend.tests.api.test_hog_flow_action_email import _email_function_template, webhook_template

SERVICE = "products.workflows.backend.services.data_suggestions.service"
FLAG = "products.workflows.backend.presentation.views.workflow_data_suggestions.posthoganalytics.feature_enabled"


def _idea(trigger_event: str, stage: LifecycleStage = "trial") -> WorkflowIdea:
    return WorkflowIdea(
        name=f"Follow up on {trigger_event}",
        description="Send a short email after the event.",
        reason=f"{trigger_event} happens often.",
        trigger_event=trigger_event,
        stage=stage,
        step_outline=["email", "delay", "email"],
    )


def _step(step_id: str, step_type: str, **overrides: object) -> PlannedStep:
    values: dict = {
        "id": step_id,
        "type": step_type,
        "name": step_id,
        "setup_note": "",
        "next": None,
        "branches": None,
        "template_id": None,
        "wait_event": None,
        "wait_event_next": None,
        "duration": None,
        "email_template_id": None,
        "email_subject": None,
        "email_heading": None,
        "email_paragraphs": None,
        "email_button_label": None,
        "slack_message": None,
    }
    values.update(overrides)
    return PlannedStep(**values)


def _email_step(step_id: str, subject: str, **overrides: object) -> PlannedStep:
    return _step(
        step_id,
        "email",
        email_subject=subject,
        email_heading=subject,
        email_paragraphs=["Thanks for trying the product."],
        email_button_label="Open the app",
        **overrides,
    )


@patch(FLAG, return_value=True)
class TestWorkflowDataSuggestions(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.delete(f"workflows:data_suggestions:v3:{self.team.id}")
        sync_template_to_db(_email_function_template())
        sync_template_to_db(webhook_template)
        for event, count in [
            ("trial_started", 3),
            ("signed_up", 2),
            ("$pageview", 5),
            ("user_registered", 3),
            ("query executed", 30),
        ]:
            EventDefinition.objects.create(team=self.team, name=event)
            for index in range(count):
                _create_event(team=self.team, event=event, distinct_id=f"person-{index}")
        flush_persons_and_events()

    def _list(self, **params: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/workflow_data_suggestions/current/", params)
        assert response.status_code == 200, response.json()
        return response.json()

    @patch(f"{SERVICE}.suggest_ideas")
    def test_suggests_only_busy_events_and_caches_the_answer(self, suggest_ideas: MagicMock, _flag) -> None:
        suggest_ideas.return_value = [_idea("trial_started"), _idea("made_up_event")]

        body = self._list()

        context = suggest_ideas.call_args.kwargs["context"]
        assert dict(context.events) == {"trial_started": 3, "user_registered": 3, "query executed": 30}
        assert body["status"] == "ready"
        assert [(s["trigger_event"], s["weekly_count"]) for s in body["suggestions"]] == [("trial_started", 3)]
        assert self._list()["suggestions"] == body["suggestions"]
        assert suggest_ideas.call_count == 1

    @patch(f"{SERVICE}.suggest_ideas")
    def test_ranks_welcome_flows_above_busier_events(self, suggest_ideas: MagicMock, _flag) -> None:
        suggest_ideas.return_value = [
            _idea("query executed", stage="other"),
            _idea("trial_started", stage="trial"),
            _idea("user_registered", stage="signup"),
        ]

        body = self._list()

        assert [(s["trigger_event"], s["stage"]) for s in body["suggestions"]] == [
            ("user_registered", "signup"),
            ("trial_started", "trial"),
            ("query executed", "other"),
        ]

    @patch(f"{SERVICE}.suggest_ideas")
    def test_keeps_only_the_best_idea_per_stage(self, suggest_ideas: MagicMock, _flag) -> None:
        suggest_ideas.return_value = [
            _idea("user_registered", stage="signup"),
            _idea("query executed", stage="signup"),
            _idea("trial_started", stage="trial"),
        ]

        body = self._list()

        assert [(s["trigger_event"], s["stage"]) for s in body["suggestions"]] == [
            ("query executed", "signup"),
            ("trial_started", "trial"),
        ]

    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_jev_stages_override_the_llm_label_and_reach_the_prompt(
        self, suggest_ideas: MagicMock, classify: MagicMock, _flag
    ) -> None:
        classify.return_value = {"query executed": "onboarding", "trial_started": "other"}
        suggest_ideas.return_value = [_idea("trial_started", stage="trial"), _idea("query executed", stage="other")]

        body = self._list()

        assert suggest_ideas.call_args.kwargs["context"].stages == classify.return_value
        assert [(s["trigger_event"], s["stage"]) for s in body["suggestions"]] == [
            ("query executed", "onboarding"),
            ("trial_started", "other"),
        ]

    @patch(f"{SERVICE}.suggest_ideas")
    def test_ai_is_not_called_without_ai_data_processing_approval(self, suggest_ideas: MagicMock, _flag) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        assert self._list() == {"status": "ai_not_approved", "suggestions": []}
        suggest_ideas.assert_not_called()

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_build_returns_a_draft_the_create_endpoint_accepts(
        self, suggest_ideas: MagicMock, plan_steps: MagicMock, _flag
    ) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(
            first_step="welcome",
            steps=[
                _email_step("welcome", "Your trial started", next="wait"),
                _step(
                    "wait",
                    "wait_until_event",
                    wait_event="user_registered",
                    wait_event_next="notify",
                    duration="3d",
                    next="check",
                ),
                _step("notify", "function", template_id="template-webhook", setup_note="Add the endpoint URL"),
                _step(
                    "check",
                    "conditional_branch",
                    branches=[PlannedBranch(label="Is on a paid plan", percentage=None, next=None)],
                    next="nudge",
                ),
                _email_step("nudge", "Ready to upgrade?"),
            ],
        )
        suggestion_id = self._list()["suggestions"][0]["id"]

        build = self.client.post(
            f"/api/projects/{self.team.id}/workflow_data_suggestions/build/",
            {"suggestion_id": suggestion_id},
            format="json",
        )
        assert build.status_code == 200, build.json()
        workflow = build.json()["workflow"]
        assert [action["type"] for action in workflow["actions"]] == [
            "trigger",
            "function_email",
            "wait_until_condition",
            "function",
            "conditional_branch",
            "function_email",
            "exit",
        ]
        catalog = {template_id for template_id, _, _ in plan_steps.call_args.kwargs["context"].step_templates}
        assert "template-webhook" in catalog
        assert "template-email" not in catalog

        create = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows", {**workflow, "status": "draft"}, format="json"
        )
        assert create.status_code == 201, create.json()
        assert create.json()["trigger"]["filters"]["events"][0]["id"] == "trial_started"

    def test_build_with_an_unknown_suggestion_is_not_found(self, _flag) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_data_suggestions/build/",
            {"suggestion_id": "missing"},
            format="json",
        )
        assert response.status_code == 404

    def test_endpoints_are_off_without_the_feature_flag(self, flag: MagicMock) -> None:
        flag.return_value = False
        response = self.client.get(f"/api/projects/{self.team.id}/workflow_data_suggestions/current/")
        assert response.status_code == 403
