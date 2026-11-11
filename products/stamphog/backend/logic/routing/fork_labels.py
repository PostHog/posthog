"""The team slug -> label map that replaces a team's review request on fork pull requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.stamphog.backend.models import StamphogRepoConfig


def _label_map(configured: object) -> dict[str, str]:
    if not isinstance(configured, dict):
        return {}
    return {slug: label for slug, label in configured.items() if isinstance(slug, str) and isinstance(label, str)}


def fork_labels(repo_config: StamphogRepoConfig) -> dict[str, str]:
    """The repo's team slug -> label map. Entries that are not a string pair are ignored."""
    return _label_map(repo_config.routing_fork_labels)


def shared_behavior_labels(repo_config: StamphogRepoConfig) -> dict[str, str]:
    return _label_map(repo_config.routing_shared_behavior_labels)
