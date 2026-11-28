"""
Facade for user_journeys.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from posthog.schema import FunnelsQuery

from posthog.paging import Page, PageRequest

from ..feature_flags import is_user_journeys_enabled
from ..logic import deploys, element_paths, funnels, journeys, runs
from ..logic.run_screenshots import ScreenshotStore
from ..logic.run_urls import TeamUrlPolicy, url_shape_error
from ..models import (
    Journey as JourneyModel,
    JourneyDeploy as JourneyDeployModel,
    JourneyRun as JourneyRunModel,
    JourneyRunStep as JourneyRunStepModel,
)
from ..tasks.tasks import enqueue_journey_run
from . import contracts
from .enums import (
    JourneyRunStatus,
    JourneyRunStepStatus,
    JourneyRunTrigger,
    JourneySource,
    JourneyStepFailureReason,
    JourneyVisualChange,
)


def is_enabled(team_id: int) -> bool:
    return is_user_journeys_enabled(team_id)


def _to_contract(journey: JourneyModel) -> contracts.Journey:
    return contracts.Journey(
        id=journey.id,
        team_id=journey.team_id,
        name=journey.name,
        description=journey.description,
        # The pydantic contract parses the stored JSON into typed steps, so a malformed row fails here.
        steps=journey.steps,
        conversion_window_minutes=journey.conversion_window_minutes,
        source=JourneySource(journey.source),
        created_by_id=journey.created_by_id,
        created_at=journey.created_at,
        updated_at=journey.updated_at,
        start_url=journey.start_url,
    )


def _with_latest_runs(team_id: int, journeys: list[JourneyModel]) -> list[contracts.JourneyWithLatestRun]:
    latest = {
        summary.run.journey_id: contracts.JourneyLatestRun(
            journey_id=summary.run.journey_id,
            run_id=summary.run.id,
            status=JourneyRunStatus(summary.run.status),
            created_at=summary.run.created_at,
            finished_at=summary.run.finished_at,
            failed_step_index=summary.failure.index if summary.failure is not None else None,
        )
        for summary in runs.latest_runs(team_id, [journey.id for journey in journeys])
    }
    return [
        contracts.JourneyWithLatestRun(**asdict(_to_contract(journey)), latest_run=latest.get(journey.id))
        for journey in journeys
    ]


def _with_latest_run(journey: JourneyModel) -> contracts.JourneyWithLatestRun:
    return _with_latest_runs(journey.team_id, [journey])[0]


def list_journeys(team_id: int, page: PageRequest) -> Page[contracts.JourneyWithLatestRun]:
    """One page of the team's journeys, newest first, each with its newest run, and the total count."""
    journey_page = journeys.list_journeys(team_id, page)
    return Page(results=_with_latest_runs(team_id, journey_page.results), count=journey_page.count)


def get_journey(team_id: int, journey_id: UUID) -> contracts.JourneyWithLatestRun:
    return _with_latest_run(journeys.get_journey(team_id, journey_id))


def create_journey(
    team_id: int, created_by_id: int | None, data: contracts.CreateJourneyInput
) -> contracts.JourneyWithLatestRun:
    return _with_latest_run(journeys.create_journey(team_id, created_by_id, data))


def update_journey(
    team_id: int, journey_id: UUID, data: contracts.UpdateJourneyInput
) -> contracts.JourneyWithLatestRun:
    return _with_latest_run(journeys.update_journey(team_id, journey_id, data))


def delete_journey(team_id: int, journey_id: UUID) -> None:
    journeys.delete_journey(team_id, journey_id)


def journey_to_funnels_query(journey: contracts.Journey) -> FunnelsQuery:
    """The ordered, per-session funnel that measures conversion through the journey's steps."""
    return funnels.journey_to_funnels_query(journey)


def get_element_paths(team_id: int, query: contracts.ElementPathsQuery) -> contracts.ElementPathsResult:
    """The most common paths that sessions take before and after a click on one element."""
    return element_paths.get_element_paths(team_id, query, now=datetime.now(UTC))


def run_url_error(url: str) -> str | None:
    """Why `url` can't be a page a run opens, judged on its text alone, or None when it can."""
    return url_shape_error(url)


def _to_run(run: JourneyRunModel, failure: runs.StepFailure | None) -> contracts.JourneyRun:
    return contracts.JourneyRun(
        id=run.id,
        team_id=run.team_id,
        journey_id=run.journey_id,
        trigger=JourneyRunTrigger(run.trigger),
        status=JourneyRunStatus(run.status),
        start_url=run.start_url,
        base_url=run.base_url,
        commit_sha=run.commit_sha,
        branch=run.branch,
        viewport_width=run.viewport_width,
        viewport_height=run.viewport_height,
        error=run.error,
        baseline_run_id=run.baseline_run_id,
        created_by_id=run.created_by_id,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        deploy_id=run.deploy_id,
        failed_step_index=failure.index if failure is not None else None,
        failure_reason=failure.reason if failure is not None else None,
    )


def _image_url(store: ScreenshotStore, team_id: int, content_hash: str | None) -> str | None:
    return store.url(team_id, content_hash) if content_hash else None


def _to_run_step(step: JourneyRunStepModel, store: ScreenshotStore) -> contracts.JourneyRunStep:
    return contracts.JourneyRunStep(
        index=step.index,
        step=step.step,
        status=JourneyRunStepStatus(step.status),
        failure_reason=JourneyStepFailureReason(step.failure_reason) if step.failure_reason else None,
        message=step.message,
        screenshot_url=_image_url(store, step.team_id, step.screenshot_hash),
        baseline_screenshot_url=_image_url(store, step.team_id, step.baseline_screenshot_hash),
        diff_screenshot_url=_image_url(store, step.team_id, step.diff_screenshot_hash),
        diff_percentage=step.diff_percentage,
        visual_change=JourneyVisualChange(step.visual_change) if step.visual_change else None,
        duration_ms=step.duration_ms,
    )


def start_run(team_id: int, data: contracts.CreateJourneyRunInput) -> contracts.JourneyRun:
    """Create a pending run and queue its execution once the current transaction commits.

    Raises `JourneyNotFoundError`, `JourneyNotRunnableError`, `JourneyRunTargetNotAllowedError` or
    `JourneyRunInProgressError` before anything is recorded.
    """
    run = runs.create_run(team_id, data, url_policy=TeamUrlPolicy.for_team(team_id))
    enqueue_journey_run(team_id, run.id)
    return _to_run(run, failure=None)


def list_runs(team_id: int, journey_id: UUID, page: PageRequest) -> Page[contracts.JourneyRun]:
    """One page of a journey's runs, newest first, each with its first failed step but without its steps."""
    return runs.list_runs(team_id, journey_id, page).map(lambda summary: _to_run(summary.run, summary.failure))


def get_run(team_id: int, journey_id: UUID, run_id: UUID) -> contracts.JourneyRunDetail:
    """A run with its steps and short-lived screenshot URLs."""
    run = runs.get_run(team_id, journey_id, run_id)
    store = runs.production_runtime().store
    steps = [_to_run_step(step, store) for step in runs.get_run_steps(run)]
    failed = next((step for step in steps if step.status == JourneyRunStepStatus.FAILED), None)
    failure = (
        runs.StepFailure(index=failed.index, reason=failed.failure_reason, message=failed.message) if failed else None
    )
    return contracts.JourneyRunDetail(**asdict(_to_run(run, failure)), steps=steps)


def _to_deploy(deploy: JourneyDeployModel, run_statuses: list[JourneyRunStatus]) -> contracts.JourneyDeploy:
    return contracts.JourneyDeploy(
        id=deploy.id,
        team_id=deploy.team_id,
        commit_sha=deploy.commit_sha,
        branch=deploy.branch,
        base_url=deploy.base_url,
        label=deploy.label,
        url=deploy.url,
        deployed_at=deploy.deployed_at,
        created_at=deploy.created_at,
        created_by_id=deploy.created_by_id,
        status=deploys.deploy_status(run_statuses),
        run_count=len(run_statuses),
        journeys_over_limit=deploy.journeys_over_limit,
    )


def _to_deploy_run(row: deploys.DeployRunRow) -> contracts.JourneyDeployRun:
    run, failure = row.summary.run, row.summary.failure
    return contracts.JourneyDeployRun(
        journey_id=run.journey_id,
        journey_name=row.journey_name,
        run_id=run.id,
        status=JourneyRunStatus(run.status),
        finished_at=run.finished_at,
        failed_step_index=failure.index if failure is not None else None,
        failure_reason=failure.reason if failure is not None else None,
        message=failure.message if failure is not None else run.error or "",
    )


def _deploy_detail(deploy: JourneyDeployModel) -> contracts.JourneyDeployDetail:
    rows = deploys.deploy_runs(deploy)
    summary = _to_deploy(deploy, [JourneyRunStatus(row.summary.run.status) for row in rows])
    return contracts.JourneyDeployDetail(
        **asdict(summary),
        runs=[_to_deploy_run(row) for row in rows],
        skipped=deploys.deploy_skips(deploy),
    )


def create_deploy(team_id: int, data: contracts.CreateJourneyDeployInput) -> contracts.RecordedJourneyDeploy:
    """Record a deploy and start a run of each selected journey against it.

    Every journey of the project runs when `journey_ids` is None, up to `MAX_JOURNEYS_PER_DEPLOY`,
    oldest first; the deploy counts the rest in `journeys_over_limit`. A journey that can't run is
    reported in `skipped`. A retry with the same commit and base URL inside
    `DEPLOY_IDEMPOTENCY_WINDOW_MINUTES` returns the earlier deploy with `created=False` and starts
    nothing. Raises `JourneyRunTargetNotAllowedError`, before anything is recorded, when the project
    may not open `base_url`.
    """
    creation = deploys.create_deploy(team_id, data, url_policy=TeamUrlPolicy.for_team(team_id))
    for run_id in creation.started_run_ids:
        enqueue_journey_run(team_id, run_id)
    return contracts.RecordedJourneyDeploy(deploy=_deploy_detail(creation.deploy), created=creation.created)


def get_deploy(team_id: int, deploy_id: UUID) -> contracts.JourneyDeployDetail:
    """A deploy with the verdict on its runs, a summary of each run, and the journeys it skipped."""
    return _deploy_detail(deploys.get_deploy(team_id, deploy_id))


def list_deploys(team_id: int, page: PageRequest) -> Page[contracts.JourneyDeploy]:
    """One page of the project's deploys, newest deploy time first, each with the verdict on its runs."""
    deploy_page = deploys.list_deploys(team_id, page)
    statuses = deploys.run_statuses_by_deploy(team_id, [deploy.id for deploy in deploy_page.results])
    return deploy_page.map(lambda deploy: _to_deploy(deploy, statuses.get(deploy.id, [])))
