"""The work of the foreign keys to integration rows. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.error_tracking.backend.models import ErrorTrackingAlertDestination, ErrorTrackingExternalReference


def before_integration_delete(row: IntegrationRecord) -> None:
    ErrorTrackingExternalReference.objects.filter(integration_id=row.id).delete()
    ErrorTrackingAlertDestination.objects.for_team(row.team_id).filter(integration_id=row.id).update(integration=None)
