"""Fills in the sender of a template imported from another email tool."""

from collections.abc import Mapping
from typing import Any

from posthog.integrations import IntegrationRecord

from products.messaging.backend.provider_imports.liquid_text import literal_liquid
from products.messaging.backend.provider_imports.senders import sender_for_address


def apply_sender(
    email: dict[str, Any],
    display_name: str,
    address: str,
    senders: Mapping[str, IntegrationRecord],
    target: str = "template",
) -> tuple[str, ...]:
    """Sets `email["from"]` when `address` or its domain has a PostHog sender, and returns notes on what the person still has to do."""
    sender = sender_for_address(address, senders)
    if sender is None:
        return (f"{address} isn't a PostHog sender yet. Add it, then choose it on this {target}.",)
    email["from"] = {
        "integrationId": sender.id,
        "email": literal_liquid(address),
        "name": literal_liquid(display_name) or str(sender.config.get("name") or ""),
    }
    if not sender.config.get("verified"):
        return (f"{address} isn't verified in PostHog yet, so this {target} can't send until it is.",)
    return ()
