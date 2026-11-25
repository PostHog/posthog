"""The work of the foreign keys to integration rows and of the Slack install receiver. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.slack_app.backend.models import (
    SlackChannelSettings,
    SlackSettings,
    SlackThreadTaskMapping,
    SlackUserProfileCache,
)
from products.slack_app.backend.services.integration_references import store_integration_id
from products.slack_app.backend.signals import onboard_slack_inbox_on_saved


def before_integration_delete(row: IntegrationRecord) -> None:
    # CASCADE foreign keys.
    SlackThreadTaskMapping.objects.filter(team_id=row.team_id, integration_id=row.id).delete()
    SlackUserProfileCache.objects.filter(integration_id=row.id).delete()
    # SET_NULL, not CASCADE: the row also holds the person's or the workspace's other settings.
    SlackSettings.objects.filter(default_integration_id=row.id).update(default_integration=None)
    # A channel row may point at the install by reference. Its other settings stay, and a row left with none goes.
    SlackChannelSettings.objects.filter(default_integration_id=store_integration_id(row.id)).update(
        default_integration_id=None
    )
    SlackChannelSettings.objects.filter(
        default_integration_id__isnull=True, default_repository__isnull=True, untagged_question_mode__isnull=True
    ).delete()


def after_integration_saved(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
    onboard_slack_inbox_on_saved(row, created=created, config_changed=config_changed)
