"""The work of the foreign keys to integration rows and of the Slack install receiver. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping, SlackUserProfileCache
from products.slack_app.backend.signals import onboard_slack_inbox_on_saved


def before_integration_delete(row: IntegrationRecord) -> None:
    # CASCADE foreign keys.
    SlackThreadTaskMapping.objects.filter(team_id=row.team_id, integration_id=row.id).delete()
    SlackUserProfileCache.objects.filter(integration_id=row.id).delete()
    SlackSettings.objects.filter(default_integration_id=row.id).delete()


def after_integration_saved(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
    onboard_slack_inbox_on_saved(row, created=created, config_changed=config_changed)
