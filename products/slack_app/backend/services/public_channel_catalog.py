"""The public channels that the Slack app can join in a workspace, cached per workspace.

Slack rate limits ``conversations.list`` per app and workspace, and one walk can take up to 100
pages. Every project that installs the app in a workspace shares that quota, so the list is cached
per workspace, only one request at a time fills it, and a workspace can start only a few fills in
each window, however often the cache empties.
"""

import time
from collections.abc import Iterable

from django.core.cache import cache

from posthog.integrations import IntegrationRecord
from posthog.models.integration import SlackIntegration
from posthog.slack.channels import is_shared_channel

from products.slack_app.backend.facade.types import ChannelCatalogBusy, ChannelOption

CATALOG_TTL_SECONDS = 10 * 60
FILLS_PER_WINDOW = 3
FILL_WINDOW_SECONDS = 10 * 60
# Longer than a full walk, so a slow fill does not let a second fill start.
FILL_LOCK_SECONDS = 60
# How long a request that lost the fill waits for the winner's list before it gives up.
FILL_WAIT_SECONDS = 3.0
FILL_POLL_SECONDS = 0.1


def _catalog_key(slack_workspace_id: str) -> str:
    return f"slack_app:public_channels:v1:{slack_workspace_id}"


def _to_options(cached: list[dict]) -> tuple[ChannelOption, ...]:
    return tuple(ChannelOption(id=item["id"], name=item["name"], is_member=item["is_member"]) for item in cached)


def _wait_for_fill(key: str) -> list[dict] | None:
    deadline = time.monotonic() + FILL_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(FILL_POLL_SECONDS)
        cached = cache.get(key)
        if cached is not None:
            return cached
    return None


def _take_fill_budget(slack_workspace_id: str) -> None:
    budget_key = f"{_catalog_key(slack_workspace_id)}:fills"
    try:
        fills = 1 if cache.add(budget_key, 1, FILL_WINDOW_SECONDS) else cache.incr(budget_key)
    except ValueError:
        # The counter expired between the add and the incr, so this fill opens the next window.
        fills = 1
    if fills > FILLS_PER_WINDOW:
        raise ChannelCatalogBusy(
            "PostHog loaded this workspace's Slack channels too often. Try again in a few minutes."
        )


def public_channel_options(integration: IntegrationRecord) -> tuple[ChannelOption, ...]:
    """Leaves out shared channels, because people outside the workspace would see the bot there."""
    slack_workspace_id = integration.integration_id or ""
    key = _catalog_key(slack_workspace_id)
    cached = cache.get(key)
    if cached is not None:
        return _to_options(cached)

    fill_key = f"{key}:filling"
    if not cache.add(fill_key, 1, FILL_LOCK_SECONDS):
        cached = _wait_for_fill(key)
        if cached is not None:
            return _to_options(cached)
        # A winner that died leaves no list, so one waiting request takes over the fill.
        if not cache.add(fill_key, 1, FILL_LOCK_SECONDS):
            raise ChannelCatalogBusy("PostHog is still loading the Slack channels. Try again in a moment.")

    try:
        _take_fill_budget(slack_workspace_id)
        channels = SlackIntegration(integration).list_public_channels()
        catalog = [
            {"id": channel["id"], "name": channel["name"], "is_member": bool(channel.get("is_member"))}
            for channel in channels
            if not is_shared_channel(channel)
        ]
        cache.set(key, catalog, CATALOG_TTL_SECONDS)
    finally:
        cache.delete(fill_key)
    return _to_options(catalog)


def mark_channels_joined(slack_workspace_id: str, channel_ids: Iterable[str]) -> None:
    """Update the cached list after joins, so the page stops offering those channels without a new walk."""
    joined = set(channel_ids)
    key = _catalog_key(slack_workspace_id)
    cached = cache.get(key)
    if not joined or cached is None:
        return
    cache.set(
        key,
        [{**item, "is_member": item["is_member"] or item["id"] in joined} for item in cached],
        CATALOG_TTL_SECONDS,
    )
