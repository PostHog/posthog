"""The work of the foreign keys to integration rows. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.messaging.backend.models import OptOutSyncConfig, ProviderImportRun


def before_integration_delete(row: IntegrationRecord) -> None:
    configs = OptOutSyncConfig.objects.filter(team_id=row.team_id)
    configs.filter(app_integration_id=row.id).update(app_integration=None)
    configs.filter(webhook_integration_id=row.id).update(webhook_integration=None)
    configs.filter(track_integration_id=row.id).update(track_integration=None)
    ProviderImportRun.objects.for_team(row.team_id).filter(integration_id=row.id).update(integration=None)
