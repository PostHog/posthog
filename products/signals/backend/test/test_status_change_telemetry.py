import json
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.models import SignalReport, SignalReportArtefact


class TestCaptureStatusChangeAnalytics(BaseTest):
    """The post_save receiver is the server-side label stream for the inbox ranking model:
    it must fire exactly once per real status transition, from any surface, and never on
    creations or unrelated edits."""

    def _create_report(self, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
            signal_count=3,
            total_weight=2.5,
        )

    @parameterized.expand(
        [
            ("dismiss", SignalReport.Status.READY, SignalReport.Status.SUPPRESSED, {}),
            ("resolve_on_pr_merge", SignalReport.Status.READY, SignalReport.Status.RESOLVED, {}),
            ("snooze", SignalReport.Status.READY, SignalReport.Status.POTENTIAL, {"snooze_for": 5}),
        ]
    )
    def test_transition_emits_label_event_with_previous_and_new_status(
        self, _name, source_status, new_status, transition_kwargs
    ):
        report = self._create_report(report_status=source_status)
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(new_status, **transition_kwargs)
                report.save(update_fields=updated)
        assert mock_capture.call_count == 1
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["event"] == "signal_report_status_changed"
        assert kwargs["distinct_id"] == str(self.team.uuid)
        assert kwargs["properties"]["report_id"] == str(report.id)
        assert kwargs["properties"]["previous_status"] == source_status
        assert kwargs["properties"]["status"] == new_status
        assert kwargs["properties"]["signal_count"] == 3
        assert kwargs["properties"]["total_weight"] == 2.5

    @parameterized.expand(
        [
            ("dismissal_includes_fresh_reason", SignalReport.Status.SUPPRESSED, False, "wontfix_irrelevant"),
            # Dismissal artefacts are append-only, so an old reason must not leak onto later
            # non-dismissal transitions (e.g. a restored report getting resolved)...
            ("non_dismissal_excludes_reason", SignalReport.Status.RESOLVED, False, None),
            # ...nor onto a later feedback-less dismissal (the state API only writes a new
            # dismissal artefact when the user actually gave a reason or note).
            ("stale_reason_excluded_from_new_dismissal", SignalReport.Status.SUPPRESSED, True, None),
        ]
    )
    def test_label_snapshots_latest_classification_artefacts(
        self, _name, new_status, backdate_dismissal, expected_dismissal_reason
    ):
        report = self._create_report()
        for artefact_type, content in [
            (SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT, {"priority": "P1"}),
            (SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT, {"actionability": "immediately_actionable"}),
            (SignalReportArtefact.ArtefactType.DISMISSAL, {"reason": "wontfix_irrelevant"}),
        ]:
            SignalReportArtefact.objects.create(
                team=self.team, report=report, type=artefact_type, content=json.dumps(content)
            )
        if backdate_dismissal:
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL).update(
                created_at=timezone.now() - timedelta(hours=1)
            )
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(new_status)
                report.save(update_fields=updated)
        props = mock_capture.call_args.kwargs["properties"]
        assert props["priority"] == "P1"
        assert props["actionability"] == "immediately_actionable"
        assert props["dismissal_reason"] == expected_dismissal_reason

    def test_transient_intermediate_transition_in_one_transaction_is_collapsed(self):
        report = self._create_report(report_status=SignalReport.Status.IN_PROGRESS)
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    report.save(update_fields=report.transition_to(SignalReport.Status.READY, title="t", summary="s"))
                    report.save(update_fields=report.transition_to(SignalReport.Status.CANDIDATE))
        assert mock_capture.call_count == 1
        props = mock_capture.call_args.kwargs["properties"]
        # The committed transition, not a phantom hop through the never-committed READY state.
        assert props["previous_status"] == SignalReport.Status.IN_PROGRESS
        assert props["status"] == SignalReport.Status.CANDIDATE

    @parameterized.expand(
        [
            ("full_save_without_status_change", SignalReport.Status.READY, None),
            ("update_fields_without_status", SignalReport.Status.READY, ["title"]),
        ]
    )
    def test_non_transition_save_does_not_emit(self, _name, report_status, update_fields):
        report = self._create_report(report_status=report_status)
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                report.title = "edited"
                report.save(update_fields=update_fields)
        mock_capture.assert_not_called()

    def test_report_creation_does_not_emit(self):
        with patch("products.signals.backend.receivers.posthoganalytics.capture") as mock_capture:
            with self.captureOnCommitCallbacks(execute=True):
                self._create_report()
        mock_capture.assert_not_called()
