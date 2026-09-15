import hashlib
from collections.abc import Iterable

from posthog.dataclasses import frozen

from products.reaperhog.backend.facade.enums import BlockedReason, ClusterRank, RootKind
from products.reaperhog.backend.logic.artefacts import Hit
from products.reaperhog.backend.logic.constants import MAX_DIRECTORY_LINES, MAX_REFERENCE_FILES
from products.reaperhog.backend.logic.owners import OwnerRule, dominant_owner


@frozen
class ClusterDraft:
    hash: str
    root_kind: RootKind
    root: str
    rank: ClusterRank
    blocked_reason: BlockedReason | None
    scouts: tuple[str, ...]
    files: tuple[str, ...]
    reference_count: int
    line_count: int
    owner: str | None
    hits: tuple[Hit, ...]

    @property
    def strong(self) -> bool:
        return self.rank == ClusterRank.STRONG and self.blocked_reason is None


def cluster_hash(root_kind: RootKind, root: str) -> str:
    return hashlib.sha256(f"{root_kind}:{root}".encode()).hexdigest()[:16]


def converge(hits: Iterable[Hit], *, owner_rules: Iterable[OwnerRule] = ()) -> list[ClusterDraft]:
    rules = tuple(owner_rules)
    grouped: dict[tuple[RootKind, str], list[Hit]] = {}
    for hit in hits:
        grouped.setdefault((hit.root_kind, hit.root), []).append(hit)
    drafts = [_draft(root_kind, root, group, rules) for (root_kind, root), group in grouped.items()]
    return sorted(drafts, key=lambda d: (d.rank != ClusterRank.STRONG, d.blocked_reason is not None, d.root))


def _draft(root_kind: RootKind, root: str, hits: list[Hit], rules: tuple[OwnerRule, ...]) -> ClusterDraft:
    scouts = tuple(sorted({hit.scout.value for hit in hits}))
    files = tuple(sorted({file for hit in hits for file in hit.files}))
    reference_count = max(hit.reference_count for hit in hits)
    line_count = max(hit.line_count for hit in hits)
    decisive = any(hit.decisive for hit in hits)
    rank = ClusterRank.STRONG if decisive or len(scouts) >= 2 else ClusterRank.WEAK
    blocked = None
    if root_kind == RootKind.DIRECTORY and line_count > MAX_DIRECTORY_LINES:
        blocked = BlockedReason.OVERSIZE
    elif root_kind != RootKind.DIRECTORY and len(files) > MAX_REFERENCE_FILES:
        blocked = BlockedReason.OVERSIZE
    return ClusterDraft(
        hash=cluster_hash(root_kind, root),
        root_kind=root_kind,
        root=root,
        rank=rank,
        blocked_reason=blocked,
        scouts=scouts,
        files=files,
        reference_count=reference_count,
        line_count=line_count,
        owner=dominant_owner(files, rules) if rules else None,
        hits=tuple(hits),
    )
