"""Windowed observation selection and summary cost estimation.

Deliberately free of temporal/LLM imports: the API's run-preview endpoint imports this in the web
process, where pulling in the vision-actions engine (temporalio, LLM clients) would bloat every
request worker. The synthesis and alert activities import from here too, so the preview counts
exactly what a run would summarize.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.vision_action import VisionAction, VisionActionRun, VisionActionRunStatus
from products.replay_vision.backend.scanner_access import readable_scanner_ids

logger = structlog.get_logger(__name__)

# Sampling cap when no per-run or per-action override is set. Also the chunk size of the
# map-reduce path: one LLM pass stays reliable up to roughly this many observation lines.
MAX_OBSERVATIONS = 100
# The middle coverage tier offered in the UI.
DEEP_OBSERVATIONS = 500
# Hard ceiling on a per-run override. Bounds the map-reduce fan-out so one run stays within the
# synthesis activity timeout and a single click can't queue an unbounded LLM job.
MAX_RUN_OBSERVATIONS = 2_000


@frozen
class CoverageTier:
    key: str
    max_observations: int


# The coverage choices the run-preview endpoint estimates and the summarize modal offers.
COVERAGE_TIERS = (
    CoverageTier(key="standard", max_observations=MAX_OBSERVATIONS),
    CoverageTier(key="deep", max_observations=DEEP_OBSERVATIONS),
    CoverageTier(key="complete", max_observations=MAX_RUN_OBSERVATIONS),
)

# Pinned estimate rates for the synthesis model (USD per million tokens, gpt-4.1-mini list price).
# Used only for the pre-run estimate shown in the UI; actual billing meters real usage through the
# LLM gateway's $ai_billable events. Update alongside SYNTHESIS_MODEL in synthesis.py.
ESTIMATE_INPUT_USD_PER_MTOK = 0.40
ESTIMATE_OUTPUT_USD_PER_MTOK = 1.60
# One formatted observation line (descriptor + collapsed summary) averages this many tokens.
ESTIMATE_TOKENS_PER_OBSERVATION = 150
# System prompt + fencing overhead per LLM call, and the report each call writes back.
ESTIMATE_PROMPT_OVERHEAD_TOKENS = 1_500
ESTIMATE_OUTPUT_TOKENS_PER_CALL = 900


def apply_observation_predicate(
    queryset: "QuerySet[ReplayObservation]", selection: dict[str, Any]
) -> "QuerySet[ReplayObservation]":
    """Narrow an observation queryset to the action's targeting predicate ("run this on…").

    Filters on the persisted `scanner_result["model_output"]` JSON: monitor verdicts, classifier tags
    (fixed or freeform, any-of), and scorer score bounds. Empty or absent keys are ignored, so a
    default `selection` matches everything. Verdict/score filters implicitly exclude observations of
    other scanner types (the JSON key is absent there), which is what targeting means.
    """
    verdicts = selection.get("verdict") or []
    if isinstance(verdicts, str):  # tolerate a legacy single-string row
        verdicts = [verdicts]
    if verdicts:
        queryset = queryset.filter(scanner_result__model_output__verdict__in=verdicts)

    tags = selection.get("tags") or []
    if tags:
        # `__contains` on a JSONB array uses `@>`: matches when the stored array contains the element.
        tag_q = Q()
        for tag in tags:
            tag_q |= Q(scanner_result__model_output__tags__contains=[tag])
            tag_q |= Q(scanner_result__model_output__tags_freeform__contains=[tag])
        queryset = queryset.filter(tag_q)

    # jsonb comparison is numeric for JSON numbers, so these bounds work for int and float scores.
    # bool is rejected explicitly (it's an int subclass but a nonsensical bound).
    min_score = selection.get("min_score")
    if isinstance(min_score, int | float) and not isinstance(min_score, bool):
        queryset = queryset.filter(scanner_result__model_output__score__gte=min_score)
    max_score = selection.get("max_score")
    if isinstance(max_score, int | float) and not isinstance(max_score, bool):
        queryset = queryset.filter(scanner_result__model_output__score__lte=max_score)

    return queryset


def previous_cadence_run_at(
    team_id: int, vision_action_id: UUID, exclude_run_id: UUID | None = None
) -> datetime | None:
    """When the action's most recent completed cadence run fired, or None if it never has.

    Cadence runs anchor each window on the previous one; explicit-window period rollups
    (window_start set) are excluded so they never punch a hole in the tiled cadence windows.
    """
    runs = VisionActionRun.objects.for_team(team_id).filter(
        vision_action_id=vision_action_id,
        status=VisionActionRunStatus.COMPLETED,
        scheduled_at__isnull=False,
        window_start__isnull=True,
    )
    if exclude_run_id is not None:
        runs = runs.exclude(pk=exclude_run_id)
    return runs.order_by("-scheduled_at").values_list("scheduled_at", flat=True).first()


def default_window_start(team_id: int, vision_action_id: UUID, exclude_run_id: UUID | None = None) -> datetime:
    """The window start a run without an explicit window gets: the previous completed cadence run,
    else 24h back (the first run, or the first after a gap of failures)."""
    previous_run_at = previous_cadence_run_at(team_id, vision_action_id, exclude_run_id)
    return previous_run_at or (datetime.now(UTC) - timedelta(hours=24))


def window_observations(
    team: Team, action: VisionAction, *, window_start: datetime, window_end: datetime
) -> "QuerySet[ReplayObservation]":
    """The observations a run over [window_start, window_end) draws from — the pipeline both the
    synthesis activity and the run-preview endpoint use, so a preview counts exactly what a run
    would summarize.

    The bound scanner ids are user-supplied, so they're filtered through the action CREATOR's RBAC
    before any observation is read (mirroring `max_tools`); an action whose creator was deleted, or
    who can read none of the bound scanners, draws from nothing.
    """
    selection: dict[str, Any] = action.selection or {}
    requested_scanner_ids = selection.get("scanner_ids") or ([str(action.scanner_id)] if action.scanner_id else [])
    creator = action.created_by
    scanner_ids = readable_scanner_ids(creator, team, requested_scanner_ids) if creator is not None else []
    if len(scanner_ids) < len(requested_scanner_ids):
        # RBAC (or a malformed id) dropped some bound scanners. Log it so a silently shrinking summary
        # is diagnosable rather than reading like "no observations this period".
        logger.info(
            "vision_action.synthesis.scanners_filtered",
            vision_action_id=str(action.id),
            requested=len(requested_scanner_ids),
            readable=len(scanner_ids),
        )
    if not scanner_ids:
        return ReplayObservation.objects.none()
    observations = ReplayObservation.objects.filter(
        team_id=team.id,
        scanner_id__in=scanner_ids,
        status=ObservationStatus.SUCCEEDED,
        created_at__gte=window_start,
        created_at__lt=window_end,
    )
    return apply_observation_predicate(observations, selection)


def synthesis_llm_calls(observation_count: int) -> int:
    """How many LLM calls summarizing `observation_count` observations takes: one single pass up to
    the chunk size, else one digest call per chunk plus the final reduce pass."""
    if observation_count <= 0:
        return 0
    if observation_count <= MAX_OBSERVATIONS:
        return 1
    chunks = -(-observation_count // MAX_OBSERVATIONS)  # ceil division
    return chunks + 1


def estimate_summary_cost_usd(observation_count: int) -> float:
    """Pre-run estimate of the LLM cost of one summary, in USD. An estimate by construction: real
    token counts vary with observation verbosity, and billing meters actual usage."""
    if observation_count <= 0:
        return 0.0
    calls = synthesis_llm_calls(observation_count)
    input_tokens = observation_count * ESTIMATE_TOKENS_PER_OBSERVATION + calls * ESTIMATE_PROMPT_OVERHEAD_TOKENS
    if calls > 1:
        # The reduce pass re-reads every chunk digest (roughly one output's worth per chunk).
        input_tokens += (calls - 1) * ESTIMATE_OUTPUT_TOKENS_PER_CALL
    output_tokens = calls * ESTIMATE_OUTPUT_TOKENS_PER_CALL
    return (input_tokens * ESTIMATE_INPUT_USD_PER_MTOK + output_tokens * ESTIMATE_OUTPUT_USD_PER_MTOK) / 1_000_000


# Mirrors CREDITS_PER_DOLLAR in frontend/utils/credits.ts: 1 credit = $0.01, the display unit
# everywhere in this product.
CREDITS_PER_USD = 100


def estimate_summary_credits(observation_count: int) -> int:
    """`estimate_summary_cost_usd` in whole credits, floored at 1 so a nonzero cost never reads as free."""
    if observation_count <= 0:
        return 0
    return max(1, round(estimate_summary_cost_usd(observation_count) * CREDITS_PER_USD))
