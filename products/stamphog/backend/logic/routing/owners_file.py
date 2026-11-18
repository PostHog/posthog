"""Whether a repository carries the owners.yaml that reviewer routing reads its candidates from."""

from __future__ import annotations

from uuid import UUID

from django.core.cache import cache

import structlog
from owners_yaml.schema import OWNERS_FILENAME

from posthog.egress.limiter.policies import Priority

from products.stamphog.backend.facade.enums import OwnersFileStatus
from products.stamphog.backend.logic.github_client import StamphogGitHubClient

logger = structlog.get_logger(__name__)

# Bounds what a settings page left open, or a caller looping on the API, can spend of the installation's
# GitHub budget, which the reviews and the routing share. A newly added owners.yaml shows up within this.
OWNERS_FILE_CACHE_SECONDS = 600


def _cache_key(config_id: UUID, installation_id: str) -> str:
    # A rebind to another installation can read a different answer, so the installation is part of the key.
    return f"stamphog:owners_file:{config_id}:{installation_id}"


def owners_file_status(config_id: UUID, repository: str, installation_id: str) -> OwnersFileStatus:
    """Look for the root owners.yaml on the default branch, where routing reads ownership.

    At most one GitHub call per repository config in the cache window. The call can be shed, because
    nothing but the settings page waits on it.
    """
    if not installation_id:
        return OwnersFileStatus.UNAVAILABLE
    key = _cache_key(config_id, installation_id)
    cached = cache.get(key)
    if cached in (OwnersFileStatus.FOUND, OwnersFileStatus.MISSING):
        return OwnersFileStatus(cached)
    try:
        text = StamphogGitHubClient(installation_id).get_default_branch_file(
            repository, OWNERS_FILENAME, priority=Priority.NORMAL
        )
    except Exception:  # noqa: BLE001 - a failed check only hides the setting, so any error reads as unknown
        logger.warning("stamphog_owners_file_check_failed", repository=repository, exc_info=True)
        return OwnersFileStatus.UNAVAILABLE
    status = OwnersFileStatus.MISSING if text is None else OwnersFileStatus.FOUND
    cache.set(key, status.value, timeout=OWNERS_FILE_CACHE_SECONDS)
    return status
