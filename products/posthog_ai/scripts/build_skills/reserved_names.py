"""Skill names this repo must not ship, because context-mill owns them."""

from __future__ import annotations

# Skills authored in PostHog/context-mill. Every shipping consumer unzips this
# repo's skills first and then unzips the context-mill release on top, so a
# same-named skill here is overwritten instead of shipped — a failure that is
# silent without this check, because the copy still builds and still publishes.
OMNIBUS_SKILL_NAMES = frozenset(
    {
        "instrument-integration",
        "instrument-product-analytics",
        "instrument-feature-flags",
        "instrument-error-tracking",
        "instrument-llm-analytics",
        "instrument-logs",
        "instrument-metrics",
    }
)


def reserved_name_message(name: str, source: str) -> str:
    """The error text for a skill that reuses a context-mill name."""
    return (
        f"'{name}' is owned by PostHog/context-mill, which every consumer "
        f"overlays on top of this repo's skills, so a copy here is overwritten "
        f"rather than shipped. Remove {source} and change the context-mill source instead."
    )
