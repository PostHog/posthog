from datetime import UTC, datetime
from typing import TYPE_CHECKING

from posthog.test.base import BaseTest

from django.apps import apps

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION, TASK_RUN_TYPE_RESEARCH
from products.signals.backend.billing import SIGNALS_CREDITS_PER_REPORT_WITH_PR, get_signals_billing_credits_by_team
from products.signals.backend.models import SignalReport, SignalReportTask

if TYPE_CHECKING:
    from products.tasks.backend.models import (
        Task as TaskModel,
        TaskRun as TaskRunModel,
    )

PERIOD_START = datetime(2026, 6, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 7, 1, tzinfo=UTC)

# Sentinel so a test can force a raw `output` (e.g. SQL NULL or a non-string pr_url) without
# colliding with the str | None pr_url path.
_UNSET = object()


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=UTC)


# `products.tasks` is an isolated product, so its models are reached at runtime via the app
# registry rather than imported across the boundary (type-only imports above are ignored by tach).
def _task_model() -> type["TaskModel"]:
    return apps.get_model("tasks", "Task")


def _task_run_model() -> type["TaskRunModel"]:
    return apps.get_model("tasks", "TaskRun")


class TestSignalsBilling(BaseTest):
    def _report(self, *, team: Team | None = None, status: str = SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(team=team or self.team, status=status, signal_count=1, total_weight=1.0)

    def _pr_run(
        self,
        report: SignalReport,
        *,
        created_at: datetime,
        pr_url: str | None = "https://github.com/x/y/pull/1",
        team: Team | None = None,
        relationship: str = TASK_RUN_TYPE_IMPLEMENTATION,
        output: object = _UNSET,
    ) -> "TaskRunModel":
        team = team or self.team
        Task, TaskRun = _task_model(), _task_run_model()
        task = Task.objects.create(
            team=team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(team=team, report=report, task=task, relationship=relationship)
        run_output = output if output is not _UNSET else ({"pr_url": pr_url} if pr_url is not None else {})
        return TaskRun.objects.create(team=team, task=task, output=run_output, created_at=created_at)

    def _credits(self) -> dict[int, int]:
        return dict(get_signals_billing_credits_by_team(PERIOD_START, PERIOD_END))

    def test_flat_credit_is_fifteen_dollars(self) -> None:
        # 1 credit = $0.01, so $15 == 1500 credits.
        self.assertEqual(SIGNALS_CREDITS_PER_REPORT_WITH_PR, 1500)

    def test_report_with_pr_billed_flat(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(10))
        self.assertEqual(self._credits(), {self.team.id: 1500})

    def test_report_without_pr_not_billed(self) -> None:
        self._report()
        self.assertEqual(self._credits(), {})

    @parameterized.expand([("null_pr_url", None), ("empty_pr_url", "")])
    def test_run_without_usable_pr_url_not_billed(self, _name: str, pr_url: str | None) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(10), pr_url=pr_url)
        self.assertEqual(self._credits(), {})

    @parameterized.expand(
        [
            ("http_not_https", "http://github.com/x/y/pull/1"),
            ("gitlab", "https://gitlab.com/x/y/-/merge_requests/1"),
            ("phishy_host", "https://github.com.evil.com/x/y/pull/1"),
            ("no_scheme", "github.com/x/y/pull/1"),
            ("garbage", "not-a-url"),
        ]
    )
    def test_non_github_pr_url_not_billed(self, _name: str, pr_url: str) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(10), pr_url=pr_url)
        self.assertEqual(self._credits(), {})

    def test_run_with_null_output_not_billed(self) -> None:
        # `output` is null=True, so SQL NULL is the real default for a run with no PR — not {}.
        report = self._report()
        self._pr_run(report, created_at=_at(10), output=None)
        self.assertEqual(self._credits(), {})

    @parameterized.expand(
        [
            ("number", 123),
            ("bool", True),
            ("object", {"html_url": "https://github.com/x/y/pull/1"}),
            ("array", ["https://github.com/x/y/pull/1"]),
        ]
    )
    def test_non_string_pr_url_not_billed(self, _name: str, pr_url: object) -> None:
        # `startswith` must match only present, string-typed values; a non-string pr_url never bills.
        report = self._report()
        self._pr_run(report, created_at=_at(10), output={"pr_url": pr_url})
        self.assertEqual(self._credits(), {})

    def test_bridge_team_mismatch_not_billed(self) -> None:
        # A malformed bridge whose team disagrees with the run/report must not produce a charge.
        Task, TaskRun = _task_model(), _task_run_model()
        other = Team.objects.create(organization=self.organization, name="other")
        report = self._report()
        task = Task.objects.create(
            team=self.team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(team=other, report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION)
        TaskRun.objects.create(
            team=self.team, task=task, output={"pr_url": "https://github.com/x/y/pull/1"}, created_at=_at(10)
        )
        self.assertEqual(self._credits(), {})

    def test_run_team_mismatch_not_billed(self) -> None:
        # A run whose team disagrees with the task/bridge/report must not produce a charge.
        Task, TaskRun = _task_model(), _task_run_model()
        other = Team.objects.create(organization=self.organization, name="other")
        report = self._report()
        task = Task.objects.create(
            team=self.team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(
            team=self.team, report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        )
        TaskRun.objects.create(
            team=other, task=task, output={"pr_url": "https://github.com/x/y/pull/1"}, created_at=_at(10)
        )
        self.assertEqual(self._credits(), {})

    def test_task_team_mismatch_not_billed(self) -> None:
        # Bridge/run/report all agree but the task belongs to another team — fail closed.
        # Isolates the task__team_id check; the bridge-mismatch test breaks every clause at once.
        Task, TaskRun = _task_model(), _task_run_model()
        other = Team.objects.create(organization=self.organization, name="other")
        report = self._report()
        task = Task.objects.create(
            team=other, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(
            team=self.team, report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        )
        TaskRun.objects.create(
            team=self.team, task=task, output={"pr_url": "https://github.com/x/y/pull/1"}, created_at=_at(10)
        )
        self.assertEqual(self._credits(), {})

    def test_report_team_mismatch_not_billed(self) -> None:
        # A bridge/task/run all agree but the report belongs to another team — fail closed.
        # Isolates the report__team_id check (the other mismatch tests also break the task check).
        Task, TaskRun = _task_model(), _task_run_model()
        other = Team.objects.create(organization=self.organization, name="other")
        report = self._report(team=other)
        task = Task.objects.create(
            team=self.team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(
            team=self.team, report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        )
        TaskRun.objects.create(
            team=self.team, task=task, output={"pr_url": "https://github.com/x/y/pull/1"}, created_at=_at(10)
        )
        self.assertEqual(self._credits(), {})

    @parameterized.expand([("at_period_start", PERIOD_START, True), ("at_period_end", PERIOD_END, False)])
    def test_period_window_is_half_open(self, _name: str, created_at: datetime, billed: bool) -> None:
        # begin is inclusive, end is exclusive — a PR exactly at end belongs to the next period.
        report = self._report()
        self._pr_run(report, created_at=created_at)
        self.assertEqual(self._credits(), {self.team.id: 1500} if billed else {})

    def test_pr_before_period_not_billed(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=datetime(2026, 5, 28, tzinfo=UTC))
        self.assertEqual(self._credits(), {})

    def test_pr_after_period_not_billed(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=datetime(2026, 7, 2, tzinfo=UTC))
        self.assertEqual(self._credits(), {})

    def test_report_first_billed_in_prior_period_not_rebilled(self) -> None:
        # First PR landed last month; a second PR this month must not re-charge.
        report = self._report()
        self._pr_run(report, created_at=datetime(2026, 5, 28, tzinfo=UTC))
        self._pr_run(report, created_at=_at(20))
        self.assertEqual(self._credits(), {})

    def test_billed_once_across_consecutive_periods(self) -> None:
        # The production loop runs period after period. A report's first PR is billed in its period;
        # a later PR in the next period must charge zero. Asserts both halves, not just the second.
        july_start = PERIOD_END
        august_start = datetime(2026, 8, 1, tzinfo=UTC)
        report = self._report()
        self._pr_run(report, created_at=_at(10))
        self._pr_run(report, created_at=datetime(2026, 7, 15, tzinfo=UTC))
        self.assertEqual(dict(get_signals_billing_credits_by_team(PERIOD_START, PERIOD_END)), {self.team.id: 1500})
        self.assertEqual(get_signals_billing_credits_by_team(july_start, august_start), [])

    def test_earlier_pr_on_different_task_excludes_report(self) -> None:
        # A report can have several implementation tasks. If any of them shipped a PR before the
        # period, the report's first PR predates the window and must not be re-billed here.
        report = self._report()
        self._pr_run(report, created_at=datetime(2026, 5, 20, tzinfo=UTC))  # task A, last month
        self._pr_run(report, created_at=_at(15))  # task B, this month
        self.assertEqual(self._credits(), {})

    def test_multiple_prs_in_period_billed_once(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(5))
        self._pr_run(report, created_at=_at(22))
        self.assertEqual(self._credits(), {self.team.id: 1500})

    def test_pr_on_non_implementation_task_not_billed(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(19), relationship=TASK_RUN_TYPE_RESEARCH)
        self.assertEqual(self._credits(), {})

    @parameterized.expand(
        [
            (SignalReport.Status.RESOLVED,),
            (SignalReport.Status.SUPPRESSED,),
            # Billing follows the shipped PR, not the report's lifecycle: a report deleted after its
            # implementation landed is still charged once (matching "regardless of later status changes").
            (SignalReport.Status.DELETED,),
        ]
    )
    def test_billed_regardless_of_status_after_landing(self, status: str) -> None:
        report = self._report(status=status)
        self._pr_run(report, created_at=_at(8))
        self.assertEqual(self._credits(), {self.team.id: 1500})

    def test_first_run_with_pr_url_determines_period_not_first_run(self) -> None:
        # An earlier run with no PR URL must not count as the first PR; the in-period PR run does.
        report = self._report()
        self._pr_run(report, created_at=datetime(2026, 5, 3, tzinfo=UTC), pr_url=None)
        self._pr_run(report, created_at=_at(21))
        self.assertEqual(self._credits(), {self.team.id: 1500})

    def test_aggregates_across_teams_and_reports(self) -> None:
        team_b = Team.objects.create(organization=self.organization, name="team-b")
        for _ in range(3):
            self._pr_run(self._report(), created_at=_at(10))
        self._pr_run(self._report(team=team_b), created_at=_at(11), team=team_b)
        self._pr_run(self._report(team=team_b), created_at=_at(13), team=team_b)
        self.assertEqual(self._credits(), {self.team.id: 4500, team_b.id: 3000})

    def test_deterministic_across_runs(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(5))
        self._pr_run(report, created_at=_at(22))
        self.assertEqual(self._credits(), self._credits())

    def test_no_billable_reports_returns_empty(self) -> None:
        self.assertEqual(get_signals_billing_credits_by_team(PERIOD_START, PERIOD_END), [])
