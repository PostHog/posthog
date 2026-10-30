"""Asks the decision model which cause from a fixed list fits each moment on a chart."""

from django.db import models

import structlog
from pydantic import BaseModel

from posthog.dataclasses import frozen
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, JsonValue
from posthog.llm.system_one_client import build_system_one_client

logger = structlog.get_logger(__name__)

EXPLAIN_AI_PRODUCT = "insight_explain"
# The explanation already shows its facts while it waits, so a slow answer only delays the likely causes.
EXPLAIN_TIMEOUT_SECONDS = 10.0


class ChartCause(models.TextChoices):
    OUTSIDE_TRAFFIC = "outside_traffic", "Outside traffic"
    USAGE = "usage", "Usage"
    ONE_PERSON = "one_person", "One person"
    TRACKING = "tracking", "Tracking"
    WEEKLY_PATTERN = "weekly_pattern", "Weekly pattern"
    UNCLEAR = "unclear", "Unclear"


CAUSE_CRITERIA: dict[str, str] = {
    ChartCause.OUTSIDE_TRAFFIC: (
        "More or fewer people arrived from outside the product, for example from a launch, a post, an email, "
        "an ad or a search engine."
    ),
    ChartCause.USAGE: (
        "A real change in how people use the product, for example a new feature, a release, a changed flow, "
        "or people coming back more or less often."
    ),
    ChartCause.ONE_PERSON: "One person, a bot, a script or a test account caused most of the change.",
    ChartCause.TRACKING: (
        "A change in how the data is collected or processed, not in what people do: tracking added, removed or "
        "broken, an event renamed or sent twice, an SDK upgrade, ad blockers or consent, a changed filter or "
        "definition, or data arriving late."
    ),
    ChartCause.WEEKLY_PATTERN: "The usual weekly or seasonal rhythm, such as quieter weekends or holidays.",
    ChartCause.UNCLEAR: (
        "None of the other causes fits the facts, or the facts are not enough to tell. For example a feature "
        "flag, an experiment, an incident or a release that the facts do not mention."
    ),
}


class ExplainChapterFacts(BaseModel):
    id: str
    title: str
    summary: str
    evidence: list[str]


class ExplainFacts(BaseModel):
    series_label: str
    insight_name: str
    overview: str = ""
    chapters: list[ExplainChapterFacts]


@frozen
class ChapterCause:
    id: str
    cause: ChartCause
    confidence: float


def _chapter_key(index: int) -> str:
    return f"chapter_{index + 1}"


def _state(facts: ExplainFacts) -> JsonValue:
    return {
        "chart": {"series": facts.series_label, "insight": facts.insight_name, "overview": facts.overview},
        "chapters": {
            _chapter_key(index): {"title": chapter.title, "summary": chapter.summary, "evidence": chapter.evidence}
            for index, chapter in enumerate(facts.chapters)
        },
    }


def _question(key: str) -> ChoiceQuestion:
    # The chapter is named by its key in the state, so no text from the chart reaches the instructions.
    return ChoiceQuestion(
        instructions=(
            f"The state holds facts computed from a chart of product data. What most likely caused {key} in "
            "chapters? Read its title, its summary and its evidence, and the chart overview."
        ),
        criteria=CAUSE_CRITERIA,
    )


def explain_chart(facts: ExplainFacts, *, team_id: int) -> list[ChapterCause]:
    """The likely cause of each chapter that the model answered. Raises the System One errors."""
    if not facts.chapters:
        return []
    keys = [_chapter_key(index) for index in range(len(facts.chapters))]
    client = build_system_one_client(
        model=DEFAULT_DECISION_MODEL,
        ai_product=EXPLAIN_AI_PRODUCT,
        team_id=team_id,
        timeout=EXPLAIN_TIMEOUT_SECONDS,
    )
    result = client.decide(state=_state(facts), questions={key: _question(key) for key in keys})
    causes: list[ChapterCause] = []
    for key, chapter in zip(keys, facts.chapters):
        answer = result.answers.get(key)
        if not isinstance(answer, ChoiceAnswer) or answer.choice not in CAUSE_CRITERIA:
            logger.info("insight_explain_unanswered", team_id=team_id, chapter=key, reason=type(answer).__name__)
            continue
        causes.append(ChapterCause(id=chapter.id, cause=ChartCause(answer.choice), confidence=answer.confidence))
    return causes
