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


def _collect_cache_controls(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every `cache_control` dict in `body`, in wire order."""
    controls: list[dict[str, Any]] = []

    def _from_blocks(value: Any) -> None:
        if not isinstance(value, list):
            return
        for block in value:
            if not isinstance(block, dict):
                continue
            cc = block.get("cache_control")
            if isinstance(cc, dict):
                controls.append(cc)

    _from_blocks(body.get("system"))
    _from_blocks(body.get("tools"))

    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                _from_blocks(message.get("content"))

    return controls


def upgrade_cache_ttl(body: dict[str, Any], *, product: str) -> dict[str, Any]:
    """Mutate `body` in place (and return it), upgrading ephemeral cache
    breakpoints on the stable prefix (system, tools) and on message content to a
    1-hour TTL. No-op for non-idle-prone products or bodies without breakpoints.

    Anthropic requires 1-hour breakpoints to precede shorter ones, so if an
    earlier breakpoint already has an explicit non-1h ttl, upgrading a later
    implicit one would invert that order — skip the rewrite entirely rather
    than send a request the API will reject.
    """
    if product not in IDLE_PRONE_PRODUCTS:
        return body

    controls = _collect_cache_controls(body)

    seen_explicit_short_ttl = False
    for cc in controls:
        ttl = cc.get("ttl")
        if ttl is not None:
            if ttl != _ONE_HOUR:
                seen_explicit_short_ttl = True
        elif cc.get("type") == "ephemeral" and seen_explicit_short_ttl:
            return body

    for cc in controls:
        if cc.get("type") == "ephemeral" and "ttl" not in cc:
            cc["ttl"] = _ONE_HOUR

    return body
