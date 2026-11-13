"""A salted percentage rollout over organizations, and the organization id lists of a flag payload."""

import uuid
import hashlib

_ROLLOUT_BUCKETS = 10_000


def organization_rollout_bucket(salt: str, organization_id: uuid.UUID) -> int:
    """The organization's fixed place in the rollout of `salt`, from 0 to `_ROLLOUT_BUCKETS` - 1."""
    digest = hashlib.sha256(f"{salt}:{organization_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % _ROLLOUT_BUCKETS


def in_rollout(salt: str, percentage: float, organization_id: uuid.UUID) -> bool:
    return organization_rollout_bucket(salt, organization_id) < percentage * _ROLLOUT_BUCKETS / 100


def parse_organization_ids(organization_ids: tuple[str, ...]) -> set[uuid.UUID]:
    # A UUID parse, so an id in another UUID format still matches, and an invalid id matches nothing.
    parsed: set[uuid.UUID] = set()
    for organization_id in organization_ids:
        try:
            parsed.add(uuid.UUID(organization_id))
        except ValueError:
            continue
    return parsed
