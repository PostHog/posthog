"""Whether a repository carries the owners.yaml that reviewer routing reads its candidates from."""

from __future__ import annotations

import structlog
from owners_yaml.schema import OWNERS_FILENAME

from products.stamphog.backend.facade.enums import OwnersFileStatus
from products.stamphog.backend.logic.github_client import StamphogGitHubClient

logger = structlog.get_logger(__name__)


def owners_file_status(repository: str, installation_id: str) -> OwnersFileStatus:
    """Look for the root owners.yaml on the default branch, where routing reads ownership. One GitHub call."""
    if not installation_id:
        return OwnersFileStatus.UNAVAILABLE
    try:
        text = StamphogGitHubClient(installation_id).get_default_branch_file(repository, OWNERS_FILENAME)
    except Exception:  # noqa: BLE001 - a failed check only hides the setting, so any error reads as unknown
        logger.warning("stamphog_owners_file_check_failed", repository=repository, exc_info=True)
        return OwnersFileStatus.UNAVAILABLE
    return OwnersFileStatus.MISSING if text is None else OwnersFileStatus.FOUND
