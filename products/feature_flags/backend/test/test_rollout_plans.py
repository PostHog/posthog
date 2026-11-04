from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import POSTHOG_AI_APP_CLIENT_ID_DEV

from products.approvals.backend.exceptions import ApprovalRequired
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.feature_flag_rollout_plan import FeatureFlagRolloutPlan
from products.feature_flags.backend.rollout_plans import ROLLOUT_PLAN_MCP_SCOPES

TASK_ID = UUID("00000000-0000-4000-8000-000000000001")
FIRST_RUN_ID = UUID("00000000-0000-4000-8000-000000000002")
ROLLOUTS = "products.feature_flags.backend.rollout_plans"


@patch("products.feature_flags.backend.presentation.rollout_plans.feature_enabled_or_false", return_value=True)
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
        application = OAuthApplication.objects.create(
            name="sandbox",
            client_id=POSTHOG_AI_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=f"pha_{uuid4().hex}",
            scope=scope,
            expires=timezone.now() + timedelta(days=30),
            scoped_teams=[self.team.id],
            scoped_organizations=[],
            sandbox_task_id=task_id,
        )
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
        scopes = create_and_run_task.call_args.kwargs["posthog_mcp_scopes"]
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

    def test_refuses_a_plan_when_the_feature_is_off(
        self,
        create_and_run_task: MagicMock,
        _run: MagicMock,
        _cancel: MagicMock,
        _notify: MagicMock,
        _usage: MagicMock,
        enabled: MagicMock,
    ) -> None:
        enabled.return_value = False

        response = self.client.post(self.url, self._body(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        create_and_run_task.assert_not_called()

    def test_a_run_cannot_approve_a_plan(self, create_and_run_task: MagicMock, *_: MagicMock) -> None:
        self._use_run_token()

        response = self.client.post(self.url, self._body(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        create_and_run_task.assert_not_called()

    def test_run_token_cannot_write_flags_directly(self, *_: MagicMock) -> None:
        plan = self._plan()
        self._use_run_token(scope=" ".join(ROLLOUT_PLAN_MCP_SCOPES))

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
        assert self._rollout() == 1
        cancel.assert_not_called()
        assert "Errors reached 6%." in notify.call_args.args[0].body

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
