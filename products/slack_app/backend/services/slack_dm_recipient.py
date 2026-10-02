"""Find where in Slack to DM a PostHog user, for any product that messages people through the Slack app.

A linked Slack identity wins. Without one, the user's email is matched against each workspace's own
directory, and a match in more than one workspace is ambiguous and resolves to nobody.
"""

from collections.abc import Mapping, Sequence

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.slack.identity import resolve_slack_user

from products.slack_app.backend.services.slack_user_info import lookup_slack_user_id_by_email

logger = structlog.get_logger(__name__)


@frozen
class SlackDmRecipient:
    integration: Integration
    slack: SlackIntegration
    slack_user_id: str


def linked_slack_user_id(*, user_id: int, integration: Integration) -> str | None:
    link = (
        UserIntegration.objects.filter(
            user_id=user_id,
            kind=UserIntegration.IntegrationKind.SLACK,
            config__slack_team_id=integration.integration_id,
        )
        .order_by("-created_at")
        .first()
    )
    return link.integration_id if link else None


def linked_integration_for_recipient(
    *, user_id: int, integration_by_workspace: Mapping[str | None, Integration]
) -> Integration | None:
    linked_workspaces = (
        UserIntegration.objects.filter(user_id=user_id, kind=UserIntegration.IntegrationKind.SLACK)
        .order_by("-created_at")
        .values_list("config__slack_team_id", flat=True)
    )
    for linked_workspace in linked_workspaces:
        if isinstance(linked_workspace, str) and (integration := integration_by_workspace.get(linked_workspace)):
            return integration
    return None


def slack_user_id_by_email(*, email: str, integration: Integration, slack: SlackIntegration) -> str | None:
    """Match a PostHog email against the workspace's own Slack directory.

    This is what makes the feature work without every person linking an account first. It asks the
    customer's own directory a question about our own user's email, which is the opposite direction
    from the inbound path (where a Slack-supplied email would decide who a PostHog user is, and so
    can't be trusted).
    """
    workspace = integration.integration_id or ""
    if not email or not workspace:
        return None
    slack_user_id = lookup_slack_user_id_by_email(slack, integration, email)
    if not slack_user_id:
        return None
    profile = resolve_slack_user(slack.client, slack_user_id, workspace=workspace)
    # `users.lookupByEmail` also returns external Slack Connect members, whose profile emails are
    # controlled by their own workspace's admin. Without this check an outsider could claim a
    # teammate's address and receive messages meant for them.
    if profile.get("team_id") != workspace:
        logger.warning("slack_dm_email_match_outside_workspace", integration_id=integration.id)
        return None
    return slack_user_id


def resolve_slack_dm_recipient(*, user: User, integrations: Sequence[Integration]) -> SlackDmRecipient | None:
    """``integrations`` are the team's Slack installs the caller may deliver through."""
    integration_by_workspace = {integration.integration_id: integration for integration in integrations}
    linked = linked_integration_for_recipient(user_id=user.id, integration_by_workspace=integration_by_workspace)
    if linked is not None:
        slack_user_id = linked_slack_user_id(user_id=user.id, integration=linked)
        if not slack_user_id:
            return None
        return SlackDmRecipient(integration=linked, slack=SlackIntegration(linked), slack_user_id=slack_user_id)

    match: SlackDmRecipient | None = None
    for candidate in integrations:
        slack = SlackIntegration(candidate)
        candidate_user_id = slack_user_id_by_email(email=user.email or "", integration=candidate, slack=slack)
        if not candidate_user_id:
            continue
        if match is not None:
            return None
        match = SlackDmRecipient(integration=candidate, slack=slack, slack_user_id=candidate_user_id)
    return match
