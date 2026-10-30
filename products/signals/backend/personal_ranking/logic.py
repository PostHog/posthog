"""Build one person's ranked inbox list with one LLM call, store it and record one event.

The call goes through `build_openai_client`, as the activity summary does. Any failure of the call or
of its answer gives the list in model order with a `fallback_reason`, so a build never raises because
of the model.
"""

import json
import time
import hashlib
import datetime
import dataclasses
from typing import Any, Literal

from django.utils import timezone

import structlog
from openai import APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, trace_id_from_seed
from posthog.models import Team, User
from posthog.ph_client import ph_scoped_capture

from products.signals.backend.activity_summary.read import ActivitySummaryStatus, get_summary
from products.signals.backend.models import PersonalInboxRanking
from products.signals.backend.personal_ranking.candidates import Candidate, gather_candidates
from products.signals.backend.personal_ranking.config import PersonalRankingConfig, read_config
from products.signals.backend.personal_ranking.prompt import (
    PROMPT_VERSION,
    RESPONSE_FORMAT,
    render_person,
    system_prompt,
    user_message,
)
from products.signals.backend.personal_ranking.validation import (
    FoldedEntry,
    MalformedRankingError,
    RankedEntry,
    ValidationCounts,
    cap,
    model_order,
    validate_ranking,
)

logger = structlog.get_logger(__name__)

AI_PRODUCT = "personal_inbox_ranking"
# Not a person: the gateway attributes every call to the pipeline.
PIPELINE_DISTINCT_ID = "signals_personal_inbox_ranking"
BUILT_EVENT = "personal inbox ranking built"
TRUNCATED_FINISH_REASON = "length"

FALLBACK_LLM_ERROR = "llm_error"
FALLBACK_TIMEOUT = "timeout"
FALLBACK_MALFORMED = "malformed_output"
FALLBACK_TRUNCATED = "truncated_output"
FALLBACK_NO_CANDIDATES = "no_candidates"
FALLBACK_AI_NOT_APPROVED = "ai_not_approved"

BuildStatus = Literal["ok", "fallback", "empty", "disabled"]

_MODEL_ORDER_REASON = "Kept in inbox order."
_NEEDS_YOU_REASONS = {
    "waiting_on_input": "Waiting on your input.",
    "claimed": "You claimed this report.",
    "suggested_reviewer": "You're a suggested reviewer.",
}


@frozen
class _ModelCall:
    content: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    fallback_reason: str | None


@frozen
class PersonalRankingBuild:
    status: BuildStatus
    personalized: bool
    fallback_reason: str | None
    entries: tuple[RankedEntry, ...]
    folded: tuple[FoldedEntry, ...]
    candidates: tuple[Candidate, ...]
    counts: ValidationCounts
    limit: int
    input_hash: str | None
    activity_summary_version: int | None
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    # None for a dry run or a disabled build, which store nothing.
    ranking_id: str | None = None

    def result_json(self) -> dict[str, Any]:
        """The stored `result`: every candidate by report id, with its rank, tier and reason."""
        by_ref = {candidate.ref: candidate for candidate in self.candidates}
        return {
            "limit": self.limit,
            "ranked": [
                {
                    "report_id": by_ref[entry.ref].report_id,
                    "rank": entry.rank,
                    "tier": entry.tier,
                    "reason": entry.reason,
                    "next_step": entry.next_step,
                    "matched": dataclasses.asdict(entry.matched) if entry.matched else None,
                    "ranked_by": entry.ranked_by,
                    "pools": list(by_ref[entry.ref].pools),
                }
                for entry in self.entries
            ],
            "folded": [
                {
                    "report_id": by_ref[fold.ref].report_id,
                    "into_report_id": by_ref[fold.into].report_id,
                    "reason": fold.reason,
                }
                for fold in self.folded
            ],
            "counts": dataclasses.asdict(self.counts),
        }


def model_order_reason(candidate: Candidate) -> str:
    return next((_NEEDS_YOU_REASONS[kind] for kind in candidate.needs_you), _MODEL_ORDER_REASON)


def normalize_focus(focus: str | None, max_chars: int) -> str | None:
    text = cap(focus, max_chars) if focus else ""
    return text or None


def input_hash(candidates: list[Candidate], *, activity_summary_version: int | None, focus: str | None) -> str:
    """Changes when a candidate, its text, status, priority, PR state, needs-you facts or score, the summary, the prompt or the focus changes."""
    rows = sorted(
        [
            candidate.report_id,
            # The prompt shows this text, so an edit makes the stored reasons out of date.
            candidate.title,
            candidate.summary_lead,
            candidate.status,
            candidate.priority,
            candidate.pull_request_state,
            list(candidate.needs_you),
            candidate.predictions.status if candidate.predictions else None,
            [[entry.outcome, round(entry.probability, 2)] for entry in candidate.predictions.predictions]
            if candidate.predictions
            else [],
        ]
        for candidate in candidates
    )
    payload = {
        "candidates": rows,
        "activity_summary_version": activity_summary_version,
        "prompt_version": PROMPT_VERSION,
        "focus": focus,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _client(team: Team, user: User, now: datetime.datetime, config: PersonalRankingConfig) -> OpenAI:
    client = build_openai_client(
        "signals",
        ai_product=AI_PRODUCT,
        trace_id=trace_id_from_seed(f"{AI_PRODUCT}:{team.id}:{user.id}:{now.isoformat()}"),
        properties={"team_id": str(team.id), "user_id": str(user.id), "prompt_version": str(PROMPT_VERSION)},
        distinct_id=PIPELINE_DISTINCT_ID,
    )
    # One attempt: a retry would run past the timeout, and the fallback list is always there.
    return client.with_options(timeout=config.timeout_seconds, max_retries=0)


def _call_model(
    team: Team,
    user: User,
    now: datetime.datetime,
    config: PersonalRankingConfig,
    messages: list[ChatCompletionMessageParam],
) -> _ModelCall:
    started = time.monotonic()

    def elapsed_ms() -> int:
        return round((time.monotonic() - started) * 1000)

    try:
        response = _client(team, user, now, config).chat.completions.create(
            model=config.model,
            messages=messages,
            user=PIPELINE_DISTINCT_ID,
            response_format=RESPONSE_FORMAT,
            max_completion_tokens=config.max_completion_tokens,
        )
    except APITimeoutError:
        return _ModelCall(
            content=None, tokens_in=None, tokens_out=None, latency_ms=elapsed_ms(), fallback_reason=FALLBACK_TIMEOUT
        )
    except Exception:
        logger.exception("signals.personal_ranking.llm_call_failed", team_id=team.id, user_id=user.id)
        return _ModelCall(
            content=None, tokens_in=None, tokens_out=None, latency_ms=elapsed_ms(), fallback_reason=FALLBACK_LLM_ERROR
        )
    usage = response.usage
    choice = response.choices[0] if response.choices else None
    truncated = choice is not None and choice.finish_reason == TRUNCATED_FINISH_REASON
    return _ModelCall(
        content=choice.message.content if choice is not None else None,
        tokens_in=usage.prompt_tokens if usage is not None else None,
        tokens_out=usage.completion_tokens if usage is not None else None,
        latency_ms=elapsed_ms(),
        fallback_reason=FALLBACK_TRUNCATED if truncated else None,
    )


def _capture(team: Team, user: User, build: PersonalRankingBuild, *, has_focus: bool) -> None:
    # Ids, counts and accounting only. Report text, reasons and the summary are user content.
    try:
        pools: dict[str, int] = {}
        for candidate in build.candidates:
            for pool in candidate.pools:
                pools[pool] = pools.get(pool, 0) + 1
        # The build runs in a Celery task, where the global client can drop events before it flushes.
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=user.distinct_id or PIPELINE_DISTINCT_ID,
                event=BUILT_EVENT,
                properties={
                    "team_id": team.id,
                    "user_id": user.id,
                    "ranking_id": build.ranking_id,
                    "status": build.status,
                    "personalized": build.personalized,
                    "fallback_reason": build.fallback_reason,
                    "model": build.model,
                    "prompt_version": PROMPT_VERSION,
                    "activity_summary_version": build.activity_summary_version,
                    "has_focus": has_focus,
                    "limit": build.limit,
                    "candidate_count": len(build.candidates),
                    "ranked_by_llm_count": sum(1 for entry in build.entries if entry.ranked_by == "llm"),
                    "folded_count": len(build.folded),
                    "pool_counts": pools,
                    **dataclasses.asdict(build.counts),
                    "tokens_in": build.tokens_in,
                    "tokens_out": build.tokens_out,
                    "latency_ms": build.latency_ms,
                },
                groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            )
    except Exception:
        logger.exception("signals.personal_ranking.capture_failed", team_id=team.id, user_id=user.id)


def _store(team: Team, user: User, build: PersonalRankingBuild) -> PersonalRankingBuild:
    status = PersonalInboxRanking.Status(build.status)
    row = PersonalInboxRanking.objects.for_team(team.id).create(
        team_id=team.id,
        user_id=user.id,
        input_hash=build.input_hash or "",
        candidate_ids=[candidate.report_id for candidate in build.candidates],
        result=build.result_json(),
        personalized=build.personalized,
        activity_summary_version=build.activity_summary_version,
        model=build.model,
        prompt_version=PROMPT_VERSION,
        tokens_in=build.tokens_in,
        tokens_out=build.tokens_out,
        latency_ms=build.latency_ms,
        status=status,
        fallback_reason=build.fallback_reason,
    )
    return dataclasses.replace(build, ranking_id=str(row.id))


def build_personal_ranking(
    team: Team,
    user: User,
    *,
    focus: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    config: PersonalRankingConfig | None = None,
) -> PersonalRankingBuild:
    """Rank the person's candidate reports. `dry_run` calls the model but stores no row and records no event."""
    config = config or read_config()
    limit = min(max(limit or config.default_limit, 1), config.max_limit)
    if not config.enabled:
        return PersonalRankingBuild(
            status="disabled",
            personalized=False,
            fallback_reason=None,
            entries=(),
            folded=(),
            candidates=(),
            counts=ValidationCounts(),
            limit=limit,
            input_hash=None,
            activity_summary_version=None,
            model=config.model,
        )

    now = timezone.now()
    focus = normalize_focus(focus, config.focus_max_chars)
    summary = get_summary(team, user.id)
    summary_ready = summary is not None and summary.status == ActivitySummaryStatus.READY
    summary_version = summary.version if summary is not None and summary_ready else None
    candidates = gather_candidates(team, user, config, now=now)
    refs = [candidate.ref for candidate in candidates]
    model_reasons = {candidate.ref: model_order_reason(candidate) for candidate in candidates}

    status: BuildStatus = "empty"
    fallback_reason: str | None = FALLBACK_NO_CANDIDATES
    validated = None
    call = None
    if candidates and team.organization.is_ai_data_processing_approved is not True:
        # Report text never goes to the model without the organization's approval, so the list stays in model order.
        status, fallback_reason = "fallback", FALLBACK_AI_NOT_APPROVED
    elif candidates:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt(config, limit)},
            {
                "role": "user",
                "content": user_message(render_person(summary, config), candidates, focus=focus, now=now, limit=limit),
            },
        ]
        call = _call_model(team, user, now, config, messages)
        fallback_reason = call.fallback_reason
        if fallback_reason is None:
            try:
                validated = validate_ranking(
                    call.content,
                    refs=refs,
                    model_reasons=model_reasons,
                    limit=limit,
                    reason_limits=config.reason_limits,
                    next_step_max_chars=config.next_step_max_chars,
                )
            except MalformedRankingError as error:
                logger.warning(
                    "signals.personal_ranking.malformed_output", team_id=team.id, user_id=user.id, error=str(error)
                )
                fallback_reason = FALLBACK_MALFORMED
        status = "ok" if validated is not None else "fallback"

    build = PersonalRankingBuild(
        status=status,
        personalized=validated is not None and summary_ready,
        fallback_reason=fallback_reason,
        entries=validated.entries if validated is not None else model_order(refs, model_reasons, limit),
        folded=validated.folded if validated is not None else (),
        candidates=tuple(candidates),
        counts=validated.counts if validated is not None else ValidationCounts(),
        limit=limit,
        input_hash=input_hash(candidates, activity_summary_version=summary_version, focus=focus),
        activity_summary_version=summary_version,
        model=config.model,
        tokens_in=call.tokens_in if call is not None else None,
        tokens_out=call.tokens_out if call is not None else None,
        latency_ms=call.latency_ms if call is not None else None,
    )
    if dry_run:
        return build
    build = _store(team, user, build)
    _capture(team, user, build, has_focus=focus is not None)
    return build
