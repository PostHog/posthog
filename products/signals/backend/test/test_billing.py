from datetime import UTC, datetime
from typing import TYPE_CHECKING

from posthog.test.base import BaseTest

from django.apps import apps

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.billing import SIGNALS_CREDITS_PER_REPORT_WITH_PR, get_signals_billing_credits_by_team
from products.signals.backend.models import SignalReport, SignalReportTask

if TYPE_CHECKING:
    from products.tasks.backend.models import (
        Task as TaskModel,
        TaskRun as TaskRunModel,
    )

PERIOD_START = datetime(2026, 6, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 7, 1, tzinfo=UTC)


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
        relationship: str = SignalReportTask.Relationship.IMPLEMENTATION,
    ) -> "TaskRunModel":
        team = team or self.team
        Task, TaskRun = _task_model(), _task_run_model()
        task = Task.objects.create(
            team=team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(team=team, report=report, task=task, relationship=relationship)
        return TaskRun.objects.create(
            team=team, task=task, output=({"pr_url": pr_url} if pr_url is not None else {}), created_at=created_at
        )

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

    def test_bridge_team_mismatch_not_billed(self) -> None:
        # A malformed bridge whose team disagrees with the run/report must not produce a charge.
        Task, TaskRun = _task_model(), _task_run_model()
        other = Team.objects.create(organization=self.organization, name="other")
        report = self._report()
        task = Task.objects.create(
            team=self.team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(
            team=other, report=report, task=task, relationship=SignalReportTask.Relationship.IMPLEMENTATION
        )
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
            team=self.team, report=report, task=task, relationship=SignalReportTask.Relationship.IMPLEMENTATION
        )
        TaskRun.objects.create(
            team=other, task=task, output={"pr_url": "https://github.com/x/y/pull/1"}, created_at=_at(10)
        )
        self.assertEqual(self._credits(), {})

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

    def test_multiple_prs_in_period_billed_once(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(5))
        self._pr_run(report, created_at=_at(22))
        self.assertEqual(self._credits(), {self.team.id: 1500})

    def test_pr_on_non_implementation_task_not_billed(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(19), relationship=SignalReportTask.Relationship.RESEARCH)
        self.assertEqual(self._credits(), {})

    @parameterized.expand([(SignalReport.Status.RESOLVED,), (SignalReport.Status.SUPPRESSED,)])
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
