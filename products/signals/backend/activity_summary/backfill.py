"""Activity summaries built as of past dates, for the offline evaluation of activity summary vectors.

A backfill build reads only the inputs before its as-of moment, and writes only an embedding under its
own document type and an event. It never touches `UserActivitySummary`, its versions or the queue state.
"""

import datetime
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

from django.db import connection

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.activity_summary.logic import (
    MIN_UNITS,
    ActivitySummaryUpdate,
    UpdateStatus,
    build_summary_as_of,
    render_as_of,
)
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION, summary_text
from products.signals.backend.activity_summary.queue import max_update_cost_usd
from products.signals.backend.activity_summary.render import DEFAULT_LIMITS, RENDER_VERSION, Product, RenderLimits
from products.signals.backend.activity_summary.summaries import DEFAULT_MODEL
from products.signals.backend.activity_summary.tick import capture_generated, emit_summary_embedding
from products.signals.backend.models import SignalReportAction

logger = structlog.get_logger(__name__)

# Separate from the live `activity_summary` type, so the live vectors stay clean.
BACKFILL_DOCUMENT_TYPE = "activity_summary_backfill"
SOURCE_BACKFILL = "backfill"
# The document id suffix of a build without inbox inputs, so both variants of one pair and day coexist.
EXCLUDE_INBOX_SUFFIX = ":no_inbox"
INBOX_PRODUCTS: frozenset[Product] = frozenset({Product.INBOX})
# The status of a build that raised. It can have called the model, so it counts at the highest cost.
STATUS_EXCEPTION = "exception"


@frozen(order=True)
class TeamUser:
    team_id: int
    user_id: int


@frozen
class BackfillJob:
    team_id: int
    user_id: int
    as_of: datetime.datetime


@frozen
class BackfillOptions:
    limits: RenderLimits = DEFAULT_LIMITS
    min_units: int = MIN_UNITS
    exclude_inbox: bool = False


@frozen
class BackfillPlan:
    jobs: int
    # Jobs whose rendered input clears `min_units`, so a real run would call the model for each.
    builds: int
    max_cost_usd: float


@frozen
class BackfillResult:
    jobs: int
    attempted: int
    statuses: dict[str, int]
    cost_usd: float
    stopped_at_cost_cap: bool


def eligible_team_ids(team_ids: Iterable[int]) -> set[int]:
    """The teams whose organization approved AI data processing and opted in to AI training."""
    return set(
        Team.objects.filter(
            id__in=list(team_ids),
            organization__is_ai_data_processing_approved=True,
            organization__is_ai_training_opted_in=True,
        ).values_list("id", flat=True)
    )


def inbox_users(as_of: datetime.datetime) -> set[TeamUser]:
    """Every (team, user) with an inbox report action that started before `as_of`."""
    return {
        TeamUser(team_id=team_id, user_id=user_id)
        for team_id, user_id in (
            # nosemgrep: idor-lookup-without-team (an operator backfill over all teams, with no user input)
            SignalReportAction.all_teams.filter(first_at__lt=as_of).values_list("team_id", "user_id").distinct()
        )
    }


def backfill_jobs(
    as_of_dates: Sequence[datetime.datetime],
    *,
    pair: TeamUser | None = None,
) -> list[BackfillJob]:
    """One job per as-of date and pair, for `pair` or for the inbox users before that date, on eligible teams only."""
    jobs: list[BackfillJob] = []
    for as_of in as_of_dates:
        pairs = {pair} if pair is not None else inbox_users(as_of)
        eligible = eligible_team_ids({p.team_id for p in pairs})
        jobs.extend(
            BackfillJob(team_id=p.team_id, user_id=p.user_id, as_of=as_of)
            for p in sorted(pairs)
            if p.team_id in eligible
        )
    return jobs


def _excluded_products(options: BackfillOptions) -> frozenset[Product]:
    return INBOX_PRODUCTS if options.exclude_inbox else frozenset()


def document_id(job: BackfillJob, exclude_inbox: bool) -> str:
    base = f"{job.user_id}:{job.as_of.date().isoformat()}"
    return f"{base}{EXCLUDE_INBOX_SUFFIX}" if exclude_inbox else base


def _emit_embedding(job: BackfillJob, update: ActivitySummaryUpdate, exclude_inbox: bool) -> None:
    if update.summary is None:
        return
    emit_summary_embedding(
        job.team_id,
        content=summary_text(update.summary),
        document_type=BACKFILL_DOCUMENT_TYPE,
        document_id=document_id(job, exclude_inbox),
        # The as-of moment, so a rerun of the same job replaces its own row.
        timestamp=job.as_of,
        metadata={
            "prompt_version": PROMPT_VERSION,
            "render_version": RENDER_VERSION,
            "model": DEFAULT_MODEL,
            "source": SOURCE_BACKFILL,
            "exclude_inbox": exclude_inbox,
        },
    )


def run_job(job: BackfillJob, options: BackfillOptions) -> ActivitySummaryUpdate:
    """Build one summary as of the job date, then emit its embedding and its event."""
    update = build_summary_as_of(
        job.team_id,
        job.user_id,
        job.as_of,
        limits=options.limits,
        min_units=options.min_units,
        exclude_products=_excluded_products(options),
        trace_variant=f"{SOURCE_BACKFILL}:{document_id(job, options.exclude_inbox)}",
    )
    if update.status == UpdateStatus.OK:
        try:
            _emit_embedding(job, update, options.exclude_inbox)
        except Exception:
            logger.exception("activity_summary_backfill_embedding_failed", team_id=job.team_id, user_id=job.user_id)
    if update.status in (UpdateStatus.OK, UpdateStatus.FAILED):
        try:
            capture_generated(job.team_id, job.user_id, update, None, source=SOURCE_BACKFILL)
        except Exception:
            logger.exception("activity_summary_backfill_capture_failed", team_id=job.team_id, user_id=job.user_id)
    return update


def plan_backfill(jobs: Sequence[BackfillJob], options: BackfillOptions) -> BackfillPlan:
    """Count the jobs that would call the model, without a model call."""
    builds = 0
    for job in jobs:
        built = render_as_of(
            job.team_id, job.user_id, job.as_of, limits=options.limits, exclude_products=_excluded_products(options)
        )
        builds += built is not None and built.rendered.units >= options.min_units
    return BackfillPlan(jobs=len(jobs), builds=builds, max_cost_usd=builds * max_update_cost_usd(options.limits))


def _run_job_in_thread(job: BackfillJob, options: BackfillOptions) -> ActivitySummaryUpdate:
    try:
        return run_job(job, options)
    finally:
        # Each worker thread opens its own connection, and nothing else closes it.
        connection.close()


def _guarded(
    run: Callable[[BackfillJob, BackfillOptions], ActivitySummaryUpdate], job: BackfillJob, options: BackfillOptions
) -> ActivitySummaryUpdate | None:
    try:
        return run(job, options)
    except Exception:
        logger.exception("activity_summary_backfill_job_failed", team_id=job.team_id, user_id=job.user_id)
        return None


def run_backfill(
    jobs: Sequence[BackfillJob],
    options: BackfillOptions,
    *,
    concurrency: int = 1,
    max_cost_usd: float,
    on_batch: Callable[[int, float], None] | None = None,
) -> BackfillResult:
    """Run the jobs in batches of `concurrency`, and stop between batches when the cost reaches `max_cost_usd`.

    A build without a cost, or a build that raised, counts at the highest cost of one update."""
    bound = max_update_cost_usd(options.limits)
    statuses: Counter[str] = Counter()
    cost = 0.0
    attempted = 0
    batch_size = max(1, concurrency)
    executor = ThreadPoolExecutor(max_workers=batch_size) if batch_size > 1 else None
    try:
        while attempted < len(jobs) and cost < max_cost_usd:
            batch = jobs[attempted : attempted + batch_size]
            attempted += len(batch)
            if executor is None:
                outcomes = [_guarded(run_job, job, options) for job in batch]
            else:
                outcomes = list(executor.map(lambda job: _guarded(_run_job_in_thread, job, options), batch))
            for update in outcomes:
                if update is None:
                    statuses[STATUS_EXCEPTION] += 1
                    cost += bound
                    continue
                statuses[update.status.value] += 1
                if update.status in (UpdateStatus.OK, UpdateStatus.FAILED):
                    cost += bound if update.cost_usd is None else update.cost_usd
            if on_batch is not None:
                on_batch(attempted, cost)
    finally:
        if executor is not None:
            executor.shutdown()
    return BackfillResult(
        jobs=len(jobs),
        attempted=attempted,
        statuses=dict(statuses),
        cost_usd=cost,
        stopped_at_cost_cap=attempted < len(jobs),
    )
