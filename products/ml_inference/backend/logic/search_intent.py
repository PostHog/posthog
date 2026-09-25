"""
Classify a filter picker search: which tab (taxonomic group) does the person look for?

Value-shaped input (an email address, a URL, a path) is matched by pattern and never goes to the model.
Everything else is one multiple choice question to the decision model, over the tabs the picker shows.
"""

import re
import hashlib
import dataclasses

from django.core.cache import cache

import structlog

from ..facade.contracts import ChoiceAnswer, DecisionQuestion, DecisionRequest, SearchIntent, SearchIntentRequest
from ..facade.enums import DecisionQuestionType, SearchIntentSource
from . import decisions

logger = structlog.get_logger(__name__)

MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 64
# The picker waits for no answer, so a late answer is worth nothing and a short timeout frees the worker.
SEARCH_INTENT_TIMEOUT_SECONDS = 2.0
# The frontend acts on an answer only above this confidence. Tune it from the eval suite, not by feel.
CONFIDENT_THRESHOLD = 0.6
CACHE_TTL_SECONDS = 24 * 60 * 60
# The state carries no team data, so one cached answer serves every team that types the same search.
CACHE_KEY_PREFIX = "ml_inference:search_intent:v1"

# The tabs the model can choose from, with the meaning the model reads. A tab the picker does not show is not offered.
SEARCH_INTENT_OPTIONS: dict[str, str] = {
    "events": "An event: something a person did, such as a pageview, a signup, a purchase or a click.",
    "actions": "A saved action: a named combination of events.",
    "event_properties": (
        "A property of one event, such as the current URL, path, browser, device, UTM tags, referrer "
        "or the country the event came from."
    ),
    "person_properties": (
        "A property of a person, such as their email address, name, company, plan or the date they signed up."
    ),
    "session_properties": "A property of a whole session, such as its duration, entry URL, exit URL or channel type.",
    "cohorts": "A saved cohort: a named group of people.",
    "feature_flags": "A feature flag, or the people who match a feature flag.",
    "event_feature_flags": "The value of a feature flag that was active when an event happened.",
    "pageview_urls": "One specific page URL.",
    "email_addresses": "One specific person's email address.",
    "elements": "An element on the page, such as a button, a link or a form field.",
}

_EMAIL_VALUE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
_URL_VALUE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)
_PATH_VALUE = re.compile(r"^/[\w\-./]*$")
# Long digit runs are ids or phone numbers, which are not ours to send.
_DIGIT_RUN = re.compile(r"\d{6,}")
_SCENE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_QUESTION_ID = "tab"
_INSTRUCTIONS = "Which tab of the filter picker holds the thing this person searches for?"


def _skipped() -> SearchIntent:
    return SearchIntent(group_type=None, confidence=0.0, is_confident=False, source=SearchIntentSource.SKIPPED)


def _rule_match(group_type: str) -> SearchIntent:
    return SearchIntent(group_type=group_type, confidence=1.0, is_confident=True, source=SearchIntentSource.RULE)


def rule_intent(query: str, available_group_types: tuple[str, ...]) -> SearchIntent | None:
    """Match value-shaped input. None means the query is not a value and the model can read it."""
    if "@" in query:
        if _EMAIL_VALUE.match(query) and "email_addresses" in available_group_types:
            return _rule_match("email_addresses")
        if _EMAIL_VALUE.match(query) and "person_properties" in available_group_types:
            return _rule_match("person_properties")
        # A partial email address is still personal data, so it never goes to the model.
        return _skipped()
    if _URL_VALUE.match(query) or _PATH_VALUE.match(query):
        if "pageview_urls" in available_group_types:
            return _rule_match("pageview_urls")
        return _skipped()
    if _DIGIT_RUN.search(query):
        return _skipped()
    return None


def search_intent_state(query: str, active_group_type: str, scene: str | None) -> str:
    lines = ["A person uses the filter picker in PostHog, a product analytics tool."]
    if scene and _SCENE.match(scene):
        lines.append(f"Page: {scene}")
    lines.append(f"Open tab: {active_group_type}")
    lines.append(f"Search: {query}")
    return "\n".join(lines)


def _cache_key(model: str, state: str, options: dict[str, str]) -> str:
    digest = hashlib.sha256("\n".join([model, state, *sorted(options)]).encode()).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{digest}"


# The cross-category tab already shows every group, so there is no better tab to suggest from it.
_ALL_GROUPS_TAB = "suggested_filters"


def with_switch_suggestion(intent: SearchIntent, active_group_type: str) -> SearchIntent:
    """Suggest a different tab only for a confident answer that names a tab other than the open one."""
    suggests_switch = (
        intent.is_confident
        and intent.group_type is not None
        and intent.group_type != active_group_type
        and active_group_type != _ALL_GROUPS_TAB
    )
    return dataclasses.replace(intent, suggests_switch=suggests_switch)


def classify_search_intent(request: SearchIntentRequest, *, use_cache: bool = True) -> SearchIntent:
    """Raises the decision gateway errors; the caller decides whether a failed answer matters."""
    return with_switch_suggestion(_classify(request, use_cache=use_cache), request.active_group_type)


def _classify(request: SearchIntentRequest, *, use_cache: bool) -> SearchIntent:
    query = " ".join(request.query.split())
    if not MIN_QUERY_CHARS <= len(query) <= MAX_QUERY_CHARS:
        return _skipped()
    matched = rule_intent(query, request.available_group_types)
    if matched is not None:
        return matched

    options = {
        group_type: meaning
        for group_type, meaning in SEARCH_INTENT_OPTIONS.items()
        if group_type in request.available_group_types
    }
    if len(options) < 2:
        return _skipped()

    decision = DecisionRequest(
        team_id=request.team_id,
        state=search_intent_state(query, request.active_group_type, request.scene),
        questions={
            _QUESTION_ID: DecisionQuestion(
                type=DecisionQuestionType.CHOICE, instructions=_INSTRUCTIONS, criteria=options
            )
        },
    )
    key = _cache_key(decision.model, decision.state, options)
    if use_cache:
        cached = cache.get(key)
        if isinstance(cached, SearchIntent):
            return cached

    result = decisions.decide(decision, timeout_seconds=SEARCH_INTENT_TIMEOUT_SECONDS)
    answer = result.answers[_QUESTION_ID]
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in options:
        logger.warning("ml_inference_search_intent_unexpected_answer", team_id=request.team_id)
        return _skipped()
    intent = SearchIntent(
        group_type=answer.choice,
        confidence=answer.confidence,
        is_confident=answer.confidence >= CONFIDENT_THRESHOLD,
        source=SearchIntentSource.MODEL,
    )
    if use_cache:
        cache.set(key, intent, CACHE_TTL_SECONDS)
    return intent
