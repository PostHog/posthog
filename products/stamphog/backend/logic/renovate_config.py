"""Reads the repo's opt-in to Renovate reviews from the `renovate:` section of `.stamphog/policy.yml`.

The file is read from the DEFAULT branch only, so a Renovate PR cannot opt its own repository in.
The opt-in is exactly `renovate: {enabled: true}`. Every other shape reads as off, with a warning so a
typo does not silently leave reviews off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .default_branch_policy import load_default_branch_policy

if TYPE_CHECKING:
    from ..models import StamphogRepoConfig

logger = structlog.get_logger(__name__)


def renovate_reviews_enabled(repo_config: StamphogRepoConfig) -> bool:
    """Whether the repo opted in to Renovate reviews. A transient fetch failure raises."""
    policy = load_default_branch_policy(repo_config)
    if policy is None or "renovate" not in policy:
        return False
    section = policy["renovate"]
    if not isinstance(section, dict) or section.get("enabled") is not True:
        logger.warning("stamphog_renovate_config_not_enabled", repository=repo_config.repository)
        return False
    return True
