"""Build one person's ranked inbox list with one LLM call, store it and record one event.

The call goes through `build_openai_client`, as the activity summary does. Any failure of the call or
of its answer gives the list in model order with a `fallback_reason`, so a build never raises because
of the model. A person with no ready activity summary gets the list in model order with no call, because
the model has nothing to personalize it with.
"""

import json
import time
import random
import hashlib
import datetime
import itertools
import dataclasses
from typing import Any, Literal

from django.utils import timezone

import structlog
from openai import APIError, APITimeoutError, BadRequestError, NotGiven, Omit, OpenAI, not_given, omit
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, trace_id_from_seed
from posthog.llm.openai_flex import is_flex_recoverable
from posthog.models import Team, User
from posthog.ph_client import ph_scoped_capture

from products.signals.backend.activity_summary.read import ActivitySummaryStatus, get_summary
from products.signals.backend.models import PersonalInboxRanking
from products.signals.backend.personal_ranking.candidates import Candidate, gather_candidates
from products.signals.backend.personal_ranking.config import (
    PersonalRankingConfig,
    ReasoningEffort,
    ServiceTier,
    config_for_user,
    list_limit,
    read_config,
)
from products.signals.backend.personal_ranking.inbox_activity import InboxActivityBlock, read_inbox_activity
from products.signals.backend.personal_ranking.precheck import fingerprint_matches, input_fingerprint, store_fingerprint
from products.signals.backend.personal_ranking.prompt import (
    PROMPT_VERSION,
    RESPONSE_FORMAT,
    TIERS,
    render_inbox_activity,
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

# (model, effort) pairs the API rejected in this process. Later calls with that pair leave the effort out.
_REJECTED_REASONING_EFFORTS: set[tuple[str, str]] = set()
# (model, tier) pairs the API rejected in this process. Later calls with that pair leave the tier out.
_REJECTED_SERVICE_TIERS: set[tuple[str, str]] = set()
# A refused flex call retries on the default tier only when this much of `timeout_seconds` is left.
# With less time left, the retry would most likely time out too, so the build uses the fallback list at once.
MIN_DEFAULT_TIER_RETRY_SECONDS = 15.0

AI_PRODUCT = "personal_inbox_ranking"
# Not a person: the gateway attributes every call to the pipeline.
PIPELINE_DISTINCT_ID = "signals_personal_inbox_ranking"
BUILT_EVENT = "personal inbox ranking built"
TRUNCATED_FINISH_REASON = "length"
# The most old rows one build deletes. Each build deletes again, so a larger backlog shrinks over later builds.
PRUNE_BATCH_SIZE = 100

FALLBACK_LLM_ERROR = "llm_error"
FALLBACK_TIMEOUT = "timeout"
FALLBACK_MALFORMED = "malformed_output"
FALLBACK_TRUNCATED = "truncated_output"
FALLBACK_NO_CANDIDATES = "no_candidates"
FALLBACK_AI_NOT_APPROVED = "ai_not_approved"
FALLBACK_NO_ACTIVITY_SUMMARY = "no_activity_summary"
# A later build with the same input hash can rank the list. AI approval is not part of the hash.
RETRYABLE_FALLBACK_REASONS = frozenset(
    {FALLBACK_LLM_ERROR, FALLBACK_TIMEOUT, FALLBACK_MALFORMED, FALLBACK_TRUNCATED, FALLBACK_AI_NOT_APPROVED}
)

# The input parts that `input_parts` hashes one by one. The report parts have one hash for each candidate.
REPORT_PARTS = ("text", "status", "priority", "pull_request_state", "needs_you", "scores")
INPUT_PARTS = (
    "candidate_set",
    *REPORT_PARTS,
    "activity_summary_version",
    "prompt_version",
    "config",
    "focus",
    "inbox_activity",
)
# The person had no list before this build.
CHANGED_NO_PREVIOUS = "no_previous_list"
# The previous list has no part hashes, so the build cannot tell which part changed.
CHANGED_UNKNOWN = "unknown"
_PART_HASH_CHARS = 16

BuildStatus = Literal["ok", "fallback", "empty", "disabled"]
# `hit` confirmed the list with no gather. `miss` ran the full check. `agreed` and `disagreed` are sampled hits that
# ran the full check too, and `disagreed` means the full check found a change that the pre-check did not.
PrecheckOutcome = Literal["hit", "miss", "agreed", "disagreed"]
PRECHECK_OUTCOMES: tuple[PrecheckOutcome, ...] = ("hit", "miss", "agreed", "disagreed")
# What started a build, on the build event and the trace, so cost can be split by it.
BuildTrigger = Literal["on_demand", "tick", "first_summary"]

_MODEL_ORDER_REASON = "Kept in inbox order."
_NEEDS_YOU_REASONS = {
    "waiting_on_input": "Waiting on your input.",
    "claimed": "You claimed this report.",
}


@frozen
class _ModelCall:
    content: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    fallback_reason: str | None
    # The tier that the response reports.
    served_service_tier: str | None = None
    service_tier_fallback: bool = False


@frozen
class _Completion:
    response: ChatCompletion
    # The flex call failed with an error that `is_flex_recoverable` accepts, so the default tier gave the answer.
    service_tier_fallback: bool


@frozen
class InputChanges:
    """How the inputs of a build differ from the inputs of the person's previous list."""

    # Names from `INPUT_PARTS`, or only `CHANGED_NO_PREVIOUS` or `CHANGED_UNKNOWN`.
    changed_parts: tuple[str, ...]
    # The reports in both lists with a changed report part. Null when the parts are not comparable.
    changed_report_count: int | None = None
    # The largest probability move of a report in both lists. Null when no probability is in both lists.
    max_score_move: float | None = None
    joined_count: int | None = None
    left_count: int | None = None
    # The reports that left and were in the first `rank_top` entries of the previous list.
    left_top_count: int | None = None

    def properties(self) -> dict[str, Any]:
        return {
            "changed_parts": list(self.changed_parts),
            "changed_report_count": self.changed_report_count,
            "max_score_move": self.max_score_move,
            "candidates_joined": self.joined_count,
            "candidates_left": self.left_count,
            "candidates_left_top": self.left_top_count,
        }


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
    model_called: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    # The tier that the config asked for, and the tier that the response reports. None when no call ran.
    service_tier: ServiceTier | None = None
    served_service_tier: str | None = None
    service_tier_fallback: bool = False
    # None for a dry run or a disabled build, which store nothing.
    ranking_id: str | None = None
    # The stored `input_parts`. None for a disabled build.
    input_parts: dict[str, Any] | None = None
    # None for a dry run or a disabled build.
    input_changes: InputChanges | None = None
    # None when the config leaves the block out.
    inbox_activity: InboxActivityBlock | None = None

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
    return next(
        (_NEEDS_YOU_REASONS[kind] for kind in candidate.needs_you if kind in _NEEDS_YOU_REASONS), _MODEL_ORDER_REASON
    )


def may_call_model(team: Team, *, summary_ready: bool) -> bool:
    """Whether a build with candidates calls the model, as `build_personal_ranking` decides it.

    Only such a build spends the shared daily limit.
    """
    return summary_ready and team.organization.is_ai_data_processing_approved is True


def normalize_focus(focus: str | None, max_chars: int) -> str | None:
    text = cap(focus, max_chars) if focus else ""
    return text or None


def _config_part(config: PersonalRankingConfig, limit: int) -> list[str]:
    # The rendered prompt holds every lever it names, such as `rank_top`, the tier caps and the reason limits.
    return [config.model, config.reasoning_effort, system_prompt(config, limit)]


def input_hash(
    candidates: list[Candidate],
    *,
    config: PersonalRankingConfig,
    limit: int,
    activity_summary_version: int | None,
    focus: str | None,
    inbox_activity: InboxActivityBlock | None,
) -> str:
    """Changes when a candidate, its text, status, priority, PR state, needs-you facts or score, the summary, the prompt, the config, the focus or the hashed inbox activity changes."""
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
        "config": _config_part(config, limit),
        "focus": focus,
        # Left out when the block is off, so the hash stays as it was before the block existed.
        **({"inbox_activity": inbox_activity.hash_part()} if inbox_activity is not None else {}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _part_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:_PART_HASH_CHARS]


def _report_parts(candidate: Candidate) -> dict[str, Any]:
    predictions = candidate.predictions
    return {
        "text": [candidate.title, candidate.summary_lead],
        "status": candidate.status,
        "priority": candidate.priority,
        "pull_request_state": candidate.pull_request_state,
        "needs_you": list(candidate.needs_you),
        "scores": [
            predictions.status if predictions else None,
            [[entry.outcome, round(entry.probability, 2)] for entry in predictions.predictions] if predictions else [],
        ],
    }


def input_parts(
    candidates: list[Candidate],
    *,
    config: PersonalRankingConfig,
    limit: int,
    activity_summary_version: int | None,
    focus: str | None,
    inbox_activity: InboxActivityBlock | None,
) -> dict[str, Any]:
    """The inputs of `input_hash` as one hash per part, so a later build can name the parts that changed.

    The report parts have one hash for each report. `scores` keeps the probabilities, so a later build can measure the move.
    """
    return {
        "parts": {
            "activity_summary_version": _part_hash(activity_summary_version),
            "prompt_version": _part_hash(PROMPT_VERSION),
            "config": _part_hash(_config_part(config, limit)),
            "focus": _part_hash(focus),
            **({"inbox_activity": _part_hash(inbox_activity.hash_part())} if inbox_activity is not None else {}),
        },
        "reports": {
            candidate.report_id: {part: _part_hash(value) for part, value in _report_parts(candidate).items()}
            for candidate in candidates
        },
        "scores": {
            candidate.report_id: {
                entry.outcome: round(entry.probability, 4) for entry in candidate.predictions.predictions
            }
            for candidate in candidates
            if candidate.predictions
        },
    }


def _max_score_move(previous: dict[str, dict[str, float]], current: dict[str, dict[str, float]]) -> float | None:
    moves = [
        abs(probability - previous[report_id][outcome])
        for report_id, scores in current.items()
        if report_id in previous
        for outcome, probability in scores.items()
        if outcome in previous[report_id]
    ]
    return round(max(moves), 4) if moves else None


def compare_inputs(previous: PersonalInboxRanking | None, current: dict[str, Any], *, rank_top: int) -> InputChanges:
    """The parts that differ between the previous list and the current inputs. Never raises."""
    if previous is None:
        return InputChanges(changed_parts=(CHANGED_NO_PREVIOUS,))
    stored = previous.input_parts
    try:
        if not stored:
            return InputChanges(changed_parts=(CHANGED_UNKNOWN,))
        stored_reports: dict[str, dict[str, str]] = stored["reports"]
        current_reports: dict[str, dict[str, str]] = current["reports"]
        joined = current_reports.keys() - stored_reports.keys()
        left = stored_reports.keys() - current_reports.keys()
        changed = {"candidate_set"} if joined or left else set()
        changed |= {part for part in current["parts"] if current["parts"][part] != stored["parts"].get(part)}
        changed_reports = 0
        for report_id in current_reports.keys() & stored_reports.keys():
            report_changed = {
                part
                for part in REPORT_PARTS
                if current_reports[report_id].get(part) != stored_reports[report_id].get(part)
            }
            changed |= report_changed
            changed_reports += bool(report_changed)
        top_ids = {entry["report_id"] for entry in previous.result.get("ranked", [])[:rank_top]}
        return InputChanges(
            changed_parts=tuple(part for part in INPUT_PARTS if part in changed),
            changed_report_count=changed_reports,
            max_score_move=_max_score_move(stored.get("scores", {}), current["scores"]),
            joined_count=len(joined),
            left_count=len(left),
            left_top_count=len(left & top_ids),
        )
    except (KeyError, TypeError, AttributeError):
        logger.warning("signals.personal_ranking.unreadable_input_parts", ranking_id=str(previous.id))
        return InputChanges(changed_parts=(CHANGED_UNKNOWN,))


def latest_row(team: Team, user: User) -> PersonalInboxRanking | None:
    return PersonalInboxRanking.objects.for_team(team.id).filter(user_id=user.id).order_by("-created_at", "-id").first()


def ready_summary_version(team: Team, user: User) -> int | None:
    summary = get_summary(team, user.id)
    return summary.version if summary is not None and summary.status == ActivitySummaryStatus.READY else None


def record_check(team: Team, row: PersonalInboxRanking, now: datetime.datetime) -> None:
    """Record that the list still matches the current inputs, so it counts as fresh again."""
    PersonalInboxRanking.objects.for_team(team.id).filter(id=row.id).update(checked_at=now)


@frozen
class InputCheck:
    unchanged: bool
    calls_model: bool
    # None when the pre-check is off.
    precheck: PrecheckOutcome | None = None


def _fingerprint(
    team: Team,
    user: User,
    config: PersonalRankingConfig,
    *,
    now: datetime.datetime,
    limit: int,
    summary_version: int | None,
) -> str | None:
    try:
        return input_fingerprint(team, user, config, now=now, limit=limit, summary_version=summary_version)
    except Exception:
        logger.exception("signals.personal_ranking.precheck_failed", team_id=team.id, user_id=user.id)
        return None


def check_inputs(
    team: Team,
    user: User,
    config: PersonalRankingConfig,
    *,
    now: datetime.datetime,
    limit: int | None = None,
    precheck: bool = False,
) -> InputCheck:
    """Compare the latest list with the current inputs. A list that still matches counts as fresh again.

    With `precheck` and the tick's `precheck_hours` above 0, a fingerprint that matches the one stored by the last
    full check of the latest list confirms the list with no gather. Any doubt runs the full check.
    """
    config = config_for_user(config, user.id)
    limit = list_limit(config, limit)
    latest = latest_row(team, user)
    summary_version = ready_summary_version(team, user)
    reusable = latest if latest is not None and latest.fallback_reason not in RETRYABLE_FALLBACK_REASONS else None
    precheck_hours = config.tick.precheck_hours if precheck else 0
    fingerprint = None
    sampled = False
    if precheck_hours > 0 and reusable is not None:
        fingerprint = _fingerprint(team, user, config, now=now, limit=limit, summary_version=summary_version)
        if fingerprint is not None and fingerprint_matches(team, user, reusable, fingerprint):
            if random.random() >= config.tick.precheck_sample_share:
                record_check(team, reusable, now)
                return InputCheck(unchanged=True, calls_model=False, precheck="hit")
            sampled = True
    candidates = gather_candidates(team, user, config, now=now, with_sources=False)
    current_hash = input_hash(
        candidates,
        config=config,
        limit=limit,
        activity_summary_version=summary_version,
        focus=None,
        inbox_activity=read_inbox_activity(team, user, config, now=now),
    )
    unchanged = reusable is not None and reusable.input_hash == current_hash
    outcome: PrecheckOutcome | None = None
    if sampled:
        outcome = "agreed" if unchanged else "disagreed"
    elif precheck_hours > 0:
        outcome = "miss"
    if outcome == "disagreed":
        logger.warning("signals.personal_ranking.precheck_disagreed", team_id=team.id, user_id=user.id)
    if reusable is not None and unchanged:
        record_check(team, reusable, now)
        if fingerprint is not None:
            store_fingerprint(team, user, reusable, fingerprint, precheck_hours)
        return InputCheck(unchanged=True, calls_model=False, precheck=outcome)
    return InputCheck(
        unchanged=False,
        calls_model=bool(candidates) and may_call_model(team, summary_ready=summary_version is not None),
        precheck=outcome,
    )


def requested_service_tier(config: PersonalRankingConfig, trigger: BuildTrigger) -> ServiceTier | None:
    return config.on_demand_service_tier if trigger == "on_demand" else config.service_tier


def _client(
    team: Team,
    user: User,
    now: datetime.datetime,
    config: PersonalRankingConfig,
    trigger: BuildTrigger,
    service_tier: ServiceTier | None,
) -> OpenAI:
    client = build_openai_client(
        "signals",
        ai_product=AI_PRODUCT,
        trace_id=trace_id_from_seed(f"{AI_PRODUCT}:{team.id}:{user.id}:{now.isoformat()}"),
        properties={
            "team_id": str(team.id),
            "user_id": str(user.id),
            "prompt_version": str(PROMPT_VERSION),
            "trigger": trigger,
            "model_arm": config.model_arm,
            **({"requested_service_tier": service_tier} if service_tier is not None else {}),
        },
        distinct_id=PIPELINE_DISTINCT_ID,
    )
    # One attempt: a retry would run past the timeout, and the fallback list is always there.
    return client.with_options(timeout=config.timeout_seconds, max_retries=0)


def _create_completion(
    client: OpenAI,
    config: PersonalRankingConfig,
    messages: list[ChatCompletionMessageParam],
    service_tier: ServiceTier | None,
) -> _Completion:
    started = time.monotonic()

    def create(
        reasoning_effort: ReasoningEffort | Omit, tier: ServiceTier | Omit, timeout: float | NotGiven
    ) -> ChatCompletion:
        return client.chat.completions.create(
            model=config.model,
            messages=messages,
            user=PIPELINE_DISTINCT_ID,
            response_format=RESPONSE_FORMAT,
            max_completion_tokens=config.max_completion_tokens,
            reasoning_effort=reasoning_effort,
            service_tier=tier,
            timeout=timeout,
        )

    reasoning_effort: ReasoningEffort | Omit = (
        omit if (config.model, config.reasoning_effort) in _REJECTED_REASONING_EFFORTS else config.reasoning_effort
    )
    tier: ServiceTier | Omit = (
        omit if service_tier is None or (config.model, service_tier) in _REJECTED_SERVICE_TIERS else service_tier
    )
    timeout: float | NotGiven = not_given
    fell_back = False
    # Each pass drops a parameter or leaves flex, so the loop makes at most three requests.
    while True:
        try:
            return _Completion(response=create(reasoning_effort, tier, timeout), service_tier_fallback=fell_back)
        except BadRequestError as error:
            # A rejected parameter fails fast, so the retry stays inside the timeout.
            if not isinstance(reasoning_effort, Omit) and "reasoning_effort" in str(error):
                _REJECTED_REASONING_EFFORTS.add((config.model, reasoning_effort))
                logger.warning(
                    "signals.personal_ranking.reasoning_effort_rejected",
                    model=config.model,
                    reasoning_effort=reasoning_effort,
                )
                reasoning_effort = omit
            elif not isinstance(tier, Omit) and "service_tier" in str(error):
                _REJECTED_SERVICE_TIERS.add((config.model, tier))
                logger.warning("signals.personal_ranking.service_tier_rejected", model=config.model, service_tier=tier)
                tier = omit
            else:
                raise
        except APIError as error:
            # A flex timeout used the whole timeout, so it stays a `timeout` fallback.
            remaining = config.timeout_seconds - (time.monotonic() - started)
            if (
                tier != "flex"
                or isinstance(error, APITimeoutError)
                or not is_flex_recoverable(error)
                or remaining < MIN_DEFAULT_TIER_RETRY_SECONDS
            ):
                raise
            logger.warning(
                "signals.personal_ranking.flex_fell_back",
                model=config.model,
                error_type=type(error).__name__,
                status_code=getattr(error, "status_code", None),
            )
            # The retry sends no tier, so it runs on the default tier of the project.
            tier, timeout, fell_back = omit, remaining, True


def _call_model(
    team: Team,
    user: User,
    now: datetime.datetime,
    config: PersonalRankingConfig,
    messages: list[ChatCompletionMessageParam],
    trigger: BuildTrigger,
) -> _ModelCall:
    started = time.monotonic()

    def elapsed_ms() -> int:
        return round((time.monotonic() - started) * 1000)

    service_tier = requested_service_tier(config, trigger)
    try:
        completion = _create_completion(
            _client(team, user, now, config, trigger, service_tier), config, messages, service_tier
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
    response = completion.response
    usage = response.usage
    choice = response.choices[0] if response.choices else None
    truncated = choice is not None and choice.finish_reason == TRUNCATED_FINISH_REASON
    return _ModelCall(
        content=choice.message.content if choice is not None else None,
        tokens_in=usage.prompt_tokens if usage is not None else None,
        tokens_out=usage.completion_tokens if usage is not None else None,
        latency_ms=elapsed_ms(),
        fallback_reason=FALLBACK_TRUNCATED if truncated else None,
        served_service_tier=response.service_tier,
        service_tier_fallback=completion.service_tier_fallback,
    )


def _capture(
    team: Team,
    user: User,
    build: PersonalRankingBuild,
    config: PersonalRankingConfig,
    *,
    has_focus: bool,
    trigger: BuildTrigger,
) -> None:
    # Ids, counts and accounting only. Report text, reasons and the summary are user content.
    try:
        pools: dict[str, int] = {}
        by_ref = {candidate.ref: candidate for candidate in build.candidates}
        for candidate in build.candidates:
            for pool in candidate.pools:
                pools[pool] = pools.get(pool, 0) + 1
        needs_you_refs = {
            candidate.ref
            for candidate in build.candidates
            if any(kind in _NEEDS_YOU_REASONS for kind in candidate.needs_you)
        }
        leading_needs_you = itertools.takewhile(lambda entry: entry.ref in needs_you_refs, build.entries)
        # The build runs in a Celery task, where the global client can drop events before it flushes.
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=user.distinct_id or PIPELINE_DISTINCT_ID,
                event=BUILT_EVENT,
                properties={
                    **({"$update_person_last_seen_at": False} if trigger != "on_demand" else {}),
                    "team_id": team.id,
                    "user_id": user.id,
                    "ranking_id": build.ranking_id,
                    "status": build.status,
                    "personalized": build.personalized,
                    "fallback_reason": build.fallback_reason,
                    "model_called": build.model_called,
                    "model": build.model,
                    "model_arm": config.model_arm,
                    "prompt_version": PROMPT_VERSION,
                    "activity_summary_version": build.activity_summary_version,
                    "has_focus": has_focus,
                    "trigger": trigger,
                    "limit": build.limit,
                    "rank_top": config.rank_top,
                    "reasoning_effort": config.reasoning_effort,
                    "service_tier": build.service_tier,
                    "served_service_tier": build.served_service_tier,
                    "service_tier_fallback": build.service_tier_fallback,
                    "candidate_count": len(build.candidates),
                    "ranked_by_llm_count": sum(1 for entry in build.entries if entry.ranked_by == "llm"),
                    "folded_count": len(build.folded),
                    # Needs you means waiting on their input or claimed by them. The leading count is the run of
                    # such reports at the top of the list, so a list that opens with them shows up here.
                    "needs_you_candidate_count": len(needs_you_refs),
                    "needs_you_leading_count": sum(1 for _ in leading_needs_you),
                    # The list as stored: the ranked reports by rank, then the folded reports. A later build
                    # prunes the row, so an offline comparison of rankings and outcomes reads the order here.
                    "report_ids": [
                        *(by_ref[entry.ref].report_id for entry in build.entries),
                        *(by_ref[fold.ref].report_id for fold in build.folded),
                    ],
                    "tier_counts": {tier: sum(1 for entry in build.entries if entry.tier == tier) for tier in TIERS},
                    "pool_counts": pools,
                    **dataclasses.asdict(build.counts),
                    "tokens_in": build.tokens_in,
                    "tokens_out": build.tokens_out,
                    "latency_ms": build.latency_ms,
                    **(build.input_changes.properties() if build.input_changes is not None else {}),
                    **(build.inbox_activity.properties() if build.inbox_activity is not None else {}),
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
        input_parts=build.input_parts,
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


def _prune(team: Team, user: User, keep: int) -> None:
    """Delete one batch of the person's rows older than the newest `keep`, so the table stays bounded."""
    rows = PersonalInboxRanking.objects.for_team(team.id).filter(user_id=user.id)
    stale_ids = list(rows.order_by("-created_at", "-id").values_list("id", flat=True)[keep : keep + PRUNE_BATCH_SIZE])
    if stale_ids:
        rows.filter(id__in=stale_ids).delete()


def build_personal_ranking(
    team: Team,
    user: User,
    *,
    focus: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    config: PersonalRankingConfig | None = None,
    trigger: BuildTrigger = "on_demand",
) -> PersonalRankingBuild:
    """Rank the person's candidate reports. `dry_run` calls the model but stores no row and records no event."""
    config = config_for_user(config or read_config(), user.id)
    limit = list_limit(config, limit)
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
    ready_summary = summary if summary is not None and summary.status == ActivitySummaryStatus.READY else None
    summary_version = ready_summary.version if ready_summary is not None else None
    candidates = gather_candidates(team, user, config, now=now)
    inbox_activity = read_inbox_activity(team, user, config, now=now, candidates=candidates)
    refs = [candidate.ref for candidate in candidates]
    model_reasons = {candidate.ref: model_order_reason(candidate) for candidate in candidates}

    status: BuildStatus = "empty"
    fallback_reason: str | None = FALLBACK_NO_CANDIDATES
    validated = None
    call = None
    if candidates and team.organization.is_ai_data_processing_approved is not True:
        # Report text never goes to the model without the organization's approval, so the list stays in model order.
        status, fallback_reason = "fallback", FALLBACK_AI_NOT_APPROVED
    elif candidates and ready_summary is None:
        # With no summary the model cannot personalize the list, so the build skips the paid call.
        status, fallback_reason = "fallback", FALLBACK_NO_ACTIVITY_SUMMARY
    elif candidates and ready_summary is not None:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt(config, limit)},
            {
                "role": "user",
                "content": user_message(
                    render_person(ready_summary, config),
                    candidates,
                    focus=focus,
                    now=now,
                    limit=limit,
                    rank_top=config.rank_top,
                    inbox_activity=render_inbox_activity(inbox_activity, now) if inbox_activity is not None else None,
                ),
            },
        ]
        call = _call_model(team, user, now, config, messages, trigger)
        fallback_reason = call.fallback_reason
        if fallback_reason is None:
            try:
                validated = validate_ranking(
                    call.content,
                    refs=refs,
                    model_reasons=model_reasons,
                    needs_you={candidate.ref: candidate.needs_you for candidate in candidates},
                    limit=limit,
                    rank_top=config.rank_top,
                    top_max=config.top_max,
                    worth_a_look_max=config.worth_a_look_max,
                    reason_limits=config.reason_limits,
                    next_step_max_chars=config.next_step_max_chars,
                )
            except MalformedRankingError as error:
                logger.warning(
                    "signals.personal_ranking.malformed_output", team_id=team.id, user_id=user.id, error=str(error)
                )
                fallback_reason = FALLBACK_MALFORMED
        status = "ok" if validated is not None else "fallback"

    parts = input_parts(
        candidates,
        config=config,
        limit=limit,
        activity_summary_version=summary_version,
        focus=focus,
        inbox_activity=inbox_activity,
    )
    build = PersonalRankingBuild(
        status=status,
        personalized=validated is not None,
        fallback_reason=fallback_reason,
        entries=validated.entries
        if validated is not None
        else model_order(refs, model_reasons, min(limit, config.worth_a_look_max)),
        folded=validated.folded if validated is not None else (),
        candidates=tuple(candidates),
        counts=validated.counts if validated is not None else ValidationCounts(),
        limit=limit,
        input_hash=input_hash(
            candidates,
            config=config,
            limit=limit,
            activity_summary_version=summary_version,
            focus=focus,
            inbox_activity=inbox_activity,
        ),
        input_parts=parts,
        inbox_activity=inbox_activity,
        activity_summary_version=summary_version,
        model=config.model,
        model_called=call is not None,
        tokens_in=call.tokens_in if call is not None else None,
        tokens_out=call.tokens_out if call is not None else None,
        latency_ms=call.latency_ms if call is not None else None,
        service_tier=requested_service_tier(config, trigger) if call is not None else None,
        served_service_tier=call.served_service_tier if call is not None else None,
        service_tier_fallback=call.service_tier_fallback if call is not None else False,
    )
    if dry_run:
        return build
    changes = compare_inputs(latest_row(team, user), parts, rank_top=config.rank_top)
    build = _store(team, user, dataclasses.replace(build, input_changes=changes))
    try:
        _prune(team, user, config.max_rows_per_person)
    except Exception:
        logger.exception("signals.personal_ranking.prune_failed", team_id=team.id, user_id=user.id)
    _capture(team, user, build, config, has_focus=focus is not None, trigger=trigger)
    return build
