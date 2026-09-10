"""Read-only run and snapshot lookups, plus the review-state filters the runs list is built on."""

from __future__ import annotations

from uuid import UUID

from django.db import models as db_models
from django.db.models import Count, Q

from posthog.helpers.trigram_search import (
    TrigramSearchField,
    apply_trigram_search,
    drop_similar_when_exact_exists,
    normalize_search_term,
)

from ..db import WRITER_DB
from ..facade.enums import RunPurpose, RunStatus, SnapshotResult
from ..models import Run, RunSnapshot
from . import errors


def is_run_stale(run: Run) -> bool:
    return run.superseded_by_id is not None


_HAS_CHANGES = Q(changed_count__gt=0) | Q(new_count__gt=0) | Q(removed_count__gt=0)

_CURRENT = Q(superseded_by__isnull=True)

_ON_PR = Q(pr_number__isnull=False)

REVIEW_STATE_FILTERS: dict[str, Q] = {
    # Only PR runs need human review — master/branch pushes without a PR are just drift
    "needs_review": Q(status=RunStatus.COMPLETED)
    & _HAS_CHANGES
    & Q(approved=False)
    & _CURRENT
    & _ON_PR
    & Q(purpose=RunPurpose.REVIEW),
    "clean": (Q(status=RunStatus.COMPLETED) & ~_HAS_CHANGES) | Q(approved=True),
    "processing": Q(status=RunStatus.PROCESSING) & _CURRENT,
    "stale": Q(superseded_by__isnull=False) & Q(approved=False) & _HAS_CHANGES,
}

# Free-text search over the runs list uses the shared trigram helper for the
# prose-like fields (branch, run type), where fuzzy/typo matching helps. Commit
# SHA and PR number are matched exactly (prefix / numeric id) via extra_exact_q —
# fuzzy matching a hex SHA or an integer is meaningless.
RUN_SEARCH_FIELDS = (TrigramSearchField("branch"), TrigramSearchField("run_type"))


def list_runs_for_team(
    team_id: int,
    review_state: str | None = None,
    repo_id: UUID | None = None,
    pr_number: int | None = None,
    commit_sha: str | None = None,
    branch: str | None = None,
    search: str | None = None,
) -> db_models.QuerySet[Run]:
    qs = Run.objects.filter(team_id=team_id).select_related("repo")
    if repo_id is not None:
        qs = qs.filter(repo_id=repo_id)
    if review_state and review_state in REVIEW_STATE_FILTERS:
        qs = qs.filter(REVIEW_STATE_FILTERS[review_state])
    if pr_number is not None:
        qs = qs.filter(pr_number=pr_number)
    if commit_sha:
        qs = qs.filter(commit_sha=commit_sha)
    if branch:
        qs = qs.filter(branch=branch)
    if search and (term := normalize_search_term(search)):
        # Commit SHA matches by prefix (reviewers paste the short SHA); PR number by exact id.
        extra_exact_q = Q(commit_sha__istartswith=term)
        if term.isdigit():
            extra_exact_q |= Q(pr_number=int(term))
        return drop_similar_when_exact_exists(
            apply_trigram_search(
                qs,
                term,
                span_prefix="visual_review.runs.search",
                fields=RUN_SEARCH_FIELDS,
                extra_exact_q=extra_exact_q,
                tiebreakers=("-created_at",),
            )
        )
    return qs.order_by("-created_at")


def get_review_state_counts(team_id: int, repo_id: UUID | None = None) -> dict[str, int]:
    qs = Run.objects.filter(team_id=team_id)
    if repo_id is not None:
        qs = qs.filter(repo_id=repo_id)
    return qs.aggregate(
        needs_review=Count("id", filter=REVIEW_STATE_FILTERS["needs_review"]),
        clean=Count("id", filter=REVIEW_STATE_FILTERS["clean"]),
        processing=Count("id", filter=REVIEW_STATE_FILTERS["processing"]),
        stale=Count("id", filter=REVIEW_STATE_FILTERS["stale"]),
    )


def get_run(run_id: UUID, team_id: int | None = None) -> Run:
    try:
        qs = Run.objects.select_related("repo")
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        return qs.get(id=run_id)
    except Run.DoesNotExist as e:
        raise errors.RunNotFoundError(f"Run {run_id} not found") from e


def _get_run_for_update(run_id: UUID, team_id: int | None = None) -> Run:
    """Get a run with a row-level lock on the writer DB. Must be called inside a transaction."""
    try:
        qs = Run.objects.using(WRITER_DB).select_for_update().select_related("repo")
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        return qs.get(id=run_id)
    except Run.DoesNotExist as e:
        raise errors.RunNotFoundError(f"Run {run_id} not found") from e


def get_run_with_snapshots(run_id: UUID, team_id: int | None = None) -> Run:
    try:
        qs = Run.objects.prefetch_related(
            "snapshots__current_artifact",
            "snapshots__baseline_artifact",
            "snapshots__diff_artifact",
        )
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        return qs.get(id=run_id)
    except Run.DoesNotExist as e:
        raise errors.RunNotFoundError(f"Run {run_id} not found") from e


def get_run_snapshots(run_id: UUID, team_id: int | None = None) -> list[RunSnapshot]:
    run = get_run(run_id, team_id=team_id)
    return list(
        run.snapshots.select_related("current_artifact", "baseline_artifact", "diff_artifact").order_by(
            db_models.Case(
                db_models.When(result=SnapshotResult.UNCHANGED, then=1),
                default=0,
            ),
            "identifier",
        )
    )


# Default-branch fallback. We don't track repos' actual default branch, so we
# include both candidates and assume nobody has both — whichever has rows wins.
# When `trunk`/`develop`-style defaults show up, this becomes a `Repo` field.
_DEFAULT_BRANCHES = ("master", "main")
