import pytest
import time_machine
from unittest.mock import patch

from django.apps import apps

from asgiref.sync import async_to_sync

from posthog.exceptions import QuotaLimitExceeded
from posthog.usage_counters import UsageCounter, UsageCounterService
from posthog.utils import get_current_day

from products.signals.backend.spend import record_task_cost_delta
from products.tasks.backend.facade.api import enforce_self_driving_pr_quota
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.enforce_self_driving_quota import (
    SELF_DRIVING_QUOTA_STOP_CHECKING,
    EnforceSelfDrivingRunQuotaInput,
    enforce_self_driving_run_quota,
)

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    remove_limited_team_tokens,
    update_org_billing_quotas,
)


def _run_activity(activity_environment, run: TaskRun) -> str:
    return async_to_sync(activity_environment.run)(
        enforce_self_driving_run_quota,
        EnforceSelfDrivingRunQuotaInput(run_id=str(run.id), task_id=str(run.task_id), team_id=run.team_id),
    )


def _make_self_driving_run(test_task, test_task_run):
    SignalReport = apps.get_model("signals", "SignalReport")
    report = SignalReport.objects.create(team=test_task.team, status=SignalReport.Status.READY, title="t", summary="s")
    test_task.origin_product = Task.OriginProduct.SIGNAL_REPORT
    test_task.signal_report_id = report.id
    test_task.save(update_fields=["origin_product", "signal_report_id"])
    test_task_run.status = TaskRun.Status.IN_PROGRESS
    test_task_run.save(update_fields=["status"])
    return report


@pytest.mark.requires_secrets
class TestEnforceSelfDrivingRunQuotaActivity:
    @pytest.mark.django_db(transaction=True)
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_running_spend_blocks_new_work_but_allows_accepted_work_to_finish(
        self, activity_environment, test_task, test_task_run
    ) -> None:
        report = _make_self_driving_run(test_task, test_task_run)
        organization = test_task.team.organization
        organization.usage = {
            "signals_spend_credits": {"usage": 90, "limit": 100, "billing_start_date": "2026-06-10"},
            "period": ["2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"],
        }
        organization.customer_trust_scores = {}
        organization.save()
        spend = (
            apps.get_model("signals", "SignalSpend")
            .objects.for_team(test_task.team_id)
            .create(
                team_id=test_task.team_id,
                report=report,
                task_run_id=test_task_run.id,
                kind="reviewer_triggered_implementation",
                usage_billing=True,
            )
        )
        record_task_cost_delta(team_id=test_task.team_id, run_id=test_task_run.id, cost_delta_microusd=200_000)
        period = get_current_day()
        counters = UsageCounterService()
        assert counters.get_legacy(UsageCounter.SIGNALS_SPEND_CREDITS, period.start, period.end) == []
        quota_counts = dict(
            counters.get_legacy(UsageCounter.SIGNALS_SPEND_CREDITS, period.start, period.end, caller="quota_limiting")
        )
        organization.usage["signals_spend_credits"]["todays_usage"] = quota_counts[test_task.team_id]
        organization.save(update_fields=["usage"])
        try:
            update_org_billing_quotas(organization)
            organization.refresh_from_db()
            organization.usage["signals_spend_credits"].update(usage=0, todays_usage=0, limit=20)
            organization.save(update_fields=["usage"])
            update_org_billing_quotas(organization)
            with (
                patch("products.signals.backend.quota.self_driving_quota_enforcement_enabled", return_value=True),
                patch(
                    "products.tasks.backend.facade.cancellation.cancel_task_run", return_value=("accepted", None)
                ) as cancel,
            ):
                assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_STOP_CHECKING
                with pytest.raises(QuotaLimitExceeded, match="spending limit"):
                    enforce_self_driving_pr_quota(test_task.team)
            cancel.assert_not_called()
            test_task_run.refresh_from_db()
            assert test_task_run.status == TaskRun.Status.IN_PROGRESS
            spend.refresh_from_db()
            assert spend.finalized_at is None
        finally:
            remove_limited_team_tokens(
                QuotaResource.SIGNALS_SPEND_CREDITS,
                [test_task.team.api_token],
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            )

    @pytest.mark.django_db(transaction=True)
    def test_legacy_running_work_also_finishes(self, activity_environment, test_task, test_task_run) -> None:
        _make_self_driving_run(test_task, test_task_run)
        with patch("products.tasks.backend.facade.cancellation.cancel_task_run") as cancel:
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_STOP_CHECKING
        cancel.assert_not_called()
        test_task_run.refresh_from_db()
        assert test_task_run.status == TaskRun.Status.IN_PROGRESS

    @pytest.mark.django_db(transaction=True)
    def test_trial_costs_keep_refreshing_without_interrupting_work(
        self, activity_environment, test_task, test_task_run
    ) -> None:
        _make_self_driving_run(test_task, test_task_run)
        with patch("products.signals.backend.facade.trial.refresh_trial_run_spend", return_value=True) as check:
            assert _run_activity(activity_environment, test_task_run) == "proceed"
        check.assert_called_once_with(team_id=test_task.team_id, run_id=test_task_run.id)
