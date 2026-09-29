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

from posthog.cloud_utils import is_hobby
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import JsonValue, NoulAnswer, NoulQuestion, SystemOneResult
from posthog.llm.system_one_client import (
    DEFAULT_TIMEOUT_SECONDS,
    GATEWAY_MAX_QUESTIONS,
    build_system_one_client,
    system_one_configured,
)
from posthog.models import Team

from products.product_analytics.backend.presentation.insight_metadata import summarize_query_for_naming

logger = structlog.get_logger(__name__)

# Shared with FEATURE_FLAGS in frontend/src/lib/constants.tsx.
SUGGESTIONS_FLAG = "product-analytics-metadata-suggestions"
JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"

# A tag with a lower probability is more likely wrong than right for the person to have to remove.
TAG_THRESHOLD = 0.6
# The gateway batches questions per call. MAX_TAGS is set to 3 times GATEWAY_MAX_QUESTIONS to limit
# one suggestion request to 3 gateway calls. The view offers the most used tags first, so increasing
# MAX_TAGS requires increasing the 3x multiplier. Note: if GATEWAY_MAX_QUESTIONS changes, update this.
MAX_TAGS = 3 * GATEWAY_MAX_QUESTIONS
# The gateway calls run one after another inside the request, so they share one timeout between them.
# Otherwise a slow gateway could hold a request worker for MAX_TAGS / GATEWAY_MAX_QUESTIONS timeouts.
SUGGESTION_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
# A tag name holds up to 255 characters, and a full chunk of long names would push the state past MAX_STATE_BYTES.
MAX_TAG_NAME_CHARS = 60
MAX_SUMMARY_LINE_CHARS = 200
JEV_WINDOW_TOKENS = 8_192
# Each question is one row of the model's window, and the row repeats the state. A token holds at least
# one UTF-8 byte, so a state of this many bytes can never overflow the window, whatever the script.
# The rest of the window holds the question text and the model's own prompt format.
MAX_STATE_BYTES = 7_000


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
    """Whether this team gets suggestions: the instance must not be self-hosted, the product flag must be on
    and a System One gateway must be configured. Fails closed on a flag-eval blip, because the flag is how
    the rollout stays small."""
    # Jev runs only on PostHog's own inference hosts, so a self-hosted install has nothing to call.
    if is_hobby():
        return False
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
    """Keeps a head and a tail rather than only a head, so two names that differ near the end
    (a shared prefix with a different suffix, e.g. a versioned or dated variant) don't clip identical."""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    head = (limit - 2) // 2
    tail = limit - 3 - head
    return f"{text[:head]}...{text[len(text) - tail :]}" if tail else f"{text[:head]}..."


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
    if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > MAX_STATE_BYTES:
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


def _ask_jev(team_id: int, state: JsonValue, questions: Mapping[str, NoulQuestion], timeout: float) -> SystemOneResult:
    # No TypeSafe fallback: the state holds a customer's insight metadata, which must not leave PostHog.
    client = build_system_one_client(
        model=JEV_MODEL, ai_product="product_analytics", distinct_id=team_distinct_id(team_id), timeout=timeout
    )
    return client.decide(state=state, questions=questions)


def suggest_tags(team_id: int, context: InsightContext, available_tags: Sequence[str]) -> TagSuggestion:
    """Asks one yes/no question per tag. ``available_tags`` comes most used first, so the cap drops the rarest."""
    # Tags that clip to the same text look identical to Jev, so only the most used of them is asked about.
    by_clipped_name: dict[str, str] = {}
    for tag in available_tags:
        by_clipped_name.setdefault(_clip(tag, MAX_TAG_NAME_CHARS), tag)
    tags = list(by_clipped_name.values())[:MAX_TAGS]
    batches = [tags[start : start + GATEWAY_MAX_QUESTIONS] for start in range(0, len(tags), GATEWAY_MAX_QUESTIONS)]
    timeout = SUGGESTION_TIMEOUT_SECONDS / max(len(batches), 1)
    scores: dict[str, float] = {}
    for batch in batches:
        chunk = {f"t{offset}": tag for offset, tag in enumerate(batch)}
        result = _ask_jev(team_id, _state(context, chunk), {key: _tag_question(key) for key in chunk}, timeout)
        for key, tag in chunk.items():
            answer = result.answers.get(key)
            if isinstance(answer, NoulAnswer):
                scores[tag] = answer.probability
    chosen = tuple(sorted((tag for tag, score in scores.items() if score >= TAG_THRESHOLD), key=lambda t: -scores[t]))
    return TagSuggestion(tags=chosen, scores=scores)
