import json

import pytest
from unittest.mock import patch

from django.apps import apps

from asgiref.sync import async_to_sync

from products.signals.backend.quota import SelfDrivingQuotaGate
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.enforce_self_driving_quota import (
    SELF_DRIVING_QUOTA_CANCELLED,
    SELF_DRIVING_QUOTA_PROCEED,
    SELF_DRIVING_QUOTA_STOP_CHECKING,
    EnforceSelfDrivingRunQuotaInput,
    enforce_self_driving_run_quota,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.enforce_self_driving_quota"


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
    def test_non_self_driving_origin_stops_checking_without_gating(self, activity_environment, test_task_run):
        # The gate must never touch user or AI tasks: a wrong-origin run exits before any quota read.
        with patch(f"{MODULE}.self_driving_quota_gate") as gate_mock:
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_STOP_CHECKING
        gate_mock.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_run_with_pr_url_stops_checking_even_when_over_quota(self, activity_environment, test_task, test_task_run):
        # A shipped PR means the report is already billed; cancelling would kill paid work.
        _make_self_driving_run(test_task, test_task_run)
        test_task_run.output = {"pr_url": "https://github.com/x/y/pull/1"}
        test_task_run.save(update_fields=["output"])
        with patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=True)):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_STOP_CHECKING
        test_task_run.refresh_from_db()
        assert test_task_run.status == TaskRun.Status.IN_PROGRESS

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        ("gate", "expected"),
        [
            (SelfDrivingQuotaGate(limited=False, enforced=False), SELF_DRIVING_QUOTA_PROCEED),
            # Dark launch: limited but not enforced must never cancel.
            (SelfDrivingQuotaGate(limited=True, enforced=False), SELF_DRIVING_QUOTA_PROCEED),
        ],
    )
    def test_under_quota_or_dark_launch_proceeds(self, activity_environment, test_task, test_task_run, gate, expected):
        _make_self_driving_run(test_task, test_task_run)
        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=gate),
            patch(f"{MODULE}.capture_signal_report_quota_paused"),
        ):
            assert _run_activity(activity_environment, test_task_run) == expected
        test_task_run.refresh_from_db()
        assert test_task_run.status == TaskRun.Status.IN_PROGRESS

    @pytest.mark.django_db(transaction=True)
    def test_dark_launch_telemetry_emits_once_per_run_not_per_recheck(
        self, activity_environment, test_task, test_task_run
    ):
        # The 5-minute recheck would otherwise emit a would-block event per tick for the run's whole
        # lifetime, corrupting the measurement the dark launch exists to produce.
        _make_self_driving_run(test_task, test_task_run)
        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=False)),
            patch(f"{MODULE}.capture_signal_report_quota_paused") as capture_mock,
        ):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_PROCEED
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_PROCEED
        assert capture_mock.call_count == 1

    @pytest.mark.django_db(transaction=True)
    def test_already_terminal_cancel_outcome_never_releases_the_report(
        self, activity_environment, test_task, test_task_run
    ):
        # The un-billing race: the run finished (possibly shipping its PR) between the activity's
        # snapshot and the cancel. Releasing would delete the SignalReportTask row the billing
        # usage query counts that PR through.
        report = _make_self_driving_run(test_task, test_task_run)
        from products.signals.backend.task_run_artefacts import record_implementation_task

        record_implementation_task(team_id=test_task.team_id, report_id=str(report.id), task_id=str(test_task.id))
        SignalReportTask = apps.get_model("signals", "SignalReportTask")
        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=True)),
            patch(f"{MODULE}.capture_signal_report_quota_paused"),
            patch(
                "products.tasks.backend.facade.cancellation.cancel_task_run",
                return_value=("already_terminal", None),
            ),
        ):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_STOP_CHECKING
        assert SignalReportTask.objects.filter(task_id=test_task.id).exists()

    @pytest.mark.django_db(transaction=True)
    def test_pr_landing_during_cancel_keeps_billing_records(self, activity_environment, test_task, test_task_run):
        # The agent can report its PR while the cancel interrupt is in flight: the report is then
        # billed, so its records must survive even though the run ends cancelled.
        report = _make_self_driving_run(test_task, test_task_run)
        from products.signals.backend.task_run_artefacts import record_implementation_task

        record_implementation_task(team_id=test_task.team_id, report_id=str(report.id), task_id=str(test_task.id))
        SignalReportTask = apps.get_model("signals", "SignalReportTask")

        def _cancel_and_land_pr(*args, **kwargs):
            TaskRun.objects.filter(id=test_task_run.id).update(output={"pr_url": "https://github.com/x/y/pull/2"})
            return ("accepted", None)

        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=True)),
            patch(f"{MODULE}.capture_signal_report_quota_paused"),
            patch("products.tasks.backend.facade.cancellation.cancel_task_run", side_effect=_cancel_and_land_pr),
        ):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_CANCELLED
        assert SignalReportTask.objects.filter(task_id=test_task.id).exists()

    @pytest.mark.django_db(transaction=True)
    def test_non_github_pr_url_does_not_grant_enforcement_immunity(
        self, activity_environment, test_task, test_task_run
    ):
        # Run output is caller-writable and only GitHub PR URLs are billable, so a forged
        # non-GitHub value must neither stop the rechecks nor keep the report's records
        # after the cancel.
        report = _make_self_driving_run(test_task, test_task_run)
        from products.signals.backend.task_run_artefacts import record_implementation_task

        record_implementation_task(team_id=test_task.team_id, report_id=str(report.id), task_id=str(test_task.id))
        test_task_run.output = {"pr_url": "https://example.com/not-github/pull/1"}
        test_task_run.save(update_fields=["output"])
        SignalReportTask = apps.get_model("signals", "SignalReportTask")
        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=True)),
            patch(f"{MODULE}.capture_signal_report_quota_paused"),
            patch("products.tasks.backend.facade.cancellation.cancel_task_run", return_value=("accepted", None)),
        ):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_CANCELLED
        assert not SignalReportTask.objects.filter(task_id=test_task.id).exists()

    @pytest.mark.django_db(transaction=True)
    def test_release_failure_still_reports_cancelled(self, activity_environment, test_task, test_task_run):
        # The cancel is irreversible: a release failure must not tell the workflow to proceed as if
        # the run were healthy.
        _make_self_driving_run(test_task, test_task_run)
        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=True)),
            patch(f"{MODULE}.capture_signal_report_quota_paused"),
            patch("products.tasks.backend.facade.cancellation.cancel_task_run", return_value=("accepted", None)),
            patch(
                "products.signals.backend.task_run_artefacts.release_quota_cancelled_implementation",
                side_effect=RuntimeError("db down"),
            ),
        ):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_CANCELLED

    @pytest.mark.django_db(transaction=True)
    def test_enforced_over_quota_cancels_run_and_releases_report(self, activity_environment, test_task, test_task_run):
        # The core money path: a PR-less self-driving run on an enforced over-quota team is cancelled
        # and its report is released so a later cycle can re-implement it.
        report = _make_self_driving_run(test_task, test_task_run)
        from products.signals.backend.task_run_artefacts import record_implementation_task

        record_implementation_task(
            team_id=test_task.team_id,
            report_id=str(report.id),
            task_id=str(test_task.id),
            run_id=str(test_task_run.id),
        )
        SignalReportTask = apps.get_model("signals", "SignalReportTask")
        SignalReportArtefact = apps.get_model("signals", "SignalReportArtefact")

        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=True)),
            patch(f"{MODULE}.capture_signal_report_quota_paused") as capture_mock,
            patch(
                "products.tasks.backend.facade.cancellation.cancel_task_run", return_value=("accepted", None)
            ) as cancel_mock,
        ):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_CANCELLED

        assert cancel_mock.call_count == 1
        assert cancel_mock.call_args.kwargs["source"] == "self_driving_quota"
        assert not SignalReportTask.objects.filter(task_id=test_task.id).exists()
        notes = [
            a
            for a in SignalReportArtefact.objects.filter(report_id=report.id, type="note")
            if "pull request limit" in json.loads(a.content)["note"]
        ]
        assert len(notes) == 1
        assert capture_mock.call_args.kwargs["stage"] == "implementation_run"
        assert capture_mock.call_args.kwargs["enforced"] is True

    @pytest.mark.django_db(transaction=True)
    def test_fails_open_when_gate_errors(self, activity_environment, test_task, test_task_run):
        # A quota-infra blip must never kill a healthy run.
        _make_self_driving_run(test_task, test_task_run)
        with patch(f"{MODULE}.self_driving_quota_gate", side_effect=RuntimeError("redis down")):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_PROCEED
        test_task_run.refresh_from_db()
        assert test_task_run.status == TaskRun.Status.IN_PROGRESS

    @pytest.mark.django_db(transaction=True)
    def test_cancel_failure_is_not_misclassified_as_fail_open(self, activity_environment, test_task, test_task_run):
        # A cancel that dies part-way may have already delivered the completion signal, so it is
        # not a benign quota-check blip: it must not feed the fail-open counter, and nothing may
        # be released while the run could still be alive — the next recheck retries the cancel.
        report = _make_self_driving_run(test_task, test_task_run)
        from products.signals.backend.task_run_artefacts import record_implementation_task

        record_implementation_task(team_id=test_task.team_id, report_id=str(report.id), task_id=str(test_task.id))
        SignalReportTask = apps.get_model("signals", "SignalReportTask")
        with (
            patch(f"{MODULE}.self_driving_quota_gate", return_value=SelfDrivingQuotaGate(limited=True, enforced=True)),
            patch(f"{MODULE}.capture_signal_report_quota_paused"),
            patch(
                "products.tasks.backend.facade.cancellation.cancel_task_run",
                side_effect=RuntimeError("signal round-trip died"),
            ),
            patch(f"{MODULE}.record_quota_check_failed_open") as failed_open_mock,
        ):
            assert _run_activity(activity_environment, test_task_run) == SELF_DRIVING_QUOTA_PROCEED
        failed_open_mock.assert_not_called()
        assert SignalReportTask.objects.filter(task_id=test_task.id).exists()
