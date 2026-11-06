from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.db import connection, transaction
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFindingCode,
    ExperimentMetricEffects,
    ExperimentResults,
    ExperimentVariantEffect,
)
from products.product_analytics.backend.facade.contracts import InsightSeries, SavedInsightDefinition
from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.goal_scouts.ideas import IDEA_TAG
from products.signals.backend.goal_scouts.scout import GoalRunGate, goal_run_gate
from products.signals.backend.goal_scouts.sweep import advance_goal, live_goal_keys
from products.signals.backend.goal_scouts.tracking import Baseline
from products.signals.backend.goal_scouts.verdict import MIN_SAMPLES_PER_VARIANT, verdict
from products.signals.backend.implementation_pr import ImplementationPr
from products.signals.backend.models import (
    SignalReport,
    SignalScoutConfig,
    SignalScoutGoal,
    SignalScoutGoalIdea,
    SignalScoutRun,
    SignalSpend,
)
from products.signals.backend.scout_authorship import report_is_from_goal_scout, report_is_hidden_from_inbox
from products.signals.backend.task_run_artefacts import ReportTaskCapExceeded, enforce_report_task_cap

ENOUGH = MIN_SAMPLES_PER_VARIANT
MODULE = "products.signals.backend.goal_scouts"
GUARDRAILS = [{"name": "Uploads", "direction": "increase", "max_regression": 0.05}]


def results(
    primary: tuple[float, float] | None,
    *,
    significant: bool = True,
    guard: tuple[float, float] = (-0.01, 0.01),
    days: int = 3,
    exposures: dict[str, float] | None = None,
    findings: tuple[ExperimentHealthFindingCode, ...] = (),
) -> ExperimentResults:
    test = ExperimentVariantEffect(
        key="test",
        low=primary[0] if primary else None,
        high=primary[1] if primary else None,
        significant=significant,
    )
    return ExperimentResults(
        start_date=timezone.now() - timedelta(days=days),
        variants=("control", "test"),
        exposures=exposures or {"control": ENOUGH, "test": ENOUGH},
        primary=(ExperimentMetricEffects(name="1. Share rate", variants=(test,)),),
        secondary=(
            ExperimentMetricEffects(
                name="1. Uploads",
                variants=(ExperimentVariantEffect(key="test", low=guard[0], high=guard[1], significant=True),),
            ),
        ),
        finding_codes=findings,
    )


class TestVerdict(SimpleTestCase):
    @parameterized.expand(
        [
            ("win", results((0.05, 0.2)), "increase", SignalScoutGoalIdea.Outcome.WON),
            ("win_when_lower_is_better", results((-0.2, -0.05)), "decrease", SignalScoutGoalIdea.Outcome.WON),
            ("loss", results((-0.2, -0.05)), "increase", SignalScoutGoalIdea.Outcome.LOST),
            ("guardrail_harm_beats_a_win", results((0.05, 0.2), guard=(-0.3, -0.1)), "increase", "harmed"),
            ("no_clear_effect", results((-0.05, 0.2), significant=False), "increase", SignalScoutGoalIdea.Outcome.FLAT),
            ("clear_win_before_the_planned_end_waits", results((0.05, 0.2), days=1), "increase", None),
            (
                "harm_stops_before_the_planned_end",
                results((0.05, 0.2), guard=(-0.3, -0.1), days=1),
                "increase",
                "harmed",
            ),
            ("the_clock_starts_at_the_first_exposure", results((0.05, 0.2)), "increase", None, 1),
            (
                "sample_ratio_mismatch_marks_a_broken_test",
                results((0.05, 0.2), findings=(ExperimentHealthFindingCode.SRM,)),
                "increase",
                "broken",
            ),
            (
                "people_in_several_variants_mark_a_broken_test",
                results((0.05, 0.2), findings=(ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE,)),
                "increase",
                "broken",
            ),
            (
                "small_groups_never_decide",
                results((0.05, 0.2), exposures={"control": ENOUGH, "test": ENOUGH - 1}),
                "increase",
                None,
            ),
        ]
    )
    def test_outcome(
        self, _name: str, data: ExperimentResults, direction: str, expected: str | None, exposed_days: int | None = None
    ) -> None:
        now = timezone.now()
        exposed_at = now - timedelta(days=exposed_days) if exposed_days else None
        found = verdict(data, direction=direction, guardrails=GUARDRAILS, run_days=2, exposed_at=exposed_at, now=now)
        assert found.outcome == expected


@dataclass(frozen=False)
class FakeRun:
    task_id: UUID
    status: str = "in_progress"
    error_message: str = ""
    id: UUID = field(default_factory=uuid4)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")


@dataclass(frozen=False)
class GoalWorld:
    runs: dict[str, FakeRun] = field(default_factory=dict)
    prs: dict[str, ImplementationPr] = field(default_factory=dict)
    experiments: dict[str, int] = field(default_factory=dict)
    results: ExperimentResults | None = None
    ended: list[tuple[int, str, str]] = field(default_factory=list)
    values: list[float] = field(default_factory=lambda: [0.1, 0.1, 0.1])
    baseline: Baseline = field(default_factory=lambda: Baseline(ready=True, value=0.1, note=""))
    logs: str = ""
    cleanup_task: UUID = field(default_factory=uuid4)
    scout_runs_started: int = 0

    def launch(self, *, report_id: str, **kwargs: Any) -> bool:
        self.runs[report_id] = FakeRun(task_id=uuid4())
        return True

    def finish(self, report_id: str, *, pr: str = "", flag: str = "", status: str = "completed") -> None:
        self.runs[report_id].status = status
        if pr:
            self.prs[report_id] = ImplementationPr(url=pr, merged=False, state="open")
        if flag:
            self.experiments[flag] = 7

    def pr_state(self, report_id: str, state: str) -> None:
        self.prs[report_id] = ImplementationPr(
            url=self.prs[report_id].url, merged=state == "merged", state=state, merged_at=timezone.now()
        )

    def series(self, **kwargs: Any) -> InsightSeries:
        start = date.today() - timedelta(days=len(self.values))
        points = [(start + timedelta(days=index), value) for index, value in enumerate(self.values)]
        return InsightSeries(
            short_id=kwargs["short_id"],
            name="Share rate",
            series={"Share rate": points},
            period="day",
            averaged_series=[],
            event_name="shared",
        )


class TestGoalScoutLoop(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.world = world = GoalWorld()
        stubs: list[tuple[str, dict[str, Any]]] = [
            ("products.signals.backend.facade.goal_scouts.goal_scouts_enabled", {"return_value": True}),
            (f"{MODULE}.sweep.goal_scouts_enabled", {"return_value": True}),
            (f"{MODULE}.goals.validate_scout_repositories", {"side_effect": lambda value, *args, **kwargs: value}),
            (f"{MODULE}.build.create_implementation_task_if_absent", {"side_effect": world.launch}),
            (f"{MODULE}.build.task_run_usage_limited", {"return_value": False}),
            (f"{MODULE}.sweep.latest_run", {"side_effect": lambda team_id, report_id: world.runs.get(report_id)}),
            (f"{MODULE}.sweep.run_logs", {"side_effect": lambda *args: world.logs}),
            (f"{MODULE}.sweep.baseline", {"side_effect": lambda *args, **kwargs: world.baseline}),
            (f"{MODULE}.sweep.get_experiment_results", {"side_effect": lambda **kwargs: world.results}),
            (f"{MODULE}.sweep.cleanup_task_id", {"side_effect": lambda **kwargs: world.cleanup_task}),
            (
                f"{MODULE}.sweep.experiment_for_read",
                {
                    "side_effect": lambda **kwargs: (
                        SimpleNamespace(id=world.experiments[kwargs["feature_flag_key"]])
                        if kwargs["feature_flag_key"] in world.experiments
                        else None
                    )
                },
            ),
            (
                f"{MODULE}.sweep.ship",
                {
                    "side_effect": lambda **kwargs: world.ended.append(
                        (kwargs["experiment_id"], kwargs["conclusion"], kwargs["variant"])
                    )
                },
            ),
            (
                f"{MODULE}.goals.conclude",
                {
                    "side_effect": lambda **kwargs: world.ended.append(
                        (kwargs["experiment_id"], kwargs["conclusion"], "")
                    )
                },
            ),
            (f"{MODULE}.metrics.get_insight_series", {"side_effect": world.series}),
            (
                f"{MODULE}.metrics.saved_insight_for_read",
                {
                    "side_effect": lambda **kwargs: SavedInsightDefinition(
                        id=1, short_id=kwargs["short_id"], name="Share rate", query={}
                    )
                },
            ),
            (f"{MODULE}.metrics.insight_delivery_evidence", {"return_value": None}),
            (f"{MODULE}.goals.check_fleet_gates", {"return_value": None}),
            (f"{MODULE}.goals.sync_connect", {}),
            (
                "products.signals.backend.temporal.agentic.scout_scheduler.start_manual_signals_scout_run",
                {"side_effect": self._scout_run_started},
            ),
            (f"{MODULE}.notify.create_notification", {}),
        ]
        for target, kwargs in stubs:
            self.patch(target, **kwargs)
        for target in (f"{MODULE}.sweep", f"{MODULE}.read", f"{MODULE}.build"):
            self.patch(
                f"{target}.fetch_implementation_pr_state_for_reports",
                side_effect=lambda report_ids, team_id: {key: world.prs[key] for key in report_ids if key in world.prs},
            )

    def _scout_run_started(self, *args: Any, **kwargs: Any) -> None:
        self.world.scout_runs_started += 1

    def patch(self, target: str, **kwargs: Any) -> MagicMock:
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def create(self, **overrides: Any) -> SignalScoutGoal:
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/goals/",
            {
                "title": "Make sharing easier",
                "statement": "A one-click share after upload will make more people share.",
                "repositories": ["posthog/example-app"],
                "goal_insight": "abc12345",
                "goal_metric": "Share rate after upload",
                "secondary_metrics": [{"insight": "upl12345", **GUARDRAILS[0]}],
                "target": "0.3",
                "budget_cents": 20000,
                **overrides,
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        return SignalScoutGoal.objects.for_team(self.team.id).select_related("config").get(pk=response.json()["id"])

    def gate(self, goal: SignalScoutGoal) -> GoalRunGate:
        found = goal_run_gate(self.team.id, goal.pk)
        assert found is not None
        return found

    def tick(self, goal: SignalScoutGoal) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            advance_goal(self.team.id, goal.pk)
        goal.refresh_from_db()
        goal.config.refresh_from_db()

    def detail(self, goal: SignalScoutGoal) -> dict[str, Any]:
        response = self.client.get(f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/")
        assert response.status_code == 200, response.content
        return response.json()

    def row(self, goal: SignalScoutGoal, kind: str) -> SignalScoutGoalIdea:
        found = SignalScoutGoalIdea.objects.for_team(self.team.id).filter(goal=goal, kind=kind).order_by("-created_at")
        return found.select_related("report").first() or self.fail(f"no {kind} row")

    def scout_run(self, goal: SignalScoutGoal, report_ids: list[str], status: str = "completed") -> SignalScoutRun:
        task = apps.get_model("tasks", "Task").objects.create(team=self.team, title="scout", description="d")
        task_run = apps.get_model("tasks", "TaskRun").objects.create(
            team=self.team, task=task, status=status, completed_at=timezone.now()
        )
        return SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=task_run,
            scout_config=goal.config,
            skill_name=goal.config.skill_name,
            skill_version=1,
            emitted_report_ids=report_ids,
            metadata={"goal_id": str(goal.pk)},
        )

    def file_idea(
        self, goal: SignalScoutGoal, title: str = "Share button after upload", summary: str = "Evidence."
    ) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title=title, summary=summary, tags=[IDEA_TAG]
        )
        self.scout_run(goal, [str(report.id)])
        return report

    def running(self, **overrides: Any) -> SignalScoutGoal:
        goal = self.create(**overrides)
        self.world.finish(str(self.row(goal, "tracking").report_id))
        self.tick(goal)
        self.tick(goal)
        assert goal.status == SignalScoutGoal.Status.RUNNING, goal.note
        return goal

    def build(self, goal: SignalScoutGoal, work_id: str, days: int | None = 2) -> Any:
        plan = {"days": days, "mde": 30, "audience": 5000} if days else None
        return self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/build/",
            {"work_id": work_id, "plan": plan},
            format="json",
        )

    def reviewing(self, goal: SignalScoutGoal, days: int | None = 2) -> SignalScoutGoalIdea:
        report = self.file_idea(goal)
        assert self.build(goal, str(report.id), days).status_code == 200
        idea = self.row(goal, "idea")
        self.world.finish(str(report.id), pr="https://github.com/posthog/example-app/pull/9", flag=idea.flag_key)
        self.tick(goal)
        idea.refresh_from_db()
        assert idea.stage == SignalScoutGoalIdea.Stage.REVIEW and idea.experiment_id == 7
        return idea

    def ship_idea(self, goal: SignalScoutGoal, outcome: ExperimentResults) -> SignalScoutGoalIdea:
        idea = self.reviewing(goal)
        self.world.pr_state(str(idea.report_id), "merged")
        self.world.results = outcome
        self.tick(goal)
        self.tick(goal)
        with time_machine.travel(timezone.now() + timedelta(days=3)):
            self.tick(goal)
        idea.refresh_from_db()
        return idea

    def test_goal_walks_from_tracking_to_a_won_idea_and_reaches_its_target(self) -> None:
        notify = self.patch(f"{MODULE}.notify.create_notification")
        goal = self.create()
        tracking = self.row(goal, "tracking")
        assert tracking.stage == "building" and str(tracking.report_id) in self.world.runs
        assert report_is_hidden_from_inbox(self.team.id, str(tracking.report_id))
        assert self.gate(goal).refusal.startswith("The scout looks for ideas once tracking")

        self.world.finish(str(tracking.report_id))
        self.tick(goal)
        self.tick(goal)
        assert (goal.status, goal.baseline_value, self.world.scout_runs_started) == ("running", 0.1, 1)
        assert (self.team.id, goal.pk) in live_goal_keys()
        gate = self.gate(goal)
        assert gate.refusal == "" and "Mode for this run: find" in gate.context

        idea = self.ship_idea(goal, results((0.05, 0.2)))
        assert (idea.stage, idea.outcome, idea.result["shipped"]) == ("done", "won", True)
        assert idea.flag_key == f"goal-{goal.pk.hex[-8:]}-1"
        assert self.world.ended == [(7, "won", "test")]
        assert report_is_from_goal_scout(self.team.id, str(idea.report_id))
        with transaction.atomic(), pytest.raises(ReportTaskCapExceeded):
            enforce_report_task_cap(
                team_id=self.team.id,
                report_id=str(idea.report_id),
                relationship=TASK_RUN_TYPE_IMPLEMENTATION,
                created_by_id=self.user.id,
            )

        self.tick(goal)
        work = next(item for item in self.detail(goal)["work"] if item["id"] == str(idea.id))
        assert work["cleanup"]["task_id"] == str(self.world.cleanup_task)

        self.world.values = [0.31, 0.32, 0.33]
        self.tick(goal)
        assert goal.status == "running" and goal.goal_met_since is not None
        with time_machine.travel(timezone.now() + timedelta(hours=73)):
            self.tick(goal)
        assert goal.status == "reached" and goal.reached_at is not None
        assert (goal.config.status, goal.config.pause_reason) == ("paused_by_system", "goal_ended")
        assert self.detail(goal)["results"]["spend"]["tested_ideas"] == 1
        sent = [call.args[0] for call in notify.call_args_list]
        assert {data.source_url for data in sent} == {f"/project/{self.team.id}/inbox/scouts/{goal.config.skill_name}"}
        assert len({data.idempotency_key for data in sent}) == len({data.title for data in sent}) == 2

        cleanup = str(self.world.cleanup_task)
        latest = self.patch("products.tasks.backend.facade.api.get_latest_run_by_task")
        run_task = self.patch(
            "products.tasks.backend.facade.api.run_task",
            return_value=SimpleNamespace(error=None, run_error="", run_id=uuid4()),
        )
        for status, expected in (("completed", 400), ("failed", 200)):
            latest.return_value = {cleanup: SimpleNamespace(status=status)}
            response = self.client.post(
                f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/act/",
                {"work_id": str(idea.id), "action": "retry_cleanup"},
                format="json",
            )
            assert response.status_code == expected, response.content
        assert [call.args[0] for call in run_task.call_args_list] == [cleanup]

    def test_no_scout_run_before_tracking_and_baseline_and_a_described_measure_gets_its_insight(self) -> None:
        self.world.baseline = Baseline(ready=False, value=0.1, note="Waiting for data: 120 of 300 observations.")
        goal = self.create(goal_insight="", goal_description="Share rate after upload", target=None)
        tracking = self.row(goal, "tracking")
        assert "Insight: <short id>" in (tracking.report.summary or "")
        self.world.logs = '{"text": "Tracking is correct.\\nInsight: def45678"}'
        self.world.finish(str(tracking.report_id))
        self.tick(goal)
        assert goal.insight_short_id == "def45678" and goal.status == "setting_up"
        self.tick(goal)
        assert goal.note == "Set the target to start."
        response = self.client.patch(
            f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/", {"target": "0.4"}, format="json"
        )
        assert response.status_code == 200, response.content
        self.tick(goal)
        assert (goal.status, goal.note) == ("setting_up", "Waiting for data: 120 of 300 observations.")
        assert self.gate(goal).refusal and self.world.scout_runs_started == 0
        self.world.baseline = Baseline(ready=True, value=0.1, note="")
        self.tick(goal)
        assert goal.status == "running" and self.world.scout_runs_started == 1

    def test_only_one_idea_is_built_at_a_time(self) -> None:
        goal = self.running()
        first = self.file_idea(
            goal, "Instant uploads", "Most stop ([funnel](http://localhost/project/1/insights/abc))."
        )
        second = self.file_idea(goal, "Add more files after a share")
        work = {item["id"]: item for item in self.detail(goal)["work"]}
        assert work[str(first.id)]["stage"] == "proposed"
        assert [item["kind"] for item in work[str(first.id)]["evidence"]] == ["insight"]
        assert self.build(goal, str(first.id)).status_code == 200
        refused = self.build(goal, str(second.id))
        assert refused.status_code == 400 and "current idea" in str(refused.json())
        assert self.gate(goal).refusal == "New ideas come after its result."

    def test_an_idea_built_without_a_plan_is_planned_from_its_traffic(self) -> None:
        goal = self.running()
        idea = self.reviewing(goal, days=None)
        self.world.pr_state(str(idea.report_id), "merged")
        self.world.results = results((0.05, 0.2), exposures={"control": 400, "test": 400})
        self.tick(goal)
        self.tick(goal)
        idea.refresh_from_db()
        assert (idea.stage, idea.note, idea.plan.get("days")) == ("live", "Measuring traffic to plan the test.", None)
        traffic, self.world.results = self.world.results, None
        self.tick(goal)
        idea.refresh_from_db()
        assert idea.stage == "live"
        self.world.results = traffic
        with time_machine.travel(timezone.now() + timedelta(days=1, hours=1)):
            self.tick(goal)
        idea.refresh_from_db()
        assert idea.stage == "live" and idea.plan["days"] >= 2 and idea.plan["audience"] > 0

    def test_listing_goals_reads_all_scout_runs_at_once(self) -> None:
        goal = self.running()
        self.scout_run(goal, [])

        def queries() -> int:
            with CaptureQueriesContext(connection) as captured:
                assert self.client.get(f"/api/projects/{self.team.id}/signals/scout/goals/").status_code == 200
            return len(captured)

        queries()
        before = queries()
        for _ in range(4):
            self.scout_run(goal, [])
        assert queries() == before

    def test_an_owner_idea_waiting_for_the_scout_can_be_removed_but_not_retried(self) -> None:
        goal = self.running()
        url = f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}"
        added = self.client.post(f"{url}/ideas/", {"title": "Bigger upload button"}, format="json")
        assert "owner-1" in {item["id"] for item in added.json()["work"]}
        assert self.world.scout_runs_started == 2

        def act(action: str) -> Any:
            return self.client.post(f"{url}/act/", {"work_id": "owner-1", "action": action}, format="json")

        assert act("retry").status_code == 400
        removed = act("drop")
        assert removed.status_code == 200, removed.content
        assert "owner-1" not in {item["id"] for item in removed.json()["work"]}
        assert act("drop").status_code == 400

    def test_two_empty_scout_runs_ask_the_owner_for_an_idea(self) -> None:
        notify = self.patch(f"{MODULE}.notify.create_notification")
        goal = self.running()
        self.scout_run(goal, [])
        latest = self.scout_run(goal, [])
        latest.summary = "No step in the upload flow lost enough people to test."
        latest.save(update_fields=["summary"])
        self.tick(goal)
        state = self.detail(goal)["state"]
        assert (state["headline"], state["action"]["label"]) == ("The Scout found no new ideas", "Add an idea")
        sent = [call.args[0] for call in notify.call_args_list]
        assert any("No step in the upload flow lost enough people" in item.body for item in sent)
        added = self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/ideas/", {"title": "Bigger upload button"}
        )
        assert added.json()["state"]["headline"] == "Checking your ideas"

    def test_a_losing_idea_concludes_and_the_loop_continues(self) -> None:
        goal = self.running()
        idea = self.ship_idea(goal, results((-0.2, -0.05)))
        assert (idea.stage, idea.outcome) == ("done", "lost")
        assert self.world.ended == [(7, "lost", "control")]
        assert self.world.scout_runs_started == 2
        self.tick(goal)
        assert goal.status == "running"
        assert "Mode for this run: find" in self.gate(goal).context

    def test_a_closed_pull_request_drops_the_idea_and_ends_its_experiment(self) -> None:
        goal = self.running()
        idea = self.reviewing(goal)
        self.world.pr_state(str(idea.report_id), "closed")
        self.tick(goal)
        idea.refresh_from_db()
        assert (idea.stage, idea.outcome) == ("dropped", "dropped")
        assert self.world.ended == [(7, "stopped_early", "")]
        assert self.build(goal, str(self.file_idea(goal, "Another idea").id)).status_code == 200

    def test_a_goal_scout_with_a_running_test_is_deleted_only_after_close(self) -> None:
        goal = self.running()
        idea = self.reviewing(goal)
        config_url = f"/api/projects/{self.team.id}/signals/scout/configs/{goal.pk}/"
        refused = self.client.delete(config_url)
        assert refused.status_code == 400 and "Close the goal first" in str(refused.json())
        with self.captureOnCommitCallbacks(execute=True):
            closed = self.client.post(f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/close/")
        assert closed.status_code == 200, closed.content
        idea.refresh_from_db()
        assert (idea.stage, self.world.ended) == ("dropped", [(7, "stopped_early", "")])
        assert self.client.delete(config_url).status_code == 204
        assert not SignalScoutGoal.objects.for_team(self.team.id).filter(pk=goal.pk).exists()

    def test_spent_budget_stops_the_goal_and_more_budget_resumes_it(self) -> None:
        goal = self.running(budget_cents=1000)
        run = self.scout_run(goal, [])
        SignalSpend.objects.for_team(self.team.id).create(
            team=self.team,
            kind=SignalSpend.Kind.SCOUT_RUN,
            scout_run=run,
            task_run_id=run.task_run_id,
            spend=Decimal(1500),
        )
        self.tick(goal)
        assert goal.status == "spent" and goal.config.status == SignalScoutConfig.Status.PAUSED_BY_SYSTEM
        response = self.client.patch(
            f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/", {"budget_cents": 5000}, format="json"
        )
        assert response.status_code == 200, response.content
        goal.refresh_from_db()
        goal.config.refresh_from_db()
        assert goal.status == "running" and goal.config.status == SignalScoutConfig.Status.ACTIVE

    @parameterized.expand(
        [
            ("measure", {"goal_insight": "zzz12345"}, 400),
            ("guardrails", {"secondary_metrics": []}, 400),
            ("repositories", {"repositories": ["posthog/other"]}, 400),
            ("target", {"target": "0.5"}, 200),
            ("belief", {"statement": "Sharing should take one click."}, 200),
        ]
    )
    def test_locked_fields_refuse_edits_after_start(self, _name: str, change: dict[str, Any], expected: int) -> None:
        goal = self.running()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/", change, format="json"
        )
        assert response.status_code == expected, response.content

    def test_activity_merges_goal_runs_ideas_experiments_and_spend(self) -> None:
        goal = self.running()
        idea = self.ship_idea(goal, results((0.05, 0.2)))
        SignalSpend.objects.for_team(self.team.id).create(
            team=self.team,
            kind=SignalSpend.Kind.REVIEWER_TRIGGERED_IMPLEMENTATION,
            report_id=idea.report_id,
            task_run_id=uuid4(),
            spend=Decimal(40),
        )
        self.patch(
            f"{MODULE}.activity.activity_for_experiments",
            return_value=[
                SimpleNamespace(
                    id="exp-1",
                    at=timezone.now(),
                    scope="Experiment",
                    item_id="7",
                    name="Share button",
                    activity="updated",
                    changes=({"field": "start_date", "after": "2026-11-01"},),
                )
            ],
        )
        response = self.client.get(f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/activity/")
        assert response.status_code == 200, response.content
        titles = {entry["title"] for entry in response.json()}
        assert {
            "Goal created",
            "Goal running",
            "Scout run finished",
            "Idea learned",
            "Pull request merged",
            "Experiment started",
            "Spend recorded",
        } <= titles, titles

    def test_retry_resumes_stuck_tracking(self) -> None:
        goal = self.create()
        tracking = self.row(goal, "tracking")
        self.world.finish(str(tracking.report_id), status="failed")
        self.tick(goal)
        tracking.refresh_from_db()
        assert tracking.stage == "stuck"
        self.patch(f"{MODULE}.build.resume_task", return_value="")
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/scout/goals/{goal.pk}/act/",
            {"work_id": str(tracking.id), "action": "retry"},
            format="json",
        )
        assert response.status_code == 200, response.content
        tracking.refresh_from_db()
        assert tracking.stage == "building"
