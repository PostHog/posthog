import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.oauth import POSTHOG_AI_APP_CLIENT_ID_DEV, resolve_scopes

from products.approvals.backend.exceptions import ApprovalRequired
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.feature_flag_rollout_plan import FeatureFlagRolloutPlan
from products.feature_flags.backend.rollout_plans import (
    AGENT_ROLLOUTS_OFF_REASON,
    AI_PROCESSING_OFF_REASON,
    RUN_ENDED_REASON,
    stop_rollout_plans_with_ended_runs,
)
from products.feature_flags.backend.task_profiles import (
    FEATURE_FLAG_ROLLOUT_PROFILE,
    ROLLOUT_HIDDEN_TOOLS,
    ROLLOUT_PLAN_MCP_SCOPES,
)
from products.tasks.backend.models import Task, TaskRun

TASK_ID = UUID("00000000-0000-4000-8000-000000000001")
FIRST_RUN_ID = UUID("00000000-0000-4000-8000-000000000002")
ROLLOUTS = "products.feature_flags.backend.rollout_plans"
TASK_WORKFLOW = "products.tasks.backend.temporal.client.execute_task_processing_workflow"


def _run_token(
    user: User, team: Team, *, task_id: UUID, scope: str = "feature_flag_rollout_plan:write"
) -> OAuthAccessToken:
    application, _ = OAuthApplication.objects.get_or_create(
        client_id=POSTHOG_AI_APP_CLIENT_ID_DEV,
        defaults={
            "name": "sandbox",
            "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://example.com/callback",
            "algorithm": "RS256",
            "organization": team.organization,
            "user": user,
        },
    )
    return OAuthAccessToken.objects.create(
        user=user,
        application=application,
        token=f"pha_{uuid4().hex}",
        scope=scope,
        expires=timezone.now() + timedelta(days=30),
        scoped_teams=[team.id],
        scoped_organizations=[],
        sandbox_task_id=task_id,
    )


class TestFeatureFlagRolloutToolset(SimpleTestCase):
    def test_the_only_reachable_writes_are_the_plan_reports(self) -> None:
        catalog = Path(__file__).parents[4] / "services" / "mcp" / "schema" / "generated-tool-definitions.json"
        definitions: dict[str, dict] = json.loads(catalog.read_text())
        granted = set(resolve_scopes(ROLLOUT_PLAN_MCP_SCOPES))

        reachable_writes = {
            name
            for name, definition in definitions.items()
            if name not in ROLLOUT_HIDDEN_TOOLS
            and set(definition.get("required_scopes") or []) <= granted
            and (definition.get("annotations") or {}).get("readOnlyHint") is not True
        }

        assert reachable_writes == {"feature-flag-rollout-plan-advance", "feature-flag-rollout-plan-fail"}


@patch(f"{ROLLOUTS}.is_sandbox_run_request", return_value=True)
@patch(f"{ROLLOUTS}.get_feature_flag_or_none", return_value=True)
@patch(f"{ROLLOUTS}.task_run_usage_limited", return_value=False)
@patch(f"{ROLLOUTS}.create_notification")
@patch(f"{ROLLOUTS}.cancel_task_run")
@patch(f"{ROLLOUTS}.tasks_facade.run_task")
@patch(f"{ROLLOUTS}.tasks_facade.create_and_run_task")
class TestFeatureFlagRolloutPlanAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = FeatureFlag.objects.create(
            team=self.team,
            key="faster-report-cache",
            created_by=self.user,
            version=1,
            filters={"groups": [{"properties": [], "rollout_percentage": 1}]},
        )
        self.other_flag = FeatureFlag.objects.create(
            team=self.team,
            key="other-flag",
            created_by=self.user,
            version=1,
            filters={"groups": [{"properties": [], "rollout_percentage": 1}]},
        )
        self.url = f"/api/projects/{self.team.id}/feature_flag_rollout_plans/"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

    def _body(self, **overrides: Any) -> dict[str, Any]:
        return {
            "feature_flag": self.flag.id,
            "percentages": [5, 50, 100],
            "soak_hours": 24,
            "health_checks": "Stop when the error rate on dashboard 7 passes 2%.",
            **overrides,
        }

    def _plan(self, **overrides: Any) -> FeatureFlagRolloutPlan:
        values = {
            "team": self.team,
            "feature_flag": self.flag,
            "created_by": self.user,
            "condition_index": 0,
            "percentages": [5, 50, 100],
            "soak_hours": 24,
            "health_checks": "Stop when the error rate passes 2%.",
            "expected_flag_version": 1,
            "task_id": TASK_ID,
            "latest_run_id": FIRST_RUN_ID,
            **overrides,
        }
        return FeatureFlagRolloutPlan.objects.for_team(self.team.id).create(**values)

    def _use_run_token(self, *, task_id: UUID = TASK_ID, scope: str = "feature_flag_rollout_plan:write") -> None:
        token = _run_token(self.user, self.team, task_id=task_id, scope=scope)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

    def _advance(self, plan: FeatureFlagRolloutPlan) -> Any:
        return self.client.post(f"{self.url}{plan.id}/advance/", {"summary": "Errors held at 0.4%."}, format="json")

    def _rollout(self, flag: FeatureFlag | None = None) -> int:
        flag = FeatureFlag.objects.get(pk=(flag or self.flag).pk)
        return flag.get_filters()["groups"][0]["rollout_percentage"]

    def _scheduled_runs(self, run_task: MagicMock) -> None:
        run_task.side_effect = lambda *args, **kwargs: MagicMock(error=None, run_id=uuid4())

    def test_starting_a_plan_gives_the_run_no_general_flag_write_scope(
        self, create_and_run_task: MagicMock, *_: MagicMock
    ) -> None:
        create_and_run_task.return_value = MagicMock(task_id=TASK_ID, latest_run=MagicMock(id=FIRST_RUN_ID))

        response = self.client.post(self.url, self._body(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        plan = FeatureFlagRolloutPlan.objects.for_team(self.team.id).get(pk=response.json()["id"])
        assert (plan.task_id, plan.latest_run_id) == (TASK_ID, FIRST_RUN_ID)
        assert create_and_run_task.call_args.kwargs["profile"] == FEATURE_FLAG_ROLLOUT_PROFILE
        scopes = resolve_scopes(create_and_run_task.call_args.kwargs["posthog_mcp_scopes"])
        assert "feature_flag_rollout_plan:write" in scopes
        assert not [
            scope for scope in scopes if scope.endswith(":write") and scope != "feature_flag_rollout_plan:write"
        ]
        assert self._rollout() == 1

    @parameterized.expand(
        [
            ("not_increasing", {"percentages": [50, 25]}, status.HTTP_400_BAD_REQUEST),
            ("repeats_a_percentage", {"percentages": [5, 5]}, status.HTTP_400_BAD_REQUEST),
            ("above_everyone", {"percentages": [5, 101]}, status.HTTP_400_BAD_REQUEST),
            ("not_above_current_rollout", {"percentages": [1, 5]}, status.HTTP_400_BAD_REQUEST),
            ("no_such_condition", {"condition_index": 4}, status.HTTP_400_BAD_REQUEST),
            ("too_short_a_soak", {"soak_hours": 0}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_refuses_a_plan_that_cannot_run(
        self,
        create_and_run_task: MagicMock,
        _run: MagicMock,
        _cancel: MagicMock,
        _notify: MagicMock,
        _usage: MagicMock,
        _enabled: MagicMock,
        _bound: MagicMock,
        _name: str,
        overrides: dict[str, Any],
        expected: int,
    ) -> None:
        response = self.client.post(self.url, self._body(**overrides), format="json")

        assert response.status_code == expected, response.json()
        create_and_run_task.assert_not_called()

    @parameterized.expand(
        [
            ("another_config_format", {"version": 2, "return_type": "boolean", "default_value": False, "rules": []}),
            ("already_at_everyone", {"groups": [{"properties": [], "rollout_percentage": None}]}),
        ]
    )
    def test_refuses_a_flag_it_cannot_roll_out(
        self,
        create_and_run_task: MagicMock,
        _run: MagicMock,
        _cancel: MagicMock,
        _notify: MagicMock,
        _usage: MagicMock,
        _enabled: MagicMock,
        _bound: MagicMock,
        _name: str,
        filters: dict[str, Any],
    ) -> None:
        FeatureFlag.objects.filter(pk=self.flag.pk).update(filters=filters)

        response = self.client.post(self.url, self._body(), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        create_and_run_task.assert_not_called()

    def test_refuses_a_second_active_plan(self, create_and_run_task: MagicMock, *_: MagicMock) -> None:
        self._plan()

        response = self.client.post(self.url, self._body(), format="json")

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()

    @parameterized.expand(
        [
            ("feature_off", False, True, AGENT_ROLLOUTS_OFF_REASON, AGENT_ROLLOUTS_OFF_REASON),
            ("ai_processing_off", True, False, AI_PROCESSING_OFF_REASON, AI_PROCESSING_OFF_REASON),
            ("ai_processing_unset", True, None, AI_PROCESSING_OFF_REASON, AI_PROCESSING_OFF_REASON),
            ("flag_service_unreachable", None, True, AGENT_ROLLOUTS_OFF_REASON, None),
        ]
    )
    def test_when_a_plan_can_start_and_continue(
        self,
        create_and_run_task: MagicMock,
        run_task: MagicMock,
        _cancel: MagicMock,
        notify: MagicMock,
        _usage: MagicMock,
        flag_value: MagicMock,
        _bound: MagicMock,
        _name: str,
        flag_result: bool | None,
        ai_processing: bool | None,
        start_refusal: str,
        stop_reason: str | None,
    ) -> None:
        flag_value.return_value = flag_result
        self.organization.is_ai_data_processing_approved = ai_processing
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self._scheduled_runs(run_task)

        response = self.client.post(self.url, self._body(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == start_refusal
        create_and_run_task.assert_not_called()

        plan = self._plan()
        self._use_run_token()

        response = self._advance(plan)

        if stop_reason is None:
            assert response.json()["status"] == FeatureFlagRolloutPlan.Status.ACTIVE
            assert self._rollout() == 5
        else:
            assert (response.json()["status"], response.json()["stop_reason"]) == (
                FeatureFlagRolloutPlan.Status.STOPPED,
                stop_reason,
            )
            assert self._rollout() == 1
            run_task.assert_not_called()
            notify.assert_called_once()

    def test_a_run_cannot_approve_a_plan(self, create_and_run_task: MagicMock, *_: MagicMock) -> None:
        self._use_run_token()

        response = self.client.post(self.url, self._body(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        create_and_run_task.assert_not_called()

    def test_run_token_cannot_write_flags_directly(self, *_: MagicMock) -> None:
        plan = self._plan()
        self._use_run_token(scope=" ".join(resolve_scopes(ROLLOUT_PLAN_MCP_SCOPES)))

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{self.other_flag.id}/set_release_condition_rollout/",
            {"condition_index": 0, "rollout_percentage": 100, "version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self._rollout(self.other_flag) == 1
        assert plan.status == FeatureFlagRolloutPlan.Status.ACTIVE

    def test_advance_applies_only_the_next_approved_percentage(
        self, _create: MagicMock, run_task: MagicMock, *_: MagicMock
    ) -> None:
        self._scheduled_runs(run_task)
        plan = self._plan()
        self._use_run_token()

        response = self._advance(plan)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._rollout() == 5
        assert self._rollout(self.other_flag) == 1
        plan.refresh_from_db()
        assert plan.steps_applied == 1
        kwargs = run_task.call_args.kwargs
        assert kwargs["posthog_mcp_scopes"] == ROLLOUT_PLAN_MCP_SCOPES
        assert kwargs["validated_data"]["resume_from_run_id"] == str(FIRST_RUN_ID)
        assert kwargs["validated_data"]["scheduled_at"] == plan.next_check_at
        assert plan.latest_run_id != FIRST_RUN_ID

    def test_another_run_cannot_advance_the_plan(self, _create: MagicMock, run_task: MagicMock, *_: MagicMock) -> None:
        plan = self._plan()
        self._use_run_token(task_id=UUID("00000000-0000-4000-8000-000000000009"))

        assert self._advance(plan).status_code == status.HTTP_403_FORBIDDEN
        assert self._rollout() == 1
        run_task.assert_not_called()

    @parameterized.expand([("advance", {"summary": "Errors held."}), ("fail", {"reason": "Injected."})])
    def test_an_earlier_run_of_the_plan_cannot_report(
        self,
        _create: MagicMock,
        run_task: MagicMock,
        _cancel: MagicMock,
        _notify: MagicMock,
        _usage: MagicMock,
        _enabled: MagicMock,
        bound: MagicMock,
        report: str,
        body: dict[str, str],
    ) -> None:
        self._scheduled_runs(run_task)
        bound.side_effect = lambda *, run_id, **_: run_id == str(FIRST_RUN_ID)
        plan = self._plan()
        self._use_run_token()
        assert self._advance(plan).status_code == status.HTTP_200_OK

        with time_machine.travel(timezone.now() + timedelta(hours=25)):
            response = self.client.post(f"{self.url}{plan.id}/{report}/", body, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        plan.refresh_from_db()
        assert (plan.status, plan.steps_applied) == (FeatureFlagRolloutPlan.Status.ACTIVE, 1)
        assert self._rollout() == 5

    def test_a_person_cannot_advance_the_plan(self, _create: MagicMock, run_task: MagicMock, *_: MagicMock) -> None:
        plan = self._plan()

        assert self._advance(plan).status_code == status.HTTP_403_FORBIDDEN
        assert self._rollout() == 1

    def test_run_cannot_skip_the_time_between_steps(
        self, _create: MagicMock, run_task: MagicMock, *_: MagicMock
    ) -> None:
        self._scheduled_runs(run_task)
        plan = self._plan()
        self._use_run_token()

        assert self._advance(plan).status_code == status.HTTP_200_OK
        assert self._advance(plan).status_code == status.HTTP_409_CONFLICT
        assert self._rollout() == 5
        assert run_task.call_count == 1

    def test_the_chain_ends_after_the_approved_steps_and_one_last_check(
        self, _create: MagicMock, run_task: MagicMock, _cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        self._scheduled_runs(run_task)
        plan = self._plan()
        self._use_run_token()

        seen = []
        with time_machine.travel(timezone.now(), tick=False) as clock:
            for _step in range(4):
                assert self._advance(plan).status_code == status.HTTP_200_OK
                seen.append(self._rollout())
                clock.shift(timedelta(hours=25))
            assert self._advance(plan).status_code == status.HTTP_409_CONFLICT

        plan.refresh_from_db()
        assert seen == [5, 50, 100, 100]
        assert plan.status == FeatureFlagRolloutPlan.Status.COMPLETED
        assert plan.next_check_at is None
        assert run_task.call_count == 3
        assert "finished" in notify.call_args.args[0].title

    def test_a_flag_edited_by_a_person_stops_the_plan_instead_of_overwriting_it(
        self, _create: MagicMock, run_task: MagicMock, _cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        FeatureFlag.objects.filter(pk=self.flag.pk).update(
            version=2, filters={"groups": [{"properties": [], "rollout_percentage": 3}]}
        )
        self._use_run_token()

        response = self._advance(plan)

        assert response.json()["status"] == FeatureFlagRolloutPlan.Status.STOPPED
        assert response.json()["steps_applied"] == 0
        assert self._rollout() == 3
        run_task.assert_not_called()
        assert notify.call_args.args[0].target_id == str(self.user.id)

    def test_a_flag_that_needs_approval_stops_the_plan(
        self, _create: MagicMock, run_task: MagicMock, _cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        self._use_run_token()

        with patch(f"{ROLLOUTS}.update_flag", side_effect=ApprovalRequired(MagicMock(), "Needs approval.", {})):
            response = self._advance(plan)

        assert response.json()["status"] == FeatureFlagRolloutPlan.Status.STOPPED
        assert "approval" in response.json()["stop_reason"]
        run_task.assert_not_called()
        notify.assert_called_once()

    def test_losing_edit_access_stops_the_plan(
        self, _create: MagicMock, run_task: MagicMock, _cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        self._use_run_token()

        with patch(f"{ROLLOUTS}.user_can_edit_flag", return_value=False):
            response = self._advance(plan)

        assert response.json()["status"] == FeatureFlagRolloutPlan.Status.STOPPED
        assert self._rollout() == 1
        notify.assert_called_once()

    def test_an_unexpected_error_during_a_step_undoes_the_flag_change(
        self, _create: MagicMock, run_task: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        self._use_run_token()
        self.client.raise_request_exception = False

        with patch.object(FeatureFlagRolloutPlan, "save", side_effect=RuntimeError("Database unavailable.")):
            response = self._advance(plan)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert self._rollout() == 1
        plan.refresh_from_db()
        assert (plan.status, plan.steps_applied) == (FeatureFlagRolloutPlan.Status.ACTIVE, 0)
        run_task.assert_not_called()

    def test_a_stop_during_scheduling_cancels_the_check_it_could_not_see(
        self, _create: MagicMock, run_task: MagicMock, cancel: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        new_run_id = uuid4()

        def stop_while_scheduling(*args: Any, **kwargs: Any) -> MagicMock:
            FeatureFlagRolloutPlan.objects.filter(pk=plan.pk).update(status=FeatureFlagRolloutPlan.Status.STOPPED)
            return MagicMock(error=None, run_id=new_run_id)

        run_task.side_effect = stop_while_scheduling
        self._use_run_token()

        response = self._advance(plan)

        assert response.json()["status"] == FeatureFlagRolloutPlan.Status.STOPPED
        assert cancel.call_args.args[:3] == (new_run_id, TASK_ID, self.team.id)
        plan.refresh_from_db()
        assert plan.latest_run_id == FIRST_RUN_ID

    def test_a_failed_schedule_stops_the_plan_and_tells_the_person(
        self, _create: MagicMock, run_task: MagicMock, _cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        run_task.return_value = None
        plan = self._plan()
        self._use_run_token()

        response = self._advance(plan)

        assert response.json()["status"] == FeatureFlagRolloutPlan.Status.STOPPED
        notify.assert_called_once()

    def test_failing_health_check_stops_the_plan_and_notifies_the_person(
        self, _create: MagicMock, _run: MagicMock, cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        self._use_run_token()

        response = self.client.post(f"{self.url}{plan.id}/fail/", {"reason": "Errors reached 6%."}, format="json")

        assert response.json()["status"] == FeatureFlagRolloutPlan.Status.STOPPED
        assert response.json()["next_check_at"] is None
        assert self._rollout() == 1
        cancel.assert_not_called()
        assert "Errors reached 6%." in notify.call_args.args[0].body

    def test_a_run_that_ended_without_reporting_stops_only_its_own_plan(
        self, _create: MagicMock, _run: MagicMock, cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        ended = self._plan(next_check_at=timezone.now() + timedelta(hours=1))
        running = self._plan(feature_flag=self.other_flag, latest_run_id=uuid4())

        with patch(f"{ROLLOUTS}.tasks_facade.ended_task_run_ids", return_value={FIRST_RUN_ID}) as ended_run_ids:
            stop_rollout_plans_with_ended_runs()

        assert set(ended_run_ids.call_args.args[0]) == {FIRST_RUN_ID, running.latest_run_id}
        ended.refresh_from_db()
        running.refresh_from_db()
        assert (ended.status, ended.stop_reason, ended.next_check_at) == (
            FeatureFlagRolloutPlan.Status.STOPPED,
            RUN_ENDED_REASON,
            None,
        )
        assert running.status == FeatureFlagRolloutPlan.Status.ACTIVE
        assert self._rollout() == 1
        cancel.assert_not_called()
        notify.assert_called_once()
        assert RUN_ENDED_REASON in notify.call_args.args[0].body

    def test_the_sweep_keeps_a_plan_that_scheduled_a_new_check_meanwhile(
        self, _create: MagicMock, _run: MagicMock, _cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()

        def schedule_during_the_sweep(_run_ids: Any) -> set[UUID]:
            FeatureFlagRolloutPlan.objects.for_team(self.team.id).filter(pk=plan.pk).update(latest_run_id=uuid4())
            return {FIRST_RUN_ID}

        with patch(f"{ROLLOUTS}.tasks_facade.ended_task_run_ids", side_effect=schedule_during_the_sweep):
            stop_rollout_plans_with_ended_runs()

        plan.refresh_from_db()
        assert plan.status == FeatureFlagRolloutPlan.Status.ACTIVE
        notify.assert_not_called()

    def test_the_sweep_stops_a_plan_and_its_pending_check_when_ai_processing_is_turned_off(
        self, _create: MagicMock, _run: MagicMock, cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        with patch(f"{ROLLOUTS}.tasks_facade.ended_task_run_ids", return_value=set()):
            stop_rollout_plans_with_ended_runs()

        plan.refresh_from_db()
        assert (plan.status, plan.stop_reason) == (FeatureFlagRolloutPlan.Status.STOPPED, AI_PROCESSING_OFF_REASON)
        assert cancel.call_args.args[:3] == (FIRST_RUN_ID, TASK_ID, self.team.id)
        notify.assert_called_once()

    def test_a_person_stopping_the_plan_cancels_the_pending_check(
        self, _create: MagicMock, _run: MagicMock, cancel: MagicMock, notify: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()

        response = self.client.post(f"{self.url}{plan.id}/stop/", {"reason": "Pausing for the launch."}, format="json")

        assert response.json()["status"] == FeatureFlagRolloutPlan.Status.STOPPED
        assert cancel.call_args.args[:3] == (FIRST_RUN_ID, TASK_ID, self.team.id)
        notify.assert_not_called()

    def test_a_run_cannot_use_the_stop_action_for_people(
        self, _create: MagicMock, _run: MagicMock, cancel: MagicMock, *_: MagicMock
    ) -> None:
        plan = self._plan()
        self._use_run_token()

        response = self.client.post(f"{self.url}{plan.id}/stop/", {"reason": "Skip it."}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        cancel.assert_not_called()

    def test_another_run_cannot_stop_the_plan(self, _create: MagicMock, _run: MagicMock, *_: MagicMock) -> None:
        plan = self._plan()
        self._use_run_token(task_id=UUID("00000000-0000-4000-8000-000000000009"))

        response = self.client.post(f"{self.url}{plan.id}/fail/", {"reason": "Injected."}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        plan.refresh_from_db()
        assert plan.status == FeatureFlagRolloutPlan.Status.ACTIVE

    def test_list_returns_only_the_plans_of_that_flag(self, *_: MagicMock) -> None:
        plan = self._plan()
        self._plan(feature_flag=self.other_flag)

        response = self.client.get(self.url, {"feature_flag": self.flag.id})

        assert [item["id"] for item in response.json()] == [str(plan.id)]


@patch(f"{ROLLOUTS}.get_feature_flag_or_none", return_value=True)
@patch(TASK_WORKFLOW)
class TestFeatureFlagRolloutPlanTask(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = FeatureFlag.objects.create(
            team=self.team,
            key="faster-report-cache",
            created_by=self.user,
            version=1,
            filters={"groups": [{"properties": [], "rollout_percentage": 1}]},
        )
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/feature_flag_rollout_plans/"

    def _start(self) -> dict[str, Any]:
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url,
                {
                    "feature_flag": self.flag.id,
                    "percentages": [5, 50],
                    "soak_hours": 24,
                    "health_checks": "Stop when the error rate on dashboard 7 passes 2%.",
                },
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def _bound_token(self, task_id: str, run_id: UUID) -> OAuthAccessToken:
        token = _run_token(self.user, self.team, task_id=UUID(task_id))
        TaskRun.update_state_atomic(run_id, updates={"sandbox_oauth_token_ids": [str(token.id)]})
        return token

    def test_the_run_uses_the_rollout_profile_and_refuses_follow_ups(self, *_: MagicMock) -> None:
        body = self._start()

        task = Task.objects.get(pk=body["task_id"])
        assert task.stored_profile == FEATURE_FLAG_ROLLOUT_PROFILE
        assert task.repository is None
        run = TaskRun.objects.get(task=task)
        assert run.state["pending_dispatch"]["posthog_mcp_scopes"] == ROLLOUT_PLAN_MCP_SCOPES
        assert run.state["pending_dispatch"]["create_pr"] is False

        follow_up = self.client.post(f"/api/projects/{self.team.id}/tasks/{task.id}/run/", {}, format="json")

        assert follow_up.status_code == status.HTTP_404_NOT_FOUND, follow_up.json()

    def test_only_the_token_of_the_latest_run_can_report(self, *_: MagicMock) -> None:
        body = self._start()
        plan = FeatureFlagRolloutPlan.objects.for_team(self.team.id).get(pk=body["id"])
        first_run_id = plan.latest_run_id
        assert first_run_id is not None
        first_token = self._bound_token(body["task_id"], first_run_id)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {first_token.token}")
        advance_url = f"{self.url}{body['id']}/advance/"

        assert self.client.post(advance_url, {"summary": "Healthy."}, format="json").status_code == status.HTTP_200_OK

        plan.refresh_from_db()
        assert plan.latest_run_id is not None and plan.latest_run_id != first_run_id
        second_run = TaskRun.objects.get(pk=plan.latest_run_id)
        assert second_run.state["resume_from_run_id"] == str(first_run_id)
        with time_machine.travel(timezone.now() + timedelta(hours=25)):
            refused = self.client.post(advance_url, {"summary": "Healthy."}, format="json")
            assert refused.status_code == status.HTTP_403_FORBIDDEN

            second_token = self._bound_token(body["task_id"], second_run.id)
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {second_token.token}")
            accepted = self.client.post(advance_url, {"summary": "Healthy."}, format="json")
            assert accepted.status_code == status.HTTP_200_OK, accepted.json()

        flag = FeatureFlag.objects.get(pk=self.flag.pk)
        assert flag.get_filters()["groups"][0]["rollout_percentage"] == 50
