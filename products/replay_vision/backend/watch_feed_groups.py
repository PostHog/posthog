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

from django.db.models import F
from django.db.models.functions import Greatest

import numpy as np

from products.replay_vision.backend.models.replay_scanner_semantics import ReplayScannerFeedGroup
from products.replay_vision.backend.semantic_space import (
    SEMANTIC_DIMENSIONS,
    SemanticSpace,
    nearest_cluster,
    pack,
    unpack,
)

FEED_GROUP_MIN_SIMILARITY = 0.65
FEED_GROUP_MIN_RAW_SIMILARITY = 0.90
# A group with no new member for this long stops taking members, so a story that returns later starts a new card.
FEED_GROUP_ACTIVE_WINDOW = timedelta(days=30)
MAX_CACHED_GROUPS_PER_SCANNER = 20_000
MAX_CACHED_GROUPS = 200_000


class _ScannerGroups:
    """One scanner's active groups as arrays with spare capacity, and the centre member count they reflect."""

    def __init__(self, groups: list[ReplayScannerFeedGroup], version: int) -> None:
        self.size = len(groups)
        capacity = max(16, self.size * 2)
        self.ids: list[uuid.UUID] = [group.id for group in groups]
        self._sums = np.zeros((capacity, SEMANTIC_DIMENSIONS), dtype=np.float32)
        self._counts = np.zeros(capacity, dtype=np.float32)
        self._last = np.zeros(capacity, dtype=np.float64)
        for index, group in enumerate(groups):
            self._sums[index] = unpack(group.vector_sum)
            self._counts[index] = group.member_count
            self._last[index] = group.last_member_at.timestamp()
        self.version = version

    def __len__(self) -> int:
        return self.size

    @property
    def sums(self) -> np.ndarray:
        return self._sums[: self.size]

    @property
    def counts(self) -> np.ndarray:
        return self._counts[: self.size]

    @property
    def last(self) -> np.ndarray:
        return self._last[: self.size]

    def add(self, group_id: uuid.UUID, vector: np.ndarray, at: datetime) -> None:
        if self.size == len(self._counts):
            self._sums = np.concatenate([self._sums, np.zeros_like(self._sums)])
            self._counts = np.concatenate([self._counts, np.zeros_like(self._counts)])
            self._last = np.concatenate([self._last, np.zeros_like(self._last)])
        self.ids.append(group_id)
        self._sums[self.size] = vector
        self._counts[self.size] = 1.0
        self._last[self.size] = at.timestamp()
        self.size += 1

    def trim(self, now: datetime) -> None:
        """Drop groups that stopped taking members, then the least recent ones above the per-scanner cap."""
        keep = np.nonzero(self.last >= (now - FEED_GROUP_ACTIVE_WINDOW).timestamp())[0]
        if len(keep) > MAX_CACHED_GROUPS_PER_SCANNER:
            keep = keep[np.argsort(self.last[keep])[-MAX_CACHED_GROUPS_PER_SCANNER:]]
        if len(keep) == self.size:
            return
        self.ids = [self.ids[i] for i in keep]
        self._sums[: len(keep)] = self.sums[keep]
        self._counts[: len(keep)] = self.counts[keep]
        self._last[: len(keep)] = self.last[keep]
        self.size = len(keep)


class FeedGroupCache:
    def __init__(self) -> None:
        self._scanners: OrderedDict[str, _ScannerGroups] = OrderedDict()

    def assign(self, *, team_id: int, scanner_id: str, space: SemanticSpace, version: int, now: datetime) -> uuid.UUID:
        """Put one observation in its scanner's closest active group, or start a group. Call under the centre lock,
        with the centre's member count before this observation joins."""
        groups = self._load(team_id, scanner_id, version, now)
        best = nearest_cluster(
            groups.sums, groups.counts, space, FEED_GROUP_MIN_SIMILARITY, FEED_GROUP_MIN_RAW_SIMILARITY
        )
        if best is None:
            group = ReplayScannerFeedGroup.objects.for_team(team_id).create(
                team_id=team_id,
                scanner_id=scanner_id,
                vector_sum=pack(space.vector),
                member_count=1,
                last_member_at=now,
            )
            groups.add(group.id, space.vector, now)
            group_id = group.id
        else:
            group_id = groups.ids[best]
            groups.sums[best] += space.vector
            groups.counts[best] += 1
            groups.last[best] = max(groups.last[best], now.timestamp())
            # The backfill replays old rows while the consumer adds new ones, so the latest member time never moves back.
            ReplayScannerFeedGroup.objects.for_team(team_id).filter(id=group_id).update(
                vector_sum=pack(groups.sums[best]),
                member_count=F("member_count") + 1,
                last_member_at=Greatest("last_member_at", now),
            )
        groups.version = version + 1
        return group_id

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
        total = sum(len(groups) for groups in self._scanners.values())
        while total > MAX_CACHED_GROUPS and len(self._scanners) > 1:
            _, evicted = self._scanners.popitem(last=False)
            total -= len(evicted)

    def clear(self) -> None:
        self._scanners.clear()


feed_group_cache = FeedGroupCache()
