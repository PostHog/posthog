"""Accounts that each project member connects themselves.

A source that sets `SourceConfig.memberIntegrationKind` syncs every integration of that kind in
the project. Each integration is one account, created by the member who connected it.
"""

from dataclasses import field
from typing import Any

from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, OauthIntegration, UndecryptedIntegrationSecretError

ALL_ACCOUNTS_UNREADABLE = "None of the connected accounts could be read"


@frozen
class MemberAccount:
    account_id: str
    access_token: str = field(repr=False)


def member_integrations(team_id: int, kind: str) -> list[Integration]:
    return list(Integration.objects.filter(team_id=team_id, kind=kind).select_related("created_by").order_by("id"))


def readable_member_accounts(integrations: list[Integration], logger: FilteringBoundLogger) -> list[MemberAccount]:
    """The accounts whose access token is usable, after refreshing the expired ones."""
    accounts: list[MemberAccount] = []
    for integration in integrations:
        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()
        account_id = integration.integration_id
        try:
            access_token = integration.access_token
        except UndecryptedIntegrationSecretError:
            # One account with an unreadable stored token must not stop the other accounts.
            access_token = None
        if integration.errors or not account_id or not access_token:
            logger.warning(
                "Skipping a connected account whose access expired. Its owner needs to reconnect it.",
                account_id=account_id,
            )
            continue
        accounts.append(MemberAccount(account_id=account_id, access_token=access_token))

    # A source with accounts where none can be refreshed is broken. A source with no accounts yet is not.
    if integrations and not accounts:
        raise ValueError(ALL_ACCOUNTS_UNREADABLE)
    return accounts


def member_account_rows(integrations: list[Integration]) -> list[dict[str, Any]]:
    """One row for each connected account, naming the PostHog user who connected it."""
    rows: list[dict[str, Any]] = []
    for integration in integrations:
        connected_by = integration.created_by
        rows.append(
            {
                "account_id": integration.integration_id,
                "display_name": integration.display_name,
                "connected_by_email": connected_by.email if connected_by else None,
                "connected_by_name": connected_by.get_full_name() if connected_by else None,
                "connected_at": integration.created_at,
            }
        )
    return rows
