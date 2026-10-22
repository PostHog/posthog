"""One activity summary update for one (team, user): gather, filter, render, summarize, persist."""

import datetime
import dataclasses
from enum import StrEnum
from typing import Any, Protocol

from django.db.models import Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.activity_summary.inputs import activity_parents, user_activity, user_tasks, user_views
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION, summary_text
from products.signals.backend.activity_summary.render import (
    DEFAULT_LIMITS,
    RENDER_VERSION,
    RenderLimits,
    build_input,
    sampling_seed,
)
from products.signals.backend.activity_summary.summaries import (
    DEFAULT_MODEL,
    MODEL_PRICES,
    cost_usd,
    gateway_client,
    summarize,
)
from products.signals.backend.models import UserActivitySummary

# Fewer rendered lines than this since the last update say too little to change the summary.
MIN_UNITS = 3
MIN_UPDATE_INTERVAL = datetime.timedelta(days=1)
# A pair that skipped or failed waits this long, so it does not take the queue head on every tick.
RETRY_BACKOFF = datetime.timedelta(hours=6)
# The error prefixes of an update that raised before it stored a result, before and after the model call.
EXCEPTION_ERROR_PREFIX = "exception: "
EXCEPTION_AFTER_MODEL_CALL_ERROR_PREFIX = "exception_after_model_call: "
# The watermark is inclusive in the stored summary, so the next read starts just after it.
_WATERMARK_STEP = datetime.timedelta(microseconds=1)


class UpdateAfterModelCallError(Exception):
    """An update raised after the model call, so the call counts against the daily caps."""

    def __init__(self, cost_usd: float | None) -> None:
        super().__init__("activity summary update raised after the model call")
        self.cost_usd = cost_usd


class UpdateStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED_AI_NOT_APPROVED = "skipped_ai_not_approved"
    SKIPPED_NOT_ELIGIBLE_YET = "skipped_not_eligible_yet"
    SKIPPED_TOO_FEW_UNITS = "skipped_too_few_units"


@frozen
class ActivitySummaryUpdate:
    status: UpdateStatus
    rendered_input: str | None = None
    summary: dict[str, Any] | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    error: str | None = None
    inputs_used: dict[str, Any] | None = None
    input_watermark: datetime.datetime | None = None
    rebuilt: bool = False


class StoredSummaryVersion(Protocol):
    @property
    def prompt_version(self) -> int | None: ...

    @property
    def render_version(self) -> int | None: ...

    @property
    def generated_at(self) -> datetime.datetime | None: ...


def is_stale(stored: StoredSummaryVersion | None, rebuild_before: datetime.datetime | None) -> bool:
    """True when a stored summary came from an older prompt or render, or before `rebuild_before`.

    A stale summary is rebuilt from the full window, so a version change reaches every input.
    """
    if stored is None or stored.generated_at is None:
        return False
    if (stored.prompt_version, stored.render_version) != (PROMPT_VERSION, RENDER_VERSION):
        return True
    return rebuild_before is not None and stored.generated_at < rebuild_before


def _input_start(watermark: datetime.datetime | None, now: datetime.datetime, window_days: int) -> datetime.datetime:
    earliest = now - datetime.timedelta(days=window_days)
    return earliest if watermark is None else max(earliest, watermark + _WATERMARK_STEP)


def _back_off(
    team_id: int, user_id: int, stored: UserActivitySummary | None, next_eligible_at: datetime.datetime
) -> None:
    # `update()` leaves `updated_at` alone, so the daily caps do not count a skip as a model call.
    if stored is not None:
        UserActivitySummary.objects.for_team(team_id).filter(id=stored.id).update(next_eligible_at=next_eligible_at)
        return
    UserActivitySummary.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        user_id=user_id,
        defaults={"status": UserActivitySummary.Status.SKIPPED, "next_eligible_at": next_eligible_at},
    )


def record_update_exception(team_id: int, user_id: int, error: BaseException) -> ActivitySummaryUpdate:
    """Store an update that raised as failed, keep the stored summary and watermark, and back the pair off.

    An update that raised after the model call keeps its cost. A missing cost counts at the bound.
    An update that raised before the model call keeps the cost of the earlier update.
    """
    next_eligible_at = timezone.now() + RETRY_BACKOFF
    if isinstance(error, UpdateAfterModelCallError):
        message = f"{EXCEPTION_AFTER_MODEL_CALL_ERROR_PREFIX}{type(error.__cause__).__name__}"
        UserActivitySummary.objects.for_team(team_id).update_or_create(
            team_id=team_id,
            user_id=user_id,
            defaults={
                "status": UserActivitySummary.Status.FAILED,
                "error": message,
                "tokens_in": None,
                "tokens_out": None,
                "cost_usd": error.cost_usd,
                "latency_ms": None,
                "next_eligible_at": next_eligible_at,
            },
        )
        return ActivitySummaryUpdate(status=UpdateStatus.FAILED, error=message, cost_usd=error.cost_usd)

    message = f"{EXCEPTION_ERROR_PREFIX}{type(error).__name__}"
    # `update()` leaves `updated_at` and a paid cost alone, so the daily caps still count an earlier update.
    updated = (
        UserActivitySummary.objects.for_team(team_id)
        .filter(user_id=user_id)
        .update(
            status=UserActivitySummary.Status.FAILED,
            error=message,
            cost_usd=Coalesce("cost_usd", Value(0.0)),
            next_eligible_at=next_eligible_at,
        )
    )
    if not updated:
        UserActivitySummary.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            user_id=user_id,
            defaults={
                "status": UserActivitySummary.Status.FAILED,
                "error": message,
                "cost_usd": 0.0,
                "next_eligible_at": next_eligible_at,
            },
        )
    return ActivitySummaryUpdate(status=UpdateStatus.FAILED, error=message, cost_usd=0.0)


def update_activity_summary(
    team_id: int,
    user_id: int,
    *,
    dry_run: bool = False,
    force: bool = False,
    min_units: int = MIN_UNITS,
    min_update_interval: datetime.timedelta = MIN_UPDATE_INTERVAL,
    limits: RenderLimits = DEFAULT_LIMITS,
    rebuild_before: datetime.datetime | None = None,
) -> ActivitySummaryUpdate:
    """Update the stored activity summary of one user in one project.

    Reads only the inputs newer than the stored watermark, or the last `limits.window_days` on a first
    run or for a stale summary (see `is_stale`). A stale summary is not sent to the model. A failed
    update records the error and keeps the stored summary and the watermark. With `dry_run`, the
    model is still called but nothing is written. `force` ignores `next_eligible_at`.
    A skip for too few units and a failed update set `next_eligible_at` to `RETRY_BACKOFF` from now.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    if team.organization.is_ai_data_processing_approved is not True:
        return ActivitySummaryUpdate(status=UpdateStatus.SKIPPED_AI_NOT_APPROVED)

    now = timezone.now()
    stored = UserActivitySummary.objects.for_team(team_id).filter(user_id=user_id).first()
    if not force and stored is not None and stored.next_eligible_at is not None and stored.next_eligible_at > now:
        return ActivitySummaryUpdate(status=UpdateStatus.SKIPPED_NOT_ELIGIBLE_YET)

    rebuild = is_stale(stored, rebuild_before)
    start = _input_start(stored.input_watermark if stored and not rebuild else None, now, limits.window_days)
    tasks = user_tasks(team_id, user_id, start, now)
    activity = user_activity(team_id, user_id, start, now)
    views = user_views(team_id, user_id, start, now)
    rendered = build_input(
        tasks,
        activity,
        as_of=now,
        seed=sampling_seed(now.date().isoformat(), team_id, user_id),
        views=views,
        limits=limits,
        parents=activity_parents(team_id, activity),
    )
    if rendered is None or rendered.units < min_units:
        if not dry_run:
            _back_off(team_id, user_id, stored, now + RETRY_BACKOFF)
        return ActivitySummaryUpdate(
            status=UpdateStatus.SKIPPED_TOO_FEW_UNITS,
            rendered_input=rendered.text if rendered else None,
            inputs_used={"drops": rendered.drops} if rendered else None,
        )

    inputs_used: dict[str, Any] = {
        "tasks": rendered.n_tasks,
        "activity_lines": rendered.n_activity_lines,
        "view_lines": rendered.n_view_lines,
        "input_chars": rendered.input_chars,
        "drops": rendered.drops,
        "limits": dataclasses.asdict(limits),
    }
    watermark = max([task.at for task in tasks] + [item.at for item in activity] + [view.at for view in views])
    previous = stored.summary if stored is not None and not rebuild else None
    model = DEFAULT_MODEL
    outcome = summarize(
        gateway_client(team_id, user_id, now.date()),
        rendered_input=rendered.text,
        previous_summary=previous,
        model=model,
        as_of=now.date(),
        max_completion_tokens=limits.max_completion_tokens,
        profile_max_chars=limits.profile_max_chars,
    )
    cost = cost_usd(outcome.tokens_in, outcome.tokens_out, MODEL_PRICES.get(model))
    result = ActivitySummaryUpdate(
        status=UpdateStatus.OK if outcome.summary is not None else UpdateStatus.FAILED,
        rendered_input=rendered.text,
        summary=outcome.summary,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        cost_usd=cost,
        latency_ms=outcome.latency_ms,
        error=outcome.error,
        inputs_used=inputs_used,
        input_watermark=watermark if outcome.summary is not None else None,
        rebuilt=rebuild,
    )
    if dry_run:
        return result

    try:
        accounting: dict[str, Any] = {
            "tokens_in": outcome.tokens_in,
            "tokens_out": outcome.tokens_out,
            "cost_usd": cost,
            "latency_ms": outcome.latency_ms,
            "inputs_used": inputs_used,
            "error": outcome.error,
        }
        if outcome.summary is None:
            UserActivitySummary.objects.for_team(team_id).update_or_create(
                team_id=team_id,
                user_id=user_id,
                defaults={
                    **accounting,
                    "status": UserActivitySummary.Status.FAILED,
                    "next_eligible_at": now + RETRY_BACKOFF,
                },
            )
            return result

        UserActivitySummary.objects.for_team(team_id).update_or_create(
            team_id=team_id,
            user_id=user_id,
            defaults={
                **accounting,
                "status": UserActivitySummary.Status.OK,
                "summary": outcome.summary,
                "summary_text": summary_text(outcome.summary),
                "generated_at": now,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "render_version": RENDER_VERSION,
                "input_watermark": watermark,
                "next_eligible_at": now + min_update_interval,
            },
        )
        return result
    except Exception as error:
        raise UpdateAfterModelCallError(cost) from error
