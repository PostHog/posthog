"""Reads `.stamphog/policy.yml` from a repo's DEFAULT branch for the sections the server owns.

The server reads only its own top-level keys (`digest:`, `renovate:`). The rest of the schema is the
review engine's concern (products/stamphog/packages/pr-approval-agent/policy.py). The file is never
read at the PR head, so a PR cannot change the config that applies to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml
import structlog

from .github_client import StamphogGitHubClient

if TYPE_CHECKING:
    from ..models import StamphogRepoConfig

logger = structlog.get_logger(__name__)

POLICY_PATH = ".stamphog/policy.yml"


def load_default_branch_policy(repo_config: StamphogRepoConfig) -> dict[str, Any] | None:
    """The parsed policy, or None when the file is absent or is not a YAML mapping.

    A malformed file logs a warning, so a repo owner's typo does not silently vanish. A transient
    fetch failure raises, so each caller can retry instead of reading the config as absent.
    """
    raw_text = StamphogGitHubClient(repo_config.installation_id).get_file_text(repo_config.repository, POLICY_PATH)
    if raw_text is None:
        return None
    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        logger.warning("stamphog_policy_invalid_yaml", repository=repo_config.repository, exc_info=True)
        return None
    if not isinstance(parsed, dict):
        logger.warning("stamphog_policy_root_not_a_mapping", repository=repo_config.repository)
        return None
    return parsed
