"""Reads the repo's opt-in to Renovate reviews from the `renovate:` section of `.stamphog/policy.yml`.

The file is read from the DEFAULT branch only, so a Renovate PR cannot opt its own repository in.
The opt-in is exactly `renovate: {enabled: true}`. Every other shape reads as off, with a warning so a
typo does not silently leave reviews off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
import structlog

from .digest_config import DIGEST_CONFIG_PATH
from .github_client import StamphogGitHubClient

if TYPE_CHECKING:
    from ..models import StamphogRepoConfig

logger = structlog.get_logger(__name__)


def renovate_reviews_enabled(repo_config: StamphogRepoConfig) -> bool:
    """Whether the repo opted in to Renovate reviews. A transient fetch failure raises."""
    raw_text = StamphogGitHubClient(repo_config.installation_id).get_file_text(
        repo_config.repository, DIGEST_CONFIG_PATH
    )
    if raw_text is None:
        return False
    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        logger.warning("stamphog_renovate_config_invalid_yaml", repository=repo_config.repository)
        return False
    if not isinstance(parsed, dict) or "renovate" not in parsed:
        return False
    section = parsed["renovate"]
    if not isinstance(section, dict) or section.get("enabled") is not True:
        logger.warning("stamphog_renovate_config_not_enabled", repository=repo_config.repository)
        return False
    return True
