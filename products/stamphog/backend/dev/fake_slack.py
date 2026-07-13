"""Slack fake installed at the ``SlackIntegration`` seam.

Both the digest post path (``logic/slack_digest``) and the channel-resolution path
(``logic/channel_resolution``) construct ``SlackIntegration(integration)`` and then use
``.client.chat_postMessage`` / ``.list_channels``. The harness patches ``SlackIntegration``
in both modules with ``FakeSlackIntegration``, which records every posted message and serves
a scripted workspace channel list. A real ``Integration`` row still exists in the DB, so the
id-lookup guard (``Integration.objects.filter(id=..., team_id=..., kind="slack")``) is exercised.
"""

from __future__ import annotations

from typing import Any


class FakeSlackClient:
    """Records ``chat_postMessage`` calls; returns a Slack-shaped ``{"ok", "ts"}``."""

    def __init__(self, posted: list[dict[str, Any]]) -> None:
        self._posted = posted

    def chat_postMessage(self, *, channel: str, blocks: list[dict], text: str, **kwargs: Any) -> dict[str, Any]:
        self._posted.append({"channel": channel, "blocks": blocks, "text": text})
        FakeSlackIntegration.total_posted += 1
        return {"ok": True, "ts": "1234.5678"}


class FakeSlackIntegration:
    """Stand-in for ``posthog.models.integration.SlackIntegration``.

    Class-level state is shared across every instance a run constructs, so the harness can
    read ``posted_messages`` and script ``workspace_channels`` regardless of which module
    built the instance.
    """

    posted_messages: list[dict[str, Any]] = []
    workspace_channels: list[dict[str, str]] = []
    # Cumulative across resets, for the end-of-run summary.
    total_posted: int = 0

    def __init__(self, integration: Any) -> None:
        self.integration = integration

    @property
    def client(self) -> FakeSlackClient:
        return FakeSlackClient(FakeSlackIntegration.posted_messages)

    def list_channels(self, should_include_private_channels: bool = False, authed_user: str = "") -> list[dict]:
        # Public-only, name-sorted, mirroring the real signature the resolver calls with.
        return sorted(FakeSlackIntegration.workspace_channels, key=lambda c: c["name"])

    @classmethod
    def reset(cls, channels: list[dict[str, str]]) -> None:
        cls.posted_messages = []
        cls.workspace_channels = list(channels)
