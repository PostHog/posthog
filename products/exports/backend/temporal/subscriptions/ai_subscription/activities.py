import time
import uuid
import asyncio
import hashlib
import datetime as dt
import dataclasses
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone as tz

import dateutil.parser
import posthoganalytics
import temporalio.activity
from asgiref.sync import sync_to_async
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.constants import SUBSCRIPTION_AI_PROMPT_FEATURE_FLAG_KEY
from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.models.subscription_context import SubscriptionContext
from products.exports.backend.temporal.subscriptions.ai_subscription.delivery import (
    build_ai_subscription_report,
    build_ai_teams_card,
    build_chart_image_urls,
    send_email_ai_subscription_credit_limited,
    send_email_ai_subscription_report,
    send_slack_ai_subscription_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import AiReportResult
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import PromptRejectedError
from products.exports.backend.temporal.subscriptions.delivery_common import (
    auto_disable_and_return,
    deliver_email,
    deliver_slack,
    strip_null_bytes,
)
from products.exports.backend.temporal.subscriptions.delivery_webhook import deliver_teams_webhook
from products.exports.backend.temporal.subscriptions.types import (
    AI_REPORT_CHARTS_KEY,
    AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_PROMPT_SNAPSHOT_KEY,
    AI_REPORT_RECOMMENDATION_INPUT_KEY,
    AI_REPORT_RECOMMENDATIONS_KEY,
    AI_REPORT_SNAPSHOT_KEY,
    AI_REPORT_WINDOW_END_KEY,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    GenerateAIReportInputs,
    GenerateAIReportResult,
    QueryErrorDetails,
    RecipientResult,
)
from products.subscriptions.backend.facade.api import read_recommendation_generation
from products.subscriptions.backend.facade.contracts import RecommendationContext, RecommendationGenerationInput
from products.subscriptions.backend.facade.proactive import (
    RecommendationAppendixDTO,
    claim_recommendation_run,
    finalize_recommendation_run,
    get_proactive_config,
    read_recommendation_appendix,
    recent_recommendation_memory,
    resolve_draft_repository_binding,
    start_or_reuse_recommendation_generation,
)

from ee.billing.quota_limiting import is_team_over_ai_credit_budget
from ee.tasks.subscriptions import _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import AI_CONSENT_REVOKED_DISABLE_REASON, AI_PROMPT_INVALID_DISABLE_REASON

LOGGER = get_logger(__name__)

# If the org's AI-credit balance isn't synced yet, reschedule roughly a billing cycle out so a
# skipped sub still moves forward instead of re-firing every tick.
_CREDIT_RESET_FALLBACK_DAYS = 31
_PULSE_CONTEXT_LIMIT = 20
_PULSE_POLL_INTERVAL_SECONDS = 10


async def _generate_recommendation_appendix(
    *,
    input: RecommendationGenerationInput,
    snapshot: dict[str, object],
    timeout_seconds: float,
    poll_interval_seconds: float = 10,
) -> RecommendationAppendixDTO:
    run = await database_sync_to_async(claim_recommendation_run, thread_sensitive=False)(
        team_id=input.team_id,
        subscription_id=input.subscription_id,
        delivery_id=input.delivery_id,
        actor_id=input.actor_id,
        snapshot=snapshot,
    )
    if run.status != "pending":
        persisted = await database_sync_to_async(read_recommendation_appendix, thread_sensitive=False)(
            team_id=input.team_id,
            delivery_id=input.delivery_id,
        )
        if persisted is None:
            raise RuntimeError("terminal recommendation run has no appendix")
        return persisted

    try:
        handle = await database_sync_to_async(start_or_reuse_recommendation_generation, thread_sensitive=False)(
            input=input,
            run_id=run.id,
        )
        deadline = time.monotonic() + max(timeout_seconds, 0)
        state = await database_sync_to_async(read_recommendation_generation, thread_sensitive=False)(input, handle)
        while state.status == "pending" and time.monotonic() < deadline:
            temporalio.activity.heartbeat()
            await asyncio.sleep(min(max(poll_interval_seconds, 0), max(deadline - time.monotonic(), 0)))
            state = await database_sync_to_async(read_recommendation_generation, thread_sensitive=False)(input, handle)

        if state.status != "completed" or state.result is None:
            failure_code = "timeout" if state.status == "pending" else state.failure_code
            return await database_sync_to_async(finalize_recommendation_run, thread_sensitive=False)(
                team_id=input.team_id,
                run_id=run.id,
                failure_code=failure_code or "generation_failed",
            )
        return await database_sync_to_async(finalize_recommendation_run, thread_sensitive=False)(
            team_id=input.team_id,
            run_id=run.id,
            result=state.result,
        )
    except Exception:
        return await database_sync_to_async(finalize_recommendation_run, thread_sensitive=False)(
            team_id=input.team_id,
            run_id=run.id,
            failure_code="pulse_failure",
        )


async def _load_snapshot(delivery_id: uuid.UUID) -> dict | None:
    # Single read of the delivery's content_snapshot (both the AI report markdown and the
    # diagnostics live here). DoesNotExist is tolerated: a missing row just means "no report yet".
    @database_sync_to_async(thread_sensitive=False)
    def _read() -> dict | None:
        try:
            snapshot = SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)
        except SubscriptionDelivery.DoesNotExist:
            return None
        return snapshot if isinstance(snapshot, dict) else None

    return await _read()


def _snapshot_report(snapshot: dict | None) -> str | None:
    report = snapshot.get(AI_REPORT_SNAPSHOT_KEY) if snapshot else None
    return report if isinstance(report, str) and report else None


@frozen
class DiagnosticCounts:
    failed_step_count: int
    total_step_count: int
    query_errors: list[QueryErrorDetails]

    @property
    def error_types(self) -> list[str]:
        return sorted({error["type"] for error in self.query_errors if error["type"]})


def _query_error_details(
    error_type: str | None, error_code: str | None, error_message: str | None
) -> QueryErrorDetails:
    return {
        "type": error_type,
        "code": error_code,
        "message": error_message,
    }


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _tally_diagnostics(steps: list[QueryErrorDetails | None]) -> DiagnosticCounts:
    # One typed object keeps every failed query's type, code, and safe message paired. None marks a
    # successful step. The same representation is built from persisted and in-memory diagnostics.
    query_errors = [step for step in steps if step is not None]
    return DiagnosticCounts(
        failed_step_count=len(query_errors),
        total_step_count=len(steps),
        query_errors=query_errors,
    )


def _snapshot_diagnostic_counts(snapshot: dict | None) -> DiagnosticCounts:
    # The prior run's failure shape, read back from the persisted diagnostics on Temporal redispatch.
    diagnostics = snapshot.get(AI_REPORT_DIAGNOSTICS_KEY) if snapshot else None
    if not isinstance(diagnostics, list):
        return DiagnosticCounts(failed_step_count=0, total_step_count=0, query_errors=[])
    # Only well-formed dict entries count — a malformed one would inflate the total and mask an
    # all-failed report; `ok is not False` keeps a missing/None ok out of the failed set.
    return _tally_diagnostics(
        [
            None
            if d.get("ok") is not False
            else _query_error_details(
                _string_or_none(d.get("error_type")),
                _string_or_none(d.get("error_code")),
                _string_or_none(d.get("human_readable_error")),
            )
            for d in diagnostics
            if isinstance(d, dict)
        ]
    )


def _report_diagnostic_counts(result: AiReportResult) -> DiagnosticCounts:
    return _tally_diagnostics(
        [
            None if d.ok else _query_error_details(d.error_type, d.error_code, d.human_readable_error)
            for d in result.diagnostics
        ]
    )


async def _persist_ai_report(delivery_id: uuid.UUID, result: AiReportResult, prompt: str | None) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def _write() -> None:
        # No DoesNotExist guard: create_delivery_record always writes this row before
        # generation runs, so a missing row is a wiring bug — let it raise loudly.
        delivery = SubscriptionDelivery.objects.get(pk=delivery_id)
        # LLM output and the user prompt can carry NUL bytes that Postgres text/jsonb reject;
        # scrub them here (payloads are small) as they are the untrusted inputs on this write path.
        delivery.content_snapshot = {
            **(delivery.content_snapshot or {}),
            AI_REPORT_SNAPSHOT_KEY: strip_null_bytes(result.markdown),
            AI_REPORT_DIAGNOSTICS_KEY: strip_null_bytes([dataclasses.asdict(d) for d in result.diagnostics]),
            AI_REPORT_WINDOW_END_KEY: result.window_end_utc,
            AI_REPORT_CHARTS_KEY: strip_null_bytes([dataclasses.asdict(chart) for chart in result.charts]),
            # prompt is None for non-AI subs; "" if cleared — omit either.
            **({AI_REPORT_PROMPT_SNAPSHOT_KEY: strip_null_bytes(prompt)} if prompt else {}),
        }
        delivery.save(update_fields=["content_snapshot", "last_updated_at"])

    await _write()


def _render_recommendations_appendix(appendix: RecommendationAppendixDTO) -> str:
    items = appendix.recommendations
    if not items:
        return ""
    citation_titles = {citation.id: citation.title for citation in appendix.citations}
    lines = ["## Recommendations"]
    for item in items[:3]:
        lines.extend(
            (
                f"### {item.title}",
                item.rationale,
                f"Why now: {item.why_now}",
                f"Confidence: {item.confidence}; effort: {item.effort}",
                f"Metric: {item.metric_name} ({item.metric_direction}, {item.expected_metric_movement})",
            )
        )
        sources = [citation_titles[citation_id] for citation_id in item.citation_ids if citation_id in citation_titles]
        if sources:
            lines.append(f"Sources: {', '.join(sources)}")
    return "\n\n".join(lines)


async def _append_recommendations(delivery_id: uuid.UUID, appendix: RecommendationAppendixDTO) -> None:
    rendered = _render_recommendations_appendix(appendix)
    if not rendered:
        return

    @database_sync_to_async(thread_sensitive=False)
    def _write() -> None:
        with transaction.atomic():
            delivery = SubscriptionDelivery.objects.select_for_update().get(pk=delivery_id)
            snapshot = delivery.content_snapshot if isinstance(delivery.content_snapshot, dict) else {}
            existing = snapshot.get(AI_REPORT_RECOMMENDATIONS_KEY)
            if existing == rendered:
                return
            report = snapshot.get(AI_REPORT_SNAPSHOT_KEY)
            if not isinstance(report, str) or not report:
                return
            if isinstance(existing, str):
                report = report.removesuffix(f"\n\n{existing}")
            delivery.content_snapshot = {
                **snapshot,
                AI_REPORT_SNAPSHOT_KEY: f"{report}\n\n{rendered}",
                AI_REPORT_RECOMMENDATIONS_KEY: rendered,
            }
            delivery.save(update_fields=["content_snapshot", "last_updated_at"])

    await _write()


@database_sync_to_async(thread_sensitive=False)
def _freeze_recommendation_input(delivery_id: uuid.UUID, candidate: dict[str, object]) -> dict[str, object]:
    with transaction.atomic():
        delivery = SubscriptionDelivery.objects.select_for_update().get(pk=delivery_id)
        snapshot = delivery.content_snapshot if isinstance(delivery.content_snapshot, dict) else {}
        existing = snapshot.get(AI_REPORT_RECOMMENDATION_INPUT_KEY)
        if isinstance(existing, dict):
            return existing
        delivery.content_snapshot = {**snapshot, AI_REPORT_RECOMMENDATION_INPUT_KEY: candidate}
        delivery.save(update_fields=["content_snapshot", "last_updated_at"])
        return candidate


@frozen
class _FrozenRecommendationInput:
    prompt: str
    contexts: tuple[RecommendationContext, ...]
    public_web_research: bool
    claim_snapshot: dict[str, object]


def _parse_frozen_recommendation_input(payload: object, base_report: str) -> _FrozenRecommendationInput | None:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None
    report_hash = payload.get("report_hash")
    prompt = payload.get("prompt")
    raw_contexts = payload.get("contexts")
    public_web_research = payload.get("public_web_research")
    if (
        report_hash != hashlib.sha256(base_report.encode()).hexdigest()
        or not isinstance(prompt, str)
        or not prompt
        or not isinstance(raw_contexts, list)
        or len(raw_contexts) > _PULSE_CONTEXT_LIMIT
        or not isinstance(public_web_research, bool)
    ):
        return None
    contexts: list[RecommendationContext] = []
    for raw_context in raw_contexts:
        if not isinstance(raw_context, dict):
            return None
        context_id = raw_context.get("id")
        content = raw_context.get("content")
        citable = raw_context.get("citable")
        if not isinstance(context_id, str) or not isinstance(content, str) or not isinstance(citable, bool):
            return None
        contexts.append(RecommendationContext(id=context_id, content=content, citable=citable))
    return _FrozenRecommendationInput(
        prompt=prompt,
        contexts=tuple(contexts),
        public_web_research=public_web_research,
        claim_snapshot={
            "version": 1,
            "report_hash": report_hash,
            "prompt": prompt,
            "contexts": raw_contexts,
            "public_web_research": public_web_research,
        },
    )


@database_sync_to_async(thread_sensitive=False)
def _actor_has_project_access(subscription: Subscription) -> bool:
    return bool(
        subscription.created_by
        and UserAccessControl(user=subscription.created_by, team=subscription.team).has_project_access
    )


@database_sync_to_async(thread_sensitive=False)
def _recommendation_contexts(subscription: Subscription) -> tuple[RecommendationContext, ...]:
    result: list[RecommendationContext] = []
    if subscription.created_by is None:
        return ()
    user_access_control = UserAccessControl(user=subscription.created_by, team=subscription.team)
    contexts = (
        SubscriptionContext.objects.for_team(subscription.team_id)
        .filter(subscription_id=subscription.id)
        .select_related("dashboard", "insight")[:3]
    )
    for context in contexts:
        if (
            context.dashboard_id
            and context.dashboard
            and not context.dashboard.deleted
            and user_access_control.check_access_level_for_object(context.dashboard, "viewer")
        ):
            result.append(
                RecommendationContext(
                    id=f"dashboard:{context.dashboard_id}",
                    content=(context.dashboard.name or "Untitled dashboard")[:300],
                )
            )
        elif (
            context.insight_id
            and context.insight
            and not context.insight.deleted
            and user_access_control.check_access_level_for_object(context.insight, "viewer")
        ):
            result.append(
                RecommendationContext(
                    id=f"insight:{context.insight_id}",
                    content=(context.insight.name or context.insight.derived_name or "Untitled insight")[:300],
                )
            )
    memory = recent_recommendation_memory(team_id=subscription.team_id, subscription_id=subscription.id)
    for item in memory[: _PULSE_CONTEXT_LIMIT - len(result)]:
        result.append(
            RecommendationContext(
                id=f"memory:{item.semantic_key}",
                content=f"Previously recommended at {item.created_at}: {item.title}. Do not repeat this exact idea.",
                citable=False,
            )
        )
    return tuple(result)


@temporalio.activity.defn
async def enrich_ai_subscription_report(inputs: GenerateAIReportInputs) -> None:
    """Best-effort Pulse adapter. Its failures never prevent the saved report from shipping."""
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "team", "team__organization").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)
    snapshot = await _load_snapshot(inputs.delivery_id)
    report = _snapshot_report(snapshot)
    prompt = snapshot.get(AI_REPORT_PROMPT_SNAPSHOT_KEY) if snapshot else None
    if (
        report is None
        or subscription.created_by is None
        or not subscription.created_by.is_active
        or not isinstance(prompt, str)
        or not prompt
    ):
        return
    actor_id = subscription.created_by.id
    actor_distinct_id = subscription.created_by.distinct_id
    if not actor_distinct_id:
        return
    if not settings.PULSE_PROACTIVE_ENABLED or not await _actor_has_project_access(subscription):
        return
    alpha_enabled = await sync_to_async(posthoganalytics.feature_enabled, thread_sensitive=False)(
        SUBSCRIPTION_AI_PROMPT_FEATURE_FLAG_KEY,
        actor_distinct_id,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if not alpha_enabled:
        return
    config = await database_sync_to_async(get_proactive_config, thread_sensitive=False)(
        team_id=subscription.team_id, subscription_id=subscription.id
    )
    if not config.enabled:
        return
    appendix = (snapshot or {}).get(AI_REPORT_RECOMMENDATIONS_KEY)
    base_report = report.removesuffix(f"\n\n{appendix}") if isinstance(appendix, str) else report
    existing = await database_sync_to_async(read_recommendation_appendix, thread_sensitive=False)(
        team_id=subscription.team_id, delivery_id=inputs.delivery_id
    )
    if existing is not None:
        await _append_recommendations(inputs.delivery_id, existing)
        return
    frozen_payload = (snapshot or {}).get(AI_REPORT_RECOMMENDATION_INPUT_KEY)
    if not isinstance(frozen_payload, dict):
        contexts = await _recommendation_contexts(subscription)
        frozen_payload = await _freeze_recommendation_input(
            inputs.delivery_id,
            {
                "version": 1,
                "report_hash": hashlib.sha256(base_report.encode()).hexdigest(),
                "prompt": prompt[:10_000],
                "contexts": [
                    {"id": context.id, "content": context.content, "citable": context.citable} for context in contexts
                ],
                "public_web_research": config.allow_public_web_research and settings.PULSE_PUBLIC_RESEARCH_ENABLED,
            },
        )
    frozen = _parse_frozen_recommendation_input(frozen_payload, base_report)
    if frozen is None:
        return
    current_public_web_research = config.allow_public_web_research and settings.PULSE_PUBLIC_RESEARCH_ENABLED
    if frozen.public_web_research and not current_public_web_research:
        return
    try:
        if await sync_to_async(is_team_over_ai_credit_budget, thread_sensitive=False)(subscription.team.api_token):
            return
    except Exception:
        return
    try:
        repository = await database_sync_to_async(resolve_draft_repository_binding, thread_sensitive=False)(
            team_id=subscription.team_id,
            actor_id=actor_id,
            config=config,
        )
    except Exception:
        repository = None
    generation_input = RecommendationGenerationInput(
        team_id=subscription.team_id,
        subscription_id=subscription.id,
        delivery_id=inputs.delivery_id,
        actor_id=actor_id,
        idempotency_key=f"pulse-recommendations:{inputs.delivery_id}",
        report_markdown=base_report[:100_000],
        prompt=frozen.prompt,
        contexts=frozen.contexts,
        public_web_research=frozen.public_web_research,
        create_draft_pr=config.create_draft_pr,
        repository_name=config.repository,
        repository_integration_id=config.repository_integration_id,
        repository=repository,
    )
    try:
        appendix = await _generate_recommendation_appendix(
            input=generation_input,
            snapshot=frozen.claim_snapshot,
            timeout_seconds=settings.PULSE_PROACTIVE_TIMEOUT_SECONDS,
            poll_interval_seconds=_PULSE_POLL_INTERVAL_SECONDS,
        )
        await _append_recommendations(inputs.delivery_id, appendix)
    except Exception:
        LOGGER.exception("proactive recommendation enrichment failed", delivery_id=str(inputs.delivery_id))


def _capture_ai_credit_event(
    subscription: Subscription, event: str, properties: dict[str, object] | None = None
) -> None:
    try:
        distinct_id = (
            subscription.created_by.distinct_id
            if subscription.created_by and subscription.created_by.distinct_id
            else f"team_{subscription.team_id}"
        )
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=distinct_id,
                event=event,
                properties={
                    "subscription_id": subscription.id,
                    "team_id": subscription.team_id,
                    "$process_person_profile": False,
                    **(properties or {}),
                },
                groups={"organization": str(subscription.team.organization_id)},
            )
    except Exception:
        LOGGER.warning(f"{event}.capture_failed", subscription_id=subscription.id, exc_info=True)


def _ai_credit_reset_date(subscription: Subscription) -> datetime:
    usage = subscription.team.organization.usage
    # usage["period"] is [current_period_start, current_period_end] as ISO strings (set in
    # billing_manager.py); index 1 — the period end — is when AI credits reset. isinstance guard:
    # a non-dict `usage` would raise AttributeError on .get, which the parse except below misses.
    period = usage.get("period") if isinstance(usage, dict) else None
    if period and len(period) == 2 and period[1]:
        try:
            reset_date = dateutil.parser.isoparse(period[1])
            # A rolled-over-but-not-yet-synced period leaves period[1] in the past, which would
            # resume "on a past date" and re-fire every tick — fall through to the fallback instead.
            if reset_date > tz.now():
                return reset_date
        except (ValueError, TypeError):
            pass
    return tz.now() + dt.timedelta(days=_CREDIT_RESET_FALLBACK_DAYS)


def _skip_ai_delivery_over_credit_limit_sync(subscription: Subscription) -> datetime:
    """Reschedule the over-limit subscription past the credit reset and notify the owner once.
    Runs entirely sync (DB + email) — call via `database_sync_to_async`.

    Persists `next_delivery_date = reset_date` so the always-runs `advance_next_delivery_date`
    activity recomputes from it (`rrule.after(reset_date)`) — otherwise the next slot could fall
    before the reset and re-fire while still over-limit.
    """
    reset_date = _ai_credit_reset_date(subscription)
    subscription.next_delivery_date = reset_date
    subscription.save(update_fields=["next_delivery_date"])

    creator = subscription.created_by
    # Skip the notice if the creator has left the org: they can no longer act on the credit limit,
    # and emailing them their former org's billing status leaks it outside the org. The org still
    # learns it's over budget through the normal billing/quota path.
    creator_is_org_member = (
        creator is not None
        and OrganizationMembership.objects.filter(
            organization_id=subscription.team.organization_id, user=creator
        ).exists()
    )
    if creator and creator.email and creator_is_org_member:
        send_email_ai_subscription_credit_limited(
            email=creator.email,
            subscription=subscription,
            resume_date=reset_date,
            # Stable within a billing period (reset_date is the period end), so MessagingRecord
            # dedups to one notice per credit-reset cycle.
            billing_period_key=reset_date.date().isoformat(),
        )
    _capture_ai_credit_event(
        subscription, "ai_subscription_skipped_over_credit_budget", {"resumes_at": reset_date.isoformat()}
    )
    return reset_date


@temporalio.activity.defn
async def generate_ai_subscription_report(inputs: GenerateAIReportInputs) -> GenerateAIReportResult:
    # The "decide what to send" phase, split from delivery so the LLM runs once up front with
    # its own retry policy. Terminal failures (consent revoked, prompt invalid) auto-disable and
    # return aborted=True; transient errors bubble up for the activity's Temporal retry.
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "team", "team__organization").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    # Idempotency on Temporal redispatch: if a prior attempt already produced the report,
    # don't re-bill the LLM — the point of the generate -> deliver split is one LLM run.
    # One snapshot read serves both the "already generated?" check and the prior failure shape.
    snapshot = await _load_snapshot(inputs.delivery_id)
    if _snapshot_report(snapshot) is not None:
        await LOGGER.ainfo("generate_ai_subscription_report.already_generated", subscription_id=subscription.id)
        counts = _snapshot_diagnostic_counts(snapshot)
        return GenerateAIReportResult(
            aborted=False,
            failed_step_count=counts.failed_step_count,
            total_step_count=counts.total_step_count,
            query_errors=counts.query_errors,
            target_type=subscription.target_type,
        )

    # Consent is gated once here, before any LLM cost — creation-time gates don't catch an
    # org that revokes AI-data-processing approval later. Auto-disable so it stops re-firing.
    if not subscription.team.organization.is_ai_data_processing_approved:
        LOGGER.warning("generate_ai_subscription_report.consent_revoked", subscription_id=subscription.id)
        aborted = await auto_disable_and_return(
            subscription,
            AI_CONSENT_REVOKED_DISABLE_REASON,
            [],
        )
        return GenerateAIReportResult(
            aborted=True, recipient_results=aborted.recipient_results, target_type=subscription.target_type
        )

    # Gate on AI credits before any LLM cost — but only past the idempotency check above, so an
    # already-generated report (its tokens already spent) still ships. The interactive Max path
    # enforces this same limit in ee/api/conversation.py; scheduled reports need their own check
    # or they'd keep spending against an exhausted balance. Fail open: a transient quota-lookup
    # error shouldn't drop a deliverable report. The check reads Redis (not the DB), so
    # sync_to_async — but the reschedule below writes the row, so that stays database_sync_to_async.
    try:
        over_credit_budget = await sync_to_async(is_team_over_ai_credit_budget, thread_sensitive=False)(
            subscription.team.api_token
        )
    except Exception as exc:
        over_credit_budget = False
        LOGGER.warning(
            "generate_ai_subscription_report.ai_credit_budget_check_failed",
            subscription_id=subscription.id,
            error=str(exc),
            exc_info=True,
        )
        # Fail-open is invisible to alerting otherwise — the report ships while billing against a
        # possibly-exhausted balance, the exact failure mode this gate exists to prevent.
        await sync_to_async(_capture_ai_credit_event, thread_sensitive=False)(
            subscription, "ai_subscription_credit_check_failed", {"error": str(exc)}
        )
    if over_credit_budget:
        reset_date = await database_sync_to_async(_skip_ai_delivery_over_credit_limit_sync, thread_sensitive=False)(
            subscription
        )
        LOGGER.warning(
            "generate_ai_subscription_report.ai_skipped_over_credit_limit",
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            resumes_at=reset_date.isoformat(),
        )
        # skipped=True → the workflow records SKIPPED (not FAILED — the sub isn't broken) and skips
        # delivery; the sub stays enabled and advance_next_delivery_date recomputes from the reset.
        return GenerateAIReportResult(skipped=True, target_type=subscription.target_type)

    try:
        report_result = await build_ai_subscription_report(subscription)
    except PromptRejectedError as exc:
        # Structurally permanent: no creator, prompt now fails sanitization, or the
        # planner returned a malformed plan. Re-firing wastes LLM tokens every cycle.
        LOGGER.warning(
            "generate_ai_subscription_report.prompt_rejected",
            subscription_id=subscription.id,
            reason=str(exc),
        )
        _capture_delivery_failed_event(subscription, exc)
        # Seed a recipient result with the exception detail first — it carries planner
        # context that the disable reason (appended next by `auto_disable_and_return`)
        # doesn't.
        # PromptRejectedError messages are handcrafted rejections (empty/too long/no creator), safe to show.
        recipient_results = [
            RecipientResult(
                recipient=subscription.recipient_label,
                status="failed",
                error={"message": str(exc), "type": "PromptRejectedError"},
                human_readable_error=str(exc),
            )
        ]
        aborted = await auto_disable_and_return(
            subscription,
            AI_PROMPT_INVALID_DISABLE_REASON,
            recipient_results,
        )
        return GenerateAIReportResult(
            aborted=True, recipient_results=aborted.recipient_results, target_type=subscription.target_type
        )

    await _persist_ai_report(inputs.delivery_id, report_result, subscription.prompt)
    counts = _report_diagnostic_counts(report_result)
    return GenerateAIReportResult(
        aborted=False,
        failed_step_count=counts.failed_step_count,
        total_step_count=counts.total_step_count,
        query_errors=counts.query_errors,
        target_type=subscription.target_type,
    )


async def _deliver_ai_subscription(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    # Ships the report generate_ai_subscription_report already produced (read back from the
    # delivery row) — no LLM work here. Transient send errors retry; terminal Slack errors auto-disable.
    if inputs.delivery_id is None:
        # The AI workflow always creates the delivery row and runs generation before
        # delivery, so a missing reference is a wiring bug, not a runtime state.
        raise ApplicationError(f"AI delivery for subscription {subscription.id} has no delivery_id", non_retryable=True)

    delivery_id = inputs.delivery_id
    snapshot = await _load_snapshot(delivery_id)
    markdown = _snapshot_report(snapshot)
    if markdown is None:
        # Generation persists the report before delivery is scheduled, so a missing report
        # means the row was lost. Non-retryable: re-running *delivery* can't regenerate the
        # report, so retrying just burns attempts — fail loud rather than ship an empty report.
        raise ApplicationError(
            f"AI report missing for subscription {subscription.id} (delivery {inputs.delivery_id})",
            non_retryable=True,
        )

    chart_images = await database_sync_to_async(build_chart_image_urls, thread_sensitive=False)(
        (snapshot or {}).get(AI_REPORT_CHARTS_KEY) or [], team_id=subscription.team_id
    )

    if subscription.target_type == Subscription.SubscriptionTarget.EMAIL:
        # Dedup key for MessagingRecord: stable across this run's retries, unique per run so a re-test re-sends.
        workflow_run_id = temporalio.activity.info().workflow_run_id
        if workflow_run_id is None:
            raise ApplicationError("AI email delivery requires a workflow run id", non_retryable=True)

        async def _send_email(email: str) -> None:
            await database_sync_to_async(send_email_ai_subscription_report, thread_sensitive=False)(
                email=email,
                subscription=subscription,
                markdown=markdown,
                delivery_run_id=workflow_run_id,
                delivery_id=delivery_id,
                charts=chart_images,
            )

        return await deliver_email(subscription, inputs, recipient_results, _send_email)
    if subscription.target_type == Subscription.SubscriptionTarget.SLACK:
        return await deliver_slack(
            subscription,
            recipient_results,
            lambda integration: send_slack_ai_subscription_report(
                subscription=subscription,
                markdown=markdown,
                integration=integration,
                delivery_id=delivery_id,
                charts=chart_images,
            ),
        )
    if subscription.target_type == Subscription.SubscriptionTarget.TEAMS:
        card = build_ai_teams_card(subscription, markdown, delivery_id=delivery_id)
        return await deliver_teams_webhook(subscription, recipient_results, body=card)
    # `validate_subscription_for_delivery` auto-disables unsupported targets up front,
    # so reaching here means an invariant was violated.
    raise ApplicationError(
        f"AI delivery reached an unsupported target {subscription.target_type!r}", non_retryable=True
    )
