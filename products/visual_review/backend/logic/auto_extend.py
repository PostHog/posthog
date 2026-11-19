"""Extend a quarantine that is about to run out while its story still renders differently.

A quarantine that lapses while the story still differs on the default branch fails pull requests and
the merge queue until a person quarantines it again. Automatic quarantine does not catch every such
story again. A story that renders one fixed picture in every run, such as a stale baseline under
quarantine, never renders clean, so it is never proven flaky.

The window covers the `AUTO_EXTEND_RECENT_RUNS` newest full default-branch runs without a pull
request, chosen as automatic release chooses them. Only a `changed` render counts as a difference. One is enough to extend,
because a quarantine exists to hide that difference. Only renders against the story's current baseline
count, which is the baseline of its newest render in the window. Approving a new picture changes the
baseline, so the changed renders from before the approval drop out. A flake keeps its baseline, so its
changed renders still count. A quarantine whose story rendered no difference in the window lapses as
planned. Every quarantine counts, whoever opened it.

An extension replaces the active quarantine with an automatic one, like any new quarantine does. It
does not count toward the daily limit of automatic quarantines, because it hides nothing new.

The decision is `should_extend`, a pure function over plain values. The queries around it only
collect them and act on the answer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import ph_scoped_capture

from ..db import WRITER_DB
from ..facade.contracts import (
    AUTO_EXTEND_BEFORE_EXPIRY_HOURS,
    AUTO_EXTEND_REASON_PREFIX,
    AUTO_EXTEND_RECENT_RUNS,
    AUTO_QUARANTINE_DAYS,
    AUTO_QUARANTINE_MAX_STORIES_PER_RUN,
)
from ..facade.enums import ActorType, AutoQuarantineMode, QuarantineLiftState, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, QuarantineLiftRequest, Repo, Run, RunSnapshot
from . import auto_lift, auto_quarantine, github_api, quarantine

logger = structlog.get_logger(__name__)

_MAX_REASON_CHARS = 255
_REPORT_SECONDS = 24 * 60 * 60


@frozen
class RecentRenders:
    """How one quarantined story rendered in the recent default-branch runs, and when its quarantine ends."""

    expires_at: datetime | None
    default_branch_runs: int
    renders: int
    # Only `changed`, whatever the row's review state: `new` and `removed` are problems of the baseline file.
    changed_renders: int
    changed_pictures: int


def is_due(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    return now < expires_at <= now + timedelta(hours=AUTO_EXTEND_BEFORE_EXPIRY_HOURS)


def should_extend(renders: RecentRenders, now: datetime) -> bool:
    return is_due(renders.expires_at, now) and renders.changed_renders > 0


def looks_like_stale_baseline(renders: RecentRenders) -> bool:
    """Whether every recent render shows the same changed picture, which a flake does not do."""
    return renders.renders > 0 and renders.changed_renders == renders.renders and renders.changed_pictures == 1


def extend_reason(renders: RecentRenders) -> str:
    if looks_like_stale_baseline(renders):
        reason = (
            f"{AUTO_EXTEND_REASON_PREFIX}: the same changed picture in all {renders.renders} renders of the last "
            f"{renders.default_branch_runs} default-branch runs. The baseline looks stale, so approve the new "
            "picture instead of waiting"
        )
    else:
        pictures = "1 picture" if renders.changed_pictures == 1 else f"{renders.changed_pictures} pictures"
        reason = (
            f"{AUTO_EXTEND_REASON_PREFIX}: changed in {renders.changed_renders} of the last "
            f"{renders.default_branch_runs} default-branch runs, {pictures}"
        )
    return reason[:_MAX_REASON_CHARS]


@frozen
class _ActiveQuarantine:
    id: UUID
    identifier: str
    expires_at: datetime | None
    source: str


def _newest_active_quarantines(run: Run, now: datetime) -> list[_ActiveQuarantine]:
    """The newest active quarantine of each identifier, because only that one decides when the story lapses."""
    return [
        _ActiveQuarantine(id=entry_id, identifier=identifier, expires_at=expires_at, source=source)
        for entry_id, identifier, expires_at, source in QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, team_id=run.team_id, run_type=run.run_type)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by("identifier", "-created_at")
        .distinct("identifier")
        .values_list("id", "identifier", "expires_at", "source")
    ]


@frozen
class _Counts:
    renders: int
    changed_renders: int
    changed_pictures: int


_NOT_RENDERED = _Counts(renders=0, changed_renders=0, changed_pictures=0)


@frozen
class _Render:
    baseline_hash: str
    result: str
    current_hash: str


def _count_against_current_baseline(newest_first: list[_Render]) -> _Counts:
    current_baseline = newest_first[0].baseline_hash
    renders = [render for render in newest_first if render.baseline_hash == current_baseline]
    changed = [render for render in renders if render.result == SnapshotResult.CHANGED]
    return _Counts(
        renders=len(renders),
        changed_renders=len(changed),
        changed_pictures=len({render.current_hash for render in changed}),
    )


def _counts(run: Run, run_ids: list[UUID], identifiers: list[str]) -> dict[str, _Counts]:
    """`run_ids` is newest first."""
    position = {run_id: index for index, run_id in enumerate(run_ids)}
    rows = sorted(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id__in=run_ids, team_id=run.team_id, identifier__in=identifiers)
        .values_list("run_id", "identifier", "baseline_hash", "result", "current_hash"),
        key=lambda row: position[row[0]],
    )
    renders_by_identifier: dict[str, list[_Render]] = defaultdict(list)
    for _, identifier, baseline_hash, result, current_hash in rows:
        renders_by_identifier[identifier].append(
            _Render(baseline_hash=baseline_hash, result=result, current_hash=current_hash)
        )
    return {
        identifier: _count_against_current_baseline(newest_first)
        for identifier, newest_first in renders_by_identifier.items()
    }


def _recent_renders(run: Run, default_branch: str, due: list[_ActiveQuarantine]) -> dict[UUID, RecentRenders]:
    run_ids = list(
        auto_lift.default_branch_runs_until(run, default_branch).values_list("id", flat=True)[:AUTO_EXTEND_RECENT_RUNS]
    )
    counts = _counts(run, run_ids, [entry.identifier for entry in due])
    recent: dict[UUID, RecentRenders] = {}
    for entry in due:
        story = counts.get(entry.identifier, _NOT_RENDERED)
        recent[entry.id] = RecentRenders(
            expires_at=entry.expires_at,
            default_branch_runs=len(run_ids),
            renders=story.renders,
            changed_renders=story.changed_renders,
            changed_pictures=story.changed_pictures,
        )
    return recent


def _extend(run: Run, entry: _ActiveQuarantine, reason: str, now: datetime) -> bool:
    """Replace the quarantine with an automatic one. False when somebody changed it after the read."""
    with transaction.atomic(using=WRITER_DB):
        # The run first, like `quarantine_identifier`, so a manual quarantine of the same story takes the locks
        # in the same order. No-key, because FOR UPDATE conflicts with the KEY SHARE lock of a lift request
        # that names this run, and could deadlock with a lift that holds the quarantine row.
        Run.objects.using(WRITER_DB).select_for_update(no_key=True).filter(id=run.id, team_id=run.team_id).exists()
        # A person who lifted or replaced the quarantine since the read changed its expiry. Their choice wins.
        unchanged = (
            QuarantinedIdentifier.objects.using(WRITER_DB)
            .select_for_update()
            .filter(id=entry.id, team_id=run.team_id, expires_at=entry.expires_at)
            .exists()
        )
        if not unchanged:
            return False
        extension = quarantine.quarantine_identifier(
            repo_id=run.repo_id,
            identifier=entry.identifier,
            run_type=run.run_type,
            reason=reason,
            user_id=None,
            team_id=run.team_id,
            expires_at=now + timedelta(days=AUTO_QUARANTINE_DAYS),
            source_run_id=run.id,
            source=ActorType.AUTO,
            notify_owners=True,
        )
        # The extension continues the same quarantine, so a pending fix-PR lift must still lift it. On the
        # old row, the lift would find the quarantine ended and resolve as superseded.
        QuarantineLiftRequest.objects.using(WRITER_DB).filter(
            quarantine_id=entry.id, team_id=run.team_id, state=QuarantineLiftState.PENDING
        ).update(quarantine_id=extension.id, updated_at=now)
    return True


def _report(
    capture_ph_event: Callable[..., Any],
    repo: Repo,
    run: Run,
    entry: _ActiveQuarantine,
    renders: RecentRenders,
    mode: str,
    applied: bool,
) -> None:
    logger.info(
        "visual_review.quarantine_extended_automatically",
        repo_id=str(repo.id),
        run_id=str(run.id),
        identifier=entry.identifier,
        default_branch_runs=renders.default_branch_runs,
        changed_renders=renders.changed_renders,
        changed_pictures=renders.changed_pictures,
        mode=mode,
        applied=applied,
    )
    # Best effort, like `runs.capture_run_processing_metrics`: instrumentation never fails the task.
    try:
        capture_ph_event(
            distinct_id=repo.repo_full_name or str(repo.id),
            event="vr_quarantine_extend",
            properties={
                "repo": repo.repo_full_name,
                "team_id": repo.team_id,
                "run_id": str(run.id),
                "run_type": run.run_type,
                "identifier": entry.identifier,
                "quarantine_source": entry.source,
                "default_branch_runs": renders.default_branch_runs,
                "renders": renders.renders,
                "changed_renders": renders.changed_renders,
                "changed_pictures": renders.changed_pictures,
                "stale_baseline": looks_like_stale_baseline(renders),
                "mode": mode,
                "applied": applied,
            },
        )
    except Exception:
        logger.warning("visual_review.quarantine_extend_capture_failed", run_id=str(run.id), exc_info=True)


def extend_differing_quarantines(run_id: UUID) -> None:
    """Extend, or in preview report, every quarantine close to its expiry whose story still renders differently."""
    run = Run.objects.using(WRITER_DB).select_related("repo").get(id=run_id)
    if not auto_lift.may_release(run) or run.status != RunStatus.COMPLETED:
        return
    repo = run.repo
    mode = repo.auto_quarantine_mode
    if mode == AutoQuarantineMode.OFF:
        return
    # A branch called master is not the default branch of a repo whose default branch is main.
    if github_api.default_branch_name(repo) != run.branch:
        return

    now = timezone.now()
    due = [entry for entry in _newest_active_quarantines(run, now) if is_due(entry.expires_at, now)]
    if not due:
        return
    # The commit is client-supplied, and an off-branch run would extend quarantines on evidence from outside
    # the default branch. Checked after the cheap reads, so a run with nothing due skips the GitHub lookup.
    if not auto_lift.is_on_default_branch(repo, run.commit_sha):
        logger.warning(
            "visual_review.auto_extend_commit_not_on_default_branch", repo_id=str(repo.id), run_id=str(run.id)
        )
        return
    recent = _recent_renders(run, run.branch, due)
    # Soonest expiry first, so the cap keeps the stories that lapse first.
    to_extend = sorted(
        (entry for entry in due if should_extend(recent[entry.id], now)),
        key=lambda entry: entry.expires_at or now,
    )
    applied = mode == AutoQuarantineMode.ON
    # The cap counts only handled entries. Otherwise in preview the same already reported entries fill
    # every run, and the entries after them are never reported.
    handled = 0
    with ph_scoped_capture() as capture_ph_event:
        for entry in to_extend:
            if handled == AUTO_QUARANTINE_MAX_STORIES_PER_RUN:
                break
            renders = recent[entry.id]
            if applied:
                if not _extend(run, entry, extend_reason(renders), now):
                    continue
            elif not auto_quarantine.first_report(
                "quarantine_extend", repo, run.run_type, entry.identifier, _REPORT_SECONDS
            ):
                continue
            _report(capture_ph_event, repo, run, entry, renders, mode, applied)
            handled += 1
