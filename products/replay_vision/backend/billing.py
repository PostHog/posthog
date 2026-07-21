"""Bills replay vision credits from the immutable `ReplayObservationUsage` receipt ledger, the same source the in-product quota meter reads.

Credits use the same unit as ai_credits: 1 credit = $0.01. Each observation costs a
model-dependent number of credits, frozen onto its receipt at success time so later
price changes never reprice history.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from django.db.models import Case, IntegerField, Sum, Value, When
from django.db.models.functions import Coalesce

import structlog

from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ScannerModel

logger = structlog.get_logger(__name__)

CREDITS_PER_DOLLAR = 100  # 1 credit = $0.01, matching ai_credits

# Google's list prices, tracked from GEMINI_PRICING_URL (standard tier, prompts <= 200k tokens).
GEMINI_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"


GeminiTier = Literal["flash lite", "flash", "pro"]


@dataclass(frozen=True)
class GeminiModelInfo:
    tier: GeminiTier  # Google's model tier
    input_usd_per_1m: float  # Google list price per 1M input tokens
    output_usd_per_1m: float  # Google list price per 1M output tokens
    credits_per_observation: int  # what we charge (1 credit = $0.01)
    retired: bool = False  # no longer selectable; kept because frozen snapshots/receipts outlive the lineup


# Everything we know per Gemini model, current and retired, in one place. The current lineup
# (non-retired rows) offers one model per Google tier and must mirror `ScannerModel`.
#
# | model                        | tier       | $/1M in | $/1M out | credits/observation |
# |------------------------------|------------|---------|----------|---------------------|
# | gemini-3.5-flash-lite        | flash lite |    0.30 |     2.50 |                   2 |
# | gemini-3.6-flash             | flash      |    1.50 |     7.50 |                  15 |
# | gemini-3.1-pro-preview       | pro        |    2.00 |    12.00 |                  20 |
# | gemini-2.5-flash             | (retired)  |    0.30 |     2.50 |                   2 |
# | gemini-3-flash-preview       | (retired)  |    0.50 |     3.00 |                   5 |
# | gemini-3.5-flash             | (retired)  |    1.50 |     9.00 |                  15 |
# | gemini-3.1-flash-lite-preview| (retired)  |    0.25 |     1.50 |                   2 |
#
# Credit prices are hand-set to stay on the price points users already know from the previous
# lineup (2 for the budget tier, 15 for flash); pro scales flash by the input-price ratio
# (15 x $2.00/$1.50 = 20), since observations are video-input dominated.
# `suggested_observation_credits` is the derivation tool for repricing: it turns token prices +
# a target margin into a credit price, and lands on 15/20 for flash/pro at TARGET_MARGIN (the
# budget tier is pinned at its historical 2, a ~2.5x margin).
GEMINI_MODELS: dict[str, GeminiModelInfo] = {
    ScannerModel.GEMINI_3_5_FLASH_LITE: GeminiModelInfo(
        tier="flash lite", input_usd_per_1m=0.30, output_usd_per_1m=2.50, credits_per_observation=2
    ),
    ScannerModel.GEMINI_3_6_FLASH: GeminiModelInfo(
        tier="flash", input_usd_per_1m=1.50, output_usd_per_1m=7.50, credits_per_observation=15
    ),
    ScannerModel.GEMINI_3_1_PRO: GeminiModelInfo(
        tier="pro", input_usd_per_1m=2.00, output_usd_per_1m=12.00, credits_per_observation=20
    ),
    "gemini-2.5-flash": GeminiModelInfo(
        tier="flash", input_usd_per_1m=0.30, output_usd_per_1m=2.50, credits_per_observation=2, retired=True
    ),
    "gemini-3-flash-preview": GeminiModelInfo(
        tier="flash", input_usd_per_1m=0.50, output_usd_per_1m=3.00, credits_per_observation=5, retired=True
    ),
    "gemini-3.5-flash": GeminiModelInfo(
        tier="flash", input_usd_per_1m=1.50, output_usd_per_1m=9.00, credits_per_observation=15, retired=True
    ),
    "gemini-3.1-flash-lite-preview": GeminiModelInfo(
        tier="flash lite", input_usd_per_1m=0.25, output_usd_per_1m=1.50, credits_per_observation=2, retired=True
    ),
}

# Typical observation shape, measured from production LLM analytics: the rasterized session video
# dominates input (~25k tokens, sent to the provider once per observation at the standard input
# rate), and structured findings are small (~200 output tokens).
AVG_INPUT_TOKENS_PER_OBSERVATION = 25_000
AVG_OUTPUT_TOKENS_PER_OBSERVATION = 200

# Sale price = provider token cost x this multiplier. The headroom above 1x pays for everything the
# token prices don't: rasterizing the recording to video, provider-side video cache storage, retries,
# and PostHog margin.
TARGET_MARGIN = 3.75


def suggested_observation_credits(info: GeminiModelInfo, margin: float = TARGET_MARGIN) -> int:
    """Suggested credits per observation for a model, derived from its token prices and a target margin."""
    input_cost_usd = AVG_INPUT_TOKENS_PER_OBSERVATION * info.input_usd_per_1m / 1_000_000
    output_cost_usd = AVG_OUTPUT_TOKENS_PER_OBSERVATION * info.output_usd_per_1m / 1_000_000
    return max(1, math.ceil((input_cost_usd + output_cost_usd) * margin * CREDITS_PER_DOLLAR))


# Keyed on the raw model-id string (not the enum) because frozen `scanner_snapshot`s and
# receipts outlive enum members; retired ids keep pricing in-flight observations.
OBSERVATION_CREDITS_BY_MODEL: dict[str, int] = {
    model: info.credits_per_observation for model, info in GEMINI_MODELS.items()
}

# Unknown models bill at the highest known price: never underbill on a mapping gap.
_FALLBACK_CREDITS = max(OBSERVATION_CREDITS_BY_MODEL.values())


def observation_credits_for_model(model: str) -> int:
    credits = OBSERVATION_CREDITS_BY_MODEL.get(model)
    if credits is None:
        logger.warning("replay_vision.unknown_model_credits", model=model, fallback=_FALLBACK_CREDITS)
        return _FALLBACK_CREDITS
    return credits


def observation_credits_case() -> Case:
    """SQL mirror of `observation_credits_for_model`, for pricing observations inside a query."""
    return Case(
        *(
            When(scanner_snapshot__model=model, then=Value(credits))
            for model, credits in OBSERVATION_CREDITS_BY_MODEL.items()
        ),
        default=Value(_FALLBACK_CREDITS),
        output_field=IntegerField(),
    )


def get_replay_vision_credits_by_team(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    # Bucket by receipt write time so a late receipt is never dropped from an already-run daily report.
    rows = (
        ReplayObservationUsage.objects.filter(created_at__gte=begin, created_at__lt=end, team_id__isnull=False)
        .values("team_id")
        .annotate(total_credits=Coalesce(Sum("credits"), 0, output_field=IntegerField()))
        .values_list("team_id", "total_credits")
    )
    return cast(list[tuple[int, int]], list(rows))
