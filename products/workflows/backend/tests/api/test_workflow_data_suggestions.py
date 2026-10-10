from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models import EventDefinition

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.data_suggestions.planner import (
    PlannedBranch,
    PlannedStep,
    PlannedWorkflow,
    WorkflowIdea,
)
from products.workflows.backend.services.data_suggestions.ranking import LifecycleStage
from products.workflows.backend.services.data_suggestions.service import _FULL_SCAN_MAX_WEEKLY_EVENTS, _weekly_counts
from products.workflows.backend.services.data_suggestions.stages import StageClassificationFailed
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
        **overrides,
    )


@patch(FLAG, return_value=True)
class TestWorkflowDataSuggestions(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        for audience in ("new", "existing"):
            cache.delete(f"workflows:data_suggestions:v3:{self.team.id}:{audience}")
        self.jev_configured = patch(f"{SERVICE}.system_one_configured", return_value=True).start()
        patch(f"{SERVICE}.classify_event_stages", return_value={}).start()
        self.addCleanup(patch.stopall)
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

    def _add_sign_up_workflow(self) -> None:
        HogFlow.objects.create(
            team=self.team,
            name="Existing sign-up flow",
            status="draft",
            trigger={"type": "event", "filters": {"events": [{"id": "signed_up", "type": "events"}]}},
            actions=[],
        )

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
        assert context.prioritize_onboarding is True
        assert body["status"] == "ready"
        assert [(s["trigger_event"], s["weekly_count"]) for s in body["suggestions"]] == [("trial_started", 3)]
        assert self._list()["suggestions"] == body["suggestions"]
        assert suggest_ideas.call_count == 1

    @patch(f"{SERVICE}.suggest_ideas")
    def test_existing_teams_get_flat_weights_and_no_ideas_for_covered_moments(
        self, suggest_ideas: MagicMock, _flag
    ) -> None:
        self._add_sign_up_workflow()
        suggest_ideas.return_value = [
            _idea("trial_started", stage="trial"),
            _idea("user_registered", stage="signup"),
            _idea("query executed", stage="other"),
        ]

        body = self._list()

        context = suggest_ideas.call_args.kwargs["context"]
        assert dict(context.events) == {"trial_started": 3, "query executed": 30}
        assert context.prioritize_onboarding is False
        assert [(s["trigger_event"], s["stage"]) for s in body["suggestions"]] == [
            ("query executed", "other"),
            ("trial_started", "trial"),
        ]

    @patch(f"{SERVICE}.MAX_CLASSIFIED_EVENTS", 2)
    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_existing_triggers_reach_jev_when_candidates_fill_the_cap(
        self, suggest_ideas: MagicMock, classify: MagicMock, _flag
    ) -> None:
        HogFlow.objects.create(
            team=self.team,
            name="Existing sign-up flow",
            status="draft",
            trigger={"type": "event", "filters": {"events": [{"id": "org_provisioned", "type": "events"}]}},
            actions=[],
        )
        classify.side_effect = lambda team_id, event_names: {
            name: stage
            for name, stage in {"org_provisioned": "signup", "user_registered": "signup"}.items()
            if name in event_names[:2]
        }
        suggest_ideas.return_value = [_idea("trial_started")]

        self._list()

        assert "user_registered" not in dict(suggest_ideas.call_args.kwargs["context"].events)

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

    @parameterized.expand(
        [
            ("jev fails", StageClassificationFailed(), []),
            ("claude returns nothing", None, []),
        ]
    )
    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_failed_run_shows_nothing_and_is_not_retried_on_every_visit(
        self,
        _name: str,
        classify_error: Exception | None,
        ideas: list,
        suggest_ideas: MagicMock,
        classify: MagicMock,
        _flag,
    ) -> None:
        classify.side_effect = classify_error
        classify.return_value = {}
        suggest_ideas.return_value = ideas

        assert self._list() == {"status": "unavailable", "suggestions": []}
        assert self._list() == {"status": "unavailable", "suggestions": []}
        assert classify.call_count == 1

    @patch(f"{SERVICE}._estimated_weekly_events", return_value=2 * _FULL_SCAN_MAX_WEEKLY_EVENTS)
    def test_large_teams_get_sampled_counts_scaled_back_up(self, _estimate: MagicMock, _flag) -> None:
        counts = _weekly_counts(self.team, exclude=set())

        assert counts
        assert all(count % 2 == 0 for count in counts.values())

    @parameterized.expand(
        [
            ("without ai data processing approval", False, True, "ai_not_approved"),
            ("without jev", True, False, "unavailable"),
        ]
    )
    @patch(f"{SERVICE}.suggest_ideas")
    def test_ai_is_not_called(
        self, _name: str, approved: bool, jev_configured: bool, status: str, suggest_ideas: MagicMock, _flag
    ) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        self.jev_configured.return_value = jev_configured

        assert self._list() == {"status": status, "suggestions": []}
        suggest_ideas.assert_not_called()

    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_failed_refresh_keeps_the_working_suggestions(
        self, suggest_ideas: MagicMock, classify: MagicMock, _flag
    ) -> None:
        classify.return_value = {}
        suggest_ideas.return_value = [_idea("trial_started")]
        suggestions = self._list()["suggestions"]
        classify.side_effect = StageClassificationFailed()

        assert self._list(refresh="true") == {"status": "ready", "suggestions": suggestions}
        assert self._list() == {"status": "ready", "suggestions": suggestions}

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
