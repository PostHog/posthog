"""Dispatch semantics for workflow-triggered scout runs.

Covers the things that make this path different from the manual `run` endpoint: the 30-minute
workflow cooldown, the refusal to run a paused scout, the `triggered_by="workflow"` stamp that both
of those read off, and the queue that keeps a fire the scout was too busy to run. The endpoint that
fires it is the workflows product's `workflow_scout_runs`, tested next to it.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutPendingTrigger, SignalScoutRun
from products.signals.backend.scout_harness.limits import (
    MAX_PENDING_WORKFLOW_TRIGGERS,
    TRIGGERED_BY_SCHEDULE,
    TRIGGERED_BY_WORKFLOW,
    WORKFLOW_RUN_COOLDOWN_S,
)
from products.signals.backend.scout_harness.run_gates import ScoutRunRejectionKind
from products.signals.backend.scout_harness.workflow_runs import (
    DrainSummary,
    WorkflowScoutRunQueued,
    WorkflowScoutRunRejected,
    drain_pending_workflow_triggers,
    pending_trigger_lanes_for_scheduled_runs,
    start_workflow_scout_run,
)
from products.signals.backend.scout_harness.workflow_trigger_queue import (
    claim_pending_triggers,
    enqueue_workflow_trigger,
)
from products.signals.backend.temporal.agentic.scout_scheduler import workflow_triggered_run_workflow_id
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task, TaskRun

SKILL = "signals-scout-error-tracking"

_DISPATCH = "products.signals.backend.temporal.agentic.scout_scheduler.start_workflow_signals_scout_run"
_CONNECT = "products.signals.backend.scout_harness.workflow_runs.sync_connect"
_FLAG = "products.signals.backend.scout_harness.run_gates._read_flag_payload"
_DAILY_LIMIT = "products.signals.backend.scout_harness.run_gates.daily_report_limit_gate"
_COLLISION = WorkflowAlreadyStartedError("wf", "RunSignalsScout")


class _ScoutLaneTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A workflow fire honours the same enrolment kill switch and daily budget the coordinator
        # does, so enrol this team by default and let the cases below exercise the gates they are
        # actually about.
        self._enrol({"guaranteed_team_ids": [self.team.id]})
        LLMSkill.objects.create(team=self.team, name=SKILL, is_latest=True, deleted=False)
        self.config = SignalScoutConfig.objects.create(
            team=self.team, skill_name=SKILL, status=SignalScoutConfig.Status.ACTIVE, enabled=True
        )

    def _enrol(self, payload: dict) -> None:
        flag = patch(_FLAG, return_value=payload)
        flag.start()
        self.addCleanup(flag.stop)

    def _seed_run(
        self,
        *,
        triggered_by: str | None,
        age: timedelta = timedelta(minutes=1),
        status: str = TaskRun.Status.COMPLETED,
        metadata: dict | None = None,
    ) -> SignalScoutRun:
        """A scout run of the given trigger source and status, `age` in the past."""
        task = Task.objects.create(team=self.team, title="t", description="d")
        task_run = TaskRun.objects.create(task=task, team=self.team, status=status)
        run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=self.config,
            skill_name=SKILL,
            skill_version=1,
            metadata={**({"triggered_by": triggered_by} if triggered_by else {}), **(metadata or {})},
        )
        # `created_at` is auto_now_add, so the age has to be written back.
        SignalScoutRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - age)
        return run

    def _queue(self, note: str, workflow_id: str | None = "flow-1") -> None:
        enqueue_workflow_trigger(
            team=self.team, skill_name=SKILL, note=note, workflow_id=workflow_id, reason="run_in_flight"
        )

    def _pending(self) -> list[tuple[str, str | None]]:
        return list(
            SignalScoutPendingTrigger.objects.for_team(self.team.id)
            .order_by("received_at", "id")
            .values_list("note", "workflow_id")
        )

    def _pending_ids(self) -> tuple[str, ...]:
        return tuple(
            str(trigger_id)
            for trigger_id in SignalScoutPendingTrigger.objects.for_team(self.team.id)
            .order_by("received_at", "id")
            .values_list("id", flat=True)
        )


class TestWorkflowScoutRunDispatch(_ScoutLaneTestCase):
    """The Signals-side decision: may this fire spend a run, and what does it record?"""

    def setUp(self) -> None:
        super().setUp()
        # Stable per (team, skill): what the endpoint hands back, and what a retry collides with.
        self.workflow_id = workflow_triggered_run_workflow_id(self.team.id, SKILL)

    def _run(
        self,
        workflow_origin_key: str | None = None,
        run_note: str | None = None,
        trigger_workflow_id: str | None = None,
        queue_when_busy: bool = True,
        dispatch_error: BaseException | None = None,
    ) -> Any:
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1", side_effect=dispatch_error) as dispatch:
            started = start_workflow_scout_run(
                team_id=self.team.id,
                skill_name=SKILL,
                workflow_origin_key=workflow_origin_key,
                run_note=run_note,
                trigger_workflow_id=trigger_workflow_id,
                queue_when_busy=queue_when_busy,
            )
        self.last_dispatch = dispatch
        return started

    def _make_busy(self, busy: str) -> BaseException | None:
        if busy == "cooldown":
            self._seed_run(triggered_by=TRIGGERED_BY_WORKFLOW, age=timedelta(minutes=5))
        elif busy == "in_flight":
            self._seed_run(triggered_by=None, status=TaskRun.Status.IN_PROGRESS)
        else:
            # The pre-dispatch check can't see a run whose row isn't written yet, so the Temporal
            # id-conflict policy is the backstop.
            return _COLLISION
        return None

    def _assert_rejected(self, reason: str, kind: ScoutRunRejectionKind, **run_kwargs: Any) -> None:
        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            self._run(**run_kwargs)
        assert caught.exception.rejection.reason == reason
        assert caught.exception.rejection.kind is kind

    def test_dispatches_the_run_as_workflow_triggered(self) -> None:
        started = self._run(workflow_origin_key="job:step:1", run_note="PR #4821", trigger_workflow_id="flow-1")

        assert started.skill_name == SKILL
        assert started.workflow_id == self.workflow_id
        self.last_dispatch.assert_called_once()
        assert self.last_dispatch.call_args.kwargs["skill_name"] == SKILL
        assert self.last_dispatch.call_args.kwargs["workflow_origin_key"] == "job:step:1"
        assert self.last_dispatch.call_args.kwargs["run_note"] == "PR #4821"
        assert self.last_dispatch.call_args.kwargs["trigger_workflow_id"] == "flow-1"

    def test_never_stamps_last_run_at(self) -> None:
        self._run()

        self.config.refresh_from_db()
        # A trigger is additive to the schedule: stamping would let fires starve the patrol.
        assert self.config.last_run_at is None

    _BUSY_CASES = [
        ("cooldown", "workflow_cooldown", ScoutRunRejectionKind.THROTTLED),
        ("in_flight", "run_in_flight", ScoutRunRejectionKind.CONFLICT),
        ("temporal_collision", "run_in_flight", ScoutRunRejectionKind.CONFLICT),
    ]

    @parameterized.expand(_BUSY_CASES)
    def test_a_busy_scout_queues_the_fire_with_its_note(self, busy: str, *_: Any) -> None:
        dispatch_error = self._make_busy(busy)

        outcome = self._run(run_note="Issue #42", trigger_workflow_id="flow-1", dispatch_error=dispatch_error)

        assert outcome == WorkflowScoutRunQueued(skill_name=SKILL, pending_count=1)
        assert self._pending() == [("Issue #42", "flow-1")]

    @parameterized.expand(_BUSY_CASES)
    def test_a_busy_scout_skips_the_fire_when_the_step_asks_to(
        self, busy: str, reason: str, kind: ScoutRunRejectionKind
    ) -> None:
        dispatch_error = self._make_busy(busy)

        self._assert_rejected(reason, kind, run_note="Issue #42", queue_when_busy=False, dispatch_error=dispatch_error)
        assert self._pending() == []

    def test_the_queue_drops_duplicate_notes_and_then_the_oldest_fires(self) -> None:
        self._make_busy("in_flight")

        for number in range(MAX_PENDING_WORKFLOW_TRIGGERS + 2):
            self._run(run_note=f"Issue #{number}")
        duplicate = self._run(run_note=f"Issue #{MAX_PENDING_WORKFLOW_TRIGGERS}")

        assert duplicate.pending_count == MAX_PENDING_WORKFLOW_TRIGGERS
        assert [note for note, _ in self._pending()] == [
            f"Issue #{number}" for number in range(2, MAX_PENDING_WORKFLOW_TRIGGERS + 2)
        ]

    def test_a_free_scout_takes_the_queued_fires_along_with_this_one(self) -> None:
        self._queue("Issue #1")

        started = self._run(run_note="Issue #2", workflow_origin_key="job:step:1", trigger_workflow_id="flow-2")

        assert started.workflow_id == self.workflow_id
        kwargs = self.last_dispatch.call_args.kwargs
        assert kwargs["pending_trigger_ids"] == self._pending_ids()
        assert kwargs["run_note"] is None
        assert kwargs["workflow_origin_key"] == "job:step:1"
        # The run claims the rows when it starts, so they are still queued at dispatch.
        assert self._pending() == [("Issue #1", "flow-1"), ("Issue #2", "flow-2")]

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

    @parameterized.expand(
        [
            ("paused", "scout_not_runnable", ScoutRunRejectionKind.CONFLICT),
            ("unenrolled", "not_enrolled", ScoutRunRejectionKind.FORBIDDEN),
            ("daily_report_limit", "daily_report_limit", ScoutRunRejectionKind.THROTTLED),
        ]
    )
    def test_a_gate_beats_the_queue_so_a_busy_scout_still_rejects(
        self, gate: str, reason: str, kind: ScoutRunRejectionKind
    ) -> None:
        # A queued fire would otherwise get around a pause or a spend gate on the next tick.
        self._make_busy("in_flight")
        if gate == "paused":
            self.config.status = SignalScoutConfig.Status.PAUSED_BY_USER
            self.config.enabled = False
            self.config.save()
        elif gate == "unenrolled":
            self._enrol({"guaranteed_team_ids": [self.team.id], "skip_team_ids": [self.team.id]})
        else:
            limit = patch(_DAILY_LIMIT, return_value=MagicMock(limited=True))
            limit.start()
            self.addCleanup(limit.stop)

        self._assert_rejected(reason, kind, run_note="Issue #42")
        assert self._pending() == []

    def test_rejects_an_unknown_scout(self) -> None:
        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            with patch(_CONNECT), patch(_DISPATCH):
                start_workflow_scout_run(team_id=self.team.id, skill_name="signals-scout-nope")
        assert caught.exception.rejection.kind is ScoutRunRejectionKind.NOT_FOUND

    def test_rejects_a_config_whose_skill_is_gone(self) -> None:
        LLMSkill.objects.filter(team=self.team, name=SKILL).update(deleted=True)

        self._assert_rejected("skill_missing", ScoutRunRejectionKind.NOT_FOUND)

    def test_a_live_trial_run_does_not_make_the_scout_busy(self) -> None:
        self._seed_run(triggered_by=None, status=TaskRun.Status.IN_PROGRESS, metadata={"scout_trial": {"version": 1}})

        assert self._run().workflow_id == self.workflow_id

    def test_refuses_a_child_environment(self) -> None:
        # No human credential is left at run time to authorize against the environment that owns
        # the scouts, so a child environment's workflow is refused rather than resolved upwards.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")

        with self.assertRaises(WorkflowScoutRunRejected) as caught:
            with patch(_CONNECT), patch(_DISPATCH) as dispatch:
                start_workflow_scout_run(team_id=env.id, skill_name=SKILL)

        assert caught.exception.rejection.kind is ScoutRunRejectionKind.FORBIDDEN
        dispatch.assert_not_called()


class TestPendingWorkflowTriggerDrain(_ScoutLaneTestCase):
    """What the coordinator does with queued fires: which run takes them, and when they wait."""

    def _drain(self, *, excluded: set[tuple[int, str]] | None = None, dispatch_error: BaseException | None = None):
        with patch(_CONNECT), patch(_DISPATCH, side_effect=dispatch_error) as dispatch:
            summary = drain_pending_workflow_triggers(excluded or set())
        self.last_dispatch = dispatch
        return summary

    def test_dispatches_one_run_that_carries_every_queued_fire(self) -> None:
        self._queue("Issue #1")
        self._queue("Issue #2")

        summary = self._drain()

        assert summary == DrainSummary(lanes=1, dispatched=1)
        self.last_dispatch.assert_called_once()
        assert self.last_dispatch.call_args.kwargs["pending_trigger_ids"] == self._pending_ids()
        assert len(self._pending()) == 2

    @parameterized.expand(["cooldown", "in_flight", "paused", "daily_report_limit", "collision", "dispatch_error"])
    def test_a_lane_that_cannot_run_keeps_its_fires_for_a_later_tick(self, blocker: str) -> None:
        self._queue("Issue #1")
        dispatch_error: BaseException | None = None
        if blocker == "cooldown":
            self._seed_run(triggered_by=TRIGGERED_BY_WORKFLOW, age=timedelta(minutes=5))
        elif blocker == "in_flight":
            self._seed_run(triggered_by=None, status=TaskRun.Status.IN_PROGRESS)
        elif blocker == "paused":
            self.config.status = SignalScoutConfig.Status.PAUSED_BY_USER
            self.config.enabled = False
            self.config.save()
        elif blocker == "daily_report_limit":
            limit = patch(_DAILY_LIMIT, return_value=MagicMock(limited=True))
            limit.start()
            self.addCleanup(limit.stop)
        elif blocker == "collision":
            dispatch_error = _COLLISION
        else:
            dispatch_error = RuntimeError("temporal unavailable")

        summary = self._drain(dispatch_error=dispatch_error)

        assert summary == DrainSummary(lanes=1, deferred=1)
        assert self._pending() == [("Issue #1", "flow-1")]

    def test_leaves_a_lane_alone_when_its_scheduled_run_takes_the_fires(self) -> None:
        self._queue("Issue #1")

        summary = self._drain(excluded={(self.team.id, SKILL)})

        assert summary == DrainSummary()
        self.last_dispatch.assert_not_called()

    def test_drops_the_fires_of_a_scout_that_no_longer_exists(self) -> None:
        self._queue("Issue #1")
        LLMSkill.objects.filter(team=self.team, name=SKILL).update(deleted=True)

        summary = self._drain()

        assert summary == DrainSummary(lanes=1, dropped=1)
        assert self._pending() == []

    def test_a_due_scheduled_run_takes_the_fires_only_while_no_run_is_live(self) -> None:
        self._queue("Issue #1")
        lane = (self.team.id, SKILL)

        assert pending_trigger_lanes_for_scheduled_runs({lane})[lane].trigger_ids == self._pending_ids()

        self._seed_run(triggered_by=None, status=TaskRun.Status.IN_PROGRESS)
        assert pending_trigger_lanes_for_scheduled_runs({lane}) == {}

    def test_a_claim_renders_every_fire_once_in_arrival_order(self) -> None:
        with time_machine.travel(datetime(2026, 10, 26, 10, 0, tzinfo=UTC), tick=False):
            self._queue("Issue #1")
        with time_machine.travel(datetime(2026, 10, 26, 10, 5, tzinfo=UTC), tick=False):
            self._queue("", workflow_id="flow-2")
        trigger_ids = self._pending_ids()

        claimed = claim_pending_triggers(
            team_id=self.team.id, skill_name=SKILL, trigger_ids=trigger_ids, triggered_by=TRIGGERED_BY_SCHEDULE
        )
        again = claim_pending_triggers(
            team_id=self.team.id, skill_name=SKILL, trigger_ids=trigger_ids, triggered_by=TRIGGERED_BY_WORKFLOW
        )

        assert claimed.count == 2
        assert claimed.run_note == (
            "- 2026-10-26T10:00:00Z: Issue #1\n- 2026-10-26T10:05:00Z: an event fired with no note"
        )
        # Two workflows fired, so no single one can be named as the trigger.
        assert claimed.trigger_workflow_id is None
        assert again.count == 0
        assert self._pending() == []
