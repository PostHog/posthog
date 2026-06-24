"""Upgrade prompt-cache breakpoints to a 1-hour TTL for idle-prone agent products.

Interactive agent sessions (PostHog Code) have human think-time gaps of minutes
between turns. The default ephemeral cache lives ~5 minutes, so a gap longer than
that expires the cache and forces a full rewrite next turn —
posthog.com/blog/optimizing-agent-cost saw exactly this from 5-15 min idle
periods (incl. subagent timeouts). A 1-hour TTL survives those gaps.

Economics: a 1h cache write costs ~2.0x base input vs ~1.25x for the 5-min TTL,
but it avoids a full re-write (~1.25x again) every time an idle gap would have
expired the 5-min cache; reads in between stay ~0.1x either way. With >=1 such
gap per hour, 1h nets cheaper for interactive sessions.

Pure transform: it only UPGRADES existing `{"type": "ephemeral"}` breakpoints the
SDK already set — never adds new ones, never overrides an explicit ttl. Gated
upstream by `cost_controls` (alpha) + product.
"""

from __future__ import annotations

from typing import Any

# Interactive, human-in-the-loop products whose sessions have think-time gaps.
# Async/batched products (background_agents, signals) don't benefit the same way.
IDLE_PRONE_PRODUCTS = frozenset({"posthog_code", "slack_app"})

_ONE_HOUR = "1h"


def _upgrade_block(block: Any) -> None:
    if not isinstance(block, dict):
        return
    cc = block.get("cache_control")
    if isinstance(cc, dict) and cc.get("type") == "ephemeral" and "ttl" not in cc:
        cc["ttl"] = _ONE_HOUR


def _upgrade_blocks(value: Any) -> None:
    if isinstance(value, list):
        for block in value:
            _upgrade_block(block)


def upgrade_cache_ttl(body: dict[str, Any], *, product: str) -> dict[str, Any]:
    """Mutate `body` in place (and return it), upgrading ephemeral cache
    breakpoints on the stable prefix (system, tools) and on message content to a
    1-hour TTL. No-op for non-idle-prone products or bodies without breakpoints.
    """
    if product not in IDLE_PRONE_PRODUCTS:
        return body

    _upgrade_blocks(body.get("system"))
    _upgrade_blocks(body.get("tools"))

    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                _upgrade_blocks(message.get("content"))

    return body
