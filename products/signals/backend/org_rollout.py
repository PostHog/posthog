"""A salted percentage rollout over organizations or other ids, and the organization id lists of a flag payload."""

import uuid
import hashlib

ROLLOUT_BUCKETS = 10_000


def rollout_bucket(salt: str, key: uuid.UUID | int) -> int:
    """The key's fixed place in the rollout of `salt`, from 0 to `ROLLOUT_BUCKETS` - 1."""
    digest = hashlib.sha256(f"{salt}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % ROLLOUT_BUCKETS


def organization_rollout_bucket(salt: str, organization_id: uuid.UUID) -> int:
    return rollout_bucket(salt, organization_id)


def in_rollout(salt: str, percentage: float, organization_id: uuid.UUID) -> bool:
    return organization_rollout_bucket(salt, organization_id) < percentage * ROLLOUT_BUCKETS / 100


def parse_organization_ids(organization_ids: tuple[str, ...]) -> set[uuid.UUID]:
    # A UUID parse, so an id in another UUID format still matches, and an invalid id matches nothing.
    parsed: set[uuid.UUID] = set()
    for organization_id in organization_ids:
        try:
            parsed.add(uuid.UUID(organization_id))
        except ValueError:
            continue
    return parsed
