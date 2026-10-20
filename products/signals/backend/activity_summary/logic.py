"""One activity summary update for one (team, user): gather, filter, render, summarize, persist."""

import datetime
from enum import StrEnum
from typing import Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.activity_summary.inputs import user_activity, user_tasks
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION, summary_text
from products.signals.backend.activity_summary.render import RENDER_VERSION, WINDOW_DAYS, build_input, sampling_seed
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
# The watermark is inclusive in the stored summary, so the next read starts just after it.
_WATERMARK_STEP = datetime.timedelta(microseconds=1)


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


def _input_start(watermark: datetime.datetime | None, now: datetime.datetime) -> datetime.datetime:
    earliest = now - datetime.timedelta(days=WINDOW_DAYS)
    return earliest if watermark is None else max(earliest, watermark + _WATERMARK_STEP)


def update_activity_summary(
    team_id: int, user_id: int, *, dry_run: bool = False, force: bool = False
) -> ActivitySummaryUpdate:
    """Update the stored activity summary of one user in one project.

    Reads only the inputs newer than the stored watermark, or the last `WINDOW_DAYS` on a first
    run. A failed update records the error and keeps the stored summary and the watermark. With
    `dry_run`, the model is still called but nothing is written. `force` ignores `next_eligible_at`.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    if team.organization.is_ai_data_processing_approved is not True:
        return ActivitySummaryUpdate(status=UpdateStatus.SKIPPED_AI_NOT_APPROVED)

    now = timezone.now()
    stored = UserActivitySummary.objects.for_team(team_id).filter(user_id=user_id).first()
    if not force and stored is not None and stored.next_eligible_at is not None and stored.next_eligible_at > now:
        return ActivitySummaryUpdate(status=UpdateStatus.SKIPPED_NOT_ELIGIBLE_YET)

    start = _input_start(stored.input_watermark if stored else None, now)
    tasks = user_tasks(team_id, user_id, start, now)
    activity = user_activity(team_id, user_id, start, now)
    rendered = build_input(tasks, activity, as_of=now, seed=sampling_seed(now.date().isoformat(), team_id, user_id))
    if rendered is None or rendered.units < MIN_UNITS:
        return ActivitySummaryUpdate(
            status=UpdateStatus.SKIPPED_TOO_FEW_UNITS,
            rendered_input=rendered.text if rendered else None,
            inputs_used={"drops": rendered.drops} if rendered else None,
        )

    inputs_used: dict[str, Any] = {
        "tasks": rendered.n_tasks,
        "activity_lines": rendered.n_activity_lines,
        "input_chars": rendered.input_chars,
        "drops": rendered.drops,
    }
    watermark = max([task.at for task in tasks] + [item.at for item in activity])
    previous = stored.summary if stored is not None else None
    model = DEFAULT_MODEL
    outcome = summarize(
        gateway_client(team_id, user_id, now.date()),
        rendered_input=rendered.text,
        previous_summary=previous,
        model=model,
        as_of=now.date(),
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
    )
    if dry_run:
        return result

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
            defaults={**accounting, "status": UserActivitySummary.Status.FAILED},
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
            "next_eligible_at": now + MIN_UPDATE_INTERVAL,
        },
    )
    return result
