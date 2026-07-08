import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.signals.backend.billing import SIGNALS_CREDITS_PER_REPORT_WITH_PR
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportRefund
from products.signals.backend.tasks import (
    _REFUND_SYNC_MAX_RETRIES,
    sync_pending_signals_refund_credits,
    sync_signals_refund_credit,
)
from products.signals.backend.test.test_billing import _make_pr_run, _make_report

_PERIOD = ["2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"]
_NOW = "2026-06-15T12:00:00Z"


def _make_refund(
    report: SignalReport,
    *,
    billing_path: str = SignalReportRefund.BillingPath.CREDITED,
    pr_run_created_at: datetime | None = None,
) -> SignalReportRefund:
    return SignalReportRefund.objects.create(
        team=report.team,
        report=report,
        reason=SignalReportRefund.Reason.PR_INCORRECT,
        billing_path=billing_path,
        credits=SIGNALS_CREDITS_PER_REPORT_WITH_PR,
        pr_url="https://github.com/x/y/pull/1",
        pr_run_created_at=pr_run_created_at or datetime(2026, 6, 10, tzinfo=UTC),
    )


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestSignalReportRefundAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.usage = {"period": _PERIOD}
        self.organization.save()

    def _refund_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/refund/"

    def _state_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/state/"

    def _report_with_pr(
        self, *, pr_created_at: datetime, report_status: str = SignalReport.Status.READY
    ) -> SignalReport:
        report = _make_report(self.team, status=report_status)
        _make_pr_run(self.team, report, created_at=pr_created_at)
        return report

    def _refund(self, report: SignalReport, body: dict | None = None):
        return self.client.post(self._refund_url(str(report.id)), body or {"reason": "pr_not_useful"}, format="json")

    @freeze_time(_NOW)
    def test_refund_earlier_in_period_goes_credited_and_archives(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, 9, 30, tzinfo=UTC))
        response = self._refund(report, {"reason": "pr_incorrect", "note": "does not fix the bug"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["billing_path"] == "credited"
        assert body["credits"] == 1500
        assert body["reason"] == "pr_incorrect"
        assert body["pr_url"] == "https://github.com/x/y/pull/1"
        assert body["already_refunded"] is False
        assert body["billing_synced"] is False
        assert body["credit_amount_usd"] is None

        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        refund = report.refund
        assert refund.billing_path == SignalReportRefund.BillingPath.CREDITED
        assert refund.pr_run_created_at == datetime(2026, 6, 10, 9, 30, tzinfo=UTC)
        assert refund.created_by_id == self.user.id
        assert refund.note == "does not fix the bug"

        dismissal = SignalReportArtefact.objects.get(report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL)
        content = json.loads(dismissal.content)
        assert content["reason"] == "refunded"
        assert content["note"] == "does not fix the bug"

    @freeze_time(_NOW)
    def test_refund_on_pr_run_day_goes_excluded(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 15, 8, 0, tzinfo=UTC))
        response = self._refund(report)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["billing_path"] == "excluded"

    @freeze_time("2026-06-15T00:30:00Z")
    def test_refund_just_after_utc_midnight_goes_credited(self, _flag):
        # The path rule is the PR run's UTC day, not "before the 03:45 send" — a 23:50 PR refunded
        # at 00:30 must go credited even though the usage report hasn't shipped yet.
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 14, 23, 50, tzinfo=UTC))
        response = self._refund(report)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["billing_path"] == "credited"

    @freeze_time(_NOW)
    def test_refund_without_billable_pr_is_rejected(self, _flag):
        report = _make_report(self.team)
        response = self._refund(report)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "no billable implementation PR" in response.json()["error"]

    @freeze_time(_NOW)
    def test_refund_for_previous_period_pr_is_rejected(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 5, 20, tzinfo=UTC))
        response = self._refund(report)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "previous billing period" in response.json()["error"]

    @parameterized.expand(
        [
            ("pr_in_current_month", datetime(2026, 6, 10, tzinfo=UTC), status.HTTP_200_OK),
            ("pr_in_previous_month", datetime(2026, 5, 20, tzinfo=UTC), status.HTTP_400_BAD_REQUEST),
        ]
    )
    @freeze_time(_NOW)
    def test_missing_billing_period_falls_back_to_calendar_month(self, _name, pr_created_at, expected_status, _flag):
        self.organization.usage = None
        self.organization.save()
        report = self._report_with_pr(pr_created_at=pr_created_at)
        response = self._refund(report)
        assert response.status_code == expected_status

    @freeze_time(_NOW)
    def test_refund_on_exempt_report_is_rejected(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        SignalReport.objects.filter(id=report.id).update(
            billing_exempt_reason=SignalReport.BillingExemptReason.POSTHOG_HEALTH_CHECK
        )
        response = self._refund(report)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "never-billable" in response.json()["error"]

    @freeze_time(_NOW)
    def test_second_refund_is_idempotent(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        first = self._refund(report, {"reason": "pr_incorrect"})
        second = self._refund(report, {"reason": "duplicate"})

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["already_refunded"] is True
        # The original refund is returned unchanged — the second reason never sticks.
        assert second.json()["reason"] == "pr_incorrect"
        assert second.json()["id"] == first.json()["id"]
        assert SignalReportRefund.objects.filter(report=report).count() == 1

    @freeze_time(_NOW)
    def test_refund_reaches_already_archived_report(self, _flag):
        # An archived-but-charged report must still be refundable (suppressed reports are hidden
        # from most by-id actions); it stays suppressed.
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        report.transition_to(SignalReport.Status.SUPPRESSED)
        report.save()
        response = self._refund(report)
        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED

    @freeze_time(_NOW)
    def test_refund_keeps_resolved_report_resolved(self, _flag):
        report = self._report_with_pr(
            pr_created_at=datetime(2026, 6, 10, tzinfo=UTC), report_status=SignalReport.Status.RESOLVED
        )
        response = self._refund(report)
        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assert report.status == SignalReport.Status.RESOLVED
        # The permanent marker still lands even though the status did not change.
        assert SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL
        ).exists()

    @freeze_time(_NOW)
    def test_invalid_reason_is_rejected(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        response = self._refund(report, {"reason": "because"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportRefund.objects.filter(report=report).exists()

    @freeze_time(_NOW)
    def test_credited_refund_enqueues_billing_sync_on_commit(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        with patch("products.signals.backend.views.sync_signals_refund_credit.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self._refund(report)
        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_called_once_with(str(report.refund.id))

    @freeze_time(_NOW)
    def test_excluded_refund_never_calls_billing(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 15, 8, 0, tzinfo=UTC))
        with patch("products.signals.backend.views.sync_signals_refund_credit.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self._refund(report)
        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_not_called()

    @freeze_time(_NOW)
    def test_refund_fires_analytics_event(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        with patch("products.signals.backend.views.report_user_action") as mock_report:
            self._refund(report)
        mock_report.assert_called_once()
        assert mock_report.call_args.args[1] == "signals_pr_refund_created"
        properties = mock_report.call_args.kwargs["properties"]
        assert properties["billing_path"] == "credited"
        assert properties["credits"] == 1500
        assert properties["pr_merged"] is False
        assert properties["days_since_pr"] == 5

    @freeze_time(_NOW)
    def test_restore_of_refunded_report_is_blocked(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        assert self._refund(report).status_code == status.HTTP_200_OK

        response = self.client.post(self._state_url(str(report.id)), {"state": "potential"}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error"] == "Refunded reports can't be restored."
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED

    @freeze_time(_NOW)
    def test_bulk_restore_of_refunded_report_is_blocked(self, _flag):
        refunded = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        assert self._refund(refunded).status_code == status.HTTP_200_OK
        archived = _make_report(self.team)
        archived.transition_to(SignalReport.Status.SUPPRESSED)
        archived.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/reports/bulk-state/",
            {"ids": [str(refunded.id), str(archived.id)], "state": "potential"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        results = {r["id"]: r for r in response.json()["results"]}
        assert results[str(refunded.id)]["outcome"] == "skipped"
        assert results[str(refunded.id)]["detail"] == "Refunded reports can't be restored."
        assert results[str(archived.id)]["outcome"] == "transitioned"
        refunded.refresh_from_db()
        assert refunded.status == SignalReport.Status.SUPPRESSED

    @freeze_time(_NOW)
    def test_report_response_includes_refund_and_exemption_fields(self, _flag):
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        self._refund(report)
        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["refund"]["billing_path"] == "credited"
        assert body["refund"]["reason"] == "pr_not_useful"
        assert body["billing_exempt_reason"] is None

    @freeze_time(_NOW)
    def test_refund_summary_aggregates_credited_refunds_org_wide(self, _flag):
        # Two teams in the org contribute; excluded-path, out-of-period, and foreign-org refunds don't.
        report_a = self._report_with_pr(pr_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        _make_refund(report_a, pr_run_created_at=datetime(2026, 6, 10, tzinfo=UTC))
        sibling_team = Team.objects.create(organization=self.organization, name="sibling")
        report_b = _make_report(sibling_team)
        _make_refund(report_b, pr_run_created_at=datetime(2026, 6, 12, tzinfo=UTC))
        excluded = _make_report(self.team)
        _make_refund(
            excluded,
            billing_path=SignalReportRefund.BillingPath.EXCLUDED,
            pr_run_created_at=datetime(2026, 6, 13, tzinfo=UTC),
        )
        out_of_period = _make_report(self.team)
        _make_refund(out_of_period, pr_run_created_at=datetime(2026, 5, 20, tzinfo=UTC))
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        foreign = _make_report(other_team)
        _make_pr_run(other_team, foreign, created_at=datetime(2026, 6, 14, tzinfo=UTC))
        _make_refund(foreign, pr_run_created_at=datetime(2026, 6, 14, tzinfo=UTC))

        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/refund-summary/")
        assert response.status_code == status.HTTP_200_OK
        # period_billable_credits: only report_a has a billable PR run in this org (credited
        # refunds stay counted — usage is truthful); the foreign org's billable PR must not leak in.
        assert response.json() == {
            "credited_refund_count": 2,
            "credited_credits": 3000,
            "period_billable_credits": 1500,
        }

    @freeze_time(_NOW)
    def test_refund_summary_counts_unreported_prs_live_until_excluded_refund(self, _flag):
        # A PR created today hasn't shipped to billing yet but must count in the live number,
        # and a same-day (excluded-path) refund must visibly un-count it.
        report = self._report_with_pr(pr_created_at=datetime(2026, 6, 15, 8, 0, tzinfo=UTC))
        url = f"/api/projects/{self.team.id}/signals/reports/refund-summary/"

        assert self.client.get(url).json()["period_billable_credits"] == 1500
        assert self._refund(report).json()["billing_path"] == "excluded"
        assert self.client.get(url).json()["period_billable_credits"] == 0


class TestSignalReportRefundFlagGate(APIBaseTest):
    @parameterized.expand([("refund",), ("refund_summary",)])
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_endpoints_unavailable_with_flag_off(self, action_path, _flag):
        report = _make_report(self.team)
        if action_path == "refund":
            url = f"/api/projects/{self.team.id}/signals/reports/{report.id}/refund/"
            response = self.client.post(url, {"reason": "other"}, format="json")
        else:
            url = f"/api/projects/{self.team.id}/signals/reports/refund-summary/"
            response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not SignalReportRefund.objects.filter(report=report).exists()


class TestSyncSignalsRefundCredit(BaseTest):
    def _credited_refund(self) -> SignalReportRefund:
        report = _make_report(self.team)
        return _make_refund(report)

    def test_success_records_credit_and_contract_payload(self):
        self.organization.usage = {"period": _PERIOD}
        self.organization.save()
        refund = self._credited_refund()
        with patch(
            "ee.billing.billing_manager.BillingManager.dispute_signals_pr",
            return_value={"credit_amount_usd": "15.00", "credit_id": "c1", "already_processed": False},
        ) as mock_dispute:
            sync_signals_refund_credit(str(refund.id))

        refund.refresh_from_db()
        assert refund.credit_amount_usd == Decimal("15.00")
        assert refund.billing_synced_at is not None
        assert refund.billing_sync_error is None

        organization, payload = mock_dispute.call_args.args
        assert organization.id == self.organization.id
        # The frozen cross-repo contract shape — billing keys idempotency on refund_id and
        # re-checks period membership from metadata.pr_run_created_at.
        assert payload == {
            "refund_id": str(refund.id),
            "credits": 1500,
            "metadata": {
                "team_id": self.team.id,
                "report_id": str(refund.report_id),
                "pr_url": "https://github.com/x/y/pull/1",
                "pr_run_created_at": "2026-06-10T00:00:00+00:00",
                "period_start": "2026-06-01T00:00:00+00:00",
                "period_end": "2026-07-01T00:00:00+00:00",
            },
        }

    def test_zero_credit_outcome_still_marks_synced(self):
        # "0.00" is a legitimate business outcome (free tier / free plan) — the row must complete.
        refund = self._credited_refund()
        with patch(
            "ee.billing.billing_manager.BillingManager.dispute_signals_pr",
            return_value={"credit_amount_usd": "0.00", "credit_id": "c1", "already_processed": False},
        ):
            sync_signals_refund_credit(str(refund.id))
        refund.refresh_from_db()
        assert refund.credit_amount_usd == Decimal("0.00")
        assert refund.billing_synced_at is not None

    def test_already_synced_refund_is_not_resent(self):
        refund = self._credited_refund()
        refund.billing_synced_at = timezone.now()
        refund.save(update_fields=["billing_synced_at"])
        with patch("ee.billing.billing_manager.BillingManager.dispute_signals_pr") as mock_dispute:
            sync_signals_refund_credit(str(refund.id))
        mock_dispute.assert_not_called()

    def test_delivery_losing_the_sync_race_does_not_rerecord_or_emit(self):
        # The on-commit enqueue and the hourly sweeper can both deliver the same refund; if a
        # concurrent delivery commits the sync while this one's billing call is in flight, this
        # one must not overwrite the row or emit a second issued event.
        refund = self._credited_refund()
        concurrent_synced_at = timezone.now()

        def _concurrent_delivery_wins(*args, **kwargs):
            SignalReportRefund.objects.filter(id=refund.id).update(
                credit_amount_usd=Decimal("15.00"), billing_synced_at=concurrent_synced_at
            )
            return {"credit_amount_usd": "15.00", "credit_id": "c1", "already_processed": True}

        with patch(
            "ee.billing.billing_manager.BillingManager.dispute_signals_pr", side_effect=_concurrent_delivery_wins
        ):
            with patch("products.signals.backend.tasks.ph_scoped_capture") as mock_capture_cm:
                sync_signals_refund_credit(str(refund.id))

        refund.refresh_from_db()
        assert refund.billing_synced_at == concurrent_synced_at
        mock_capture_cm.assert_not_called()

    def test_excluded_refund_never_calls_billing(self):
        report = _make_report(self.team)
        refund = _make_refund(report, billing_path=SignalReportRefund.BillingPath.EXCLUDED)
        with patch("ee.billing.billing_manager.BillingManager.dispute_signals_pr") as mock_dispute:
            sync_signals_refund_credit(str(refund.id))
        mock_dispute.assert_not_called()

    def test_failure_before_retry_exhaustion_does_not_record_terminal_error(self):
        refund = self._credited_refund()
        with patch(
            "ee.billing.billing_manager.BillingManager.dispute_signals_pr", side_effect=ValueError("billing down")
        ):
            with self.assertRaises(Exception):
                sync_signals_refund_credit(str(refund.id))
        refund.refresh_from_db()
        assert refund.billing_synced_at is None
        assert refund.billing_sync_error is None

    def test_exhausted_retries_record_terminal_error_and_event(self):
        refund = self._credited_refund()
        task = sync_signals_refund_credit
        with patch(
            "ee.billing.billing_manager.BillingManager.dispute_signals_pr", side_effect=ValueError("billing down")
        ):
            with patch("products.signals.backend.tasks.ph_scoped_capture") as mock_capture_cm:
                mock_capture = mock_capture_cm.return_value.__enter__.return_value
                task.push_request(retries=_REFUND_SYNC_MAX_RETRIES)
                try:
                    task.run(str(refund.id))
                finally:
                    task.pop_request()
        refund.refresh_from_db()
        assert refund.billing_synced_at is None
        assert "billing down" in (refund.billing_sync_error or "")
        assert mock_capture.call_args.kwargs["event"] == "signals_pr_refund_credit_failed"

    def test_sweeper_reenqueues_only_stale_unsynced_credited_rows(self):
        pending = self._credited_refund()
        synced = self._credited_refund()
        synced.billing_synced_at = timezone.now()
        synced.save(update_fields=["billing_synced_at"])
        _make_refund(_make_report(self.team), billing_path=SignalReportRefund.BillingPath.EXCLUDED)
        ancient = self._credited_refund()
        SignalReportRefund.objects.filter(id=ancient.id).update(created_at=timezone.now() - timedelta(days=8))

        with patch("products.signals.backend.tasks.sync_signals_refund_credit.delay") as mock_delay:
            sync_pending_signals_refund_credits()

        mock_delay.assert_called_once_with(str(pending.id))


class TestExemptSignalReportBillingCommand(BaseTest):
    def test_marks_report_exempt(self):
        report = _make_report(self.team)
        call_command("exempt_signal_report_billing", str(self.team.id), str(report.id), "posthog_system")
        report.refresh_from_db()
        assert report.billing_exempt_reason == SignalReport.BillingExemptReason.POSTHOG_SYSTEM

    def test_refuses_once_billable_pr_run_exists(self):
        report = _make_report(self.team)
        _make_pr_run(self.team, report, created_at=datetime(2026, 6, 10, tzinfo=UTC))
        with self.assertRaises(CommandError) as ctx:
            call_command("exempt_signal_report_billing", str(self.team.id), str(report.id), "posthog_system")
        assert "use a refund" in str(ctx.exception)
        report.refresh_from_db()
        assert report.billing_exempt_reason is None
