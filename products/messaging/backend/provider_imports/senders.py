"""Finds the PostHog sender for an address a template imported from another email tool sends from."""

from collections.abc import Mapping

from posthog.integrations import IntegrationRecord


def sender_for_address(address: str, senders: Mapping[str, IntegrationRecord]) -> IntegrationRecord | None:
    """The sender with this address, or else one on its domain, because a sender can send from any address there.
    `senders` is keyed by lowercase address. A verified sender wins over one that isn't, even over an exact match."""
    exact = senders.get(address.lower())
    domain = address.rpartition("@")[2].lower()
    on_domain = [
        sender
        for sender in senders.values()
        if str(sender.config.get("domain") or str(sender.config.get("email", "")).rpartition("@")[2]).lower() == domain
    ]
    candidates = [exact, *on_domain] if exact else on_domain
    return next(
        (sender for sender in candidates if sender.config.get("verified")), candidates[0] if candidates else None
    )
