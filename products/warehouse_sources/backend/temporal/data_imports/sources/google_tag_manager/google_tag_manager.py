import collections.abc
from typing import Any

from django.conf import settings
from django.db import OperationalError, close_old_connections

import structlog
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.settings import GTM_SCHEMAS

logger = structlog.get_logger(__name__)

GTM_API_BASE = "https://tagmanager.googleapis.com/tagmanager/v2"

# Tag Manager caps list responses; page through with `nextPageToken` until it's gone.
PAGE_SIZE = 200

_MAX_INTEGRATION_FETCH_ATTEMPTS = 4


def _get_integration(integration_id: int, team_id: int) -> Integration:
    """Fetch the OAuth ``Integration`` row, retrying a transient DB failure.

    Temporal activities read this lazily inside the row iterator, long after the pooled
    connection may have gone stale, so a transient ``OperationalError`` clears once
    ``close_old_connections`` hands back a fresh connection. The read is idempotent.
    ``Integration.DoesNotExist`` is left to propagate.
    """
    attempt = 0
    while True:
        close_old_connections()
        try:
            return Integration.objects.get(id=integration_id, team_id=team_id)
        except OperationalError:
            attempt += 1
            if attempt >= _MAX_INTEGRATION_FETCH_ATTEMPTS:
                raise


def _credentials(integration_id: int, team_id: int) -> OAuthCredentials:
    integration = _get_integration(integration_id, team_id)
    return OAuthCredentials(
        token=None,
        refresh_token=integration.refresh_token,
        client_id=settings.GOOGLE_TAG_MANAGER_APP_CLIENT_ID,
        client_secret=settings.GOOGLE_TAG_MANAGER_APP_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        # No `scopes=` on purpose: a refresh-token grant re-uses the scopes the user
        # originally consented to. Passing a scope Google didn't grant fails the refresh
        # with "invalid_scope"; a genuinely missing scope surfaces as a 403 instead, which
        # `get_non_retryable_errors` maps to an actionable reconnect message.
    )


def google_tag_manager_session(integration_id: int, team_id: int) -> AuthorizedSession:
    creds = _credentials(integration_id, team_id)
    session = AuthorizedSession(creds)
    adapter = make_tracked_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _account_path(account_id: str) -> str:
    return f"accounts/{account_id}"


def _paginate(session: AuthorizedSession, url: str, response_key: str) -> collections.abc.Iterator[dict[str, Any]]:
    """Yield each row from a paginated Tag Manager list endpoint."""
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"pageSize": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        response = session.get(url, params=params)
        response.raise_for_status()
        body = response.json()
        yield from body.get(response_key, [])
        page_token = body.get("nextPageToken")
        if not page_token:
            break


def list_accounts(session: AuthorizedSession) -> list[dict[str, Any]]:
    return list(_paginate(session, f"{GTM_API_BASE}/accounts", "account"))


def get_account(session: AuthorizedSession, account_id: str) -> dict[str, Any]:
    response = session.get(f"{GTM_API_BASE}/{_account_path(account_id)}")
    response.raise_for_status()
    return response.json()


def _list_at_path(session: AuthorizedSession, parent_path: str, suffix: str, response_key: str) -> list[dict[str, Any]]:
    return list(_paginate(session, f"{GTM_API_BASE}/{parent_path}/{suffix}", response_key))


def _iter_rows(
    session: AuthorizedSession,
    account_id: str,
    resource_name: str,
) -> collections.abc.Iterator[dict[str, Any]]:
    schema = GTM_SCHEMAS[resource_name]
    grain = schema["grain"]
    suffix = schema["path_suffix"]
    response_key = schema["response_key"]

    if grain == "account":
        if not suffix:
            # The account itself: a single object, not a list.
            yield get_account(session, account_id)
            return
        yield from _list_at_path(session, _account_path(account_id), suffix, response_key)
        return

    # container / workspace grains fan out from the account's containers.
    containers = _list_at_path(session, _account_path(account_id), "containers", "container")

    if grain == "container":
        for container in containers:
            yield from _list_at_path(session, container["path"], suffix, response_key)
        return

    # workspace grain: fan out one more level, per workspace of each container.
    for container in containers:
        workspaces = _list_at_path(session, container["path"], "workspaces", "workspace")
        for workspace in workspaces:
            yield from _list_at_path(session, workspace["path"], suffix, response_key)


def google_tag_manager_source(
    config: GoogleTagManagerSourceConfig,
    resource_name: str,
    team_id: int,
) -> SourceResponse:
    if resource_name not in GTM_SCHEMAS:
        raise ValueError(f"Unknown Google Tag Manager schema: {resource_name}")

    schema = GTM_SCHEMAS[resource_name]

    def get_rows() -> collections.abc.Iterator[list[dict[str, Any]]]:
        session = google_tag_manager_session(config.google_tag_manager_integration_id, team_id)
        rows = list(_iter_rows(session, config.account_id, resource_name))
        if rows:
            yield rows

    return SourceResponse(
        name=NamingConvention.normalize_identifier(resource_name),
        items=get_rows,
        primary_keys=list(schema["primary_key"]),
        # Tag Manager returns full snapshots with no timestamp to order or partition on, and
        # documents no ordering for its list endpoints, so no sort mode is declared.
        sort_mode=None,
    )
