"""Dispatch semantics for workflow-triggered scout runs, and the endpoint that fires them.

Covers the three things that make this path different from the manual `run` endpoint: the
30-minute workflow cooldown, the refusal to run a paused scout, and the `triggered_by="workflow"`
stamp that both of those read off.
"""

import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.limits import TRIGGERED_BY_WORKFLOW, WORKFLOW_RUN_COOLDOWN_S
from products.signals.backend.scout_harness.run_gates import ScoutRunRejectionKind
from products.signals.backend.scout_harness.workflow_runs import WorkflowScoutRunRejected, start_workflow_scout_run
from products.signals.backend.temporal.agentic.scout_scheduler import workflow_triggered_run_workflow_id
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task, TaskRun
from products.workflows.backend.models import HogFlow

SECRET = "test-signals-scout-run-jwt"
SKILL = "signals-scout-error-tracking"

_DISPATCH = "products.signals.backend.temporal.agentic.scout_scheduler.start_workflow_signals_scout_run"
_CONNECT = "products.signals.backend.scout_harness.workflow_runs.sync_connect"
_FLAG = "products.signals.backend.scout_harness.run_gates._read_flag_payload"
_STEP_FLAG = "products.workflows.backend.api.workflow_scout_runs.gated_template_enabled"


def _token(
    team_id: int, hog_flow_id: str | None, *, audience: PosthogJwtAudience = PosthogJwtAudience.SIGNALS_SCOUT_RUN
) -> str:
    claims: dict = {"team_id": team_id}
    if hog_flow_id is not None:
        claims["hog_flow_id"] = hog_flow_id
    return encode_jwt(claims, timedelta(minutes=5), audience, signing_key=SECRET)


@override_settings(SIGNALS_SCOUT_RUN_JWT_SECRETS=[SECRET])
class TestWorkflowScoutRunDispatch(APIBaseTest):
    """The Signals-side decision: may this fire spend a run, and what does it record?"""

    def setUp(self) -> None:
        super().setUp()
        # A workflow fire honours the same enrolment kill switch and daily budget the coordinator
        # does, so enrol this team by default and let the cases below exercise the gates they are
        # actually about. `test_rejects_an_unenrolled_project` overrides it.
        self._enrol({"guaranteed_team_ids": [self.team.id]})
        LLMSkill.objects.create(team=self.team, name=SKILL, is_latest=True, deleted=False)
        self.config = SignalScoutConfig.objects.create(
            team=self.team, skill_name=SKILL, status=SignalScoutConfig.Status.ACTIVE, enabled=True
        )
        # Stable per (team, skill): what the endpoint hands back, and what a retry collides with.
        self.workflow_id = workflow_triggered_run_workflow_id(self.team.id, SKILL)

    def _enrol(self, payload: dict) -> None:
        flag = patch(_FLAG, return_value=payload)
        flag.start()
        self.addCleanup(flag.stop)

    def _run(self) -> Any:
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            started = start_workflow_scout_run(team_id=self.team.id, skill_name=SKILL)
        self.last_dispatch = dispatch
        return started

    def _seed_run(self, *, triggered_by: str | None, age: timedelta = timedelta(minutes=1)) -> SignalScoutRun:
        """A finished scout run of the given trigger source, `age` in the past."""
        task = Task.objects.create(team=self.team, title="t", description="d")
        task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)
        run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=self.config,
            skill_name=SKILL,
            skill_version=1,
            metadata={"triggered_by": triggered_by} if triggered_by else {},
        )
        # `created_at` is auto_now_add, so the age has to be written back.
        SignalScoutRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - age)
        return run

    def _assert_rejected(self, reason: str, kind: ScoutRunRejectionKind) -> None:
        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            self._run()
        self.last_rejection = caught.exception
        assert caught.exception.rejection.reason == reason
        assert caught.exception.rejection.kind is kind

    def test_dispatches_the_run_as_workflow_triggered(self) -> None:
        started = self._run()

        assert started.skill_name == SKILL
        assert started.workflow_id == self.workflow_id
        self.last_dispatch.assert_called_once()
        assert self.last_dispatch.call_args.kwargs["skill_name"] == SKILL

    def test_never_stamps_last_run_at(self) -> None:
        self._run()

        self.config.refresh_from_db()
        # A trigger is additive to the schedule: stamping would let fires starve the patrol.
        assert self.config.last_run_at is None

    def test_rejects_a_second_fire_inside_the_cooldown(self) -> None:
        self._seed_run(triggered_by=TRIGGERED_BY_WORKFLOW, age=timedelta(minutes=5))

        self._assert_rejected("workflow_cooldown", ScoutRunRejectionKind.THROTTLED)

    def test_allows_a_fire_once_the_cooldown_has_rolled(self) -> None:
        self._seed_run(triggered_by=TRIGGERED_BY_WORKFLOW, age=timedelta(seconds=WORKFLOW_RUN_COOLDOWN_S + 60))

        assert self._run().workflow_id == self.workflow_id

    def test_a_scheduled_or_manual_run_does_not_extend_the_workflow_cooldown(self) -> None:
        # The cooldown bounds the workflow path specifically, so unrelated activity must not
        # silently suppress it — otherwise a busy scout would never accept a trigger.
        self._seed_run(triggered_by=None, age=timedelta(minutes=5))
        self._seed_run(triggered_by="manual", age=timedelta(minutes=5))

        assert self._run().workflow_id == self.workflow_id

    def test_rejects_an_unenrolled_project(self) -> None:
        # `skip_team_ids` is the operator kill switch: the coordinator never schedules a skipped
        # team, so automation pointed at it must be refused too — otherwise a workflow would route
        # around a rollout an operator deliberately drained.
        self._enrol({"guaranteed_team_ids": [self.team.id], "skip_team_ids": [self.team.id]})

        self._assert_rejected("not_enrolled", ScoutRunRejectionKind.FORBIDDEN)

    def test_rejects_a_paused_scout(self) -> None:
        self.config.status = SignalScoutConfig.Status.PAUSED_BY_USER
        self.config.enabled = False
        self.config.save()

        self._assert_rejected("scout_not_runnable", ScoutRunRejectionKind.CONFLICT)

    def test_rejects_an_unknown_scout(self) -> None:
        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            with patch(_CONNECT), patch(_DISPATCH):
                start_workflow_scout_run(team_id=self.team.id, skill_name="signals-scout-nope")
        assert caught.exception.rejection.kind is ScoutRunRejectionKind.NOT_FOUND

    def test_rejects_a_config_whose_skill_is_gone(self) -> None:
        LLMSkill.objects.filter(team=self.team, name=SKILL).update(deleted=True)

        self._assert_rejected("skill_missing", ScoutRunRejectionKind.NOT_FOUND)

    def test_rejects_while_a_run_is_in_flight(self) -> None:
        task = Task.objects.create(team=self.team, title="t", description="d")
        task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        SignalScoutRun.objects.create(
            task_run=task_run, team=self.team, scout_config=self.config, skill_name=SKILL, skill_version=1
        )

        self._assert_rejected("run_in_flight", ScoutRunRejectionKind.CONFLICT)
        assert self.last_rejection.in_flight_workflow_id == self.workflow_id

    def test_reports_the_workflow_id_when_temporal_single_flights_the_start(self) -> None:
        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            with patch(_CONNECT), patch(_DISPATCH, side_effect=WorkflowAlreadyStartedError("wf", "RunSignalsScout")):
                start_workflow_scout_run(team_id=self.team.id, skill_name=SKILL)

        assert caught.exception.rejection.reason == "run_in_flight"
        assert caught.exception.in_flight_workflow_id == self.workflow_id

    def test_refuses_a_child_environment(self) -> None:
        # No human credential is left at run time to authorize against the environment that owns
        # the scouts, so a child environment's workflow is refused rather than resolved upwards.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")

        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            with patch(_CONNECT), patch(_DISPATCH) as dispatch:
                start_workflow_scout_run(team_id=env.id, skill_name=SKILL)

        assert caught.exception.rejection.kind is ScoutRunRejectionKind.FORBIDDEN
        dispatch.assert_not_called()


@override_settings(SIGNALS_SCOUT_RUN_JWT_SECRETS=[SECRET])
class TestWorkflowScoutRunsAPI(APIBaseTest):
    """The transport: what the token has to prove, and how a rejection reaches the workflow step."""

    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        for target, value in ((_FLAG, {"guaranteed_team_ids": [self.team.id]}), (_STEP_FLAG, True)):
            flag = patch(target, return_value=value)
            flag.start()
            self.addCleanup(flag.stop)
        LLMSkill.objects.create(team=self.team, name=SKILL, is_latest=True, deleted=False)
        SignalScoutConfig.objects.create(
            team=self.team, skill_name=SKILL, status=SignalScoutConfig.Status.ACTIVE, enabled=True
        )
        self.hog_flow = HogFlow.objects.create(
            team=self.team, name="Run a scout", created_by=self.user, trigger={"type": "manual"}
        )
        self.url = f"/api/projects/{self.team.id}/workflow_scout_runs/"

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {"skill_name": SKILL, **(body or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id, str(self.hog_flow.id))}",
        )

    def test_dispatches_a_run(self) -> None:
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1"):
            response = self._post()

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json() == {
            "skill_name": SKILL,
            "workflow_id": workflow_triggered_run_workflow_id(self.team.id, SKILL),
            "started": True,
        }

    def test_replays_the_202_to_a_retried_step(self) -> None:
        # The engine re-sends the identical request when the first 202 is lost (a client-side
        # timeout on a slow dispatch). The retry must read as the same success, not collide with
        # the run the first request started.
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            first = self._post(body={"idempotency_key": "inv-1:run_scout"})
            second = self._post(body={"idempotency_key": "inv-1:run_scout"})
            third = self._post(body={"idempotency_key": "inv-2:run_scout"})

        assert (first.status_code, second.status_code, third.status_code) == (202, 202, 202)
        assert second.json() == first.json()
        assert dispatch.call_count == 2

    def test_answers_a_retry_that_overlaps_its_first_attempt(self) -> None:
        # The first attempt is still inside the Temporal start when the engine's retry arrives, so
        # the key is claimed but holds no result yet. The retry then collides with its sibling's
        # run; it must read that as its own success, not as a skip.
        key = f"workflow_scout_run:{self.team.id}:{self.hog_flow.id}:inv-1:run_scout"
        assert cache.add(key, {"pending": True}, timeout=60)
        with patch(_CONNECT), patch(_DISPATCH, side_effect=WorkflowAlreadyStartedError("wf", "RunSignalsScout")):
            response = self._post(body={"idempotency_key": "inv-1:run_scout"})

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json()["workflow_id"] == workflow_triggered_run_workflow_id(self.team.id, SKILL)

    def test_releases_the_key_when_the_fire_is_rejected(self) -> None:
        # A rejected fire started nothing, so a later fire under the same key is judged afresh
        # rather than finding a stale claim.
        SignalScoutConfig.objects.filter(team=self.team, skill_name=SKILL).update(
            status=SignalScoutConfig.Status.PAUSED_BY_USER, enabled=False
        )
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            first = self._post(body={"idempotency_key": "inv-1:run_scout"})
            SignalScoutConfig.objects.filter(team=self.team, skill_name=SKILL).update(
                status=SignalScoutConfig.Status.ACTIVE, enabled=True
            )
            second = self._post(body={"idempotency_key": "inv-1:run_scout"})

        assert (first.status_code, second.status_code) == (409, 202)
        assert dispatch.call_count == 1

    def test_accepts_the_longest_key_the_engine_can_send(self) -> None:
        # `<invocation uuid>:<action id>` at the action id's own 200-character limit.
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1"):
            response = self._post(body={"idempotency_key": f"{uuid.uuid4()}:{'a' * 200}"})

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()

    def test_does_not_replay_another_workflows_key(self) -> None:
        other_flow = HogFlow.objects.create(
            team=self.team, name="Another", created_by=self.user, trigger={"type": "manual"}
        )
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            self._post(body={"idempotency_key": "inv-1:run_scout"})
            self._post(body={"idempotency_key": "inv-1:run_scout"}, token=_token(self.team.id, str(other_flow.id)))

        assert dispatch.call_count == 2

    def test_rejects_a_token_minted_for_another_audience(self) -> None:
        response = self._post(
            token=_token(self.team.id, str(self.hog_flow.id), audience=PosthogJwtAudience.TASKS_CREATE)
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejects_a_token_with_no_workflow_claim(self) -> None:
        response = self._post(token=_token(self.team.id, None))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejects_a_token_minted_for_another_team(self) -> None:
        other = self.organization.teams.create(name="other")
        response = self._post(token=_token(other.id, str(self.hog_flow.id)))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ignores_a_hog_flow_id_in_the_body(self) -> None:
        # The body is attacker-shaped input; only the verified claim decides who is calling.
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1"):
            response = self._post(body={"hog_flow_id": "00000000-0000-0000-0000-000000000000"})

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()

    def test_refuses_a_project_without_the_step_flag(self) -> None:
        # A draft test run executes the step without the save-time gate, so the endpoint holds
        # the rollout flag itself.
        with patch(_STEP_FLAG, return_value=False), patch(_CONNECT), patch(_DISPATCH) as dispatch:
            response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        dispatch.assert_not_called()

    def test_rejects_a_token_for_a_deleted_workflow(self) -> None:
        # A token outlives the workflow it names (its TTL spans the whole fetch retry chain), so
        # mint one first, then delete. `delete()` nulls the in-memory pk, hence the local.
        token = _token(self.team.id, str(self.hog_flow.id))
        self.hog_flow.delete()

        response = self._post(token=token)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_maps_a_paused_scout_to_a_graceful_skip(self) -> None:
        SignalScoutConfig.objects.filter(team=self.team, skill_name=SKILL).update(
            status=SignalScoutConfig.Status.PAUSED_BY_USER, enabled=False
        )

        response = self._post()

        # 409 is a declared non-failure status on the template, so the step skips rather than fails.
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "paused_by_user" in response.json()["detail"]

    def test_maps_an_unknown_scout_to_a_step_failure(self) -> None:
        response = self._post(body={"skill_name": "signals-scout-typo"})

        # Deliberately NOT a declared non-failure status: a node naming a scout that does not exist
        # is a misconfiguration the author should see, not something to swallow.
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @override_settings(SIGNALS_SCOUT_RUN_JWT_SECRETS=[])
    def test_fails_closed_when_the_purpose_is_unprovisioned(self) -> None:
        response = self._post()

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
