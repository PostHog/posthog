import json
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team, User

from products.notifications.backend.facade.api import create_notification
from products.signals.backend.constants import FIRST_REPORT_SCOUT, FIRST_REPORT_SCOUT_TIMEOUT_SECONDS
from products.signals.backend.first_report_completion import complete_first_report_investigation
from products.signals.backend.first_report_experiment import (
    first_report_outcome_properties,
    resolve_first_report_experiment,
)
from products.signals.backend.first_report_notification import register_first_report_notification
from products.signals.backend.first_report_scout import (
    build_first_report_context,
    first_report_state,
    set_first_report_state,
)
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.config_registry import live_scout_skill_names, register_missing_configs
from products.signals.backend.scout_harness.tools.profile import compute_project_profile
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task, TaskRun
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestFirstReportExperiment(SimpleTestCase):
    @parameterized.expand(
        [
            ("test-sol", "acp", "codex", "gpt-6.1-sol", "high", "priority"),
            ("test-deepseek", "pi", None, "deepseek-ai/deepseek-v4.1-flash-1017-fast", None, None),
        ]
    )
    def test_variant_selects_the_whole_runtime(
        self, variant: str, runtime: str, adapter: str | None, model: str, effort: str | None, tier: str | None
    ) -> None:
        team = Mock(id=123, uuid="project-uuid")
        with patch(
            "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag", return_value=variant
        ) as flag:
            assignment = resolve_first_report_experiment(team)
        assert assignment is not None
        assert assignment.variant == variant
        agent_runtime = assignment.agent_runtime
        assert agent_runtime is not None
        assert (
            agent_runtime.runtime,
            agent_runtime.runtime_adapter,
            agent_runtime.model,
            agent_runtime.reasoning_effort,
            agent_runtime.service_tier,
        ) == (runtime, adapter, model, effort, tier)
        assert flag.call_args.kwargs["groups"] == {"project": "project-uuid"}
        assert flag.call_args.kwargs["send_feature_flag_events"] is False

    def test_control_is_enrolled_without_a_scout(self) -> None:
        with patch(
            "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag", return_value="control"
        ):
            assignment = resolve_first_report_experiment(Mock(id=123, uuid="project-uuid"))
        assert assignment is not None
        assert assignment.variant == "control"
        assert not assignment.runs_scout
        assert "runtime" not in assignment.properties()

    @parameterized.expand([(False,), (None,), (True,), ("unknown",), ("deepseek-fast",)])
    def test_unenrolled_or_invalid_variant_does_not_enroll(self, variant: object) -> None:
        with patch(
            "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag", return_value=variant
        ):
            assert resolve_first_report_experiment(Mock(id=123, uuid="project-uuid")) is None

    def test_flag_outage_does_not_enroll(self) -> None:
        with (
            patch(
                "products.signals.backend.first_report_experiment.posthoganalytics.get_feature_flag",
                side_effect=RuntimeError("unavailable"),
            ),
            patch("products.signals.backend.first_report_experiment.capture_exception"),
        ):
            assert resolve_first_report_experiment(Mock(id=123, uuid="project-uuid")) is None


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

    @parameterized.expand(
        [
            ("no_tables", [], False, False),
            ("unsynced_table", [None], False, False),
            ("empty_tables", [0, 0, 0, 0], False, False),
            ("synced_rows", [0, 0, 0, 20], False, True),
            ("environment_ingested_events", [], True, True),
        ]
    )
    def test_data_gate_reads_recorded_metadata_without_querying_the_warehouse(
        self, _name: str, row_counts: list[int | None], environment_ingested: bool, has_data: bool
    ) -> None:
        for index, row_count in enumerate(row_counts):
            DataWarehouseTable.objects.create(
                team=self.team,
                name=f"orders_{index}",
                format="Parquet",
                url_pattern=f"https://example.com/orders_{index}",
                row_count=row_count,
            )
        Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="Production",
            ingested_event=environment_ingested,
        )
        with patch(
            "products.signals.backend.first_report_scout.execute_hogql_query",
            side_effect=lambda **kwargs: Mock(results=[[0, None]] if len(kwargs["query"].select) == 2 else []),
        ) as query:
            context = build_first_report_context(self.team, self.user)
        assert context.has_data() is has_data
        assert not context.data_is_unknown()
        assert all(
            not call.kwargs["query"].select_from.table.chain[0].startswith("orders") for call in query.call_args_list
        )
        prompt = context.prompt_context()
        payload = json.loads(prompt.rsplit("\n\n", 1)[1])
        assert payload.get("warehouse_tables_connected", False) is bool(row_counts)
        assert "orders_" not in prompt
        assert "recorded_row_count" not in prompt

    def test_older_product_data_still_qualifies_for_an_investigation(self) -> None:
        with patch(
            "products.signals.backend.first_report_scout.execute_hogql_query",
            side_effect=lambda **kwargs: Mock(results=[[0, None]] if len(kwargs["query"].select) == 2 else [[1]]),
        ) as query:
            context = build_first_report_context(self.team, self.user)
        assert context.has_data()
        assert context.product_data["session_replay_fragments"].rows == 0
        assert context.product_data["session_replay_fragments"].has_rows is True
        sources = json.loads(context.prompt_context().rsplit("\n\n", 1)[1])["posthog_sources"]
        assert list(sources) == ["Logs", "Traces", "Product analytics", "Session recordings"]
        assert set(sources.values()) == {"data observed"}
        assert [call.kwargs["workload"] for call in query.call_args_list] == [
            Workload.OFFLINE,
            Workload.OFFLINE,
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

    @parameterized.expand([(True, "report_created"), (False, "insufficient_data")])
    def test_experiment_measures_persisted_delivery_even_when_run_failed(self, delivered: bool, expected: str) -> None:
        task = Task.objects.create(team=self.team, title="First investigation")
        task_run = TaskRun.objects.create(team=self.team, task=task, status="failed")
        report = (
            SignalReport.objects.create(
                team=self.team, status="ready", first_visible_at=task_run.created_at + timedelta(seconds=120)
            )
            if delivered
            else None
        )
        run = SignalScoutRun.objects.create(
            team=self.team,
            task_run=task_run,
            skill_name=FIRST_REPORT_SCOUT,
            skill_version=1,
            emitted_report_ids=[str(report.id)] if report else [],
            metadata={"first_report_result": {"outcome": "insufficient_data"}},
        )
        properties = first_report_outcome_properties(self.team.id, str(run.id))
        assert properties["first_report_outcome"] == expected
        assert properties["report_delivered"] is delivered
        assert properties["report_delivered_within_five_minutes"] is delivered
        if delivered:
            assert properties["first_report_latency_seconds"] == 120

    @parameterized.expand([(False,), (True,)])
    def test_query_failure_is_unknown_instead_of_no_data(self, ingested_event: bool) -> None:
        Team.objects.filter(pk=self.team.pk).update(ingested_event=ingested_event)
        with patch(
            "products.signals.backend.first_report_scout.execute_hogql_query",
            side_effect=RuntimeError("query unavailable"),
        ):
            context = build_first_report_context(self.team, self.user)
        assert context.has_data() is ingested_event
        assert context.data_is_unknown()
        context.inventory.products_in_use = ["error_tracking", "metrics"]
        sources = json.loads(context.prompt_context().rsplit("\n\n", 1)[1])["posthog_sources"]
        assert sources == {
            "Error tracking": "configured; data unverified",
            "Metrics": "configured; data unverified",
            **(
                {"Product analytics": "past event ingestion recorded; current data unverified"}
                if ingested_event
                else {}
            ),
        }

    @parameterized.expand(
        [
            ("insufficient_data", None, "insufficient_data"),
            ("no_actionable_finding", None, "no_actionable_finding"),
            ("report_created", None, "incomplete"),
            ("report_created", "suppressed", "incomplete"),
            ("report_created", "ready", "report_created"),
            ("report_created", "pending_input", "report_created"),
            ("report_created", "ready", "report_created", True),
            ("report_created", "resolved", "report_created", False, True),
            ("report_created", "suppressed", "report_created", False, True),
        ]
    )
    def test_onboarding_success_requires_a_visible_persisted_report(
        self,
        outcome: str,
        report_status: str | None,
        expected: str,
        child_environment: bool = False,
        previously_visible: bool = False,
    ) -> None:
        activator = User.objects.create_and_join(self.organization, "activator@example.com", None)
        activation_team = (
            Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
            if child_environment
            else self.team
        )
        register_first_report_notification(team=activation_team, user=activator)
        set_first_report_state(self.team.id, "pending", activation_team_id=activation_team.id)
        set_first_report_state(self.team.id, "pending", activation_team_id=self.team.id)
        set_first_report_state(self.team.id, "running")
        task = Task.objects.create(team=self.team, title="First investigation", created_by=self.user)
        task_run = TaskRun.objects.create(team=self.team, task=task, status="completed")
        report = (
            SignalReport.objects.create(
                team=self.team,
                status=report_status,
                first_visible_at=timezone.now() if previously_visible else None,
            )
            if report_status
            else None
        )
        run = SignalScoutRun.objects.create(
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
        notifications: list[object] = []
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch("products.signals.backend.first_report_completion.may_read_reports", return_value=True),
            patch(
                "products.signals.backend.first_report_completion.create_notification",
                side_effect=lambda data: notifications.append(create_notification(data)),
            ) as notify,
        ):
            complete_first_report_investigation(self.team.id, str(run.id))
            complete_first_report_investigation(self.team.id, str(run.id))
        assert notifications[0] is not None
        assert notifications[0] == notifications[1]
        notification = notify.call_args.args[0]
        assert notification.target_id == str(activator.pk)
        assert notification.team_id == activation_team.id
        assert notification.source_url == f"/project/{self.team.id}/inbox"
