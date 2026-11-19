"""The work of the foreign keys to integration rows. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.signals.backend.models import (
    SignalReportSlackThread,
    SignalReportTrackerIssue,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)


def before_integration_delete(row: IntegrationRecord) -> None:
    SignalTeamConfig.objects.filter(team_id=row.team_id, issue_tracking_integration_id=row.id).update(
        issue_tracking_integration=None
    )
    SignalUserAutonomyConfig.objects.filter(slack_notification_integration_id=row.id).update(
        slack_notification_integration=None
    )
    SignalReportTrackerIssue.objects.for_team(row.team_id).filter(integration_id=row.id).update(integration=None)
    SignalReportSlackThread.objects.for_team(row.team_id).filter(integration_id=row.id).update(integration=None)
