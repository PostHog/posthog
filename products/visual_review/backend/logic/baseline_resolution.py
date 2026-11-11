"""What a run compares against: the YAML file in git, or the baseline ledger, by the repo's mode.

A run at commit T compares against the ledger at the merge-base of T and the default branch,
overlaid with the open approvals whose commits T contains. That is what git does with the YAML
file, where the tree at T carries the baseline edits of every pull request merged into T.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from ..classifier import ToleratedKey
from ..db import WRITER_DB
from ..facade.enums import BaselineMode, SnapshotResult
from ..models import BaselineCommit, Run, RunSnapshot, ToleratedHash
from . import baseline_approvals, baselines, errors, github_api, ledger, ledger_advance, toleration
from .baseline_record import METADATA_KEY, BaselineRecord, ShadowComparison, ShadowDifference

logger = structlog.get_logger(__name__)

# The record is stored on every run, so a run whose two baselines disagree everywhere must not
# write a whole suite into it.
MAX_SHADOW_IDENTIFIERS = 1000
SHADOW_SAMPLE_SIZE = 20

LEDGER_UNCHANGED = "unchanged"
LEDGER_NEW = "new"
LEDGER_UNDETERMINED = "undetermined"


@frozen
class LedgerResolution:
    baseline: dict[str, str]
    record: BaselineRecord
    # Built for every rendered identifier against its ledger and overlay hashes, which hold every
    # baseline the classifier keys a toleration on, so the classifier reuses it.
    tolerated_lookup: dict[ToleratedKey, ToleratedHash]


@frozen
class ResolvedBaseline:
    """The baseline the classifier gets, and the record to freeze on the run."""

    baseline: dict[str, str]
    healed_count: int = 0
    record: BaselineRecord | None = None
    tolerated_lookup: dict[ToleratedKey, ToleratedHash] | None = None


@frozen
class _MergeBasePosition:
    position: int
    clamped_to_seed: bool


def _seed_commit(run: Run) -> BaselineCommit:
    seed = BaselineCommit.objects.using(WRITER_DB).filter(repo_id=run.repo_id, position=0).first()
    if seed is None:
        raise errors.BaselineResolutionError(
            f"{run.repo.repo_full_name} has no baseline ledger. "
            "Seed it with `visual_review_baseline_ledger seed`, or set the repo back to yaml mode."
        )
    return seed


def _is_older_than_seed(run: Run, merge_base_sha: str, seed: BaselineCommit) -> bool:
    ancestry = github_api.commit_ancestry(run.repo, merge_base_sha, seed.commit_sha)
    if ancestry is None:
        raise errors.BaselineResolutionError(
            f"GitHub could not tell whether the merge-base {merge_base_sha} of this run is older than the "
            "baseline ledger. Re-run the job."
        )
    return ancestry


def _advance_ledger(run: Run) -> None:
    try:
        ledger_advance.advance(run.repo)
    except github_api.GITHUB_READ_REFUSED:
        raise
    except Exception as e:
        raise errors.BaselineResolutionError(
            f"The baseline ledger could not catch up with the default branch, so this run cannot tell "
            f"which baseline to compare against: {e} Re-run the job once that is fixed."
        ) from e


def _advance_to_merge_base(run: Run, merge_base_sha: str) -> int | None:
    """Advance the ledger, then the position of the merge-base, or None when the ledger does not hold it."""
    try:
        _advance_ledger(run)
    except errors.BaselineResolutionError:
        # Advance writes the new commits before it retries older unresolved commits of other pull
        # requests. A failed retry can come after the merge-base got its position, and the run only
        # needs that position.
        position = ledger.position_of(run.repo_id, merge_base_sha)
        if position is None:
            raise
        logger.warning("visual_review.ledger_advance_failed_after_merge_base", run_id=str(run.id), exc_info=True)
        return position
    return ledger.position_of(run.repo_id, merge_base_sha)


def _merge_base_position(run: Run, merge_base_sha: str, seed: BaselineCommit) -> _MergeBasePosition:
    """The ledger position of the merge-base.

    Only ledger mode advances the ledger here, and it advances before it asks GitHub whether the
    merge-base is older than the seed: a merge-base newer than the cursor is the common case there,
    and advance places it. A shadow run must not wait on the walk, and the periodic task keeps the
    ledger ahead of nearly every run.
    """
    repo = run.repo
    advances = repo.baseline_mode == BaselineMode.LEDGER
    position = ledger.position_of(repo.id, merge_base_sha)
    if position is None and advances:
        position = _advance_to_merge_base(run, merge_base_sha)
    if position is not None:
        return _MergeBasePosition(position=position, clamped_to_seed=False)
    if _is_older_than_seed(run, merge_base_sha, seed):
        return _MergeBasePosition(position=0, clamped_to_seed=True)
    if advances:
        raise errors.BaselineResolutionError(
            f"The merge-base {merge_base_sha} of this run is not in the baseline ledger. "
            "Rebase the branch on the default branch and push again."
        )
    raise errors.BaselineResolutionError(
        f"The baseline ledger has not reached the merge-base {merge_base_sha} of this run yet."
    )


@frozen
class BaselinePick:
    baseline_hash: str
    # The overlay hash the diff task tries when the ledger hash is over a threshold.
    second_candidate: str = ""


def pick_baseline(
    identifier: str,
    render_hash: str,
    ledger_hash: str,
    overlay_hash: str,
    tolerated_lookup: dict[ToleratedKey, ToleratedHash],
) -> BaselinePick:
    """The baseline for one rendered identifier. An empty baseline hash means the snapshot is new."""
    if ledger_hash and render_hash == ledger_hash:
        return BaselinePick(baseline_hash=ledger_hash)
    if overlay_hash and render_hash == overlay_hash:
        return BaselinePick(baseline_hash=overlay_hash)
    if baseline_approvals.reproduces_by_hash(identifier, render_hash, ledger_hash, tolerated_lookup):
        return BaselinePick(baseline_hash=ledger_hash)
    if baseline_approvals.reproduces_by_hash(identifier, render_hash, overlay_hash, tolerated_lookup):
        return BaselinePick(baseline_hash=overlay_hash)
    if not ledger_hash:
        return BaselinePick(baseline_hash=overlay_hash)
    if overlay_hash and overlay_hash != ledger_hash:
        return BaselinePick(baseline_hash=ledger_hash, second_candidate=overlay_hash)
    return BaselinePick(baseline_hash=ledger_hash)


def resolve_ledger_baseline(run: Run, rendered: dict[str, str]) -> LedgerResolution:
    """The ledger baseline of a run, as the classifier's input, and the record to freeze on the run.

    `rendered` maps each identifier the run rendered to its hash. Raises `BaselineResolutionError`
    with a message for the developer when the run cannot be placed on the ledger, and lets
    `GitHubRateLimitError` and `GitHubEgressBudgetExhausted` through.
    """
    repo = run.repo
    seed = _seed_commit(run)
    default_branch = github_api.default_branch_name(repo)
    if default_branch is None:
        raise errors.BaselineResolutionError(
            f"GitHub did not name the default branch of {repo.repo_full_name}. Re-run the job."
        )

    comparison: github_api.Comparison | None = None
    if run.branch == default_branch:
        merge_base_sha = run.commit_sha
    else:
        comparison = github_api.compare_commits(repo, default_branch, run.commit_sha)
        if comparison is None or not comparison.merge_base_sha:
            raise errors.BaselineResolutionError(
                f"GitHub could not compare {run.commit_sha} with {default_branch}, so this run has no "
                "merge-base to read the baseline at. Re-run the job."
            )
        merge_base_sha = comparison.merge_base_sha

    merge_base = _merge_base_position(run, merge_base_sha, seed)
    ledger_hashes = ledger.ledger_at(repo.id, run.run_type, merge_base.position)
    overlay = baseline_approvals.overlay_for_run(run, comparison, ledger_hashes)
    overlay_hashes = {identifier: entry.content_hash for identifier, entry in overlay.entries.items()}

    tolerated_lookup = toleration.build_tolerated_lookup(
        repo.id,
        set(rendered),
        {ledger_hashes[i] for i in rendered if i in ledger_hashes} | {h for h in overlay_hashes.values() if h},
        now=timezone.now(),
    )

    baseline: dict[str, str] = {}
    second_candidates: dict[str, str] = {}
    for identifier, render_hash in rendered.items():
        pick = pick_baseline(
            identifier,
            render_hash,
            ledger_hashes.get(identifier, ""),
            overlay_hashes.get(identifier, ""),
            tolerated_lookup,
        )
        if pick.baseline_hash:
            baseline[identifier] = pick.baseline_hash
        if pick.second_candidate:
            second_candidates[identifier] = pick.second_candidate

    # Not rendered: the tree's baseline is the overlay where one applies. An approved removal
    # leaves the identifier out, so the run reports no removal for it.
    for identifier in (set(ledger_hashes) | set(overlay_hashes)) - set(rendered):
        tree_hash = overlay_hashes[identifier] if identifier in overlay_hashes else ledger_hashes[identifier]
        if tree_hash:
            baseline[identifier] = tree_hash

    record = BaselineRecord(
        mode=BaselineMode.LEDGER,
        merge_base_sha=merge_base_sha,
        position=merge_base.position,
        clamped_to_seed=merge_base.clamped_to_seed,
        containment_complete=comparison.complete if comparison is not None else True,
        overlay=dict(overlay.entries),
        candidate_approval_ids=overlay.candidate_approval_ids,
        conflicts=dict(overlay.conflicts),
        second_candidates=second_candidates,
    )
    return LedgerResolution(baseline=baseline, record=record, tolerated_lookup=tolerated_lookup)


def _shadow_record(run: Run, rendered: dict[str, str], yaml_baseline: dict[str, str]) -> BaselineRecord:
    """The ledger side of a shadow-mode run. It never raises, because the YAML decides the run."""
    try:
        resolution = resolve_ledger_baseline(run, rendered)
    except Exception as e:
        logger.warning("visual_review.shadow_baseline_unavailable", run_id=str(run.id), error=str(e))
        return BaselineRecord.unavailable(BaselineMode.SHADOW, str(e)[:500] or type(e).__name__)

    differing = sorted(
        identifier
        for identifier in rendered
        if resolution.baseline.get(identifier, "") != yaml_baseline.get(identifier, "")
    )
    ledger_removed: tuple[str, ...] | None = None
    ledger_removed_all: list[str] = []
    if not run.is_partial:
        ledger_removed_all = sorted(set(resolution.baseline) - set(rendered))
        ledger_removed = tuple(ledger_removed_all[:MAX_SHADOW_IDENTIFIERS])
    return replace(
        resolution.record,
        mode=BaselineMode.SHADOW,
        differences={
            identifier: resolution.baseline.get(identifier, "") for identifier in differing[:MAX_SHADOW_IDENTIFIERS]
        },
        differences_truncated=len(differing) > MAX_SHADOW_IDENTIFIERS,
        ledger_removed=ledger_removed,
        ledger_removed_truncated=len(ledger_removed_all) > MAX_SHADOW_IDENTIFIERS,
    )


def resolve(run: Run, rendered: dict[str, str]) -> ResolvedBaseline:
    """The baseline that decides the run, by the repo's mode.

    In yaml mode this is the YAML file, read exactly as before. In shadow mode the YAML still
    decides, and the ledger side is only recorded. In ledger mode the ledger decides, and a run it
    cannot place raises `BaselineResolutionError`.
    """
    repo = run.repo
    if repo.baseline_mode == BaselineMode.LEDGER:
        resolution = resolve_ledger_baseline(run, rendered)
        return ResolvedBaseline(
            baseline=resolution.baseline, record=resolution.record, tolerated_lookup=resolution.tolerated_lookup
        )

    yaml_baseline, healed_count = baselines._resolve_baselines_with_merge_base(
        repo,
        run.run_type,
        run.branch,
        rendered_identifiers=set(rendered),
        commit_sha=run.commit_sha,
    )
    if repo.baseline_mode != BaselineMode.SHADOW:
        return ResolvedBaseline(baseline=yaml_baseline, healed_count=healed_count)
    return ResolvedBaseline(
        baseline=yaml_baseline,
        healed_count=healed_count,
        record=_shadow_record(run, rendered, yaml_baseline),
    )


def shadow_ledger_verdict(
    identifier: str, render_hash: str, ledger_hash: str, tolerated_lookup: dict[ToleratedKey, ToleratedHash]
) -> str:
    if not ledger_hash:
        return LEDGER_NEW
    if baseline_approvals.reproduces_by_hash(identifier, render_hash, ledger_hash, tolerated_lookup):
        return LEDGER_UNCHANGED
    # Only a pixel diff could tell a changed render from noise, and shadow mode runs none.
    return LEDGER_UNDETERMINED


def compare_shadow(run: Run) -> ShadowComparison | None:
    """Store how the ledger verdict of a finished shadow-mode run differs from the YAML verdict.

    Returns the comparison, or None when the run has no usable shadow record.
    """
    metadata = run.metadata if isinstance(run.metadata, dict) else {}
    record = BaselineRecord.from_json(metadata.get(METADATA_KEY))
    if record is None or record.unavailable_reason or record.mode != BaselineMode.SHADOW:
        return None
    differences = record.differences or {}

    run_snapshots = RunSnapshot.objects.using(WRITER_DB).filter(run_id=run.id)
    snapshots = {
        snapshot.identifier: snapshot
        for snapshot in run_snapshots.filter(identifier__in=list(differences)).only(
            "identifier", "current_hash", "result", "is_quarantined"
        )
    }
    tolerated_lookup = toleration.build_tolerated_lookup(
        run.repo_id,
        set(differences),
        {h for h in differences.values() if h},
        now=timezone.now(),
    )

    pairs: Counter[str] = Counter()
    pairs_without_quarantined: Counter[str] = Counter()
    sample: list[ShadowDifference] = []
    # Positive when the ledger gate fails on more snapshots than the YAML gate did.
    gate_delta = 0
    for identifier, ledger_hash in sorted(differences.items()):
        snapshot = snapshots.get(identifier)
        if snapshot is None:
            continue
        yaml_verdict = str(snapshot.result)
        ledger_verdict = shadow_ledger_verdict(identifier, snapshot.current_hash, ledger_hash, tolerated_lookup)
        pair = f"{yaml_verdict}/{ledger_verdict}"
        pairs[pair] += 1
        if snapshot.is_quarantined:
            continue
        pairs_without_quarantined[pair] += 1
        gate_delta += int(ledger_verdict != LEDGER_UNCHANGED) - int(yaml_verdict != SnapshotResult.UNCHANGED)
        if len(sample) < SHADOW_SAMPLE_SIZE:
            sample.append(
                ShadowDifference(identifier=identifier, yaml_verdict=yaml_verdict, ledger_verdict=ledger_verdict)
            )

    yaml_only_removed: tuple[str, ...] = ()
    ledger_only_removed: tuple[str, ...] = ()
    if record.ledger_removed is not None:
        yaml_removed = set(
            run_snapshots.filter(result=SnapshotResult.REMOVED, is_quarantined=False).values_list(
                "identifier", flat=True
            )
        )
        quarantined_ledger_removed = set(
            run_snapshots.filter(identifier__in=list(record.ledger_removed), is_quarantined=True).values_list(
                "identifier", flat=True
            )
        )
        ledger_removed = set(record.ledger_removed) - quarantined_ledger_removed
        yaml_only_removed = tuple(sorted(yaml_removed - ledger_removed)[:MAX_SHADOW_IDENTIFIERS])
        ledger_only_removed = tuple(sorted(ledger_removed - yaml_removed)[:MAX_SHADOW_IDENTIFIERS])
        gate_delta += len(ledger_removed - yaml_removed) - len(yaml_removed - ledger_removed)

    yaml_failing = run_snapshots.exclude(result=SnapshotResult.UNCHANGED).filter(is_quarantined=False).count()
    truncated = record.differences_truncated or record.ledger_removed_truncated
    comparison = ShadowComparison(
        pairs=dict(pairs),
        pairs_without_quarantined=dict(pairs_without_quarantined),
        yaml_only_removed=yaml_only_removed,
        ledger_only_removed=ledger_only_removed,
        gate_differs=None if truncated else (yaml_failing > 0) != (yaml_failing + gate_delta > 0),
        sample=tuple(sample),
    )

    with transaction.atomic(using=WRITER_DB):
        locked = Run.objects.using(WRITER_DB).select_for_update().get(id=run.id)
        stored = BaselineRecord.from_json(locked.metadata.get(METADATA_KEY))
        if stored is None or stored.unavailable_reason:
            return None
        locked.metadata[METADATA_KEY] = replace(stored, comparison=comparison).to_json()
        locked.save(using=WRITER_DB, update_fields=["metadata"])

    logger.info(
        "visual_review.shadow_comparison",
        run_id=str(run.id),
        repo_id=str(run.repo_id),
        run_type=run.run_type,
        pairs=comparison.pairs,
        pairs_without_quarantined=comparison.pairs_without_quarantined,
        yaml_only_removed=len(comparison.yaml_only_removed),
        ledger_only_removed=len(comparison.ledger_only_removed),
        gate_differs=comparison.gate_differs,
        differences_truncated=record.differences_truncated,
        ledger_removed_truncated=record.ledger_removed_truncated,
    )
    return comparison
