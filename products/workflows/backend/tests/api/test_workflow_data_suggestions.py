from io import StringIO

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.utils import timezone

from clickhouse_driver.errors import NetworkError
from parameterized import parameterized

from posthog.errors import InternalCHQueryError
from posthog.event_usage import EventSource
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal

from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.messaging.backend.facade.testing import create_message_template_for_test
from products.workflows.backend.facade.contracts import DataSuggestionsResult
from products.workflows.backend.models import WorkflowIdea as WorkflowIdeaModel
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.presentation.views.data_suggestion_drafts import validated_draft
from products.workflows.backend.services.data_suggestions.builder import BuildContext, build_workflow, missing_inputs
from products.workflows.backend.services.data_suggestions.event_volume import FULL_SCAN_MAX_WEEKLY_EVENTS, weekly_counts
from products.workflows.backend.services.data_suggestions.planner import (
    PlannedBranch,
    PlannedStep,
    PlannedWorkflow,
    WorkflowIdea,
)
from products.workflows.backend.services.data_suggestions.service import (
    FAILURE_CACHE_TTL_SECONDS,
    NO_SENDER_FIELD,
    _build_key,
    _build_lock_key,
    _cache_key,
    _generation_lock_key,
    _to_cache,
    build_caller,
    run_data_suggestions,
    start_build,
)
from products.workflows.backend.services.data_suggestions.stages import StageClassificationFailed
from products.workflows.backend.services.data_suggestions.team_context import (
    email_sender,
    has_verified_email_sender,
    saved_workflow_actions,
)
from products.workflows.backend.services.email_sending_controls import ensure_workflows_config
from products.workflows.backend.tasks.data_suggestions import build_data_suggestion
from products.workflows.backend.tests.api.test_hog_flow_action_email import _email_function_template, webhook_template

SERVICE = "products.workflows.backend.services.data_suggestions.service"
EVENT_VOLUME = "products.workflows.backend.services.data_suggestions.event_volume"
VIEW = "products.workflows.backend.presentation.views.workflow_data_suggestions"


def _idea(trigger_event: str) -> WorkflowIdea:
    return WorkflowIdea(
        name=f"Follow up on {trigger_event}",
        description="Send a short email after the event.",
        reason=f"{trigger_event} happens often.",
        trigger_event=trigger_event,
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


class TestWorkflowDataSuggestions(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.delete(_cache_key(self.team))
        self.jev_configured = patch(f"{SERVICE}.system_one_configured", return_value=True).start()
        self.privacy_mode = patch(f"{SERVICE}.is_privacy_mode_enabled", return_value=False).start()
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
            for index in range(count):
                _create_event(team=self.team, event=event, distinct_id=f"person-{index}")
        flush_persons_and_events()

    def _list(self, refresh: bool = False) -> dict:
        url = f"/api/projects/{self.team.id}/workflow_data_suggestions/"
        # Celery runs eagerly in tests, so the run that generate starts has finished when it returns.
        started = self.client.post(f"{url}generate/", {"refresh": refresh}, format="json")
        assert started.status_code == 200, started.json()
        response = self.client.get(f"{url}current/")
        assert response.status_code == 200, response.json()
        return response.json()

    @patch(f"{SERVICE}.suggest_ideas")
    def test_suggests_only_busy_events_and_caches_the_answer(self, suggest_ideas: MagicMock) -> None:
        suggest_ideas.return_value = [_idea("trial_started"), _idea("made_up_event")]
        for index in range(3):
            _create_event(team=self.team, event='clicked "buy"', distinct_id=f"person-{index}")
        flush_persons_and_events()

        body = self._list()

        context = suggest_ideas.call_args.kwargs["context"]
        assert dict(context.events) == {"trial_started": 3, "user_registered": 3, "query executed": 30}
        assert body["status"] == "ready"
        assert [(s["trigger_event"], s["weekly_count"]) for s in body["suggestions"]] == [("trial_started", 3)]
        assert body["email_sender_ready"] is False
        Integration.objects.create(team=self.team, kind="email", config={"email": "hi@example.com", "verified": True})
        cached = self._list()
        assert cached["suggestions"] == body["suggestions"]
        # The flag is read on every call, so a sender verified after the cards were cached shows up right away.
        assert cached["email_sender_ready"] is True
        assert suggest_ideas.call_count == 1

    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_ranks_welcome_flows_above_busier_events(self, suggest_ideas: MagicMock, classify: MagicMock) -> None:
        classify.return_value = {"query executed": "other", "trial_started": "trial", "user_registered": "signup"}
        suggest_ideas.return_value = [
            _idea("query executed"),
            _idea("trial_started"),
            _idea("user_registered"),
        ]

        body = self._list()

        assert [(s["trigger_event"], s["stage"]) for s in body["suggestions"]] == [
            ("user_registered", "signup"),
            ("trial_started", "trial"),
            ("query executed", "other"),
        ]

    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_keeps_the_models_first_idea_per_stage(self, suggest_ideas: MagicMock, classify: MagicMock) -> None:
        classify.return_value = {"user_registered": "signup", "query executed": "signup", "trial_started": "trial"}
        suggest_ideas.return_value = [
            _idea("user_registered"),
            _idea("query executed"),
            _idea("trial_started"),
        ]

        body = self._list()

        assert [(s["trigger_event"], s["stage"]) for s in body["suggestions"]] == [
            ("user_registered", "signup"),
            ("trial_started", "trial"),
        ]

    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_jev_stages_override_the_llm_label_and_reach_the_prompt(
        self, suggest_ideas: MagicMock, classify: MagicMock
    ) -> None:
        classify.return_value = {"query executed": "onboarding", "trial_started": "other"}
        suggest_ideas.return_value = [_idea("trial_started"), _idea("query executed")]

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
    ) -> None:
        classify.side_effect = classify_error
        classify.return_value = {}
        suggest_ideas.return_value = ideas

        assert self._list() == {"status": "unavailable", "suggestions": [], "email_sender_ready": False}
        assert self._list() == {"status": "unavailable", "suggestions": [], "email_sender_ready": False}
        assert classify.call_count == 1

    @patch(f"{SERVICE}.suggest_ideas")
    def test_an_empty_answer_is_retried_soon(self, suggest_ideas: MagicMock) -> None:
        suggest_ideas.return_value = [_idea("made_up_event")]

        with time_machine.travel(timezone.now(), tick=False) as clock:
            assert self._list() == {"status": "ready", "suggestions": [], "email_sender_ready": False}
            clock.shift(FAILURE_CACHE_TTL_SECONDS + 60)
            self._list()

        assert suggest_ideas.call_count == 2

    @patch(f"{EVENT_VOLUME}.estimated_weekly_events", return_value=2 * FULL_SCAN_MAX_WEEKLY_EVENTS)
    def test_large_teams_get_sampled_counts_scaled_back_up(self, _estimate: MagicMock) -> None:
        counts = weekly_counts(self.team)

        assert counts["query executed"] % 2 == 0

    @patch(f"{EVENT_VOLUME}.estimated_weekly_events", return_value=10**9 * FULL_SCAN_MAX_WEEKLY_EVENTS)
    def test_events_a_sample_misses_are_counted_exactly(self, _estimate: MagicMock) -> None:
        assert weekly_counts(self.team) == {
            "trial_started": 3,
            "signed_up": 2,
            "user_registered": 3,
            "query executed": 30,
        }

    def test_counts_every_event_past_the_default_row_limit(self) -> None:
        names = [f"quiet_{index}" for index in range(150)]
        for name in names:
            _create_event(team=self.team, event=name, distinct_id="person-1")
        flush_persons_and_events()

        assert set(names) <= set(weekly_counts(self.team))

    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_queued_retry_reads_building_not_the_old_failure(self, suggest_ideas: MagicMock) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        suggestion_id = self._list()["suggestions"][0]["id"]
        cache.set(_build_key(self.team.id, suggestion_id, "web"), {"status": "failed"}, 60)

        retry = start_build(
            team=self.team, suggestion_id=suggestion_id, caller="web", retry=True, enqueue=lambda _token: None
        )
        poll = start_build(
            team=self.team, suggestion_id=suggestion_id, caller="web", retry=False, enqueue=lambda _token: None
        )

        assert retry.status == poll.status == "building"

    @patch(f"{SERVICE}.suggest_ideas", return_value=[])
    def test_events_a_workflow_already_triggers_on_are_not_offered(self, suggest_ideas: MagicMock) -> None:
        HogFlow.objects.create(
            team=self.team,
            name="Existing trial flow",
            status="draft",
            trigger={"type": "event", "filters": {"events": [{"id": "trial_started", "type": "events"}]}},
            actions=[],
        )

        self._list()

        assert "trial_started" not in dict(suggest_ideas.call_args.kwargs["context"].events)

    @parameterized.expand(
        [
            ("query timeout", ClickHouseQueryTimeOut()),
            ("query error", InternalCHQueryError("boom")),
            ("connection failure", NetworkError("Code: 209. (host:9440)")),
            ("database error", OperationalError("server closed the connection")),
        ]
    )
    @patch(f"{EVENT_VOLUME}.execute_hogql_query")
    def test_a_failed_count_query_shows_nothing_and_is_not_retried_on_every_visit(
        self, _name: str, error: Exception, execute: MagicMock
    ) -> None:
        execute.side_effect = error

        assert self._list() == {"status": "unavailable", "suggestions": [], "email_sender_ready": False}
        assert self._list() == {"status": "unavailable", "suggestions": [], "email_sender_ready": False}
        assert execute.call_count == 1

    @parameterized.expand(
        [
            ("read", "current", {}, "cached", 200),
            ("generate answered from the cache", "generate", {}, "cached", 200),
            ("generate that has to run", "generate", {}, "empty", 429),
            ("generate that joins a running run", "generate", {}, "running", 200),
            ("refresh while a run is going", "generate", {"refresh": True}, "running", 429),
            ("refresh", "generate", {"refresh": True}, "cached", 429),
            ("refresh sent as 1", "generate", {"refresh": "1"}, "cached", 429),
            ("build", "build", {"suggestion_id": "missing"}, "cached", 429),
        ]
    )
    @patch(f"{VIEW}.AIBurstRateThrottle.wait", return_value=None)
    @patch(f"{VIEW}.AIBurstRateThrottle.allow_request", return_value=False)
    @patch(f"{SERVICE}.suggest_ideas", return_value=[])
    def test_only_calls_that_can_run_an_llm_are_throttled(
        self,
        _name: str,
        endpoint: str,
        params: dict,
        state: str,
        status: int,
        _suggest_ideas: MagicMock,
        _allow: MagicMock,
        _wait: MagicMock,
    ) -> None:
        if state == "cached":
            cache.set(_cache_key(self.team), _to_cache(DataSuggestionsResult(status="ready", suggestions=())), 60)
        elif state == "running":
            cache.set(_generation_lock_key(self.team), "other-run", 60)
        url = f"/api/projects/{self.team.id}/workflow_data_suggestions/{endpoint}/"
        if endpoint == "current":
            response = self.client.get(url)
        else:
            response = self.client.post(url, params, format="json")

        assert response.status_code == status

    @parameterized.expand(
        [
            ("read", ["hog_flow:read", "query:read"], "get", "current", 200),
            ("read without query access", ["hog_flow:read"], "get", "current", 403),
            ("generate with a read-only key", ["hog_flow:read", "query:read"], "post", "generate", 403),
            ("generate without query access", ["hog_flow:write"], "post", "generate", 403),
        ]
    )
    @patch(f"{SERVICE}.suggest_ideas", return_value=[])
    def test_a_key_needs_workflow_and_query_scopes(
        self, _name: str, scopes: list[str], method: str, endpoint: str, status: int, suggest_ideas: MagicMock
    ) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="key", user=self.user, secure_value=hash_key_value(key), scopes=scopes)
        self.client.logout()

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/workflow_data_suggestions/{endpoint}/",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == status
        suggest_ideas.assert_not_called()

    @parameterized.expand(
        [
            ("without ai data processing approval", False, True, False, "ai_not_approved"),
            ("without jev", True, False, False, "unavailable"),
            ("in privacy mode", True, True, True, "unavailable"),
        ]
    )
    @patch(f"{SERVICE}.suggest_ideas")
    def test_ai_is_not_called(
        self,
        _name: str,
        approved: bool,
        jev_configured: bool,
        privacy_mode: bool,
        status: str,
        suggest_ideas: MagicMock,
    ) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        self.jev_configured.return_value = jev_configured
        self.privacy_mode.return_value = privacy_mode

        assert self._list() == {"status": status, "suggestions": [], "email_sender_ready": False}
        suggest_ideas.assert_not_called()

    @patch(f"{SERVICE}.classify_event_stages")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_failed_refresh_keeps_the_working_suggestions(
        self, suggest_ideas: MagicMock, classify: MagicMock
    ) -> None:
        classify.return_value = {}
        suggest_ideas.return_value = [_idea("trial_started")]
        suggestions = self._list()["suggestions"]
        classify.side_effect = StageClassificationFailed()

        assert self._list(refresh=True) == {"status": "ready", "suggestions": suggestions, "email_sender_ready": False}
        assert self._list() == {"status": "ready", "suggestions": suggestions, "email_sender_ready": False}

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_build_returns_a_draft_the_create_endpoint_accepts(
        self, suggest_ideas: MagicMock, plan_steps: MagicMock
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
        build_url = f"/api/projects/{self.team.id}/workflow_data_suggestions/build/"

        build = self.client.post(build_url, {"suggestion_id": suggestion_id}, format="json")
        assert build.status_code == 200, build.json()
        assert build.json()["status"] == "ready"
        workflow = build.json()["workflow"]
        retry = self.client.post(build_url, {"suggestion_id": suggestion_id}, format="json")
        assert retry.json()["workflow"] == workflow
        assert plan_steps.call_count == 1
        assert [action["type"] for action in workflow["actions"]] == [
            "trigger",
            "function_email",
            "wait_until_condition",
            "function",
            "conditional_branch",
            "function_email",
            "exit",
        ]
        catalog = {template.template_id for template in plan_steps.call_args.kwargs["context"].step_templates}
        assert "template-webhook" in catalog
        assert "template-email" not in catalog

        create = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows", {**workflow, "status": "draft"}, format="json"
        )
        assert create.status_code == 201, create.json()
        assert create.json()["trigger"]["filters"]["events"][0]["id"] == "trial_started"

    def test_a_built_branch_has_unset_conditions_shaped_like_an_editor_branch(self) -> None:
        built = build_workflow(
            _idea("trial_started"),
            PlannedWorkflow(
                first_step="check",
                steps=[
                    _step(
                        "check",
                        "conditional_branch",
                        branches=[PlannedBranch(label="Is on a paid plan", percentage=None, next=None)],
                    )
                ],
            ),
            BuildContext(
                allowed_events=frozenset({"trial_started"}),
                step_template_ids=frozenset(),
                channels=frozenset(),
                email_templates={},
                sender=None,
                slack_integration_id=None,
            ),
        )
        assert built is not None

        branch = next(action for action in built.workflow["actions"] if action["type"] == "conditional_branch")
        # The editor's schema rejects null filters, so a suggested branch must look like one added by hand.
        assert branch["config"]["conditions"] == [{"filters": {}, "name": "Is on a paid plan"}]
        # The draft check compiles the empty condition, which must still count as unset.
        assert validated_draft(self.team, built.workflow, EventSource.WEB) is not None
        assert [item.field for item in missing_inputs(built.workflow, {})] == ["Condition: Is on a paid plan"]

    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_second_request_does_not_generate_while_one_is_running(self, suggest_ideas: MagicMock) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        assert self._list()["status"] == "ready"
        cache.add(_generation_lock_key(self.team), "another-run", 60)

        assert self._list(refresh=True) == {"status": "generating", "suggestions": [], "email_sender_ready": False}
        assert suggest_ideas.call_count == 1

        cache.delete(_generation_lock_key(self.team))
        self._list(refresh=True)
        assert suggest_ideas.call_count == 2

    @parameterized.expand(
        [
            ("ai consent withdrawn after the click", False, "own-run", "own-run", 0, False, False),
            ("a run whose lease went to a newer run", True, "newer-run", "own-run", 1, True, False),
            ("a replica that has not seen the lock yet", True, None, "own-run", 1, False, True),
        ]
    )
    @patch(f"{SERVICE}.suggest_ideas", return_value=[])
    def test_a_background_run_checks_consent_and_only_writes_while_no_newer_run_holds_the_lock(
        self,
        _name: str,
        approved: bool,
        holder: str | None,
        token: str,
        model_calls: int,
        lock_left: bool,
        cached: bool,
        suggest_ideas: MagicMock,
    ) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        if holder is not None:
            cache.set(_generation_lock_key(self.team), holder, 60)

        run_data_suggestions(team_id=self.team.id, user_id=self.user.id, lock_token=token)

        assert suggest_ideas.call_count == model_calls
        assert (cache.get(_generation_lock_key(self.team)) is not None) is lock_left
        assert (cache.get(_cache_key(self.team)) is not None) is cached

    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_run_that_loses_its_lease_does_not_replace_the_newer_cards(self, suggest_ideas: MagicMock) -> None:
        def newer_run_takes_over(**_kwargs: object) -> list:
            cache.set(_generation_lock_key(self.team), "newer-run", 60)
            return [_idea("trial_started")]

        suggest_ideas.side_effect = newer_run_takes_over
        cache.set(_generation_lock_key(self.team), "own-run", 60)

        run_data_suggestions(team_id=self.team.id, user_id=self.user.id, lock_token="own-run")

        assert cache.get(_cache_key(self.team)) is None
        assert cache.get(_generation_lock_key(self.team)) == "newer-run"

    @parameterized.expand(
        [
            ("planner returns nothing", True, None, 200, "failed", 2),
            ("planner raises", True, RuntimeError("database gone"), 200, "failed", 2),
            ("ai consent withdrawn after the cards were cached", False, None, 404, None, 0),
        ]
    )
    @patch(f"{SERVICE}.plan_steps", return_value=None)
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_failed_build_stays_failed_for_polls_until_a_retry(
        self,
        _name: str,
        approved: bool,
        planner_error: Exception | None,
        status: int,
        build_status: str | None,
        planner_calls: int,
        suggest_ideas: MagicMock,
        plan_steps: MagicMock,
    ) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.side_effect = planner_error
        suggestion_id = self._list()["suggestions"][0]["id"]
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        build_url = f"/api/projects/{self.team.id}/workflow_data_suggestions/build/"

        responses = [
            self.client.post(build_url, {"suggestion_id": suggestion_id, "retry": retry}, format="json")
            for retry in (True, False, True)
        ]

        assert [response.status_code for response in responses] == [status] * 3
        if build_status is not None:
            assert [response.json()["status"] for response in responses] == [build_status] * 3
        assert plan_steps.call_count == planner_calls

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_saved_template_offers_its_subject_and_copies_only_the_fields_it_has(
        self, suggest_ideas: MagicMock, plan_steps: MagicMock
    ) -> None:
        saved_id = create_message_template_for_test(
            team_id=self.team.id,
            name="Trial welcome",
            content={"email": {"subject": "Saved subject", "html": "<p>Saved</p>"}},
        )
        create_message_template_for_test(
            team_id=self.team.id, name="Draft", content={"email": {"subject": "No body yet", "html": ""}}
        )
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(
            first_step="welcome", steps=[_step("welcome", "email", email_template_id=str(saved_id))]
        )
        suggestion_id = self._list()["suggestions"][0]["id"]

        built = self.client.post(
            f"/api/projects/{self.team.id}/workflow_data_suggestions/build/", {"suggestion_id": suggestion_id}
        ).json()

        offered = plan_steps.call_args.kwargs["context"].email_templates
        assert [(template.id, template.subject) for template in offered] == [(saved_id, "Saved subject")]
        assert built["status"] == "ready"
        assert built["uses_saved_template"] is True
        email = built["workflow"]["actions"][1]["config"]["inputs"]["email"]["value"]
        assert email["html"] == "<p>Saved</p>"
        assert "text" not in email

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_second_build_of_the_same_suggestion_waits_for_the_first(
        self, suggest_ideas: MagicMock, plan_steps: MagicMock
    ) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        suggestion_id = self._list()["suggestions"][0]["id"]
        cache.add(f"workflows:data_suggestions:building:{self.team.id}:{suggestion_id}:web", "first-click", 60)

        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_data_suggestions/build/",
            {"suggestion_id": suggestion_id},
            format="json",
        )

        assert response.json() == {
            "status": "building",
            "workflow": None,
            "uses_saved_template": False,
            "workflow_id": None,
            "missing_inputs": [],
        }
        plan_steps.assert_not_called()

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_an_api_key_only_gets_drafts_its_own_create_call_accepts(
        self, suggest_ideas: MagicMock, plan_steps: MagicMock
    ) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(
            first_step="notify", steps=[_step("notify", "function", template_id="template-webhook")]
        )
        suggestion_id = self._list()["suggestions"][0]["id"]
        build_url = f"/api/projects/{self.team.id}/workflow_data_suggestions/build/"
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="writer", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:write", "query:read"]
        )

        web = self.client.post(build_url, {"suggestion_id": suggestion_id}, format="json")
        self.client.logout()
        auth = {"authorization": f"Bearer {key}"}
        api = self.client.post(build_url, {"suggestion_id": suggestion_id}, format="json", headers=auth)
        saved = self.client.post(
            build_url, {"suggestion_id": suggestion_id, "save_draft": True}, format="json", headers=auth
        )

        # The webhook URL stays blank, which the web editor saves as a draft and an API client's create rejects.
        assert web.json()["status"] == "ready"
        assert api.json()["status"] == "failed"
        # Saving keeps the blank and lists it, so an agent can ask the user for it.
        draft = HogFlow.objects.get(team=self.team, id=saved.json()["workflow_id"])
        assert draft.status == "draft"
        notify = next(action["id"] for action in draft.actions if action["type"] == "function")
        assert notify in {item["step_id"] for item in saved.json()["missing_inputs"]}

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_worker_saves_a_built_draft_outside_any_request(
        self, suggest_ideas: MagicMock, plan_steps: MagicMock
    ) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(first_step="welcome", steps=[_email_step("welcome", "Welcome")])
        suggestion_id = self._list()["suggestions"][0]["id"]
        caller = build_caller(EventSource.API.value, save=True, user_id=self.user.id)
        cache.set(_build_lock_key(self.team.id, suggestion_id, caller), "token", 60)

        build_data_suggestion(self.team.id, self.user.id, suggestion_id, "token", EventSource.API.value, True)

        built = cache.get(_build_key(self.team.id, suggestion_id, caller))
        assert built["status"] == "ready"
        assert HogFlow.objects.filter(team=self.team, id=built["workflow_id"], status="draft").exists()
        # The project has no sender, so the agent learns it must add one before it can fill the field.
        assert [item["field"] for item in built["missing_inputs"]] == [NO_SENDER_FIELD]

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_worker_that_lost_its_lock_saves_no_draft(self, suggest_ideas: MagicMock, plan_steps: MagicMock) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(first_step="welcome", steps=[_email_step("welcome", "Welcome")])
        suggestion_id = self._list()["suggestions"][0]["id"]
        caller = build_caller(EventSource.API.value, save=True, user_id=self.user.id)
        cache.set(_build_lock_key(self.team.id, suggestion_id, caller), "newer-run", 60)
        drafts_before = HogFlow.objects.filter(team=self.team).count()

        build_data_suggestion(self.team.id, self.user.id, suggestion_id, "stale-run", EventSource.API.value, True)

        assert HogFlow.objects.filter(team=self.team).count() == drafts_before

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_another_editor_gets_their_own_saved_draft(self, suggest_ideas: MagicMock, plan_steps: MagicMock) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(first_step="welcome", steps=[_email_step("welcome", "Welcome")])
        suggestion_id = self._list()["suggestions"][0]["id"]
        build_url = f"/api/projects/{self.team.id}/workflow_data_suggestions/build/"
        build = {"suggestion_id": suggestion_id, "save_draft": True}

        mine = self.client.post(build_url, build, format="json").json()
        self.client.force_login(User.objects.create_and_join(self.organization, "other@example.com", None))
        theirs = self.client.post(build_url, build, format="json").json()

        # A saved draft can carry access restrictions, so one editor never receives another editor's draft.
        assert theirs["workflow_id"] != mine["workflow_id"]

    def test_a_filled_secret_counts_as_set_without_returning_its_value(self) -> None:
        flow = HogFlow.objects.create(
            team=self.team,
            name="Draft",
            status="draft",
            trigger={"type": "event", "filters": {"events": []}},
            actions=[{"id": "send", "type": "function", "config": {"template_id": "template-webhook", "inputs": {}}}],
            encrypted_inputs={"send": {"token": "super-secret"}},
        )

        actions = saved_workflow_actions(self.team, str(flow.id))

        assert actions is not None
        assert actions[0]["config"]["inputs"]["token"] == {"value": "<set>"}
        assert "super-secret" not in str(actions)

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_plan_that_links_to_a_missing_step_is_planned_again(
        self, suggest_ideas: MagicMock, plan_steps: MagicMock
    ) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.side_effect = [
            PlannedWorkflow(first_step="welcome", steps=[_email_step("welcome", "Welcome", next="never_written")]),
            PlannedWorkflow(first_step="welcome", steps=[_email_step("welcome", "Welcome")]),
        ]
        suggestion_id = self._list()["suggestions"][0]["id"]

        built = self.client.post(
            f"/api/projects/{self.team.id}/workflow_data_suggestions/build/",
            {"suggestion_id": suggestion_id},
            format="json",
        ).json()

        assert built["status"] == "ready"
        assert plan_steps.call_count == 2

    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_a_saved_build_is_read_again_from_its_draft(self, suggest_ideas: MagicMock, plan_steps: MagicMock) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(first_step="welcome", steps=[_email_step("welcome", "Welcome")])
        suggestion_id = self._list()["suggestions"][0]["id"]
        build_url = f"/api/projects/{self.team.id}/workflow_data_suggestions/build/"
        build = {"suggestion_id": suggestion_id, "save_draft": True}

        first = self.client.post(build_url, build, format="json").json()
        Integration.objects.create(team=self.team, kind="email", config={"email": "hi@example.com", "verified": True})
        cached = self.client.post(build_url, build, format="json").json()
        HogFlow.objects.filter(team=self.team, id=first["workflow_id"]).delete()
        rebuilt = self.client.post(build_url, build, format="json").json()

        assert [item["field"] for item in first["missing_inputs"]] == [NO_SENDER_FIELD]
        assert cached["workflow_id"] == first["workflow_id"]
        assert [item["field"] for item in cached["missing_inputs"]] == ["Email sender"]
        assert rebuilt["status"] == "ready"
        assert rebuilt["workflow_id"] != first["workflow_id"]
        assert plan_steps.call_count == 2

    @parameterized.expand(
        [
            ("the project default", ["old@example.com", "new@example.com"], "new@example.com", "new@example.com"),
            ("the only verified sender", ["only@example.com"], None, "only@example.com"),
            ("several senders and no default", ["a@example.com", "b@example.com"], None, None),
            ("no verified sender", [], None, None),
        ]
    )
    def test_drafts_send_from(
        self,
        _name: str,
        senders: list[str],
        default: str | None,
        expected: str | None,
    ) -> None:
        integrations = {
            address: Integration.objects.create(
                team=self.team, kind="email", config={"email": address, "verified": True}
            )
            for address in senders
        }
        if default is not None:
            ensure_workflows_config(self.team.id)
            TeamWorkflowsConfig.objects.filter(team_id=self.team.id).update(
                default_email_integration_id=integrations[default].id
            )

        sender = email_sender(self.team)

        assert (sender.email if sender else None) == expected
        assert has_verified_email_sender(self.team) is bool(senders)

    def test_build_with_an_unknown_suggestion_is_not_found(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/workflow_data_suggestions/build/",
            {"suggestion_id": "missing"},
            format="json",
        )
        assert response.status_code == 404

    @parameterized.expand(
        [
            ("one_project", ""),
            ("with_an_unknown_project", "team 999999: skipped, no such project\n"),
        ]
    )
    @patch(f"{SERVICE}.posthoganalytics.capture")
    @patch(f"{SERVICE}.plan_steps")
    @patch(f"{SERVICE}.suggest_ideas")
    def test_premade_ideas_replace_the_generated_cards_until_one_click_saves_them(
        self,
        _name: str,
        missing: str,
        suggest_ideas: MagicMock,
        plan_steps: MagicMock,
        capture: MagicMock,
    ) -> None:
        suggest_ideas.return_value = [_idea("trial_started")]
        plan_steps.return_value = PlannedWorkflow(first_step="welcome", steps=[_email_step("welcome", "Welcome")])
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        args = ["--team-ids", str(self.team.id), *(["999999"] if missing else [])]

        def prepare() -> str:
            out = StringIO()
            call_command("prepare_workflow_ideas", *args, stdout=out)
            return out.getvalue()

        with self.assertRaises(CommandError):
            call_command("prepare_workflow_ideas")
        assert prepare() == missing + f"team {self.team.id}: stored Follow up on trial_started, 0 failed to build\n"
        assert prepare() == missing + f"team {self.team.id}: skipped, 1 ideas already waiting\n"
        suggest_ideas.reset_mock()
        plan_steps.reset_mock()
        sender = Integration.objects.create(
            team=self.team, kind="email", config={"email": "hello@example.com", "verified": True}
        )
        idea = WorkflowIdeaModel.objects.for_team(self.team.id).get()

        cards = self._list(refresh=True)

        assert [(card["id"], card["premade"]) for card in cards["suggestions"]] == [(str(idea.id), True)]
        assert suggest_ideas.call_count == 0
        assert cache.get(_cache_key(self.team)) is None

        save = {"suggestion_id": str(idea.id), "save_draft": True}
        build_url = f"/api/projects/{self.team.id}/workflow_data_suggestions/build/"
        unsaved = self.client.post(build_url, {"suggestion_id": str(idea.id)}, format="json")
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        withdrawn = (self._list()["status"], self.client.post(build_url, save, format="json").status_code)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        other_team = Team.objects.create(organization=self.organization)
        foreign = self.client.post(
            f"/api/projects/{other_team.id}/workflow_data_suggestions/build/", save, format="json"
        )
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        from_child = self.client.post(
            f"/api/environments/{child.id}/workflow_data_suggestions/build/", save, format="json"
        )
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="agent", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:write", "query:read"]
        )
        self.client.logout()
        auth = {"authorization": f"Bearer {key}"}
        saved = self.client.post(build_url, save, format="json", headers=auth)
        repeated = self.client.post(build_url, save, format="json", headers=auth)

        assert (unsaved.status_code, unsaved.json()["status"], unsaved.json()["workflow_id"]) == (200, "ready", None)
        assert withdrawn == ("ai_not_approved", 404)
        assert (foreign.status_code, from_child.status_code, saved.status_code, repeated.status_code) == (
            404,
            404,
            200,
            409,
        )
        draft = HogFlow.objects.get(team=self.team)
        idea.refresh_from_db()
        assert (idea.status, idea.hog_flow_id) == ("accepted", draft.id)
        assert saved.json()["workflow_id"] == str(draft.id)
        # The sender was verified after the idea was built, so the save fills it in.
        assert draft.actions[1]["config"]["inputs"]["email"]["value"]["from"]["integrationId"] == sender.id
        assert plan_steps.call_count == 0
        events = {call.kwargs.get("event"): call.kwargs.get("properties", {}) for call in capture.call_args_list}
        assert events["workflows data suggestion built"]["source"] == EventSource.API.value
        assert events["hog_flow_created"]["workflow_id"] == str(draft.id)

        self.client.force_login(self.user)
        suggest_ideas.return_value = [_idea("user_registered")]
        assert [card["premade"] for card in self._list()["suggestions"]] == [False]
