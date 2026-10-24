from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client.connection import Workload

from products.signals.backend.constants import FIRST_REPORT_SCOUT, FIRST_REPORT_SCOUT_TIMEOUT_SECONDS
from products.signals.backend.first_report_scout import build_first_report_context, first_report_state
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.config_registry import live_scout_skill_names, register_missing_configs
from products.signals.backend.scout_harness.tools.profile import compute_project_profile
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task, TaskRun
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestFirstReportScout(BaseTest):
    def test_system_scout_never_enters_the_scheduled_fleet(self) -> None:
        LLMSkill.objects.create(team=self.team, name=FIRST_REPORT_SCOUT, body="# First report", is_latest=True)
        assert FIRST_REPORT_SCOUT not in register_missing_configs(self.team.id)
        assert not SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name=FIRST_REPORT_SCOUT).exists()
        SignalScoutConfig.objects.create(team=self.team, skill_name=FIRST_REPORT_SCOUT, enabled=True)
        assert FIRST_REPORT_SCOUT not in live_scout_skill_names(self.team.id)

    def setUp(self) -> None:
        super().setUp()
        with patch(
            "products.signals.backend.scout_harness.profile.builders.execute_hogql_query",
            return_value=Mock(results=[]),
        ):
            compute_project_profile(team=self.team, defer_surfaces=True)

    @parameterized.expand([(None, False, False), (0, False, False), (20, True, False)])
    def test_data_gate_includes_warehouse_rows_without_analytics_events(
        self, row_count: int | None, has_data: bool, unknown: bool
    ) -> None:
        if row_count is not None:
            DataWarehouseTable.objects.create(
                team=self.team,
                name="orders",
                format="Parquet",
                url_pattern="https://example.com/orders",
                row_count=row_count,
            )
        with patch(
            "products.signals.backend.first_report_scout.execute_hogql_query",
            side_effect=lambda **kwargs: Mock(results=[[0, None]] if len(kwargs["query"].select) == 2 else []),
        ):
            context = build_first_report_context(self.team, self.user)
        assert context.has_data() is has_data
        assert context.data_is_unknown() is unknown
        if has_data:
            assert '"recorded_row_count": 20' in context.prompt_context()

    def test_older_product_data_still_qualifies_for_an_investigation(self) -> None:
        with patch(
            "products.signals.backend.first_report_scout.execute_hogql_query",
            side_effect=lambda **kwargs: Mock(results=[[0, None]] if len(kwargs["query"].select) == 2 else [[1]]),
        ) as query:
            context = build_first_report_context(self.team, self.user)
        assert context.has_data()
        assert context.product_data["session_replay_fragments"].rows == 0
        assert context.product_data["session_replay_fragments"].has_rows is True
        assert [call.kwargs["workload"] for call in query.call_args_list] == [
            Workload.OFFLINE,
            Workload.OFFLINE,
            Workload.LOGS,
            Workload.LOGS,
            Workload.LOGS,
            Workload.LOGS,
        ]

    @parameterized.expand(
        [("in_progress", False, "running"), ("in_progress", True, "incomplete"), ("failed", False, "incomplete")]
    )
    def test_unfinished_runs_stop_showing_progress_after_the_deadline(
        self, status: str, expired: bool, expected: str
    ) -> None:
        task = Task.objects.create(team=self.team, title="First investigation")
        task_run = TaskRun.objects.create(team=self.team, task=task, status=status)
        if expired:
            TaskRun.objects.filter(id=task_run.id, team=self.team).update(
                created_at=timezone.now() - timedelta(seconds=FIRST_REPORT_SCOUT_TIMEOUT_SECONDS + 301)
            )
        SignalScoutRun.objects.create(team=self.team, task_run=task_run, skill_name=FIRST_REPORT_SCOUT, skill_version=1)
        result = first_report_state(self.team.id)
        assert result["status"] == expected
        assert result["task_run_id"] == str(task_run.id)

    def test_query_failure_is_unknown_instead_of_no_data(self) -> None:
        with patch(
            "products.signals.backend.first_report_scout.execute_hogql_query",
            side_effect=RuntimeError("query unavailable"),
        ):
            context = build_first_report_context(self.team, self.user)
        assert not context.has_data()
        assert context.data_is_unknown()

    @parameterized.expand(
        [
            ("insufficient_data", None, "insufficient_data"),
            ("no_actionable_finding", None, "no_actionable_finding"),
            ("report_created", None, "incomplete"),
            ("report_created", "suppressed", "incomplete"),
            ("report_created", "ready", "report_created"),
            ("report_created", "pending_input", "report_created"),
        ]
    )
    def test_onboarding_success_requires_a_visible_persisted_report(
        self, outcome: str, report_status: str | None, expected: str
    ) -> None:
        task = Task.objects.create(team=self.team, title="First investigation")
        task_run = TaskRun.objects.create(team=self.team, task=task, status="completed")
        report = SignalReport.objects.create(team=self.team, status=report_status) if report_status else None
        SignalScoutRun.objects.create(
            team=self.team,
            task_run=task_run,
            skill_name=FIRST_REPORT_SCOUT,
            skill_version=1,
            emitted_report_ids=[str(report.id)] if report else [],
            metadata={
                "first_report_result": {
                    "outcome": outcome,
                    "checked_products": ["product_analytics"],
                    "missing_data": [],
                }
            },
        )
        result = first_report_state(self.team.id)
        assert result["status"] == expected
        assert result["task_id"] == str(task.id)
        assert result["task_run_id"] == str(task_run.id)
        if expected == "report_created":
            assert report is not None
            assert result["report_id"] == str(report.id)
