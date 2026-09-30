"""Dispatch semantics for workflow-triggered scout runs.

Covers the three things that make this path different from the manual `run` endpoint: the
30-minute workflow cooldown, the refusal to run a paused scout, and the `triggered_by="workflow"`
stamp that both of those read off. The endpoint that fires it is the workflows product's
`workflow_tasks`, tested next to it.
"""

from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.limits import TRIGGERED_BY_WORKFLOW, WORKFLOW_RUN_COOLDOWN_S
from products.signals.backend.scout_harness.run_gates import ScoutRunRejectionKind
from products.signals.backend.scout_harness.workflow_runs import WorkflowScoutRunRejected, start_workflow_scout_run
from products.signals.backend.temporal.agentic.scout_scheduler import workflow_triggered_run_workflow_id
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task, TaskRun

SKILL = "signals-scout-error-tracking"

_DISPATCH = "products.signals.backend.temporal.agentic.scout_scheduler.start_workflow_signals_scout_run"
_CONNECT = "products.signals.backend.scout_harness.workflow_runs.sync_connect"
_FLAG = "products.signals.backend.scout_harness.run_gates._read_flag_payload"


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

    def _run(self, workflow_origin_key: str | None = None) -> Any:
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            started = start_workflow_scout_run(
                team_id=self.team.id, skill_name=SKILL, workflow_origin_key=workflow_origin_key
            )
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
        assert caught.exception.rejection.reason == reason
        assert caught.exception.rejection.kind is kind

    def test_dispatches_the_run_as_workflow_triggered(self) -> None:
        started = self._run(workflow_origin_key="job:step:1")

        assert started.skill_name == SKILL
        assert started.workflow_id == self.workflow_id
        self.last_dispatch.assert_called_once()
        assert self.last_dispatch.call_args.kwargs["skill_name"] == SKILL
        assert self.last_dispatch.call_args.kwargs["workflow_origin_key"] == "job:step:1"

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

    def test_skips_when_temporal_single_flights_the_start(self) -> None:
        # The pre-dispatch check can't see a run whose row isn't written yet, so the Temporal
        # id-conflict policy is the backstop and its collision reads as ordinary backpressure.
        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            with patch(_CONNECT), patch(_DISPATCH, side_effect=WorkflowAlreadyStartedError("wf", "RunSignalsScout")):
                start_workflow_scout_run(team_id=self.team.id, skill_name=SKILL)

        assert caught.exception.rejection.reason == "run_in_flight"
        assert caught.exception.rejection.kind is ScoutRunRejectionKind.CONFLICT

    def test_refuses_a_child_environment(self) -> None:
        # No human credential is left at run time to authorize against the environment that owns
        # the scouts, so a child environment's workflow is refused rather than resolved upwards.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")

        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            with patch(_CONNECT), patch(_DISPATCH) as dispatch:
                start_workflow_scout_run(team_id=env.id, skill_name=SKILL)

        assert caught.exception.rejection.kind is ScoutRunRejectionKind.FORBIDDEN
        dispatch.assert_not_called()
