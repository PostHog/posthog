import re
import math
from collections.abc import Callable

from products.workflows.backend.facade.contracts import LifecycleStage

# For a team with no workflows yet, welcome and onboarding flows convert best, but their events fire far less
# often than product usage events. These weights let a quiet sign-up event outrank a busy usage event. Volume
# counts within a stage only when events are picked for the prompt.
STAGE_WEIGHTS: dict[LifecycleStage, float] = {
    "signup": 5.0,
    "onboarding": 4.0,
    "trial": 3.0,
    "purchase": 3.0,
    "churn_risk": 2.5,
    "failure": 1.5,
    "support": 1.5,
    "other": 1.0,
}

MIN_WEEKLY_COUNT = 3
# A busy project can have hundreds of names that match one pattern, like `error`. The cap stops one pattern from
# taking every place in the list Jev classifies.
MAX_GUESSED_PER_STAGE = 15

# Only pick which events Jev gets to classify, so lifecycle-looking names are not cut by the limit. Checked in
# order. Deletion counts only for accounts and their owners, because most `*_deleted` events are routine product
# actions, not churn.
_STAGE_REGEXES: tuple[tuple[LifecycleStage, str], ...] = (
    ("signup", r"sign.?up|signed.?up|regist|(account|user|workspace|organi[sz]ation|team).?created"),
    ("onboarding", r"onboard|activat|welcome|invite"),
    ("trial", r"trial"),
    ("churn_risk", r"cancel|churn|downgrad|unsubscri|paus|(account|user|workspace|organi[sz]ation).?delet"),
    ("failure", r"fail|error"),
    ("purchase", r"subscri|upgrad|purchas|order|checkout|payment|paid|plan"),
    ("support", r"ticket|survey|feedback"),
)
_STAGE_PATTERNS: tuple[tuple[LifecycleStage, re.Pattern[str]], ...] = tuple(
    (stage, re.compile(pattern, re.IGNORECASE)) for stage, pattern in _STAGE_REGEXES
)


def guess_stage(event_name: str) -> LifecycleStage:
    for stage, pattern in _STAGE_PATTERNS:
        if pattern.search(event_name):
            return stage
    return "other"


def select_prompt_events(
    weekly_counts: dict[str, int],
    *,
    limit: int,
    stages: dict[str, LifecycleStage] | None = None,
    weights: dict[LifecycleStage, float] = STAGE_WEIGHTS,
) -> list[tuple[str, int]]:
    """The events the model gets to choose from. With stages from Jev they are ranked like the suggestions,
    without them lifecycle-looking names go first. Picking by volume alone would cut a quiet sign-up event."""
    eligible = sorted(
        ((name, count) for name, count in weekly_counts.items() if count >= MIN_WEEKLY_COUNT),
        key=lambda item: item[1],
        reverse=True,
    )
    if stages:
        return sorted(
            eligible, key=lambda item: suggestion_score(stages.get(item[0], "other"), item[1], weights), reverse=True
        )[:limit]
    lifecycle: list[tuple[str, int]] = []
    others: list[tuple[str, int]] = []
    overflow: list[tuple[str, int]] = []
    guessed_per_stage: dict[LifecycleStage, int] = {}
    for item in eligible:
        stage = guess_stage(item[0])
        if stage == "other":
            others.append(item)
        elif guessed_per_stage.get(stage, 0) < MAX_GUESSED_PER_STAGE:
            guessed_per_stage[stage] = guessed_per_stage.get(stage, 0) + 1
            lifecycle.append(item)
        else:
            overflow.append(item)
    return (lifecycle + others + overflow)[:limit]


def suggestion_score(
    stage: LifecycleStage, weekly_count: int, weights: dict[LifecycleStage, float] = STAGE_WEIGHTS
) -> float:
    return weights[stage] * math.log10(weekly_count + 1)


def pick_one_per_stage[T](items: list[T], *, stage_of: Callable[[T], LifecycleStage], limit: int) -> list[T]:
    """The best item of each stage, in the order given, so two cards never cover the same moment."""
    picked: list[T] = []
    seen: set[LifecycleStage] = set()
    for item in items:
        stage = stage_of(item)
        if stage not in seen:
            seen.add(stage)
            picked.append(item)
        if len(picked) == limit:
            break
    return picked
