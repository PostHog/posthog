from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.tasks.usage_report import get_teams_with_signals_spend_credits_used_in_period

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION, TASK_RUN_TYPE_RESEARCH
from products.signals.backend.billing import (
    SIGNALS_CREDITS_PER_REPORT_WITH_PR,
    BillingExemptionError,
    FirstBillablePrRun,
    _bridges_with_pr_run,
    annotate_first_billable_pr_run_at,
    first_billable_pr_run,
    first_billable_pr_run_at_by_report,
    get_signals_billing_credits_by_team,
    mark_report_billing_exempt,
    system_billing_exempt_reason,
)
from products.signals.backend.models import (
    SignalReport,
    SignalReportRefund,
    SignalReportTask,
    SignalScoutRun,
    SignalSpend,
)
from products.signals.backend.scout_harness.lazy_seed import HARNESS_SEEDED_BY, _compute_row_hash
from products.signals.backend.spend import complete_signal_pipeline, finish_report_spend, record_llm_spend
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team
from products.skills.backend.models.skills import LLMSkill

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    list_limited_team_attributes,
    update_all_orgs_billing_quotas,
)

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


def _seed_canonical_scout_skill(team: Team, skill_name: str) -> LLMSkill:
    """A team skill row that classifies as canonical: harness-seeded metadata whose stored
    canonical_hash matches the row's current content hash (like lazy seeding stamps it)."""
    skill = LLMSkill.objects.create(
        team=team,
        name=skill_name,
        description="d",
        body="canonical body",
        allowed_tools=[],
        metadata={"seeded_by": HARNESS_SEEDED_BY},
        version=1,
        is_latest=True,
    )
    skill.metadata["canonical_hash"] = _compute_row_hash(skill, [])
    skill.save(update_fields=["metadata"])
    return skill


def _make_report(team: Team, *, status: str = SignalReport.Status.READY) -> SignalReport:
    return SignalReport.objects.create(team=team, status=status, signal_count=1, total_weight=1.0)


def _make_pr_run(
    team: Team,
    report: SignalReport,
    *,
    created_at: datetime,
    pr_url: str | None = "https://github.com/x/y/pull/1",
    relationship: str = TASK_RUN_TYPE_IMPLEMENTATION,
    output: object = _UNSET,
) -> "TaskRunModel":
    Task, TaskRun = _task_model(), _task_run_model()
    task = Task.objects.create(
        team=team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
    )
    SignalReportTask.objects.create(team=team, report=report, task=task, relationship=relationship)
    run_output = output if output is not _UNSET else ({"pr_url": pr_url} if pr_url is not None else {})
    return TaskRun.objects.create(team=team, task=task, output=run_output, created_at=created_at)


def _make_refund(report: SignalReport, *, billing_path: str, pr_run_created_at: datetime | None = None) -> None:
    SignalReportRefund.objects.create(
        team=report.team,
        report=report,
        reason=SignalReportRefund.Reason.PR_INCORRECT,
        billing_path=billing_path,
        credits=SIGNALS_CREDITS_PER_REPORT_WITH_PR,
        pr_url="https://github.com/x/y/pull/1",
        pr_run_created_at=pr_run_created_at or _at(10),
    )


class TestSignalsBilling(BaseTest):
    def _report(self, *, team: Team | None = None, status: str = SignalReport.Status.READY) -> SignalReport:
        return _make_report(team or self.team, status=status)

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
        return _make_pr_run(
            team or self.team, report, created_at=created_at, pr_url=pr_url, relationship=relationship, output=output
        )

    def _credits(self) -> dict[int, int]:
        return dict(get_signals_billing_credits_by_team(PERIOD_START, PERIOD_END))

    def test_flat_credit_is_fifteen_dollars(self) -> None:
        # 1 credit = $0.01, so $15 == 1500 credits.
        self.assertEqual(SIGNALS_CREDITS_PER_REPORT_WITH_PR, 1500)

    @parameterized.expand([(as_list, usage_billing) for as_list in (False, True) for usage_billing in (False, True)])
    def test_organization_filter_excludes_other_organizations(self, as_list: bool, usage_billing: bool) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other org"))
        with time_machine.travel(_at(10), tick=False):
            for team in (self.team, other_team):
                self._pr_run(self._report(team=team), created_at=_at(10), team=team)
                SignalSpend.objects.for_team(team.id).create(
                    team=team,
                    kind=SignalSpend.Kind.AD_HOC,
                    signal_id=uuid4(),
                    spend=20,
                    finalized_at=_at(10),
                )
        org_filter = (
            {"organization_ids": [self.organization.id]} if as_list else {"organization_id": self.organization.id}
        )
        if usage_billing:
            self.organization.usage = {"signals_spend_credits": {"billing_start_date": "2026-06-01"}}
            self.organization.save(update_fields=["usage"])
        counter = get_signals_spend_billing_credits_by_team if usage_billing else get_signals_billing_credits_by_team
        self.assertEqual(
            dict(counter(PERIOD_START, PERIOD_END, **org_filter)), {self.team.id: 20 if usage_billing else 1500}
        )
        self.assertEqual(counter(PERIOD_START, PERIOD_END, organization_ids=[]), [])

    @parameterized.expand([(None, 1500), ("posthog_ai", 0)])
    def test_report_with_pr_billed_only_when_not_billed_as_phai(self, product: str | None, credits: int) -> None:
        report = self._report()
        run = self._pr_run(report, created_at=_at(10))
        if product:
            run.state = {"billing_product": product}
            run.save(update_fields=["state"])
        self.assertEqual(self._credits(), {self.team.id: credits} if credits else {})
        self.assertEqual(first_billable_pr_run(report.id, team_id=report.team_id) is not None, bool(credits))
        _task_run_model().objects.create(
            team=self.team,
            task=run.task,
            created_at=_at(11),
            output={"pr_url": "https://github.com/x/y/pull/2"},
            state={"billing_product": "posthog_ai"},
        )
        self.assertEqual(self._credits(), {self.team.id: credits} if credits else {})

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

    def test_excluded_refund_removes_report_from_usage_deterministically(self) -> None:
        # The excluded path promises billing never learns the report existed — and every send
        # covering the day (scheduled, delayed-org re-send, manual re-run) must agree.
        report = self._report()
        self._pr_run(report, created_at=_at(10))
        _make_refund(report, billing_path=SignalReportRefund.BillingPath.EXCLUDED)
        self.assertEqual(self._credits(), {})
        self.assertEqual(self._credits(), {})

    def test_credited_refund_leaves_usage_truthful(self) -> None:
        # The credited path fixes the money via a billing-service credit; usage must stay intact.
        report = self._report()
        self._pr_run(report, created_at=_at(10))
        _make_refund(report, billing_path=SignalReportRefund.BillingPath.CREDITED)
        self.assertEqual(self._credits(), {self.team.id: 1500})

    def test_excluded_refund_only_affects_its_own_report(self) -> None:
        refunded = self._report()
        self._pr_run(refunded, created_at=_at(10))
        _make_refund(refunded, billing_path=SignalReportRefund.BillingPath.EXCLUDED)
        other = self._report()
        self._pr_run(other, created_at=_at(11))
        self.assertEqual(self._credits(), {self.team.id: 1500})

    @parameterized.expand(
        [
            ("excluded", SignalReportRefund.BillingPath.EXCLUDED),
            ("credited", SignalReportRefund.BillingPath.CREDITED),
        ]
    )
    def test_refunded_report_with_later_second_pr_never_bills(self, _name: str, billing_path: str) -> None:
        # Pins the emergent never-billed-again semantic: the refunded report's first PR run
        # predates any later period, so a second PR run is always caught by `billed_earlier` —
        # which is why the API blocks restoring refunded reports.
        report = self._report()
        self._pr_run(report, created_at=_at(10))
        _make_refund(report, billing_path=billing_path)
        self._pr_run(report, created_at=datetime(2026, 7, 15, tzinfo=UTC))
        july_credits = dict(get_signals_billing_credits_by_team(PERIOD_END, datetime(2026, 8, 1, tzinfo=UTC)))
        self.assertEqual(july_credits, {})

    def test_exempt_report_never_appears_in_any_usage_window(self) -> None:
        report = self._report()
        report.billing_exempt_reason = SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK
        report.save(update_fields=["billing_exempt_reason"])
        self._pr_run(report, created_at=_at(10))
        self._pr_run(report, created_at=datetime(2026, 7, 15, tzinfo=UTC))
        self.assertEqual(self._credits(), {})
        self.assertEqual(self._credits(), {})
        self.assertEqual(get_signals_billing_credits_by_team(PERIOD_END, datetime(2026, 8, 1, tzinfo=UTC)), [])

    def test_first_billable_pr_run_snapshots_earliest_billable_run(self) -> None:
        # The refund action snapshots this run's timestamp + URL and decides the billing path from
        # it — returning the latest (or a non-billable) run would replay the wrong charge.
        report = self._report()
        self._pr_run(report, created_at=_at(3), pr_url=None)  # not billable, must not win
        self._pr_run(report, created_at=_at(5), pr_url="https://github.com/x/y/pull/1")
        self._pr_run(report, created_at=_at(12), pr_url="https://github.com/x/y/pull/2")
        self.assertEqual(
            first_billable_pr_run(report.id, team_id=report.team_id),
            FirstBillablePrRun(created_at=_at(5), pr_url="https://github.com/x/y/pull/1"),
        )
        self.assertIsNone(first_billable_pr_run(report.id, team_id=report.team_id + 1))

    def test_first_billable_pr_run_none_without_billable_run(self) -> None:
        report = self._report()
        self._pr_run(report, created_at=_at(3), pr_url=None)
        self.assertIsNone(first_billable_pr_run(report.id, team_id=report.team_id))

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

    def test_pr_url_filter_repeats_the_partial_index_predicate(self) -> None:
        # Postgres answers the prefix test from `task_run_github_pr_run_idx` only while the query
        # spells the predicate the same way. A changed prefix or lookup here still returns the
        # right credits, so nothing else fails — the period scan just goes back to detoasting
        # every run's `output`.
        run_model = _task_run_model()
        index = next(i for i in run_model._meta.indexes if i.name == "task_run_github_pr_run_idx")
        index_sql, index_params = run_model.objects.filter(index.condition).order_by().query.sql_with_params()
        query_sql, query_params = _bridges_with_pr_run().query.sql_with_params()
        self.assertIn(index_sql.split(" WHERE ", 1)[1], query_sql)
        self.assertTrue(all(parameter in query_params for parameter in index_params))


class TestBillingExemptions(BaseTest):
    def test_mark_report_billing_exempt_sets_reason_before_billable_run(self) -> None:
        report = _make_report(self.team)
        changed = mark_report_billing_exempt(report, SignalReport.BillingExemptReason.POSTHOG_SYSTEM)
        report.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(report.billing_exempt_reason, SignalReport.BillingExemptReason.POSTHOG_SYSTEM)

    def test_mark_report_billing_exempt_refuses_once_billable_run_exists(self) -> None:
        # The freeze rule: anything already billable is a refund, never a late exemption —
        # flipping the flag after a usage send may have observed the run breaks determinism.
        report = _make_report(self.team)
        _make_pr_run(self.team, report, created_at=_at(10))
        with self.assertRaises(BillingExemptionError):
            mark_report_billing_exempt(report, SignalReport.BillingExemptReason.POSTHOG_SYSTEM)
        report.refresh_from_db()
        self.assertIsNone(report.billing_exempt_reason)

    def test_mark_report_billing_exempt_never_rewrites_existing_reason(self) -> None:
        report = _make_report(self.team)
        mark_report_billing_exempt(report, SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK)
        changed = mark_report_billing_exempt(report, SignalReport.BillingExemptReason.POSTHOG_SYSTEM)
        report.refresh_from_db()
        self.assertFalse(changed)
        self.assertEqual(report.billing_exempt_reason, SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK)

    def _scout_run(self, skill_name: str, emitted_report_ids: list[str]) -> SignalScoutRun:
        Task, TaskRun = _task_model(), _task_run_model()
        task = Task.objects.create(team=self.team, title="scout", description="d")
        task_run = TaskRun.objects.create(team=self.team, task=task)
        return SignalScoutRun.objects.create(
            team=self.team,
            task_run=task_run,
            skill_name=skill_name,
            skill_version=1,
            emitted_report_ids=emitted_report_ids,
        )

    def test_system_policy_exempts_health_check_scout_reports_only(self) -> None:
        health_check_report = _make_report(self.team)
        other_scout_report = _make_report(self.team)
        pipeline_report = _make_report(self.team)
        self._scout_run("signals-scout-health-checks", [str(health_check_report.id)])
        self._scout_run("signals-scout-general", [str(other_scout_report.id)])

        # No skill row for the team: origin unprovable → fail closed, stays billable.
        self.assertIsNone(system_billing_exempt_reason(self.team.id, health_check_report.id))

        skill = _seed_canonical_scout_skill(self.team, "signals-scout-health-checks")
        self.assertEqual(
            system_billing_exempt_reason(self.team.id, health_check_report.id),
            SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK,
        )
        self.assertIsNone(system_billing_exempt_reason(self.team.id, other_scout_report.id))
        self.assertIsNone(system_billing_exempt_reason(self.team.id, pipeline_report.id))

        # A team-edited fork keeps the canonical name but is no longer PostHog's system:
        # the diverged row must stop minting exemptions.
        skill.body = "team-edited body"
        skill.save(update_fields=["body"])
        forked_report = _make_report(self.team)
        self._scout_run("signals-scout-health-checks", [str(forked_report.id)])
        self.assertIsNone(system_billing_exempt_reason(self.team.id, forked_report.id))

        # A republished row that kept the seed tag but dropped the stored hash proves nothing
        # about its content, so it cannot mint an exemption either.
        skill.metadata.pop("canonical_hash")
        skill.save(update_fields=["metadata"])
        unproven_report = _make_report(self.team)
        self._scout_run("signals-scout-health-checks", [str(unproven_report.id)])
        self.assertIsNone(system_billing_exempt_reason(self.team.id, unproven_report.id))


class TestSpendBasedBilling(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = "2026-06-10"
        trial = patch("products.signals.backend.spend_billing.posthoganalytics.feature_enabled", return_value=False)
        self.trial_mock = trial.start()
        self.addCleanup(trial.stop)

    @property
    def cutoff(self) -> str | None:
        return (self.organization.usage or {}).get("signals_spend_credits", {}).get("billing_start_date")

    @cutoff.setter
    def cutoff(self, value: str | None) -> None:
        self.organization.usage = {"signals_spend_credits": {"billing_start_date": value}} if value else {}
        self.organization.save(update_fields=["usage"])

    def _generation(
        self, signal_id: str, cost: int | None, *, request_id: str = "request", team: Team | None = None
    ) -> None:
        record_llm_spend(
            token_cost_microusd=cost, team_id=(team or self.team).id, signal_id=signal_id, stage="grouping"
        )

    def _day(self, day: int, *, organization_id: str | None = None) -> dict[int, int]:
        begin = _at(day, 0)
        return dict(get_signals_spend_billing_credits_by_team(begin, begin + timedelta(days=1), organization_id))

    def test_unknown_generation_cost_never_becomes_billable(self) -> None:
        signal_id = str(uuid4())
        with time_machine.travel(_at(10), tick=False):
            self._generation(signal_id, None)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
            assert self._day(10) == {}
        with time_machine.travel(_at(11), tick=False):
            self._generation(signal_id, 120_000)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        assert self._day(10) == {}
        assert self._day(11) == {}
        assert SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id).accounting_failed

    def test_new_signal_preserves_prior_days_and_bills_only_its_own_spend(self) -> None:
        signal_id, next_signal_id = str(uuid4()), str(uuid4())
        with time_machine.travel(_at(10), tick=False):
            self._generation(signal_id, 100_000)
            assert self._day(10) == {}
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        with time_machine.travel(_at(11), tick=False):
            self._generation(next_signal_id, 50_000, request_id="resumed-work")
            assert self._day(10) == {self.team.id: 10}
            assert self._day(11) == {}
            complete_signal_pipeline(team_id=self.team.id, signal_id=next_signal_id)
            complete_signal_pipeline(team_id=self.team.id, signal_id=next_signal_id)
        assert self._day(10) == {self.team.id: 10}
        assert self._day(11) == {self.team.id: 5}
        assert dict(get_signals_spend_billing_credits_by_team(PERIOD_START, PERIOD_END)) == {self.team.id: 15}
        assert SignalSpend.objects.for_team(self.team.id).count() == 2
        assert dict(get_signals_spend_billing_credits_by_team(_at(10, 0), _at(10))) == {}
        assert dict(get_signals_spend_billing_credits_by_team(_at(10), _at(10) + timedelta(microseconds=1))) == {
            self.team.id: 10
        }
        assert dict(get_signals_spend_billing_credits_by_team(_at(10) + timedelta(microseconds=1), _at(11))) == {}
        assert dict(get_signals_spend_billing_credits_by_team(_at(10), _at(10))) == {}

    @parameterized.expand([(kind,) for kind in SignalSpend.Kind.values])
    def test_next_quota_refresh_counts_settled_spend_before_daily_reporting(self, kind: str) -> None:
        self.organization.usage = {
            "signals_spend_credits": {"usage": 90, "todays_usage": 0, "limit": 100, "billing_start_date": "2026-06-10"},
            "period": ["2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"],
        }
        self.organization.customer_trust_scores = {}
        self.organization.save()
        signal_id = str(uuid4())
        with time_machine.travel(_at(9), tick=False):
            report = _make_report(self.team)
        with time_machine.travel(_at(10), tick=False):
            scout = None
            if kind == SignalSpend.Kind.SCOUT_RUN:
                task = _task_model().objects.create(team=self.team, title="Synthetic scout", description="")
                run = _task_run_model().objects.create(team=self.team, task=task)
                scout = SignalScoutRun.objects.for_team(self.team.id).create(
                    team=self.team, task_run=run, skill_name="example-scout", skill_version=1
                )
            signal_owned = kind in {SignalSpend.Kind.AD_HOC, SignalSpend.Kind.RESEARCH, SignalSpend.Kind.REPO_SELECTION}
            spend = SignalSpend.objects.for_team(self.team.id).create(
                team=self.team,
                kind=kind,
                signal_id=signal_id if signal_owned else None,
                scout_run=scout,
                report=None if signal_owned or scout else report,
                task_run_id=(scout.task_run_id if scout else uuid4()) if kind != SignalSpend.Kind.AD_HOC else None,
                spend=20,
            )
            assert self._day(10) == {}
            spend.finalized_at = _at(10)
            spend.save(update_fields=["finalized_at"])
        with time_machine.travel(_at(10) + timedelta(minutes=10), tick=False):
            update_all_orgs_billing_quotas()
            self.organization.refresh_from_db()
            assert self.organization.usage is not None
            assert self.organization.usage["signals_spend_credits"]["usage"] == 90
            assert self.organization.usage["signals_spend_credits"]["todays_usage"] == 20
            assert self.team.api_token in list_limited_team_attributes(
                QuotaResource.SIGNALS_SPEND_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
        mark_report_billing_exempt(report, SignalReport.BillingExemptReason.POSTHOG_SYSTEM)
        assert self._day(10) == {self.team.id: 20}
        with time_machine.travel(_at(11), tick=False):
            assert dict(get_teams_with_signals_spend_credits_used_in_period(_at(10, 0), _at(11, 0))) == {
                self.team.id: 20
            }

    def test_cutoff_uses_work_creation_and_is_evaluated_when_reporting(self) -> None:
        legacy, usage = str(uuid4()), str(uuid4())
        self.cutoff = None
        with time_machine.travel(_at(10, 0) - timedelta(microseconds=1), tick=False):
            self._generation(legacy, 100_000, request_id="legacy")
        with time_machine.travel(_at(10, 0), tick=False):
            self._generation(usage, 200_000, request_id="usage")
        with time_machine.travel(_at(11), tick=False):
            complete_signal_pipeline(team_id=self.team.id, signal_id=legacy)
            complete_signal_pipeline(team_id=self.team.id, signal_id=usage)
        assert self._day(11) == {}
        self.cutoff = "2026-06-10"
        assert self._day(10) == {}
        assert self._day(11, organization_id=str(self.organization.id)) == {self.team.id: 20}

    @parameterized.expand([("report",), ("signal",)])
    def test_legacy_report_charge_and_new_signal_spend_are_independent(self, existing_work: str) -> None:
        legacy_signal = str(uuid4())
        with time_machine.travel(_at(9), tick=False):
            legacy_report = _make_report(self.team) if existing_work == "report" else None
            if existing_work == "signal":
                self._generation(legacy_signal, 50_000, request_id="existing-signal")
        with time_machine.travel(_at(10), tick=False):
            if legacy_report is None:
                legacy_report = SignalReport.objects.create(team=self.team, triggering_signal_id=legacy_signal)
            _make_pr_run(self.team, legacy_report, created_at=_at(10))
            self._generation(legacy_signal, 100_000, request_id="existing-report")
            complete_signal_pipeline(team_id=self.team.id, signal_id=legacy_signal, report_id=str(legacy_report.id))
            signal_id = str(uuid4())
            self._generation(signal_id, 250_000, request_id="new-report")
            report = SignalReport.objects.create(
                team=self.team,
                status=SignalReport.Status.READY,
                triggering_signal_id=signal_id,
            )
            _make_pr_run(self.team, report, created_at=_at(10))
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id, report_id=str(report.id))
            finish_report_spend(team_id=self.team.id, signal_id=signal_id, report_id=str(report.id))
        expected = 35 if existing_work == "report" else 25
        assert self._day(10) == {self.team.id: expected}
        assert first_billable_pr_run(report.id, team_id=report.team_id) is None
        assert first_billable_pr_run(legacy_report.id, team_id=legacy_report.team_id) is None
        reports = SignalReport.objects.filter(id__in=[report.id, legacy_report.id])
        expected_refundable: set[str] = set()
        assert (
            set(first_billable_pr_run_at_by_report([report.id, legacy_report.id], team_id=self.team.id))
            == expected_refundable
        )
        with self.assertNumQueries(1):
            annotated = annotate_first_billable_pr_run_at(reports, organization_id=self.organization.id)
        assert {
            str(row.id) for row in annotated if row.__dict__["first_billable_pr_run_at"] is not None
        } == expected_refundable
        SignalReport.objects.filter(id=report.id).update(triggering_signal_id=legacy_signal)
        assert self._day(10) == {self.team.id: expected}
        assert first_billable_pr_run(report.id, team_id=report.team_id) is None

    def test_rounding_is_per_team_day_and_period_recounts_match_daily_reports(self) -> None:
        other_org = Organization.objects.create(
            name="Synthetic billing organization", usage={"signals_spend_credits": {"billing_start_date": "2026-06-10"}}
        )
        other_team = Team.objects.create(organization=other_org)
        with time_machine.travel(_at(10, 0), tick=False):
            for team in (self.team, other_team):
                for _ in range(2):
                    signal_id = str(uuid4())
                    self._generation(signal_id, 6_000, request_id=signal_id, team=team)
                    complete_signal_pipeline(team_id=team.id, signal_id=signal_id)
        with time_machine.travel(_at(10, 23), tick=False):
            signal_id = str(uuid4())
            self._generation(signal_id, 6_000, request_id=signal_id)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        with time_machine.travel(_at(11, 0), tick=False):
            signal_id = str(uuid4())
            self._generation(signal_id, 6_000, request_id=signal_id)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        with timezone.override("Pacific/Kiritimati"):
            assert self._day(10) == {self.team.id: 2, other_team.id: 1}
            assert self._day(10, organization_id=str(self.organization.id)) == {self.team.id: 2}
            assert dict(get_signals_spend_billing_credits_by_team(PERIOD_START, PERIOD_END, self.organization.id)) == {
                self.team.id: 3
            }
        other_org.usage = {"signals_spend_credits": {"billing_start_date": "2026-06-11"}}
        other_org.save(update_fields=["usage"])
        assert self._day(10) == {self.team.id: 2}
        assert self._day(10, organization_id=str(other_org.id)) == {}

    @parameterized.expand([("source",), ("report",)])
    def test_system_funded_work_keeps_spend_but_does_not_bill(self, exemption: str) -> None:
        signal_id = str(uuid4())
        with time_machine.travel(_at(10), tick=False):
            self._generation(signal_id, 100_000)
            report = None
            if exemption == "report":
                report = SignalReport.objects.create(
                    team=self.team,
                    status=SignalReport.Status.READY,
                    billing_exempt_reason=SignalReport.BillingExemptReason.POSTHOG_SYSTEM,
                )
            complete_signal_pipeline(
                team_id=self.team.id,
                signal_id=signal_id,
                report_id=str(report.id) if report else None,
                billing_exempt=exemption == "source",
            )
        assert self._day(10) == {}
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.spend == 10
        self.assertIsNotNone(spend.finalized_at)

    @parameterized.expand([("trial", True), ("unknown", None)])
    def test_trial_flag_does_not_change_billing_meter(self, _name: str, trial: bool | None) -> None:
        self.trial_mock.return_value = trial
        signal_id = str(uuid4())
        with time_machine.travel(_at(10), tick=False):
            report = _make_report(self.team)
            _make_pr_run(self.team, report, created_at=_at(10))
            self._generation(signal_id, 100_000)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id, report_id=str(report.id))
        assert self._day(10) == ({} if trial is True else {self.team.id: 10})

    def test_ending_trial_does_not_bill_its_settled_spend(self) -> None:
        signal_id = str(uuid4())
        with time_machine.travel(_at(10), tick=False):
            self.trial_mock.return_value = True
            self._generation(signal_id, 100_000)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        self.trial_mock.return_value = False
        assert self._day(10) == {}
        assert SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id).billing_exempt

    def test_scout_deletion_preserves_recognized_billing(self) -> None:
        task = _task_model().objects.create(team=self.team, title="Synthetic scout", description="")
        run = _task_run_model().objects.create(team=self.team, task=task)
        scout = SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team, task_run=run, skill_name="synthetic-scout", skill_version=1
        )
        SignalSpend.objects.for_team(self.team.id).create(
            team=self.team,
            scout_run=scout,
            task_run_id=run.id,
            kind=SignalSpend.Kind.SCOUT_RUN,
            finalized_at=_at(10),
            spend=4,
        )
        scout.delete()
        assert self._day(10) == {self.team.id: 4}

    def test_finalized_spend_ignores_subsequent_source_changes(self) -> None:
        signal_id = str(uuid4())
        with time_machine.travel(_at(10), tick=False):
            self._generation(signal_id, 100_000)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        with time_machine.travel(_at(11), tick=False):
            with self.assertRaises(ValueError):
                self._generation(signal_id, 90_000)
            complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert not spend.accounting_failed
        self.assertIsNotNone(spend.finalized_at)
        assert spend.spend == 10
        assert self._day(10) == {self.team.id: 10}
        assert self._day(11) == {}
