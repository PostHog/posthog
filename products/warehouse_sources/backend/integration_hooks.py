"""The work of the foreign keys to integration rows. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.warehouse_sources.backend.models import ExternalDataDestination


def before_integration_delete(row: IntegrationRecord) -> None:
    ExternalDataDestination.objects.for_team(row.team_id).filter(integration_id=row.id).update(integration=None)
