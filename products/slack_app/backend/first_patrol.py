"""First-patrol digest: after CSM onboarding provisions the scout fleet and fires immediate
first runs, a delayed Temporal workflow checks the outcomes and DMs the user a digest — the
finding, or an explicit all-clear — so the first scout touch lands within the first hour
even when the data is healthy.

The Temporal workflow/activities live in ``posthog/temporal/ai/slack_app/``; this module
holds the plain functions they delegate to (dispatch, collection, copy, delivery) so the
behavior is unit-testable without a Temporal environment.
"""

from __future__ import annotations

import asyncio

import structlog

from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.persona_onboarding import PERSONA_CSM, PERSONA_SCOUT_CATALOG, inbox_url

logger = structlog.get_logger(__name__)

EVENT_DIGEST_SENT = "slack_persona_onboarding_first_patrol_digest_sent"

_TITLE_BY_SKILL = {spec.skill_name: spec.title for spec in PERSONA_SCOUT_CATALOG[PERSONA_CSM]}


def start_first_patrol_digest_workflow(
    *,
    team_id: int,
    integration_id: int,
    slack_user_id: str,
    dm_channel_id: str,
    thread_ts: str | None,
    channel_name: str,
    scout_config_ids: list[str],
    provisioned_at_iso: str,
) -> None:
    """Enqueue the delayed digest workflow. Raises on dispatch failure — the caller
    (persona onboarding) treats it as best-effort."""
    from django.conf import settings  # noqa: PLC0415 — keeps the temporal graph off the slack import path

    from temporalio.common import WorkflowIDReusePolicy  # noqa: PLC0415 — same

    from posthog.temporal.ai.slack_app.posthog_slack_first_patrol import (  # noqa: PLC0415 — same
        PostHogSlackFirstPatrolWorkflow,
    )
    from posthog.temporal.ai.slack_app.types import PostHogSlackFirstPatrolInputs  # noqa: PLC0415 — same
    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415 — same

    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            PostHogSlackFirstPatrolWorkflow.run,
            PostHogSlackFirstPatrolInputs(
                team_id=team_id,
                integration_id=integration_id,
                slack_user_id=slack_user_id,
                dm_channel_id=dm_channel_id,
                thread_ts=thread_ts,
                channel_name=channel_name,
                scout_config_ids=scout_config_ids,
                provisioned_at_iso=provisioned_at_iso,
            ),
            id=f"posthog-slack-first-patrol-{integration_id}-{slack_user_id}",
            task_queue=settings.TASKS_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )


def _first_sentence(summary: str, limit: int = 140) -> str:
    text = " ".join((summary or "").split())
    if not text:
        return ""
    sentence = text.split(". ")[0].rstrip(".")
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rstrip() + "…"
    return sentence + "."


def _clause(summary: str, max_words: int = 12) -> str:
    words = " ".join((summary or "").split()).rstrip(".").split()
    if not words:
        return "checked in clean"
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "…"


def collect_first_patrol_digest(
    *, team_id: int, channel_name: str, scout_config_ids: list[str], provisioned_at_iso: str
) -> dict | None:
    """Compose the digest from the first runs' outcomes. ``None`` when no run has completed
    yet — the workflow retries once, then gives up silently (never nag)."""
    from products.signals.backend.facade.api import (  # noqa: PLC0415 — keeps the signals stack off the slack import path
        collect_scout_run_digests,
    )

    digests = collect_scout_run_digests(
        team_id=team_id, scout_config_ids=scout_config_ids, since_iso=provisioned_at_iso
    )
    if digests is None:
        return None
    found = [digest for digest in digests if digest.notifications_sent or digest.reports_filed]
    if found:
        first = found[0]
        title = _TITLE_BY_SKILL.get(first.skill_name, first.skill_name)
        headline = _first_sentence(first.summary) or "it flagged an account that needs attention."
        text = (
            f"Your scouts just finished their first patrol — *{title}* found something: {headline} "
            f"Full details in #{channel_name} and your <{inbox_url(team_id)}|PostHog inbox>."
        )
        if len(found) > 1:
            extra = len(found) - 1
            text += f" ({extra} more scout{'s' if extra > 1 else ''} reported findings too.)"
        return {"text": text, "variant": "finding", "runs_completed": len(digests)}
    clauses = "; ".join(
        f"{_TITLE_BY_SKILL.get(digest.skill_name, digest.skill_name)}: {_clause(digest.summary)}" for digest in digests
    )
    text = (
        f"First patrol done ✅ — {clauses}. Nothing to worry about right now. "
        f"I'll keep watching daily and ping #{channel_name} the moment that changes."
    )
    return {"text": text, "variant": "all_clear", "runs_completed": len(digests)}


def post_first_patrol_digest(
    *, integration_id: int, slack_user_id: str, dm_channel_id: str, thread_ts: str | None, digest: dict
) -> None:
    integration = Integration.objects.filter(id=integration_id, kind="slack").first()
    if integration is None:
        logger.info("first_patrol_integration_gone", integration_id=integration_id)
        return
    SlackIntegration(integration).client.chat_postMessage(
        channel=dm_channel_id, thread_ts=thread_ts, text=digest["text"]
    )
    capture_slack_event(
        integration,
        EVENT_DIGEST_SENT,
        slack_user_id=slack_user_id,
        variant=digest.get("variant"),
        runs_completed=digest.get("runs_completed"),
    )
