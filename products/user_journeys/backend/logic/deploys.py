"""Record the deploys CI announces, start a run of each journey against them, and roll the runs up.

Every URL check, each of which may resolve DNS, happens before the deploy's transaction opens. The
transaction then only writes: the deploy and its runs, under an advisory lock on the commit and
base URL. A retried announcement waits for that lock, then finds the deploy the first one recorded,
so it never starts a second set of runs and never sees a deploy whose runs are still being created.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from pydantic import TypeAdapter

from posthog.dataclasses import frozen
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from ..facade.contracts import (
    DEPLOY_IDEMPOTENCY_WINDOW_MINUTES,
    MAX_JOURNEYS_PER_DEPLOY,
    CreateJourneyDeployInput,
    CreateJourneyRunInput,
    JourneyDeployNotFoundError,
    JourneyDeploySkip,
    JourneyNotRunnableError,
    JourneyRunInProgressError,
    JourneyRunTargetNotAllowedError,
)
from ..facade.enums import JourneyDeploySkipReason, JourneyDeployStatus, JourneyRunStatus, JourneyRunTrigger
from ..models import Journey, JourneyDeploy, JourneyRun
from . import runs
from .run_urls import UrlPolicy, origin_of, url_shape_error

_SKIPS_ADAPTER: TypeAdapter[list[JourneyDeploySkip]] = TypeAdapter(list[JourneyDeploySkip])

_ACTIVE_RUN_STATUSES = frozenset({JourneyRunStatus.PENDING, JourneyRunStatus.RUNNING})


def deploy_status(run_statuses: Sequence[JourneyRunStatus]) -> JourneyDeployStatus:
    """The verdict on a deploy from the statuses of its runs.

    Every value except `pending` and `running` is final: `failed` wins as soon as one run fails,
    because no later run can undo it, while `errored` and `passed` wait until every run has ended.
    """
    if not run_statuses:
        return JourneyDeployStatus.NO_RUNS
    if JourneyRunStatus.FAILED in run_statuses:
        return JourneyDeployStatus.FAILED
    if any(status in _ACTIVE_RUN_STATUSES for status in run_statuses):
        if all(status == JourneyRunStatus.PENDING for status in run_statuses):
            return JourneyDeployStatus.PENDING
        return JourneyDeployStatus.RUNNING
    if JourneyRunStatus.ERRORED in run_statuses:
        return JourneyDeployStatus.ERRORED
    return JourneyDeployStatus.PASSED


@frozen
class DeployCreation:
    deploy: JourneyDeploy
    created: bool
    # Runs this call created, which the caller queues once the transaction commits.
    started_run_ids: list[UUID]


@frozen
class DeployRunRow:
    summary: runs.RunSummary
    journey_name: str


def base_url_error(base_url: str, url_policy: UrlPolicy) -> str | None:
    """Why no run may open pages on `base_url`'s origin, or None when runs may."""
    shape_error = url_shape_error(base_url)
    if shape_error is not None:
        return shape_error
    return url_policy.page_error(origin_of(base_url))


def create_deploy(team_id: int, data: CreateJourneyDeployInput, *, url_policy: UrlPolicy) -> DeployCreation:
    """Record a deploy and create a pending run of each selected journey against it.

    Raises `JourneyRunTargetNotAllowedError` before anything is written when `base_url` can't be
    opened. A journey that can't run is recorded as skipped, with the reason, instead.
    """
    base_origin = None
    if data.base_url:
        error = base_url_error(data.base_url, url_policy)
        if error is not None:
            raise JourneyRunTargetNotAllowedError(error)
        base_origin = origin_of(data.base_url)
    selection = _select_journeys(team_id, data.journey_ids)
    planned, unrunnable = _plan_runs(selection.journeys, base_origin, url_policy)
    skipped = [*selection.missing, *unrunnable]

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"user_journeys_deploy:{team_id}:{data.commit_sha}:{base_origin or ''}"],
            )
        existing = (
            JourneyDeploy.objects.for_team(team_id)
            .filter(
                commit_sha=data.commit_sha,
                base_url=base_origin,
                created_at__gte=timezone.now() - timedelta(minutes=DEPLOY_IDEMPOTENCY_WINDOW_MINUTES),
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return DeployCreation(deploy=existing, created=False, started_run_ids=[])

        deploy = JourneyDeploy.objects.for_team(team_id).create(
            team_id=team_id,
            created_by_id=data.created_by_id,
            commit_sha=data.commit_sha,
            branch=data.branch,
            base_url=base_origin,
            label=data.label,
            url=data.url,
            deployed_at=data.deployed_at or timezone.now(),
            journeys_over_limit=selection.over_limit,
        )
        started: list[UUID] = []
        for planned_run in planned:
            run_input = CreateJourneyRunInput(
                journey_id=planned_run.journey.id,
                trigger=JourneyRunTrigger.DEPLOY,
                base_url=base_origin,
                commit_sha=deploy.commit_sha,
                branch=deploy.branch,
                created_by_id=data.created_by_id,
                deploy_id=deploy.id,
            )
            try:
                started.append(runs.insert_run(team_id, planned_run.target, run_input).id)
            except JourneyRunInProgressError as e:
                skipped.append(_skip(planned_run.journey, JourneyDeploySkipReason.RUN_IN_PROGRESS, str(e)))
        deploy.skipped = _SKIPS_ADAPTER.dump_python(skipped, mode="json")
        deploy.save(update_fields=["skipped"])
    return DeployCreation(deploy=deploy, created=True, started_run_ids=started)


@frozen
class _JourneySelection:
    journeys: list[Journey]
    missing: list[JourneyDeploySkip]
    over_limit: int


@frozen
class _PlannedRun:
    journey: Journey
    target: runs.RunTarget


def _select_journeys(team_id: int, journey_ids: list[UUID] | None) -> _JourneySelection:
    journeys = Journey.objects.for_team(team_id).only("id", "name", "start_url", "steps")
    if journey_ids is None:
        # Oldest first, so adding a journey to a project over the limit never pushes out one that ran before.
        ordered = journeys.order_by("created_at", "id")
        selected = list(ordered[:MAX_JOURNEYS_PER_DEPLOY])
        over_limit = ordered.count() - len(selected) if len(selected) == MAX_JOURNEYS_PER_DEPLOY else 0
        return _JourneySelection(journeys=selected, missing=[], over_limit=over_limit)

    wanted = list(dict.fromkeys(journey_ids))
    if len(wanted) > MAX_JOURNEYS_PER_DEPLOY:
        raise ValueError(f"A deploy runs at most {MAX_JOURNEYS_PER_DEPLOY} journeys.")
    found = {journey.id: journey for journey in journeys.filter(id__in=wanted)}
    missing = [
        JourneyDeploySkip(
            journey_id=journey_id,
            journey_name=None,
            reason=JourneyDeploySkipReason.JOURNEY_NOT_FOUND,
            message="This project has no journey with this ID. Check the journey IDs the deploy sends.",
        )
        for journey_id in wanted
        if journey_id not in found
    ]
    return _JourneySelection(
        journeys=[found[journey_id] for journey_id in wanted if journey_id in found], missing=missing, over_limit=0
    )


def _plan_runs(
    journeys: list[Journey], base_origin: str | None, url_policy: UrlPolicy
) -> tuple[list[_PlannedRun], list[JourneyDeploySkip]]:
    """Split the selected journeys into those a run may start for and those it must skip, with why.

    The policy caches its verdict per host, so journeys that share an origin cost one DNS lookup.
    """
    planned: list[_PlannedRun] = []
    skipped: list[JourneyDeploySkip] = []
    for journey in journeys:
        try:
            target = runs.resolve_target(journey, base_origin)
            runs.check_target_allowed(target, url_policy)
        except JourneyNotRunnableError as e:
            skipped.append(_skip(journey, JourneyDeploySkipReason.NOT_RUNNABLE, str(e)))
        except JourneyRunTargetNotAllowedError as e:
            skipped.append(_skip(journey, JourneyDeploySkipReason.TARGET_NOT_ALLOWED, str(e)))
        else:
            planned.append(_PlannedRun(journey=journey, target=target))
    return planned, skipped


def _skip(journey: Journey, reason: JourneyDeploySkipReason, message: str) -> JourneyDeploySkip:
    return JourneyDeploySkip(journey_id=journey.id, journey_name=journey.name, reason=reason, message=message)


def get_deploy(team_id: int, deploy_id: UUID) -> JourneyDeploy:
    try:
        return JourneyDeploy.objects.for_team(team_id).get(id=deploy_id)
    except JourneyDeploy.DoesNotExist as e:
        raise JourneyDeployNotFoundError(f"Deploy {deploy_id} not found") from e


def list_deploys(team_id: int, page: PageRequest) -> Page[JourneyDeploy]:
    return select_page(JourneyDeploy.objects.for_team(team_id).order_by("-deployed_at"), page)


def deploy_skips(deploy: JourneyDeploy) -> list[JourneyDeploySkip]:
    return _SKIPS_ADAPTER.validate_python(deploy.skipped)


def run_statuses_by_deploy(team_id: int, deploy_ids: list[UUID]) -> dict[UUID, list[JourneyRunStatus]]:
    statuses: dict[UUID, list[JourneyRunStatus]] = defaultdict(list)
    rows = JourneyRun.objects.for_team(team_id).filter(deploy_id__in=deploy_ids).values_list("deploy_id", "status")
    for deploy_id, status in rows:
        statuses[deploy_id].append(JourneyRunStatus(status))
    return statuses


def deploy_runs(deploy: JourneyDeploy) -> list[DeployRunRow]:
    """The deploy's runs, by journey name, each with its first failed step."""
    deploy_run_rows = list(
        JourneyRun.objects.for_team(deploy.team_id)
        .filter(deploy_id=deploy.id)
        .select_related("journey")
        .order_by("journey__name", "id")
    )
    return [
        DeployRunRow(summary=summary, journey_name=summary.run.journey.name)
        for summary in runs.summarize(deploy.team_id, deploy_run_rows)
    ]
