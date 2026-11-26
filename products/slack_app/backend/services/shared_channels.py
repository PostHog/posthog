"""Whether PostHog may reply in a Slack channel shared with another organization.

A shared channel needs two things before PostHog replies there: someone in the channel approved PostHog, and
the workspace has not turned shared channels off. The switch applies only while the ``slack-app-web-settings``
flag is on for the organization, so without the flag the approval alone decides.
"""

from enum import StrEnum

from posthog.integrations import IntegrationRecord

from products.slack_app.backend.feature_flags import is_slack_app_web_settings_enabled
from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.slack_settings import resolve_external_channels_enabled

SHARED_CHANNELS_TURNED_OFF_MESSAGE = (
    "PostHog is turned off in channels shared with other organizations. "
    "A PostHog admin can turn it on in the Slack app settings in PostHog."
)


class SharedChannelAccess(StrEnum):
    ALLOWED = "allowed"
    NEEDS_APPROVAL = "needs_approval"
    # An approval cannot help, so callers tell the person that an admin turned shared channels off.
    TURNED_OFF = "turned_off"


def shared_channel_access(integration: IntegrationRecord, slack_channel_id: str) -> SharedChannelAccess:
    """Only for a channel that Slack marks as externally shared. Other channels need neither check."""
    slack_workspace_id = integration.integration_id or ""
    # The switch is read first, so the flag is evaluated only for a workspace whose switch is off.
    if not resolve_external_channels_enabled(slack_workspace_id) and is_slack_app_web_settings_enabled(integration):
        return SharedChannelAccess.TURNED_OFF
    if SlackChannel.approval_granted(slack_workspace_id, slack_channel_id):
        return SharedChannelAccess.ALLOWED
    return SharedChannelAccess.NEEDS_APPROVAL
