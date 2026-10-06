"""Compare a selected workflow, matrix, job or step with the same work on the default branch.

The comparison reads stored runs and jobs only. A default-branch run gives a sample only when it ran
the same jobs on the same runners as the selection, so a sample is never taken from a different
workflow, job or runner. Sparse history therefore yields few samples or none, not a looser match.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from statistics import mean

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import (
    CI_TIMING_MAX_JOB_IDS,
    CIDataFreshness,
    CIEngine,
    CITimingContext,
    CITimingIdentity,
    CITimingKind,
    CITimingSample,
    CITimingSampleStatus,
    CITimingUnavailableReason,
    RepoRef,
    WorkflowJob,
)
from products.engineering_analytics.backend.logic._shared import _require_repo
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.default_branches import query_default_branches
from products.engineering_analytics.backend.logic.queries.timing_candidates import (
    TimingCandidateRun,
    query_timing_candidates,
)
from products.engineering_analytics.backend.logic.queries.workflow_jobs import query_jobs_by_run, query_workflow_jobs
from products.engineering_analytics.backend.logic.queries.workflow_run import query_workflow_run

logger = structlog.get_logger(__name__)

WINDOW_DAYS = 7
_RECENT_SAMPLES = 3
# The answer changes only when a new default-branch run syncs, and a person can open the same
# selection many times in a row.
_CACHE_SECONDS = 5 * 60
# A repository's default branch almost never changes, and reading it scans the pull request snapshot.
_DEFAULT_BRANCH_CACHE_SECONDS = 60 * 60
# Part of the cache key. Raise it when the matching rules or the cached shape change.
_CACHE_VERSION = 1

# A skipped or neutral job did no work, so it is not part of the workload that a run executed.
_NOT_EXECUTED_CONCLUSIONS = frozenset({"skipped", "neutral"})
# A cancelled job stopped early, so its duration says nothing about how long the work takes.
_NOT_SAMPLED_CONCLUSIONS = _NOT_EXECUTED_CONCLUSIONS | {"cancelled"}
_STEP_VERDICTS = frozenset({"success", "failure", "timed_out"})
_SPANS_JOBS = frozenset({CITimingKind.WORKFLOW, CITimingKind.MATRIX})


@frozen
class _JobSignature:
    """What makes two jobs the same work: the job name and the runner tier it ran on."""

    name: str
    runner_label: str


@frozen
class TimingSelection:
    kind: CITimingKind
    # Every job the current run attempt executed. A workflow or matrix sample must repeat this set.
    executed: list[WorkflowJob]
    selected: list[WorkflowJob]
    # Set for a step selection only. Steps match by name, because a workflow edit renumbers them.
    step_name: str | None = None


def select_timing_jobs(
    jobs: Sequence[WorkflowJob], *, kind: CITimingKind, job_ids: Sequence[int], step_number: int | None
) -> TimingSelection | None:
    """The selection among one run attempt's ``jobs``, or None when none of the selected jobs ran.
    Raises ValueError when a job id is not in the attempt, when a job or step selection does not name
    exactly one job, or when the job has no such step."""
    if kind is CITimingKind.WORKFLOW:
        named = list(jobs)
    else:
        jobs_by_id = {job.id: job for job in jobs}
        wanted_ids = sorted(set(job_ids))
        if not wanted_ids or any(job_id not in jobs_by_id for job_id in wanted_ids):
            raise ValueError("Every job id must be a job of this run attempt.")
        if kind not in _SPANS_JOBS and len(wanted_ids) != 1:
            raise ValueError("A job or step comparison needs exactly one job id.")
        named = [jobs_by_id[job_id] for job_id in wanted_ids]
    executed = [job for job in jobs if job.conclusion not in _NOT_EXECUTED_CONCLUSIONS]
    selected = [job for job in named if job.conclusion not in _NOT_EXECUTED_CONCLUSIONS]
    if not selected:
        return None
    if kind is not CITimingKind.STEP:
        return TimingSelection(kind=kind, executed=executed, selected=selected)
    step = next((step for step in selected[0].steps if step.number == step_number), None)
    if step is None:
        raise ValueError("The selected job has no step with that number.")
    return TimingSelection(kind=kind, executed=executed, selected=selected, step_name=step.name)


def match_timing_sample(
    run: TimingCandidateRun, jobs: Sequence[WorkflowJob], selection: TimingSelection
) -> CITimingSample | None:
    """The sample that ``run`` gives for ``selection``, or None when it did not run the same work.
    ``jobs`` is the job list of the run's latest attempt."""
    sampled = [
        job
        for job in jobs
        if job.conclusion not in _NOT_SAMPLED_CONCLUSIONS
        and job.started_at is not None
        and job.completed_at is not None
    ]
    if selection.kind in _SPANS_JOBS and _signatures(sampled) != _signatures(selection.executed):
        return None
    wanted = _signatures(selection.selected)
    matched = [job for job in sampled if _signature(job) in wanted]
    if not matched or _signatures(matched) != wanted:
        return None
    first_job = matched[0]
    completed_at = max(job.completed_at for job in matched if job.completed_at is not None)
    step_number: int | None = None
    if selection.kind is CITimingKind.STEP:
        steps = [
            step
            for step in first_job.steps
            if step.name == selection.step_name
            and step.started_at is not None
            and step.completed_at is not None
            and step.conclusion in _STEP_VERDICTS
        ]
        # Two steps with one name cannot be told apart, so neither is a sample.
        if len(steps) != 1 or steps[0].started_at is None or steps[0].completed_at is None:
            return None
        duration = steps[0].completed_at - steps[0].started_at
        succeeded = steps[0].conclusion == "success"
        step_number = steps[0].number
    else:
        duration = completed_at - min(job.started_at for job in matched if job.started_at is not None)
        succeeded = all(job.conclusion == "success" for job in matched)
    if duration < timedelta(0):
        return None
    one_job = selection.kind not in _SPANS_JOBS
    return CITimingSample(
        run_id=run.run_id,
        run_attempt=run.run_attempt,
        job_id=first_job.id if one_job else None,
        step_number=step_number,
        ci_engine=run.ci_engine,
        native_run_id=run.native_run_id,
        native_workflow_run_id=run.native_workflow_run_id,
        native_job_id=first_job.native_job_id if one_job else None,
        native_attempt_id=first_job.native_attempt_id if one_job else None,
        status=CITimingSampleStatus.SUCCESS if succeeded else CITimingSampleStatus.FAILURE,
        duration_seconds=duration.total_seconds(),
        completed_at=completed_at,
        head_sha=run.head_sha,
    )


def _signature(job: WorkflowJob) -> _JobSignature:
    return _JobSignature(name=job.name, runner_label=job.runner_label)


def _signatures(jobs: Sequence[WorkflowJob]) -> Counter[_JobSignature]:
    return Counter(_signature(job) for job in jobs)


def build_ci_timing_context(
    *,
    curated: CuratedGitHubSource,
    repo: str,
    ci_engine: CIEngine,
    run_id: int,
    run_attempt: int,
    kind: CITimingKind,
    job_ids: Sequence[int] = (),
    step_number: int | None = None,
) -> CITimingContext:
    owner, name = _require_repo(repo)
    # A workflow selection reads no job ids, so they must not split its cache entries.
    job_ids = () if kind is CITimingKind.WORKFLOW else sorted(set(job_ids))
    if len(job_ids) > CI_TIMING_MAX_JOB_IDS:
        raise ValueError(f"Give at most {CI_TIMING_MAX_JOB_IDS} job ids.")
    selection_key = (
        f"{ci_engine.value}:{run_id}:{run_attempt}:{kind.value}:{','.join(map(str, job_ids))}"
        f":{step_number if kind is CITimingKind.STEP else ''}"
    )
    cache_key = (
        f"{_cache_prefix(curated, owner, name)}:ci_timing_context:{_CACHE_VERSION}"
        f":{hashlib.sha256(selection_key.encode()).hexdigest()}"
    )
    cached = _cache_get(cache_key)
    if isinstance(cached, dict):
        return CITimingContext(**cached)
    context = _timing_context(
        curated=curated,
        ci_engine=ci_engine,
        run_id=run_id,
        run_attempt=run_attempt,
        kind=kind,
        job_ids=job_ids,
        step_number=step_number,
    )
    _cache_set(cache_key, asdict(context), _CACHE_SECONDS)
    return context


def _timing_context(
    *,
    curated: CuratedGitHubSource,
    ci_engine: CIEngine,
    run_id: int,
    run_attempt: int,
    kind: CITimingKind,
    job_ids: Sequence[int],
    step_number: int | None,
) -> CITimingContext:
    run = query_workflow_run(curated=curated, run_id=run_id, ci_engine=ci_engine)
    if run is None:
        raise ValueError("The source holds no such run.")
    freshness = curated.ci_data_freshness()
    identity = CITimingIdentity.WORKFLOW_ID if run.workflow_id is not None else CITimingIdentity.WORKFLOW_NAME
    if curated.jobs_source() is None:
        return _without_samples(identity, freshness, unavailable_reason=CITimingUnavailableReason.JOBS_NOT_SYNCED)

    jobs = query_workflow_jobs(curated=curated, run_id=run_id, run_attempt=run_attempt, ci_engine=ci_engine)
    selection = select_timing_jobs(jobs, kind=kind, job_ids=job_ids, step_number=step_number)
    if selection is None:
        return _without_samples(identity, freshness, unavailable_reason=CITimingUnavailableReason.NOT_EXECUTED)
    default_branch = _default_branch(curated, run.repo)
    if default_branch is None:
        return _without_samples(
            identity, freshness, unavailable_reason=CITimingUnavailableReason.DEFAULT_BRANCH_UNKNOWN
        )

    candidates = query_timing_candidates(
        curated=curated,
        run=run,
        ci_engine=ci_engine,
        default_branch=default_branch,
        window_start=datetime.now(UTC) - timedelta(days=WINDOW_DAYS),
    )
    if not candidates.runs:
        return _without_samples(identity, freshness, default_branch=default_branch)
    one_job = kind not in _SPANS_JOBS
    jobs_by_run = query_jobs_by_run(
        curated=curated,
        ci_engine=ci_engine,
        run_attempts={candidate.run_id: candidate.run_attempt for candidate in candidates.runs},
        earliest_run_started_at=min(candidate.run_started_at for candidate in candidates.runs),
        # A job or step sample reads one job of each run, so the other jobs and their steps stay unread.
        job_name=selection.selected[0].name if one_job else None,
        include_steps=kind is CITimingKind.STEP,
    )
    samples = [
        sample
        for candidate in candidates.runs
        if (sample := match_timing_sample(candidate, jobs_by_run.get(candidate.run_id, []), selection)) is not None
    ]
    samples.sort(key=lambda sample: sample.completed_at, reverse=True)
    passed = [sample.duration_seconds for sample in samples if sample.status is CITimingSampleStatus.SUCCESS]
    return CITimingContext(
        default_branch=default_branch,
        window_days=WINDOW_DAYS,
        identity=identity,
        runs_scanned=len(candidates.runs),
        sampled=candidates.sampled,
        sample_count=len(passed),
        average_seconds=mean(passed) if passed else None,
        recent=samples[:_RECENT_SAMPLES],
        runs_synced_at=freshness.runs_synced_at,
        jobs_synced_at=freshness.jobs_synced_at,
        unavailable_reason=None,
    )


def _without_samples(
    identity: CITimingIdentity,
    freshness: CIDataFreshness,
    *,
    default_branch: str | None = None,
    unavailable_reason: CITimingUnavailableReason | None = None,
) -> CITimingContext:
    return CITimingContext(
        default_branch=default_branch,
        window_days=WINDOW_DAYS,
        identity=identity,
        runs_scanned=0,
        sampled=False,
        sample_count=0,
        average_seconds=None,
        recent=[],
        runs_synced_at=freshness.runs_synced_at,
        jobs_synced_at=freshness.jobs_synced_at,
        unavailable_reason=unavailable_reason,
    )


def _default_branch(curated: CuratedGitHubSource, repo: RepoRef) -> str | None:
    cache_key = f"{_cache_prefix(curated, repo.owner, repo.name)}:default_branch"
    cached = _cache_get(cache_key)
    if isinstance(cached, str):
        return cached
    wanted = (repo.owner.casefold(), repo.name.casefold())
    for (owner, name), branch in query_default_branches(curated=curated).items():
        if (owner.casefold(), name.casefold()) == wanted:
            _cache_set(cache_key, branch, _DEFAULT_BRANCH_CACHE_SECONDS)
            return branch
    return None


def _cache_prefix(curated: CuratedGitHubSource, owner: str, name: str) -> str:
    return f"engineering_analytics:{curated.team.pk}:{curated.source_id}:{owner.casefold()}/{name.casefold()}"


def _cache_get(cache_key: str) -> object:
    try:
        return cache.get(cache_key)
    except Exception:
        logger.warning("engineering_analytics_cache_read_failed", exc_info=True)
        return None


def _cache_set(cache_key: str, value: object, timeout: int) -> None:
    try:
        cache.set(cache_key, value, timeout=timeout)
    except Exception:
        logger.warning("engineering_analytics_cache_write_failed", exc_info=True)
