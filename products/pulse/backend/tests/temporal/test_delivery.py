from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import User
from posthog.models.scoping import team_scope

from products.notifications.backend.facade.enums import Priority, SourceType, TargetType
from products.pulse.backend.models import PulseDigest, PulseDigestStatus, PulseFinding
from products.pulse.backend.temporal.delivery import _dispatch_pulse_notifications, _persist_findings_sync
from products.pulse.backend.temporal.types import EnrichedFinding, MetricDescriptor

# Pulse consumes notifications only through the facade, so the fan-out is verified by what pulse asks
# the facade to do (create_notification / has_been_dispatched), not by reading notification rows.
NOTIFICATIONS_API = "products.notifications.backend.facade.api"


def _finding() -> EnrichedFinding:
    return EnrichedFinding(
        descriptor=MetricDescriptor(source="top_event", label="Signups", query={}),
        current_value=70.0,
        baseline_value=50.0,
        change_pct=0.4,
        impact=2.83,
        robust_z=3.5,
        narrative="Signups rose 40% this week.",
    )


class TestPulseNotificationFanout(BaseTest):
    def setUp(self):
        super().setUp()
        self.user2 = User.objects.create_and_join(self.organization, "second@test.com", "pw")
        now = timezone.now()
        with team_scope(self.team.id):
            self.digest = PulseDigest.objects.create(
                team=self.team,
                period_start=now - timezone.timedelta(days=7),
                period_end=now,
                status=PulseDigestStatus.GENERATING,
            )

    @patch(f"{NOTIFICATIONS_API}.has_been_dispatched", return_value=False)
    @patch(f"{NOTIFICATIONS_API}.create_notification")
    def test_dispatches_single_team_notification(self, mock_create, _mock_dispatched):
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding()])

        # One team-targeted notification; the facade resolves and fans out to the team's members.
        # The org has two members here, so a per-member loop would have created two.
        assert mock_create.call_count == 1
        data = mock_create.call_args[0][0]
        assert data.target_type == TargetType.TEAM
        assert data.target_id == str(self.team.id)
        assert data.priority == Priority.NORMAL
        assert data.source_type == SourceType.PULSE
        assert data.source_id == str(self.digest.id)
        assert data.source_url == f"/pulse?digest={self.digest.id}"
        assert "Signups" in data.title

    @patch(f"{NOTIFICATIONS_API}.has_been_dispatched")
    @patch(f"{NOTIFICATIONS_API}.create_notification")
    def test_idempotent_on_retry(self, mock_create, mock_dispatched):
        mock_dispatched.return_value = False
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding()])
        assert mock_create.call_count == 1

        # A Temporal retry sees the team's digest notification already dispatched and creates nothing more.
        mock_dispatched.return_value = True
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding()])
        assert mock_create.call_count == 1

    @patch(f"{NOTIFICATIONS_API}.has_been_dispatched", return_value=False)
    @patch(f"{NOTIFICATIONS_API}.create_notification")
    def test_no_findings_dispatches_nothing(self, mock_create, _mock_dispatched):
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [])
        mock_create.assert_not_called()

    @patch(f"{NOTIFICATIONS_API}.has_been_dispatched", return_value=False)
    @patch(f"{NOTIFICATIONS_API}.create_notification")
    def test_title_summarizes_multiple_findings(self, mock_create, _mock_dispatched):
        second = _finding()
        second.descriptor = MetricDescriptor(source="top_event", label="Churn", query={})
        _dispatch_pulse_notifications(self.team.id, str(self.digest.id), [_finding(), second])

        data = mock_create.call_args[0][0]
        assert "Signups" in data.title
        assert "+1 more" in data.title

    def test_persist_findings_without_marking_delivered(self):
        with team_scope(self.team.id):
            PulseFinding.objects.filter(digest=self.digest).delete()
            finding_ids = _persist_findings_sync(str(self.digest.id), self.team.id, [_finding()])

        self.digest.refresh_from_db()
        # Persist is findings-only; the workflow flips the digest to DELIVERED after synthesis.
        assert self.digest.status == PulseDigestStatus.GENERATING
        assert len(finding_ids) == 1
