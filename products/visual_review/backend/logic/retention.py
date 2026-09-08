"""Retention sweep: deletes expired runs and the artifacts nothing references any more."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from itertools import batched
from uuid import UUID

from django.db import connections, transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from ..db import WRITER_DB
from ..facade.enums import RunStatus
from ..models import Artifact, Repo, Run, RunSnapshot
from ..storage import ArtifactStorage
from . import artifact_store, run_queries

logger = structlog.get_logger(__name__)

# A superseded run on a PR branch is history that no page reads after the next
# push replaces it. Its last readers are the "stale" review-state filter and the
# run detail page, so this window is a grace period for people who open an old
# link.
SUPERSEDED_RUN_RETENTION_DAYS = 30

# Default-branch runs feed the baseline overview (90 days) and the snapshot
# history page, which is unbounded, so they are kept much longer.
DEFAULT_BRANCH_RUN_RETENTION_DAYS = 180

# A PR branch with no run this recent belongs to a merged or abandoned PR.
# Nothing links to it any more, so its latest runs go too.
QUIET_BRANCH_RETENTION_DAYS = 90

# An artifact can exist for a short time before anything names it, because a
# diff or thumbnail image is written to storage first and linked to its snapshot
# after. The hash checks in the candidate query cover every state after that, so
# the grace period only has to cover this gap.
ARTIFACT_ORPHAN_GRACE_DAYS = 7

ARTIFACT_SWEEP_BATCH = 500

# Caps per invocation. The task runs daily and catches up over several days,
# which keeps the first sweep of a large backlog off one long transaction.
MAX_RUNS_PER_SWEEP = 2_000
MAX_ARTIFACTS_PER_SWEEP = 20_000

# The caps above bound rows, not wall clock. Deletes over the backlog are slow
# enough that the first sweeps would run for hours, so an invocation also stops
# when its deadline passes.
SWEEP_TIME_BUDGET_SECONDS = 30 * 60

# Repos do not record their real default branch, so a run with no PR number is
# read as default-branch history and the rule fails toward keeping it.
_PROTECTED_HISTORY = Q(branch__in=run_queries._DEFAULT_BRANCHES) | Q(pr_number__isnull=True)

# The row goes first and the object second, and the DELETE repeats the reference
# checks of the candidate query, so a reference acquired between the SELECT and
# the DELETE keeps the row. An Artifact row is what makes the CLI skip an upload
# (`find_missing_hashes`), so a row that outlives its object makes every later
# run point at an image nobody will upload again. A leaked object costs storage
# and nothing else.
#
# The hash checks are scoped to the repo, because an artifact and its storage key
# belong to one repo, so a snapshot of another repo can never use this row. The id
# checks need no scope, because an id is unique on its own.
_DELETE_ARTIFACTS_SQL = """
DELETE FROM visual_review_artifact a
WHERE a.id = ANY(%(artifact_ids)s::uuid[])
  AND a.team_id = %(team_id)s
  AND NOT EXISTS (SELECT 1 FROM visual_review_runsnapshot s WHERE s.current_artifact_id = a.id)
  AND NOT EXISTS (SELECT 1 FROM visual_review_runsnapshot s WHERE s.baseline_artifact_id = a.id)
  AND NOT EXISTS (SELECT 1 FROM visual_review_runsnapshot s WHERE s.diff_artifact_id = a.id)
  AND NOT EXISTS (
      SELECT 1 FROM visual_review_runsnapshot s
      JOIN visual_review_run r ON r.id = s.run_id
      WHERE s.team_id = a.team_id AND r.repo_id = a.repo_id AND s.current_hash = a.content_hash
  )
  AND NOT EXISTS (
      SELECT 1 FROM visual_review_runsnapshot s
      JOIN visual_review_run r ON r.id = s.run_id
      WHERE s.team_id = a.team_id AND r.repo_id = a.repo_id AND s.baseline_hash = a.content_hash
  )
  AND NOT EXISTS (SELECT 1 FROM visual_review_artifact t WHERE t.thumbnail_id = a.id)
RETURNING a.id, a.storage_path
"""


@frozen
class ArtifactSweepResult:
    deleted: int
    objects_leaked: int


@frozen
class RetentionSweepResult:
    runs_deleted: int
    artifacts_deleted: int
    objects_leaked: int


class RetentionSweep:
    """Applies the retention policy to one repo."""

    def __init__(self, repo: Repo, now: datetime, deadline: float) -> None:
        self.repo = repo
        # ProductTeamModel.save() writes the canonical team_id, so the stored
        # value needs no second resolution.
        self.team_id = repo.team_id
        self.now = now
        self.deadline = deadline

    def _out_of_time(self) -> bool:
        return time.monotonic() >= self.deadline

    def _runs(self) -> QuerySet[Run]:
        return Run.objects.for_team(self.team_id, canonical=True).using(WRITER_DB).filter(repo_id=self.repo.id)

    def _snapshots(self) -> QuerySet[RunSnapshot]:
        return RunSnapshot.objects.for_team(self.team_id, canonical=True).using(WRITER_DB)

    def _artifacts(self) -> QuerySet[Artifact]:
        return Artifact.objects.for_team(self.team_id, canonical=True).using(WRITER_DB).filter(repo_id=self.repo.id)

    def _expired_superseded_run_ids(self, limit: int) -> list[UUID]:
        expired = (
            _PROTECTED_HISTORY & Q(created_at__lt=self.now - timedelta(days=DEFAULT_BRANCH_RUN_RETENTION_DAYS))
        ) | (~_PROTECTED_HISTORY & Q(created_at__lt=self.now - timedelta(days=SUPERSEDED_RUN_RETENTION_DAYS)))
        return list(
            self._runs()
            .filter(Q(superseded_by__isnull=False) & expired)
            .order_by("created_at")
            .values_list("id", flat=True)[:limit]
        )

    def _quiet_branch_run_ids(self, limit: int) -> list[UUID]:
        quiet_cutoff = self.now - timedelta(days=QUIET_BRANCH_RETENTION_DAYS)
        recent_run_on_branch = self._runs().filter(branch=OuterRef("branch"), created_at__gte=quiet_cutoff)
        # Every superseded run of a group points at the group's latest run, so
        # the latest run can only go when none of them is left.
        superseded_run_in_group = self._runs().filter(
            branch=OuterRef("branch"),
            run_type=OuterRef("run_type"),
            superseded_by__isnull=False,
        )
        # When the repo has no protected-history run, the snapshot rows of the
        # newest completed run of a run type are the only thing left that names
        # the baseline hashes committed to the repo, whatever their branch.
        # A partial run skips the identifiers outside its subset, so it names
        # only part of the baseline and cannot take over as the keeper.
        newer_completed_run = self._runs().filter(
            run_type=OuterRef("run_type"),
            status=RunStatus.COMPLETED,
            is_partial=False,
            created_at__gt=OuterRef("created_at"),
        )
        return list(
            self._runs()
            .filter(superseded_by__isnull=True, created_at__lt=quiet_cutoff)
            .exclude(_PROTECTED_HISTORY)
            .filter(~Exists(recent_run_on_branch), ~Exists(superseded_run_in_group), Exists(newer_completed_run))
            .order_by("created_at")
            .values_list("id", flat=True)[:limit]
        )

    def _delete_runs(self, run_ids: list[UUID]) -> int:
        deleted = 0
        # One run per DELETE, in the order given (oldest first). Django applies
        # SET_NULL to the runs that point at a deleted run before it deletes
        # anything, so a batch that holds two links of one supersession chain
        # would set the older link to NULL while the group's latest run still
        # exists and break the unique_latest_run_per_group index.
        for run_id in run_ids:
            if self._out_of_time():
                break
            _total, per_model = self._runs().filter(id=run_id).delete()
            deleted += per_model.get(Run._meta.label, 0)
        return deleted

    def delete_expired_runs(self) -> int:
        # Both candidate queries are expensive reads, so each one runs only when
        # there is time left to act on its result.
        if self._out_of_time():
            return 0
        deleted = self._delete_runs(self._expired_superseded_run_ids(MAX_RUNS_PER_SWEEP))
        remaining = MAX_RUNS_PER_SWEEP - deleted
        if remaining <= 0 or self._out_of_time():
            return deleted
        # The quiet-branch pass reads the groups the pass above has already
        # emptied, so the two cannot run in the other order.
        return deleted + self._delete_runs(self._quiet_branch_run_ids(remaining))

    def _unreferenced_artifact_ids(self, limit: int) -> list[UUID]:
        snapshots = self._snapshots()
        return list(
            self._artifacts()
            .filter(created_at__lt=self.now - timedelta(days=ARTIFACT_ORPHAN_GRACE_DAYS))
            .filter(
                ~Exists(snapshots.filter(current_artifact_id=OuterRef("id"))),
                ~Exists(snapshots.filter(baseline_artifact_id=OuterRef("id"))),
                ~Exists(snapshots.filter(diff_artifact_id=OuterRef("id"))),
                # A snapshot names its images by hash when the run is created
                # and gets its artifact FKs only when the link step and the
                # classifier run, so a NULL FK does not mean the row is free.
                ~Exists(snapshots.filter(run__repo_id=self.repo.id, current_hash=OuterRef("content_hash"))),
                ~Exists(snapshots.filter(run__repo_id=self.repo.id, baseline_hash=OuterRef("content_hash"))),
                # A thumbnail stays while the artifact that points at it exists.
                # That artifact's delete leaves the thumbnail unreferenced, and
                # the next sweep collects it.
                ~Exists(self._artifacts().filter(thumbnail_id=OuterRef("id"))),
            )
            .values_list("id", flat=True)[:limit]
        )

    def _delete_artifact_rows(self, artifact_ids: list[UUID]) -> list[tuple[UUID, str]]:
        with transaction.atomic(using=WRITER_DB), connections[WRITER_DB].cursor() as cursor:
            artifact_store.lock_artifact_registry(self.repo.id)
            cursor.execute(
                _DELETE_ARTIFACTS_SQL,
                {"artifact_ids": [str(artifact_id) for artifact_id in artifact_ids], "team_id": self.team_id},
            )
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def delete_orphaned_artifacts(self) -> ArtifactSweepResult:
        # The candidate query is the most expensive read of the sweep, so it
        # runs only when there is time left to act on its result.
        if self._out_of_time():
            return ArtifactSweepResult(deleted=0, objects_leaked=0)

        storage = ArtifactStorage(str(self.repo.id))
        candidates = self._unreferenced_artifact_ids(MAX_ARTIFACTS_PER_SWEEP)

        deleted = 0
        objects_leaked = 0
        for batch in batched(candidates, ARTIFACT_SWEEP_BATCH, strict=False):
            if self._out_of_time():
                break
            deleted_rows = self._delete_artifact_rows(list(batch))
            deleted += len(deleted_rows)
            failed_paths = storage.delete_paths([storage_path for _, storage_path in deleted_rows])
            objects_leaked += len(failed_paths)

        if objects_leaked:
            logger.warning(
                "visual_review.retention_artifact_object_leaked",
                repo_id=str(self.repo.id),
                team_id=self.team_id,
                objects_leaked=objects_leaked,
            )
        return ArtifactSweepResult(deleted=deleted, objects_leaked=objects_leaked)


def sweep_repo(repo: Repo, now: datetime | None = None, deadline: float | None = None) -> RetentionSweepResult:
    sweep = RetentionSweep(
        repo,
        now or timezone.now(),
        deadline if deadline is not None else time.monotonic() + SWEEP_TIME_BUDGET_SECONDS,
    )
    # Runs go first, because the snapshot rows they take with them are what
    # holds most artifacts in use.
    runs_deleted = sweep.delete_expired_runs()
    artifacts = sweep.delete_orphaned_artifacts()
    return RetentionSweepResult(
        runs_deleted=runs_deleted,
        artifacts_deleted=artifacts.deleted,
        objects_leaked=artifacts.objects_leaked,
    )
