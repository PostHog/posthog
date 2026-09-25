"""Tag suggestions for insights, from the Jev decision model.

Jev does not write text. For each of the project's existing tags it gives a calibrated probability that
the tag applies, so a suggestion only ever offers tags the project already uses. Jev runs on PostHog's own
inference hosts behind the AI gateway, reached through the shared System One client with no TypeSafe
fallback, so the metadata stays inside PostHog.

User text (the name, the description, tag names) lives in the ``state`` document, and the questions
refer to it by path. It is never interpolated into instructions, so a person's text cannot steer a question.
"""

import json
from collections.abc import Mapping, Sequence

import structlog
import posthoganalytics
from pydantic import ValidationError

from posthog.schema import InsightVizNode

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import JsonValue, NoulAnswer, NoulQuestion, SystemOneResult
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, build_system_one_client, system_one_configured
from posthog.models import Team

from products.product_analytics.backend.presentation.insight_metadata import summarize_query_for_naming

logger = structlog.get_logger(__name__)

# Shared with FEATURE_FLAGS in frontend/src/lib/constants.tsx.
SUGGESTIONS_FLAG = "product-analytics-metadata-suggestions"
JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"

# A tag with a lower probability is more likely wrong than right for the person to have to remove.
TAG_THRESHOLD = 0.6
# Each tag is one yes/no question and the gateway takes GATEWAY_MAX_QUESTIONS questions per call,
# so this caps one click at three calls. The view offers the most used tags first.
MAX_TAGS = 3 * GATEWAY_MAX_QUESTIONS
# A tag name holds up to 255 characters, and a full chunk of long names would push the state past MAX_STATE_CHARS.
MAX_TAG_NAME_CHARS = 60
MAX_SUMMARY_LINE_CHARS = 200
# Each question is one row of the model's 8,192-token window, and the row repeats the state, so the
# state stays near 4,000 tokens to leave room for the instructions.
MAX_STATE_CHARS = 16_000


class InsightTooLargeForSuggestions(ValueError):
    """The insight's outline does not fit the model's window, so no call was made."""


@frozen
class InsightContext:
    """What Jev is told about the insight. Everything here is state, not instruction."""

    summary: str
    name: str = ""
    description: str = ""


@frozen
class TagSuggestion:
    tags: tuple[str, ...]
    scores: Mapping[str, float]


def suggestions_enabled(team: Team) -> bool:
    """Whether this team gets suggestions: the product flag must be on and a System One gateway must be
    configured. Fails closed on a flag-eval blip, because the flag is how the rollout stays small."""
    try:
        flag_on = bool(
            posthoganalytics.feature_enabled(
                SUGGESTIONS_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("metadata_suggestions.flag_check_failed", team_id=team.id, exc_info=True)
        return False
    return flag_on and system_one_configured()


def build_insight_context(team: Team, query_data: object, *, name: str, description: str) -> InsightContext:
    """Raises ``ValueError`` when ``query_data`` is not an insight query."""
    if not isinstance(query_data, Mapping):
        raise ValueError("Must be a JSON object")
    try:
        query = InsightVizNode.model_validate(query_data)
    except ValidationError as error:
        raise ValueError("Invalid query format") from error
    # Path start and end points can hold URLs or IDs a person typed, so they stay in PostHog.
    summary = summarize_query_for_naming(query, team, include_path_points=False)
    return InsightContext(summary=summary, name=name, description=description)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _state(context: InsightContext, tags: Mapping[str, str]) -> dict[str, JsonValue]:
    """The state document, so the instructions can point at ``subject`` or ``tags.t3``."""
    state: dict[str, JsonValue] = {
        "subject": {
            "name": context.name,
            "description": context.description,
            "summary": [_clip(line, MAX_SUMMARY_LINE_CHARS) for line in context.summary.splitlines()],
        },
        "tags": {key: _clip(value, MAX_TAG_NAME_CHARS) for key, value in tags.items()},
    }
    if len(json.dumps(state, ensure_ascii=False)) > MAX_STATE_CHARS:
        raise InsightTooLargeForSuggestions()
    return state


def _tag_question(key: str) -> NoulQuestion:
    return NoulQuestion(
        instructions=(
            f"`subject` describes a saved insight in a product analytics tool. `tags.{key}` is one of the tags "
            "the team already uses to organize its work. Does that tag apply to this insight?"
        ),
        criteria_true=(
            "The tag names a theme, product area, team, metric family, or status that the insight clearly "
            "belongs to, so a teammate filtering by that tag would expect to find it."
        ),
        criteria_false=(
            "The tag is about something else, is too specific to a different feature, or there is not "
            "enough in the insight to say it applies."
        ),
    )


def _ask_jev(team_id: int, state: JsonValue, questions: Mapping[str, NoulQuestion]) -> SystemOneResult:
    # No TypeSafe fallback: the state holds a customer's insight metadata, which must not leave PostHog.
    client = build_system_one_client(
        model=JEV_MODEL, ai_product="product_analytics", distinct_id=team_distinct_id(team_id)
    )
    return client.decide(state=state, questions=questions)


def suggest_tags(team_id: int, context: InsightContext, available_tags: Sequence[str]) -> TagSuggestion:
    """Asks one yes/no question per tag. ``available_tags`` comes most used first, so the cap drops the rarest."""
    tags = list(dict.fromkeys(available_tags))[:MAX_TAGS]
    scores: dict[str, float] = {}
    for start in range(0, len(tags), GATEWAY_MAX_QUESTIONS):
        chunk = {f"t{start + offset}": tag for offset, tag in enumerate(tags[start : start + GATEWAY_MAX_QUESTIONS])}
        result = _ask_jev(team_id, _state(context, chunk), {key: _tag_question(key) for key in chunk})
        for key, tag in chunk.items():
            answer = result.answers.get(key)
            if isinstance(answer, NoulAnswer):
                scores[tag] = answer.probability
    chosen = tuple(sorted((tag for tag, score in scores.items() if score >= TAG_THRESHOLD), key=lambda t: -scores[t]))
    return TagSuggestion(tags=chosen, scores=scores)
