"""The team slug -> label map that replaces a team's review request on fork pull requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.stamphog.backend.models import StamphogRepoConfig


def fork_labels(repo_config: StamphogRepoConfig) -> dict[str, str]:
    """The repo's team slug -> label map. Entries that are not a string pair are ignored."""
    configured = repo_config.routing_fork_labels
    if not isinstance(configured, dict):
        return {}
    return {slug: label for slug, label in configured.items() if isinstance(slug, str) and isinstance(label, str)}
