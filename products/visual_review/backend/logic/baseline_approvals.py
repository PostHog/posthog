"""Approval rows of the baseline ledger: which ones a run counts, writing them at finalize, and evidence.

An approval says that one pull request approved one hash for one identifier. It applies to a run
only while the baseline it replaced still holds, so a run never compares against an approval that a
later merge made stale.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from ..classifier import ToleratedKey
from ..db import WRITER_DB
from ..facade.enums import (
    BaselineApprovalState,
    BaselineEvidence,
    BaselineMode,
    ReviewState,
    RunPurpose,
    RunStatus,
    SnapshotResult,
)
from ..models import BaselineApproval, Run, RunSnapshot, ToleratedHash
from . import baseline_record, github_api, ledger, quarantine, toleration
from .baseline_record import OverlayEntry

logger = structlog.get_logger(__name__)

DETAIL_SUPERSEDED = "A later approval in the same pull request replaced this one"
DETAIL_BACK_TO_BASELINE = "The pull request went back to the baseline picture"


def reproduces_by_hash(
    identifier: str, render_hash: str, target_hash: str, tolerated_lookup: dict[ToleratedKey, ToleratedHash]
) -> bool:
    """Whether a render stands for the target without a pixel diff: the same hash, or a live toleration.

    The lookup from `toleration.build_tolerated_lookup` already holds both directions of a pair.
    """
    if not render_hash or not target_hash:
        return False
    if render_hash == target_hash:
        return True
    return ToleratedKey(identifier=identifier, baseline_hash=target_hash, current_hash=render_hash) in tolerated_lookup


def base_still_holds(approval: BaselineApproval, current_hash: str) -> bool:
    """Whether the ledger's hash is still a baseline the approval was made over. An empty hash is a value too.

    The effective base counts because a stack parent that landed puts on the ledger what the reviewer compared against.
    """
    return current_hash in (approval.ledger_base_hash, approval.effective_base_hash)


def _approval_applies(approval: BaselineApproval, ledger_hashes: dict[str, str]) -> bool:
    return base_still_holds(approval, ledger_hashes.get(approval.identifier, ""))


@frozen
class CommitGraph:
    """The parent links of the commits that a run's tree has beyond its merge-base."""

    parents: dict[str, tuple[str, ...]]

    @classmethod
    def from_comparison(cls, comparison: github_api.Comparison) -> CommitGraph:
        return cls(parents={commit.sha: commit.parent_shas for commit in comparison.commits})

    def descends_from(self, sha: str, ancestor_sha: str) -> bool:
        """Whether `ancestor_sha` is a strict ancestor of `sha`. A commit outside the graph has no known parents."""
        seen: set[str] = set()
        pending = list(self.parents.get(sha, ()))
        while pending:
            current = pending.pop()
            if current == ancestor_sha:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self.parents.get(current, ()))
        return False


@frozen
class Overlay:
    entries: dict[str, OverlayEntry]
    # Every candidate that applied, also the ones the reduction dropped.
    candidate_approval_ids: tuple[UUID, ...]
    conflicts: dict[str, tuple[int, ...]]


def _newest_run_commits(run: Run, pr_numbers: Iterable[int]) -> dict[int, str]:
    newest = (
        Run.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, pr_number__in=list(pr_numbers), superseded_by__isnull=True)
        .order_by("pr_number", "-created_at")
        .distinct("pr_number")
        .values_list("pr_number", "commit_sha")
    )
    return {pr_number: commit_sha for pr_number, commit_sha in newest if pr_number is not None}


def _candidates(run: Run, comparison: github_api.Comparison | None, position: int) -> list[BaselineApproval]:
    """The approvals whose commits the run's tree contains and that the ledger at `position` does not hold yet."""
    if comparison is None:
        return []
    # An approval that landed after the run's ledger position is promoted, but the ledger the run
    # reads does not hold its hash. Without it a run that started before the landing, such as a
    # queue run of the next pull request or a stack child before its rebase, sees the approved
    # change as unapproved.
    outside_ledger = Q(state=BaselineApprovalState.OPEN) | Q(
        state=BaselineApprovalState.PROMOTED, landed_position__gt=position
    )
    pending = BaselineApproval.objects.using(WRITER_DB).filter(
        outside_ledger, repo_id=run.repo_id, run_type=run.run_type
    )
    # A list cut short cannot prove that another pull request's commit is absent, so only the
    # run's own pull request counts.
    if not comparison.complete:
        if run.pr_number is None:
            return []
        return list(pending.filter(pr_number=run.pr_number))

    contained = [commit.sha for commit in comparison.commits]
    in_tree = Q(commit_sha__in=contained) | Q(carried_commit_sha__in=contained)
    if run.pr_number is not None:
        in_tree |= Q(pr_number=run.pr_number)
    rest = pending.exclude(in_tree)
    rest_prs = set(rest.values_list("pr_number", flat=True).distinct())
    prs_with_contained_head = [
        pr_number for pr_number, commit_sha in _newest_run_commits(run, rest_prs).items() if commit_sha in contained
    ]
    approvals = list(pending.filter(in_tree))
    if prs_with_contained_head:
        approvals += list(rest.filter(pr_number__in=prs_with_contained_head))
    return approvals


def _approval_commits(approval: BaselineApproval) -> list[str]:
    return [sha for sha in (approval.commit_sha, approval.carried_commit_sha) if sha]


def _approval_descends_from(approval: BaselineApproval, other: BaselineApproval, commit_graph: CommitGraph) -> bool:
    return any(
        commit_graph.descends_from(sha, other_sha)
        for sha in _approval_commits(approval)
        for other_sha in _approval_commits(other)
    )


def approvals_that_count(approvals: list[BaselineApproval], ledger_hashes: dict[str, str]) -> list[BaselineApproval]:
    """The approvals whose base the ledger holds, and the stack layers approved over the picture of one of those.

    A layer approved over the open layer below it keeps counting after a lower layer of the stack lands
    alone, as long as the layer below still counts. The effective base comes from the overlay of the
    approved run, so a match proves the lower approval was in the upper layer's tree then. The caller
    passes only approvals in the run's tree, which covers now. Commits are not compared, because a
    restack leaves the approved commits out of the new tree. The order of `approvals` is kept.
    """
    counted_ids = {approval.id for approval in approvals if _approval_applies(approval, ledger_hashes)}
    # The uncounted approvals by the picture they were approved over, per identifier.
    over_picture: dict[str, dict[str, list[BaselineApproval]]] = {}
    for approval in approvals:
        if approval.id not in counted_ids:
            by_base = over_picture.setdefault(approval.identifier, {})
            by_base.setdefault(approval.effective_base_hash, []).append(approval)
    pending = [approval for approval in approvals if approval.id in counted_ids]
    while pending:
        lower = pending.pop()
        for upper in over_picture.get(lower.identifier, {}).get(lower.content_hash, []):
            if upper.id in counted_ids or upper.pr_number == lower.pr_number:
                continue
            counted_ids.add(upper.id)
            pending.append(upper)
    return [approval for approval in approvals if approval.id in counted_ids]


def _stack_tip(approvals: list[BaselineApproval], commit_graph: CommitGraph | None) -> BaselineApproval | None:
    """The one approval whose commit descends from the commits of all the other approvals, if there is one.

    That approval is the top of a stack. Its tree contains the changes of the layers below it, so
    the run renders its picture.
    """
    if commit_graph is None:
        return None
    tips = [
        approval
        for approval in approvals
        if all(_approval_descends_from(approval, other, commit_graph) for other in approvals if other.id != approval.id)
    ]
    if len(tips) != 1:
        return None
    return tips[0]


def reduce_overlay(
    candidates: list[BaselineApproval], ledger_hashes: dict[str, str], commit_graph: CommitGraph | None = None
) -> Overlay:
    """The overlay entry per identifier from the candidate approvals of a run, and the conflicts.

    A candidate applies only while the ledger holds its base, or while it chains on a candidate that
    applies (see `approvals_that_count`). A stack child wins over its parent,
    two pull requests with different hashes conflict, and otherwise the newest approval wins.
    Without `commit_graph` a stack child wins only when it was approved over its parent's picture.
    """
    applicable = approvals_that_count(candidates, ledger_hashes)

    by_identifier: dict[str, list[BaselineApproval]] = {}
    for approval in applicable:
        by_identifier.setdefault(approval.identifier, []).append(approval)

    entries: dict[str, OverlayEntry] = {}
    conflicts: dict[str, tuple[int, ...]] = {}
    for identifier, approvals in sorted(by_identifier.items()):
        # A stack parent's hash is the base its child approved over, so the child wins.
        remaining = [
            approval
            for approval in approvals
            if not any(
                other.id != approval.id and other.effective_base_hash == approval.content_hash for other in approvals
            )
        ]
        if not remaining:
            continue
        if len({approval.content_hash for approval in remaining}) > 1:
            # A stack child approved before its parent was approved over the old baseline, so the
            # rule above cannot see the stack. The commit graph can.
            tip = _stack_tip(remaining, commit_graph)
            if tip is None:
                conflicts[identifier] = tuple(sorted({approval.pr_number for approval in remaining}))
                continue
            remaining = [tip]
        chosen = max(remaining, key=lambda approval: (approval.approved_at, approval.id))
        entries[identifier] = OverlayEntry(
            content_hash=chosen.content_hash,
            approval_id=chosen.id,
            pr_number=chosen.pr_number,
            ledger_hash=ledger_hashes.get(identifier, ""),
        )

    return Overlay(
        entries=entries,
        candidate_approval_ids=tuple(approval.id for approval in applicable),
        conflicts=conflicts,
    )


def _closed_without_entry(approval: BaselineApproval) -> bool:
    return approval.state not in (BaselineApprovalState.OPEN, BaselineApprovalState.PROMOTED)


def _rests_on_lower_layer(approval: BaselineApproval, ledger_hashes: dict[str, str]) -> bool:
    """Whether the approval counts through its ledger base only, and was made over a lower stack layer's picture.

    The ledger base is the ledger hash under that picture, so the approval counts by itself also after
    the lower layer's approval closed. The picture the reviewer compared against reaches the ledger
    only through the lower layer's approval.
    """
    return (
        approval.effective_base_hash != approval.ledger_base_hash
        and ledger_hashes.get(approval.identifier, "") == approval.ledger_base_hash
    )


@frozen
class SuccessorKey:
    """One picture of one story in one pull request, which a later approval of that pull request can carry."""

    pr_number: int
    run_type: str
    identifier: str
    content_hash: str

    @classmethod
    def of(cls, approval: BaselineApproval) -> SuccessorKey:
        return cls(
            pr_number=approval.pr_number,
            run_type=approval.run_type,
            identifier=approval.identifier,
            content_hash=approval.content_hash,
        )


class LowerLayerWalk:
    """Follows approvals made over a lower stack layer's picture down to the approvals of the lower layers.

    An approval names the approval it was made over in `base_approval`. A row written before that column
    existed is followed through the frozen overlay of its source run. A row of the same pull request is
    followed further down, because its successor replaced it. The walk stops where the ledger holds the
    hash that a layer was made over, and at a promoted approval.
    """

    def __init__(
        self, ledger_hashes: dict[str, str], records: dict[UUID, baseline_record.BaselineRecord | None] | None = None
    ) -> None:
        self.ledger_hashes = ledger_hashes
        # The frozen records of source runs by run id, so that each run is read once per walk.
        self.records = dict(records or {})
        # Approvals read so far by id, so that a long chain of one pull request's approvals is read once.
        self.approvals: dict[UUID, BaselineApproval] = {}

    def successors(self, closed: list[BaselineApproval]) -> dict[SuccessorKey, BaselineApproval]:
        """The open or promoted approval of the same pull request and picture, per closed approval.

        A pull request that approved the same picture again lands it through the newer row. An open
        row counts under the same rule as everywhere else: its base is on the ledger, or it was made
        over an open stack layer that counts.
        """
        if not closed:
            return {}
        wanted = {SuccessorKey.of(approval) for approval in closed}
        same_stories = BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=closed[0].team_id,
            repo_id=closed[0].repo_id,
            run_type__in={approval.run_type for approval in closed},
            identifier__in={approval.identifier for approval in closed},
            state__in=(BaselineApprovalState.OPEN, BaselineApprovalState.PROMOTED),
        )
        open_by_run_type: dict[str, list[BaselineApproval]] = {}
        promoted: list[BaselineApproval] = []
        for row in same_stories:
            if row.state == BaselineApprovalState.PROMOTED:
                promoted.append(row)
            else:
                open_by_run_type.setdefault(row.run_type, []).append(row)
        counted = [
            row
            for open_rows in open_by_run_type.values()
            for row in approvals_that_count(open_rows, self.ledger_hashes)
        ]
        found: dict[SuccessorKey, BaselineApproval] = {}
        for row in [*promoted, *counted]:
            key = SuccessorKey.of(row)
            if key in wanted:
                found.setdefault(key, row)
        return found

    def _read_records(self, run_ids: set[UUID]) -> None:
        missing = run_ids - set(self.records)
        if not missing:
            return
        self.records.update(dict.fromkeys(missing))
        for source_run in Run.objects.using(WRITER_DB).filter(id__in=missing).only("id", "metadata"):
            self.records[source_run.id] = baseline_record.record_for_run(source_run)

    def _read_approvals(self, ids: set[UUID], team_id: int, repo_id: UUID) -> None:
        """Reads these approvals, and with them the other approvals of their pull requests and stories.

        A pull request that approved a story several times chains each approval to the one before,
        so the whole chain comes in with its first link.
        """
        missing = ids - set(self.approvals)
        if not missing:
            return
        rows = list(BaselineApproval.objects.using(WRITER_DB).filter(team_id=team_id, repo_id=repo_id, id__in=missing))
        if not rows:
            return
        same_story = Q()
        for row in rows:
            same_story |= Q(pr_number=row.pr_number, run_type=row.run_type, identifier=row.identifier)
        for row in BaselineApproval.objects.using(WRITER_DB).filter(same_story, team_id=team_id, repo_id=repo_id):
            self.approvals.setdefault(row.id, row)

    def _lower_layer_ids(self, nodes: list[BaselineApproval]) -> dict[UUID, UUID | None]:
        """The id of the approval each node was made over, by node id. None when nothing names it any more.

        A node is left out when its source run's record applied no approval with the node's effective
        base. That happens in `shadow` mode, where the effective base comes from the baseline file.
        """
        self._read_records(
            {node.source_run_id for node in nodes if node.base_approval_id is None and node.source_run_id is not None}
        )
        lower_ids: dict[UUID, UUID | None] = {}
        for node in nodes:
            if node.base_approval_id is not None:
                lower_ids[node.id] = node.base_approval_id
                continue
            record = None if node.source_run_id is None else self.records[node.source_run_id]
            if record is None:
                lower_ids[node.id] = None
                continue
            entry = record.overlay.get(node.identifier)
            if entry is not None and entry.content_hash == node.effective_base_hash:
                lower_ids[node.id] = entry.approval_id
        return lower_ids

    @staticmethod
    def _node_pr(steps: list[tuple[BaselineApproval, BaselineApproval]], node_id: UUID) -> int:
        return next(node.pr_number for _top, node in steps if node.id == node_id)

    def closed_bases(self, approvals: list[BaselineApproval]) -> dict[UUID, BaselineApproval | None]:
        """Per given approval that rests on a lower layer that closed without a ledger entry, that layer's approval.

        The value is None when the walk cannot name the lower layer any more. That counts as closed,
        because then nothing shows that the picture the reviewer compared against can reach the ledger.
        """
        closed: dict[UUID, BaselineApproval | None] = {}
        # Pairs of the approval the caller asked about and the approval whose lower layer is read next.
        steps = [
            (approval, approval)
            for approval in approvals
            if approval.state == BaselineApprovalState.OPEN and _rests_on_lower_layer(approval, self.ledger_hashes)
        ]
        visited = {(top.id, node.id) for top, node in steps}
        while steps:
            lower_ids = self._lower_layer_ids([node for _top, node in steps])
            first = steps[0][1]
            self._read_approvals(
                {lower_id for lower_id in lower_ids.values() if lower_id is not None}, first.team_id, first.repo_id
            )
            lowers = self.approvals
            # Only a closed layer of another pull request can have a successor that carries its picture.
            successors = self.successors(
                [
                    lowers[lower_id]
                    for node_id, lower_id in lower_ids.items()
                    if lower_id in lowers
                    and _closed_without_entry(lowers[lower_id])
                    and lowers[lower_id].pr_number != self._node_pr(steps, node_id)
                ]
            )
            next_steps: list[tuple[BaselineApproval, BaselineApproval]] = []
            for top, node in steps:
                if node.id not in lower_ids:
                    continue
                lower_id = lower_ids[node.id]
                lower = None if lower_id is None else lowers.get(lower_id)
                if lower is None:
                    closed[top.id] = None
                    continue
                if _closed_without_entry(lower) and lower.pr_number != node.pr_number:
                    successor = successors.get(SuccessorKey.of(lower))
                    if successor is None:
                        closed[top.id] = lower
                        continue
                    lower = successor
                if lower.state == BaselineApprovalState.PROMOTED or (top.id, lower.id) in visited:
                    continue
                visited.add((top.id, lower.id))
                if _rests_on_lower_layer(lower, self.ledger_hashes):
                    next_steps.append((top, lower))
            steps = next_steps
        return closed


def without_closed_lower_layers(
    approvals: list[BaselineApproval], ledger_hashes: dict[str, str]
) -> list[BaselineApproval]:
    """The approvals, without the ones made over the picture of a lower stack layer that closed without an entry.

    Such an approval counts by itself through its ledger base, but the picture the reviewer compared
    against never reaches the ledger. Without it the run shows the change against the ledger, so the
    pull request can approve it again.
    """
    closed = LowerLayerWalk(ledger_hashes).closed_bases(approvals)
    if not closed:
        return approvals
    return [approval for approval in approvals if approval.id not in closed]


def same_picture_predecessors(closed: list[BaselineApproval]) -> list[BaselineApproval]:
    """The superseded approvals of the same pull request and picture as the closed ones.

    An upper layer made over such a row, or a run that applied it, stays fresh through its
    successor, so it depends on the successor without naming it.
    """
    keys = {SuccessorKey.of(approval) for approval in closed}
    rows = (
        BaselineApproval.objects.using(WRITER_DB)
        .filter(
            team_id=closed[0].team_id,
            repo_id=closed[0].repo_id,
            state=BaselineApprovalState.SUPERSEDED,
            pr_number__in={key.pr_number for key in keys},
            identifier__in={key.identifier for key in keys},
            content_hash__in={key.content_hash for key in keys},
        )
        .only("id", "pr_number", "run_type", "identifier", "content_hash")
    )
    return [row for row in rows if SuccessorKey.of(row) in keys]


def _made_over_by_hash(lower: list[BaselineApproval]) -> list[BaselineApproval]:
    """Open approvals written before `base_approval` existed whose effective base is one of these approvals' pictures."""
    pictures = {(approval.run_type, approval.identifier, approval.content_hash) for approval in lower}
    rows = (
        BaselineApproval.objects.using(WRITER_DB)
        .filter(
            team_id=lower[0].team_id,
            repo_id=lower[0].repo_id,
            state=BaselineApprovalState.OPEN,
            base_approval__isnull=True,
            identifier__in={identifier for _run_type, identifier, _hash in pictures},
            effective_base_hash__in={content_hash for _run_type, _identifier, content_hash in pictures},
        )
        .exclude(effective_base_hash=F("ledger_base_hash"))
    )
    return [row for row in rows if (row.run_type, row.identifier, row.effective_base_hash) in pictures]


def open_approvals_made_over(closed: list[BaselineApproval]) -> list[BaselineApproval]:
    """The open approvals whose chain of base approvals reaches one of the closed approvals.

    A closed row in the chain is followed too, because a later approval of the same pull request
    names the row it replaced. A row written before `base_approval` existed is matched by the
    picture it was made over, at every step of the chain.
    """
    if not closed:
        return []
    seen = {approval.id for approval in [*closed, *same_picture_predecessors(closed)]}
    lower, lower_ids = closed, set(seen)
    made_over: list[BaselineApproval] = []
    while lower_ids:
        linked = BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=closed[0].team_id, repo_id=closed[0].repo_id, base_approval_id__in=lower_ids
        )
        rows = {row.id: row for row in [*linked, *_made_over_by_hash(lower)] if row.id not in seen}
        seen |= set(rows)
        made_over += [row for row in rows.values() if row.state == BaselineApprovalState.OPEN]
        lower, lower_ids = list(rows.values()), set(rows)
    return made_over


def overlay_for_run(
    run: Run, comparison: github_api.Comparison | None, position: int, ledger_hashes: dict[str, str]
) -> Overlay:
    """The approvals a run compares against on top of the ledger at `position`, per identifier.

    `comparison` is None for a run on the default branch, which has no candidates.
    """
    commit_graph = None if comparison is None else CommitGraph.from_comparison(comparison)
    candidates = without_closed_lower_layers(_candidates(run, comparison, position), ledger_hashes)
    return reduce_overlay(candidates, ledger_hashes, commit_graph)


def _ledger_base_hashes(
    run: Run, record: baseline_record.BaselineRecord, snapshots: list[RunSnapshot]
) -> dict[str, str]:
    """The ledger hash each approved snapshot replaced, as the run resolved it, not as the ledger is now.

    In a ledger-mode record the stamped baseline is the ledger hash wherever no overlay supplied
    it. A shadow-mode record stamped the YAML baseline, which equals the ledger hash except for the
    identifiers in `differences`. Those cover rendered identifiers only, so a removed one is read from
    the ledger at the record's position.
    """
    bases: dict[str, str] = {}
    unknown: list[str] = []
    differences = record.differences or {}
    for snapshot in snapshots:
        identifier = snapshot.identifier
        if identifier in record.overlay:
            bases[identifier] = record.overlay[identifier].ledger_hash
        elif record.mode == BaselineMode.LEDGER:
            bases[identifier] = snapshot.baseline_hash
        elif identifier in differences:
            bases[identifier] = differences[identifier]
        elif record.differences_truncated or snapshot.result == SnapshotResult.REMOVED:
            unknown.append(identifier)
        else:
            bases[identifier] = snapshot.baseline_hash
    if unknown:
        fallback = ledger.hashes_at(run.repo_id, run.run_type, unknown, record.position)
        bases.update({identifier: fallback.get(identifier, "") for identifier in unknown})
    return bases


def _base_approval_id(entry: OverlayEntry | None, effective_base_hash: str, ledger_base_hash: str) -> UUID | None:
    """The overlay approval whose picture the reviewer compared against, when that picture is not on the ledger."""
    if entry is None or entry.content_hash != effective_base_hash or effective_base_hash == ledger_base_hash:
        return None
    return entry.approval_id


def _republish_after_close(run: Run, closed: list[BaselineApproval]) -> None:
    from . import commit_status  # noqa: PLC0415 — commit_status imports this module

    commit_status.publish_after_approvals_close(run.repo, closed)


def record_approvals(run: Run, user_id: int, *, carried_commit_sha: str = "", name_deciders: bool = False) -> int:
    """Write one approval row per approved change of a finalized run. Returns the number written.

    `carried_commit_sha` is the baseline commit finalize pushed to the pull request branch, if any.
    With `name_deciders` each row names the person whose accept counts, which finalize wrote onto the
    snapshot, instead of the person who finalized. The caller holds the ledger lock and then the
    run's row lock, inside a transaction on the writer database.
    """
    record = baseline_record.record_for_run(run)
    if record is None:
        logger.warning("visual_review.baseline_approvals_without_record", run_id=str(run.id))
        return 0
    if run.pr_number is None:
        logger.warning("visual_review.baseline_approvals_without_pull_request", run_id=str(run.id))
        return 0

    approved_snapshots = list(
        run.snapshots.using(WRITER_DB).filter(
            review_state=ReviewState.APPROVED,
            result__in=(SnapshotResult.NEW, SnapshotResult.CHANGED, SnapshotResult.REMOVED),
        )
    )
    if not approved_snapshots:
        return 0
    ledger_bases = _ledger_base_hashes(run, record, approved_snapshots)
    now = timezone.now()

    new_approvals: list[BaselineApproval] = []
    back_to_baseline: list[str] = []
    for snapshot in approved_snapshots:
        approved_hash = "" if snapshot.result == SnapshotResult.REMOVED else snapshot.approved_hash
        ledger_base_hash = ledger_bases.get(snapshot.identifier, "")
        if approved_hash == ledger_base_hash:
            back_to_baseline.append(snapshot.identifier)
            continue
        new_approvals.append(
            BaselineApproval(
                repo_id=run.repo_id,
                team_id=run.team_id,
                run_type=run.run_type,
                pr_number=run.pr_number,
                identifier=snapshot.identifier,
                content_hash=approved_hash,
                ledger_base_hash=ledger_base_hash,
                effective_base_hash=snapshot.baseline_hash,
                base_approval_id=_base_approval_id(
                    record.overlay.get(snapshot.identifier), snapshot.baseline_hash, ledger_base_hash
                ),
                commit_sha=run.commit_sha,
                carried_commit_sha=carried_commit_sha,
                source_run=run,
                approved_by_id=(snapshot.reviewed_by_id or user_id) if name_deciders else user_id,
                approved_at=now,
            )
        )

    open_approvals = BaselineApproval.objects.using(WRITER_DB).filter(
        repo_id=run.repo_id, run_type=run.run_type, pr_number=run.pr_number, state=BaselineApprovalState.OPEN
    )
    closed = list(
        open_approvals.filter(
            identifier__in=[*back_to_baseline, *(approval.identifier for approval in new_approvals)]
        ).only("id", "run_type")
    )
    open_approvals.filter(identifier__in=back_to_baseline).update(
        state=BaselineApprovalState.SUPERSEDED, detail=DETAIL_BACK_TO_BASELINE, resolved_at=now, updated_at=now
    )
    open_approvals.filter(identifier__in=[approval.identifier for approval in new_approvals]).update(
        state=BaselineApprovalState.SUPERSEDED, detail=DETAIL_SUPERSEDED, resolved_at=now, updated_at=now
    )
    BaselineApproval.objects.using(WRITER_DB).bulk_create(new_approvals)
    _republish_after_close(run, closed)
    return len(new_approvals)


def rendered_approved_hash(
    approval: BaselineApproval,
    snapshot: RunSnapshot | None,
    is_partial: bool,
    tolerated_lookup: dict[ToleratedKey, ToleratedHash],
) -> bool:
    """Whether a run's render of the approval's identifier reproduces the approved picture."""
    rendered = snapshot is not None and snapshot.result != SnapshotResult.REMOVED
    if not approval.content_hash:
        # A partial run leaves stories out on purpose, so a missing render proves no removal.
        return not rendered and not is_partial
    if snapshot is None or not rendered:
        return False
    if snapshot.result == SnapshotResult.UNCHANGED and snapshot.baseline_hash == approval.content_hash:
        return True
    return reproduces_by_hash(approval.identifier, snapshot.current_hash, approval.content_hash, tolerated_lookup)


def _reproduction(run: Run, approvals: list[BaselineApproval]) -> dict[UUID, bool]:
    identifiers = {approval.identifier for approval in approvals}
    snapshots = {
        snapshot.identifier: snapshot
        for snapshot in run.snapshots.using(WRITER_DB)
        .filter(identifier__in=identifiers)
        .only("identifier", "current_hash", "baseline_hash", "result")
    }
    tolerated_lookup = toleration.build_tolerated_lookup(
        run.repo_id,
        identifiers,
        {approval.content_hash for approval in approvals if approval.content_hash},
        now=timezone.now(),
    )
    return {
        approval.id: rendered_approved_hash(
            approval, snapshots.get(approval.identifier), run.is_partial, tolerated_lookup
        )
        for approval in approvals
    }


def _back_to_baseline(run: Run, approvals: list[BaselineApproval]) -> list[UUID]:
    """The approvals whose identifier this run rendered unchanged against a baseline that is not the approved hash.

    The pull request went back to that baseline, so the approval would otherwise stay open and
    land without evidence. Quarantined identifiers are left alone, because their renders gate nothing.
    """
    unchanged_baselines = dict(
        run.snapshots.using(WRITER_DB)
        .filter(identifier__in={approval.identifier for approval in approvals}, result=SnapshotResult.UNCHANGED)
        .values_list("identifier", "baseline_hash")
    )
    quarantined = set(
        quarantine.active_quarantined_identifiers(run.repo_id, run.team_id, run.run_type, using=WRITER_DB)
    )
    return [
        approval.id
        for approval in approvals
        if approval.identifier in unchanged_baselines
        and unchanged_baselines[approval.identifier] != approval.content_hash
        and approval.identifier not in quarantined
    ]


def record_carried_commits(run: Run) -> None:
    """Point the pull request's open approvals that this run reproduced at the run's commit.

    After a rebase the approved commit is no longer in the branch, and the carried commit is what
    keeps the approval among a later run's candidates. In ledger mode an approval the run went
    back from is superseded. In shadow mode the snapshot was compared with the YAML file, so
    finalize handles that case instead.
    """
    if run.pr_number is None or run.superseded_by_id is not None:
        return
    approvals = list(
        BaselineApproval.objects.using(WRITER_DB).filter(
            repo_id=run.repo_id, run_type=run.run_type, pr_number=run.pr_number, state=BaselineApprovalState.OPEN
        )
    )
    if not approvals:
        return
    superseded = _back_to_baseline(run, approvals) if run.repo.baseline_mode == BaselineMode.LEDGER else []
    remaining = [approval for approval in approvals if approval.id not in superseded]
    reproduced = [approval_id for approval_id, ok in _reproduction(run, remaining).items() if ok] if remaining else []
    if not reproduced and not superseded:
        return
    now = timezone.now()
    with transaction.atomic(using=WRITER_DB):
        ledger.lock_ledger(run.repo_id)
        # A newer run may have superseded this one and been finalized since the read above.
        if not Run.objects.using(WRITER_DB).filter(id=run.id, superseded_by__isnull=True).exists():
            return
        BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=run.team_id, id__in=superseded, state=BaselineApprovalState.OPEN
        ).update(
            state=BaselineApprovalState.SUPERSEDED, detail=DETAIL_BACK_TO_BASELINE, resolved_at=now, updated_at=now
        )
        _republish_after_close(run, [approval for approval in approvals if approval.id in superseded])
        BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=run.team_id, id__in=reproduced, state=BaselineApprovalState.OPEN
        ).update(carried_commit_sha=run.commit_sha, updated_at=now)


def is_stale(approval: BaselineApproval, current_hash: str) -> bool:
    """Whether landing the approval now would make it `conflicted`.

    The approved hash counts as fresh because the ledger already holds that picture.
    """
    return current_hash != approval.content_hash and not base_still_holds(approval, current_hash)


def _hashes_the_run_approved(run: Run) -> dict[str, str]:
    """The hash this run's own finalize approved per identifier, empty for a removal."""
    if not run.approved:
        return {}
    approved = (
        run.snapshots.using(WRITER_DB)
        .filter(
            review_state=ReviewState.APPROVED,
            result__in=(SnapshotResult.NEW, SnapshotResult.CHANGED, SnapshotResult.REMOVED),
        )
        .values_list("identifier", "result", "approved_hash")
    )
    return {
        identifier: "" if result == SnapshotResult.REMOVED else approved_hash
        for identifier, result, approved_hash in approved
    }


def _replaced_by_the_run(run: Run, approval: BaselineApproval, approved: dict[str, str]) -> bool:
    """Whether this run's own finalize superseded the approval, so the run rests on its own decision instead."""
    return (
        approval.state == BaselineApprovalState.SUPERSEDED
        and approval.pr_number == run.pr_number
        and approval.identifier in approved
    )


def _ledger_holds_the_picture(approval: BaselineApproval, approved: dict[str, str], current: dict[str, str]) -> bool:
    """Whether the ledger holds the picture the run ends with: the approval's own, or the one the run approved instead."""
    current_hash = current.get(approval.identifier, "")
    return current_hash == approval.content_hash or approved.get(approval.identifier) == current_hash


def _moved_base_approvals(
    rests_on: list[BaselineApproval], open_related: list[BaselineApproval], current: dict[str, str]
) -> list[BaselineApproval]:
    """The open approvals the run rests on whose base the ledger no longer holds.

    `open_related` also holds the open candidates of the run's record, so an approval chained on an
    open lower stack layer stays fresh while that layer's approval counts.
    """
    counted = {approval.id for approval in approvals_that_count(open_related, current)}
    return [
        approval
        for approval in rests_on
        if approval.state == BaselineApprovalState.OPEN
        and approval.id not in counted
        and is_stale(approval, current.get(approval.identifier, ""))
    ]


def _identifiers_rendering_the_ledger(run: Run, identifiers: set[str], current: dict[str, str]) -> set[str]:
    """The stories whose render on this run is the ledger's picture, so the run needs no approval for them."""
    rendered = (
        run.snapshots.using(WRITER_DB).filter(identifier__in=identifiers).values_list("identifier", "current_hash")
    )
    return {identifier for identifier, current_hash in rendered if current_hash == current.get(identifier, "")}


def _closed_approvals_the_run_rests_on(
    run: Run, rests_on: list[BaselineApproval], walk: LowerLayerWalk
) -> list[BaselineApproval]:
    """The approvals the run rests on, directly or as a lower stack layer, that closed without an entry.

    Such an approval puts nothing on the ledger, so the picture the run compared against has no
    approval behind it any more. An open approval whose lower layer the walk cannot name counts as
    closed itself. The approval is left out while the ledger holds the picture the run ends with,
    and while an open or promoted approval of the same pull request carries the same picture.
    """
    # A run that renders the ledger's picture again, such as after a revert, rests on no approval for it.
    on_ledger = _identifiers_rendering_the_ledger(
        run, {approval.identifier for approval in rests_on}, walk.ledger_hashes
    )
    rests_on = [approval for approval in rests_on if approval.identifier not in on_ledger]
    open_rests_on = [approval for approval in rests_on if approval.state == BaselineApprovalState.OPEN]
    closed = [approval for approval in rests_on if _closed_without_entry(approval)]
    uncovered: list[BaselineApproval] = []
    if closed:
        approved = _hashes_the_run_approved(run)
        closed = [
            approval
            for approval in closed
            if not _replaced_by_the_run(run, approval, approved)
            and not _ledger_holds_the_picture(approval, approved, walk.ledger_hashes)
        ]
        successors = walk.successors(closed)
        for approval in closed:
            successor = successors.get(SuccessorKey.of(approval))
            if successor is None:
                uncovered.append(approval)
            elif successor.state == BaselineApprovalState.OPEN:
                open_rests_on.append(successor)
    by_id = {approval.id: approval for approval in open_rests_on}
    for approval_id, base in walk.closed_bases(open_rests_on).items():
        uncovered.append(by_id[approval_id] if base is None else base)
    return uncovered


def stale_approvals(run: Run) -> list[BaselineApproval]:
    """The approvals the run's passing verdict rests on that cannot land the picture the run compared against.

    These are the approvals made on the run and the approvals its frozen record applied as overlay.
    An open one is stale when its base is not on the ledger. The ledger is read at the cursor and not
    at the run's merge-base, because a merge after the run makes the approval conflict when its pull
    request lands. Nothing is stored, so a revert that moves the ledger back makes the approval fresh
    again. An approval chained on an open lower stack layer among the record's candidates stays fresh
    while that layer's approval counts. An approval that closed without a ledger entry is stale,
    and so is a lower stack layer's approval that one of them was made over. A closed approval is
    not stale when this run's own finalize replaced it, when the ledger holds the picture the run
    ends with, or when a newer approval of the same pull request carries the same picture.
    """
    record = baseline_record.record_for_run(run)
    if record is None:
        return []
    overlay_approval_ids = {entry.approval_id for entry in record.overlay.values()}
    # Only finalize writes approvals with this run as their source, and finalize marks the run approved.
    if not run.approved and not overlay_approval_ids:
        return []
    related = list(
        BaselineApproval.objects.using(WRITER_DB).filter(
            Q(source_run_id=run.id) | Q(id__in=overlay_approval_ids) | Q(id__in=record.candidate_approval_ids),
            repo_id=run.repo_id,
            run_type=run.run_type,
        )
    )
    rests_on = [
        approval for approval in related if approval.source_run_id == run.id or approval.id in overlay_approval_ids
    ]
    if not rests_on:
        return []
    head = ledger.cursor(run.repo_id)
    if head is None:
        return []
    current = ledger.hashes_at(run.repo_id, run.run_type, {approval.identifier for approval in related}, head.position)
    open_related = [approval for approval in related if approval.state == BaselineApprovalState.OPEN]
    stale = _moved_base_approvals(rests_on, open_related, current)
    walk = LowerLayerWalk(current, records={run.id: record})
    # One snapshot counts once, also when it rests on a stale approval and a closed one.
    stale_identifiers = {approval.identifier for approval in stale}
    for approval in _closed_approvals_the_run_rests_on(run, rests_on, walk):
        if approval.identifier not in stale_identifiers:
            stale.append(approval)
            stale_identifiers.add(approval.identifier)
    if not stale:
        return []
    # A quarantined snapshot does not gate the run, so a stale approval of it must not gate it either.
    quarantined = set(
        run.snapshots.using(WRITER_DB)
        .filter(identifier__in={approval.identifier for approval in stale}, is_quarantined=True)
        .values_list("identifier", flat=True)
    )
    return [approval for approval in stale if approval.identifier not in quarantined]


def _is_evidence_candidate(run: Run) -> bool:
    return run.status != RunStatus.FAILED and not run.is_partial and run.purpose == RunPurpose.OBSERVE


def record_evidence(run: Run) -> None:
    """Record on each candidate approval whether this full off-default-branch run reproduced it.

    The caller runs this before it saves the run as completed, so a merge that follows a green
    queue run always finds the evidence.
    """
    if not _is_evidence_candidate(run):
        return
    record = baseline_record.record_for_run(run)
    if record is None or not record.candidate_approval_ids:
        return
    approvals = list(
        BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=run.team_id,
            repo_id=run.repo_id,
            id__in=record.candidate_approval_ids,
            state=BaselineApprovalState.OPEN,
        )
    )
    if not approvals:
        return
    reproduction = _reproduction(run, approvals)
    by_outcome: dict[BaselineEvidence, list[UUID]] = {
        BaselineEvidence.REPRODUCED: [],
        BaselineEvidence.NOT_REPRODUCED: [],
    }
    for approval in approvals:
        outcome = BaselineEvidence.REPRODUCED if reproduction[approval.id] else BaselineEvidence.NOT_REPRODUCED
        by_outcome[outcome].append(approval.id)

    now = timezone.now()
    with transaction.atomic(using=WRITER_DB):
        ledger.lock_ledger(run.repo_id)
        for outcome, approval_ids in by_outcome.items():
            if not approval_ids:
                continue
            BaselineApproval.objects.using(WRITER_DB).filter(
                team_id=run.team_id, id__in=approval_ids, state=BaselineApprovalState.OPEN
            ).filter(Q(evidence_run_created_at__isnull=True) | Q(evidence_run_created_at__lt=run.created_at)).update(
                evidence=outcome,
                evidence_run=run,
                evidence_commit_sha=run.commit_sha,
                evidence_run_created_at=run.created_at,
                updated_at=now,
            )
