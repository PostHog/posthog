from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from products.signals.backend.models import SignalReport


class TestStampOrganizationUsesSelfDriving(BaseTest):
    def setUp(self):
        super().setUp()
        cache.delete(f"signals_uses_self_driving_stamped/{self.team.id}")

    def test_stamps_once_when_a_report_first_becomes_visible(self):
        with patch("products.signals.backend.receivers.posthoganalytics.group_identify") as mock_group_identify:
            with self.captureOnCommitCallbacks(execute=True):
                report = SignalReport.objects.create(
                    team=self.team,
                    status=SignalReport.Status.POTENTIAL,
                    title="Test report",
                    summary="Test summary",
                )
                report.save(update_fields=report.transition_to(SignalReport.Status.CANDIDATE))
                report.save(
                    update_fields=report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=3)
                )
            assert mock_group_identify.call_count == 0

            with self.captureOnCommitCallbacks(execute=True):
                report.save(
                    update_fields=report.transition_to(
                        SignalReport.Status.READY, title="Test report", summary="Test summary"
                    )
                )
            assert mock_group_identify.call_count == 1
            assert mock_group_identify.call_args.args == ("organization", str(self.team.organization_id))
            assert mock_group_identify.call_args.kwargs["properties"] == {"uses_self_driving": True}

            with self.captureOnCommitCallbacks(execute=True):
                report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))
            assert mock_group_identify.call_count == 1
