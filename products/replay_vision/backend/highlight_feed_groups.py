"""Feed groups: tight clusters of a scanner's issue observations that tell the same story, so the Highlights feed
shows each story once with the number of people it reached.

An observation joins the scanner's closest recent group, or starts one. A busy scanner has thousands of recent
groups, so the consumer keeps each scanner's groups in memory instead of reading them from Postgres on every
observation. Every assignment runs under the lock on the scanner's semantic centre and bumps its member count, so a
cache whose count disagrees with the locked row missed a write from another process and reloads.
"""

import uuid
from collections import OrderedDict
from datetime import datetime, timedelta

import numpy as np

from posthog.models.utils import uuid7

from products.replay_vision.backend.models.replay_scanner_semantics import ReplayScannerFeedGroup
from products.replay_vision.backend.semantic_space import ClusterArrays, ClusterWrites, SemanticSpace, unpack

FEED_GROUP_MIN_SIMILARITY = 0.65
FEED_GROUP_MIN_RAW_SIMILARITY = 0.90
# A group with no new member for this long stops taking members, so a story that returns later starts a new card.
FEED_GROUP_ACTIVE_WINDOW = timedelta(days=30)
MAX_CACHED_GROUPS_PER_SCANNER = 20_000
# Spare capacity counts too, so the cap bounds the memory the arrays actually hold.
MAX_CACHED_GROUPS = 100_000


class _ScannerGroups(ClusterArrays):
    """One scanner's active groups, and the centre member count they reflect."""

    def __init__(self, groups: list[ReplayScannerFeedGroup], version: int) -> None:
        super().__init__(
            [group.id for group in groups],
            [unpack(group.vector_sum) for group in groups],
            [group.member_count for group in groups],
            [group.last_member_at for group in groups],
        )
        self.version = version

    def trim(self, now: datetime) -> None:
        """Drop groups that stopped taking members, then the least recent ones above the per-scanner cap."""
        keep = np.nonzero(self.last >= (now - FEED_GROUP_ACTIVE_WINDOW).timestamp())[0]
        if len(keep) > MAX_CACHED_GROUPS_PER_SCANNER:
            keep = keep[np.argsort(self.last[keep])[-MAX_CACHED_GROUPS_PER_SCANNER:]]
        self.keep(keep)


class FeedGroupCache:
    def __init__(self) -> None:
        self._scanners: OrderedDict[str, _ScannerGroups] = OrderedDict()

    def assign(
        self,
        *,
        team_id: int,
        scanner_id: str,
        space: SemanticSpace,
        version: int,
        now: datetime,
        writes: ClusterWrites,
    ) -> uuid.UUID:
        """Put one observation in its scanner's closest active group, or start a group. Call under the centre lock,
        with the centre's member count before this observation joins, and save `writes` before the lock is released."""
        groups = self._load(team_id, scanner_id, version, now)
        best = groups.nearest(
            space, now - FEED_GROUP_ACTIVE_WINDOW, FEED_GROUP_MIN_SIMILARITY, FEED_GROUP_MIN_RAW_SIMILARITY
        )
        if best is None:
            best = groups.add(uuid7(), space.vector, now)
        else:
            groups.join(best, space.vector, now)
        writes.record(groups, best)
        groups.version = version + 1
        return groups.ids[best]

    def forget(self, scanner_id: str) -> None:
        """Drop a scanner's groups, so an assignment whose transaction rolled back never leaves them ahead of Postgres."""
        self._scanners.pop(scanner_id, None)

    def _load(self, team_id: int, scanner_id: str, version: int, now: datetime) -> _ScannerGroups:
        groups = self._scanners.get(scanner_id)
        if groups is None or groups.version != version:
            rows = list(
                ReplayScannerFeedGroup.objects.for_team(team_id)
                .filter(scanner_id=scanner_id, last_member_at__gte=now - FEED_GROUP_ACTIVE_WINDOW)
                .order_by("-last_member_at")
                .only("id", "vector_sum", "member_count", "last_member_at")[:MAX_CACHED_GROUPS_PER_SCANNER]
            )
            groups = _ScannerGroups(rows, version)
            self._scanners[scanner_id] = groups
        else:
            groups.trim(now)
        self._scanners.move_to_end(scanner_id)
        self._evict()
        return groups

    def _evict(self) -> None:
        total = sum(groups.capacity for groups in self._scanners.values())
        while total > MAX_CACHED_GROUPS and len(self._scanners) > 1:
            _, evicted = self._scanners.popitem(last=False)
            total -= evicted.capacity

    def clear(self) -> None:
        self._scanners.clear()


feed_group_cache = FeedGroupCache()
