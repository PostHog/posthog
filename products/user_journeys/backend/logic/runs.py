"""Create, execute and read journey runs.

A run moves through one state machine: `pending` when created, `running` once a worker claims it,
then `passed`, `failed` or `errored`. Each move is a conditional update on the current state, so a
retried or duplicated execution of the same run does nothing, and a worker that dies mid-run leaves
a `running` row that `reap_stale_runs` ends as `errored` once it is older than any run can take.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from ..facade.contracts import (
    CreateJourneyRunInput,
    JourneyNotRunnableError,
    JourneyRunInProgressError,
    JourneyRunNotFoundError,
    JourneyRunTargetNotAllowedError,
    JourneyStep,
)
from ..facade.enums import JourneyRunStatus, JourneyRunStepStatus, JourneyRunTrigger, JourneyStepFailureReason
from ..feature_flags import is_user_journeys_enabled
from ..models import Journey, JourneyRun, JourneyRunStep
from .journeys import get_journey, parse_steps, steps_to_json
from .run_browser import BrowserOptions, BrowserSessionFactory, BrowserUnavailableError, browserless_page
from .run_executor import RUN_TIME_BUDGET_SECONDS, RunPlan, StepExecutor, StepOutcome
from .run_screenshots import (
    ObjectStorageScreenshotStore,
    ScreenshotStorageUnavailableError,
    ScreenshotStore,
    store_and_compare,
)
from .run_urls import TeamUrlPolicy, UrlPolicy, origin_of, recorded_start_url, replace_origin, url_shape_error

logger = structlog.get_logger(__name__)

# Past the Celery hard time limit of a run, so a run older than this has no live worker.
RUN_STALE_AFTER = timedelta(seconds=RUN_TIME_BUDGET_SECONDS + 300)
# A run that no worker claimed in this time was lost from the queue.
PENDING_STALE_AFTER = timedelta(minutes=30)


@frozen
class RunRuntime:
    """What a run needs from outside this module. Tests pass a local browser and a permissive policy."""

    open_page: BrowserSessionFactory
    url_policy: Callable[[int], UrlPolicy]
    store: ScreenshotStore


def production_runtime() -> RunRuntime:
    return RunRuntime(
        open_page=browserless_page, url_policy=TeamUrlPolicy.for_team, store=ObjectStorageScreenshotStore()
    )


@frozen
class RunTarget:
    steps: list[JourneyStep]
    start_url: str
    recorded_origin: str
    base_origin: str | None


def resolve_target(journey: Journey, base_origin: str | None) -> RunTarget:
    """Where a run of `journey` starts, with `base_origin` in place of the recorded origin when given.

    Raises `JourneyNotRunnableError` when the journey has no page to start from.
    """
    steps = parse_steps(journey.steps)
    recorded = recorded_start_url(journey.start_url, steps)
    if recorded is None:
        raise JourneyNotRunnableError(
            "This journey has no start URL. Set a start URL, or make the first step an exact pageview of a full URL."
        )
    return RunTarget(
        steps=steps,
        start_url=replace_origin(recorded, base_origin) if base_origin else recorded,
        recorded_origin=origin_of(recorded),
        base_origin=base_origin,
    )


def check_target_allowed(target: RunTarget, url_policy: UrlPolicy) -> None:
    error = url_policy.page_error(target.start_url)
    if error is not None:
        raise JourneyRunTargetNotAllowedError(error)


def create_run(team_id: int, data: CreateJourneyRunInput, *, url_policy: UrlPolicy) -> JourneyRun:
    if data.base_url is not None:
        shape_error = url_shape_error(data.base_url)
        if shape_error is not None:
            raise JourneyRunTargetNotAllowedError(shape_error)
    journey = get_journey(team_id, data.journey_id)
    target = resolve_target(journey, origin_of(data.base_url) if data.base_url else None)
    check_target_allowed(target, url_policy)
    return insert_run(team_id, target, data)


def insert_run(team_id: int, target: RunTarget, data: CreateJourneyRunInput) -> JourneyRun:
    """Write a pending run for a target that was already checked. Only touches the database.

    Raises `JourneyRunInProgressError` when the journey already has an unfinished run.
    """
    reap_stale_runs(team_id, journey_id=data.journey_id)
    try:
        # The partial unique index on active runs settles two creates that race past each other.
        with transaction.atomic():
            return JourneyRun.objects.for_team(team_id).create(
                team_id=team_id,
                journey_id=data.journey_id,
                created_by_id=data.created_by_id,
                trigger=data.trigger,
                base_url=target.base_origin,
                commit_sha=data.commit_sha,
                branch=data.branch,
                viewport_width=data.viewport_width,
                viewport_height=data.viewport_height,
                deploy_id=data.deploy_id,
            )
    except IntegrityError as e:
        raise JourneyRunInProgressError("This journey already has a run in progress. Wait for it to finish.") from e


def reap_stale_runs(team_id: int, *, journey_id: UUID | None = None) -> int:
    """End runs that no worker will finish. Returns how many it ended."""
    now = timezone.now()
    runs = JourneyRun.objects.for_team(team_id)
    if journey_id is not None:
        runs = runs.filter(journey_id=journey_id)
    stuck = runs.filter(status=JourneyRunStatus.RUNNING, started_at__lt=now - RUN_STALE_AFTER).update(
        status=JourneyRunStatus.ERRORED,
        finished_at=now,
        error="The run stopped before it finished. Start it again.",
    )
    lost = runs.filter(status=JourneyRunStatus.PENDING, created_at__lt=now - PENDING_STALE_AFTER).update(
        status=JourneyRunStatus.ERRORED,
        finished_at=now,
        error="The run never started. Start it again.",
    )
    return stuck + lost


def reap_stale_runs_all_teams() -> int:
    """End stale runs in every team. Returns how many it ended.

    The search reads across teams through the partial unique index on active runs, which holds only
    pending and running rows, so it stays cheap however many runs have finished. Each team's runs are
    then ended in that team's scope.
    """
    now = timezone.now()
    stale = JourneyRun.objects.unscoped().filter(
        Q(status=JourneyRunStatus.RUNNING, started_at__lt=now - RUN_STALE_AFTER)
        | Q(status=JourneyRunStatus.PENDING, created_at__lt=now - PENDING_STALE_AFTER)
    )
    team_ids = sorted(set(stale.values_list("team_id", flat=True)))
    return sum(reap_stale_runs(team_id) for team_id in team_ids)


def get_run(team_id: int, journey_id: UUID, run_id: UUID) -> JourneyRun:
    try:
        return JourneyRun.objects.for_team(team_id).get(id=run_id, journey_id=journey_id)
    except JourneyRun.DoesNotExist as e:
        raise JourneyRunNotFoundError(f"Run {run_id} not found") from e


def get_run_steps(run: JourneyRun) -> list[JourneyRunStep]:
    return list(JourneyRunStep.objects.for_team(run.team_id).filter(run_id=run.id).order_by("index"))


@frozen
class StepFailure:
    """The first failed step of a run."""

    index: int
    reason: JourneyStepFailureReason | None
    message: str


@frozen
class RunSummary:
    run: JourneyRun
    # None unless a step of the run failed.
    failure: StepFailure | None


def first_failures(team_id: int, run_ids: list[UUID]) -> dict[UUID, StepFailure]:
    """The first failed step of each listed run that has one, read in one query."""
    rows = (
        JourneyRunStep.objects.for_team(team_id)
        .filter(run_id__in=run_ids, status=JourneyRunStepStatus.FAILED)
        .order_by("run_id", "index")
        .distinct("run_id")
        .values_list("run_id", "index", "failure_reason", "message")
    )
    return {
        run_id: StepFailure(index=index, reason=JourneyStepFailureReason(reason) if reason else None, message=message)
        for run_id, index, reason, message in rows
    }


def summarize(team_id: int, runs: list[JourneyRun]) -> list[RunSummary]:
    failures = first_failures(team_id, [run.id for run in runs])
    return [RunSummary(run=run, failure=failures.get(run.id)) for run in runs]


def list_runs(team_id: int, journey_id: UUID, page: PageRequest) -> Page[RunSummary]:
    get_journey(team_id, journey_id)
    runs_page = select_page(
        JourneyRun.objects.for_team(team_id).filter(journey_id=journey_id).order_by("-created_at"), page
    )
    return Page(results=summarize(team_id, runs_page.results), count=runs_page.count)


def latest_runs(team_id: int, journey_ids: list[UUID]) -> list[RunSummary]:
    """The newest run of each journey in `journey_ids` that has one."""
    newest = (
        JourneyRun.objects.for_team(team_id)
        .filter(journey_id__in=journey_ids)
        .order_by("journey_id", "-created_at")
        .distinct("journey_id")
    )
    return summarize(team_id, list(newest))


def execute_run(team_id: int, run_id: UUID, *, runtime: RunRuntime) -> JourneyRun:
    """Run the browser work for a pending run. A run in any other state is returned unchanged."""
    claimed = (
        JourneyRun.objects.for_team(team_id)
        .filter(id=run_id, status=JourneyRunStatus.PENDING)
        .update(status=JourneyRunStatus.RUNNING, started_at=timezone.now())
    )
    run = JourneyRun.objects.for_team(team_id).get(id=run_id)
    if not claimed:
        return run
    try:
        _execute_claimed(run, runtime)
    except (BrowserUnavailableError, ScreenshotStorageUnavailableError, JourneyNotRunnableError) as e:
        _finish_errored(run, str(e))
    except JourneyRunTargetNotAllowedError as e:
        _finish_errored(run, f"The run can't open its start page. {e}")
    except Exception as e:
        logger.exception("user_journeys.run_failed_unexpectedly", team_id=team_id, run_id=str(run_id))
        capture_exception(e, additional_properties={"team_id": team_id, "journey_run_id": str(run_id)})
        _finish_errored(run, "The run stopped because of an unexpected error. Start it again.")
    run.refresh_from_db()
    return run


def _finish_errored(run: JourneyRun, error: str) -> None:
    JourneyRun.objects.for_team(run.team_id).filter(id=run.id, status=JourneyRunStatus.RUNNING).update(
        status=JourneyRunStatus.ERRORED, finished_at=timezone.now(), error=error
    )


def _baseline_run(run: JourneyRun) -> JourneyRun | None:
    return (
        JourneyRun.objects.for_team(run.team_id)
        .filter(
            journey_id=run.journey_id,
            status=JourneyRunStatus.PASSED,
            viewport_width=run.viewport_width,
            viewport_height=run.viewport_height,
        )
        .exclude(id=run.id)
        .order_by("-created_at")
        .first()
    )


def _execute_claimed(run: JourneyRun, runtime: RunRuntime) -> None:
    if not is_user_journeys_enabled(run.team_id):
        raise JourneyNotRunnableError("User journeys is turned off for this project.")
    journey = get_journey(run.team_id, run.journey_id)
    # The journey may have changed since the run was created, so the target is resolved and checked again.
    target = resolve_target(journey, run.base_url)
    policy = runtime.url_policy(run.team_id)
    check_target_allowed(target, policy)
    JourneyRun.objects.for_team(run.team_id).filter(id=run.id).update(start_url=target.start_url)

    plan = RunPlan(
        steps=target.steps,
        start_url=target.start_url,
        recorded_origin=target.recorded_origin,
        base_origin=target.base_origin,
    )
    options = BrowserOptions(
        viewport_width=run.viewport_width,
        viewport_height=run.viewport_height,
        background=run.trigger != JourneyRunTrigger.MANUAL,
    )
    with runtime.open_page(options, policy) as page:
        outcomes = StepExecutor(page, plan).run()

    baseline = _baseline_run(run)
    baseline_steps = {step.index: step for step in get_run_steps(baseline)} if baseline is not None else {}
    snapshots = steps_to_json(target.steps)
    rows = [
        _step_row(run, outcome, snapshots[outcome.index], baseline_steps.get(outcome.index), runtime.store)
        for outcome in outcomes
    ]
    failed = any(outcome.status == JourneyRunStepStatus.FAILED for outcome in outcomes)
    with transaction.atomic():
        finished = (
            JourneyRun.objects.for_team(run.team_id)
            .filter(id=run.id, status=JourneyRunStatus.RUNNING)
            .update(
                status=JourneyRunStatus.FAILED if failed else JourneyRunStatus.PASSED,
                finished_at=timezone.now(),
                baseline_run_id=baseline.id if baseline is not None else None,
            )
        )
        # A run the reaper already ended keeps its errored state, and its late results are dropped.
        if finished:
            JourneyRunStep.objects.for_team(run.team_id).filter(run_id=run.id).delete()
            JourneyRunStep.objects.for_team(run.team_id).bulk_create(rows)


def _step_row(
    run: JourneyRun,
    outcome: StepOutcome,
    snapshot: dict[str, Any],
    baseline: JourneyRunStep | None,
    store: ScreenshotStore,
) -> JourneyRunStep:
    row = JourneyRunStep(
        team_id=run.team_id,
        run_id=run.id,
        index=outcome.index,
        step=snapshot,
        status=outcome.status,
        failure_reason=outcome.failure_reason,
        message=outcome.message,
        duration_ms=outcome.duration_ms,
    )
    if outcome.screenshot is None:
        return row
    # A baseline step only compares when it ran the same step definition.
    baseline_hash = baseline.screenshot_hash if baseline is not None and baseline.step == snapshot else None
    stored = store_and_compare(store, run.team_id, outcome.screenshot, baseline_hash)
    row.screenshot_hash = stored.screenshot_hash
    row.baseline_screenshot_hash = stored.baseline_screenshot_hash
    row.diff_screenshot_hash = stored.diff_screenshot_hash
    row.diff_percentage = stored.diff_percentage
    row.visual_change = stored.visual_change
    return row
