import re
import json
import hashlib
from typing import Any

from django.core.cache import cache

import structlog
from openai import APIError

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import GatewayNotConfiguredError, build_openai_client, team_distinct_id
from posthog.models import Team, User

from products.product_analytics.backend.facade.api import get_or_create_saved_insight, saved_insights_for_read

from ..models import SignalScoutConfig
from .metrics import delivery, metric, observed
from .plan import daily_audience, plan_anchor
from .scout import GOAL_TAG

logger = structlog.get_logger(__name__)

MODEL = "gpt-6-luna"
MAX_INSIGHTS = 80
MAX_EVENTS = 80
MAX_OPTIONS = 3
SPARK_POINTS = 30
MAX_DRAFT = 200
DRAFT_STARTS = ("Number of", "Share of", "Average")
ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
FLOOR_EVENTS = 200
CACHE_SECONDS = 600
PERIODS = {"hour": "per hour", "day": "per day", "week": "per week", "month": "per month"}
UNCHARTED = {"ActionsTable", "ActionsPie", "BoldNumber", "WorldMap", "ActionsBarValue"}

PROMPT = """You help a product owner pick the number that a goal will move.
The owner wrote what should change. Pick up to 3 measures that show it, best first.
Prefer a saved insight when it measures the same thing. When no saved insight fits, build a new measure from the events whenever the events show the action the owner wrote.
A count stays a count. A share or rate stays a share or rate.
A new measure uses only events from the list. It is one of:
- "users": the number of people who do the event, per day.
- "rate": people who do the numerator event divided by people who do the denominator event, per day.
- "per_person": the number of events divided by the number of people who do it, per day.
Always write "draft": one sentence that defines the measure this goal needs, for an analyst who will build it, even when no event shows it yet, because the analyst can add tracking. Say who is counted, which action, and in what time window, for example "Share of new uploaders who share a file within 24 hours of their first upload". Start with "Number of", "Share of" or "Average". Use at most 200 characters. Never write about missing data, and never repeat the belief.
Answer with JSON only:
{"draft": "<one sentence>", "options": [{"insight": "<short id>", "why": "<one short sentence>"},
             {"new": {"name": "<short name in sentence case, for example Share rate after upload>", "kind": "users|rate|per_person", "event": "<event>", "denominator": "<event or null>"}, "why": "<one short sentence>"}]}
The name of a new measure says only what it counts. A new measure has no time window, so its name never has one, for example "Checkout rate after signup", not "Checkout rate in the first week". A new measure has no filter, so its name never names a cause, a channel or a group of people that the events do not show, for example "People who log in", not "Summary email returners".
Suggest only measures that count the same people and the same action the owner wrote. Return {"options": []} only when no saved insight and no event shows that action."""

LABELS = """You name a product goal from the owner's belief.
Return JSON: {"name": "...", "area": "..."}.
- name: 3 to 7 words that say what should change for users, in sentence case, no period, no quotes, no product names unless the belief uses them. Example: "More people share what they upload".
- area: the part of the product the belief is about, 1 to 3 words in sentence case, like "Sharing" or "Onboarding". If one of the existing areas fits, return it exactly as written. If the belief does not point to one part of the product, return "".
Write in plain English. Do not invent facts that the belief does not state."""

MAX_NAME = 80
MAX_AREA = 40

GUARD = """You help a product owner protect their product while a goal tests changes.
The owner wrote the goal and chose the measure to move. Pick up to 3 guardrails: measures that a change for this goal could hurt, such as errors, core usage, or a nearby step that people might skip.
Never pick the chosen measure or a measure of the same action.
Prefer a saved insight. A new measure uses only events from the list, with the same shapes: "users", "rate" or "per_person".
Say which way is better for each guardrail.
Answer with JSON only:
{"options": [{"insight": "<short id>", "better": "higher|lower"},
             {"new": {"name": "<short name in sentence case>", "kind": "users|rate|per_person", "event": "<event>", "denominator": "<event or null>"}, "better": "higher|lower"}]}"""

CHECK = """You check measures that were suggested for a goal.
"fits": the measure counts the action the goal names, done by the people or things the goal names. A count, a share or a rate of that action fits. A measure for new people or first-time actions fits a goal about people in general.
"no": the measure counts another action or another thing. Uploads are not shares. Files are not dubs. People are not teams.
Answer with JSON only: {"checks": [{"id": "<id>", "verdict": "fits|no"}]}"""


def describe(query: dict[str, Any]) -> str | None:
    source = query.get("source", query) if query.get("kind") == "InsightVizNode" else query
    if source.get("kind") != "TrendsQuery":
        return None
    if (source.get("trendsFilter") or {}).get("display") in UNCHARTED:
        return None
    series = source.get("series") or []
    formula = (source.get("trendsFilter") or {}).get("formula")
    if len(series) != 1 and not formula:
        return None
    parts = [phrase(item) for item in series]
    period = PERIODS.get(source.get("interval") or "day", "per day")
    if formula and len(parts) == 2 and formula.replace(" ", "").upper() == "A/B":
        return f"{parts[0]} divided by {parts[1]}, {period}"
    if formula:
        return (
            f"{formula} of "
            + ", ".join(f"{chr(65 + index)} = {part}" for index, part in enumerate(parts))
            + f", {period}"
        )
    return f"{parts[0]}, {period}"


def phrase(item: dict[str, Any]) -> str:
    event = item.get("event") or item.get("name") or "an action"
    math = item.get("math") or "total"
    if math == "dau":
        return f"people who did {event}"
    if math == "first_time_for_user":
        return f"people who did {event} for the first time"
    if math in ("sum", "avg", "min", "max", "median") and item.get("math_property"):
        return f"{math} of {item['math_property']} on {event}"
    if math in ("unique_group", "weekly_active", "monthly_active", "unique_session"):
        return f"{math.replace('_', ' ')} of {event}"
    return f"times {event} happened"


def series_events(query: dict[str, Any]) -> list[str]:
    source = query.get("source", query) if query.get("kind") == "InsightVizNode" else query
    return [item["event"] for item in source.get("series") or [] if item.get("event")]


def new_query(kind: str, event: str, denominator: str | None) -> dict[str, Any] | None:
    numerator = {"kind": "EventsNode", "event": event, "math": "dau"}
    if kind == "users":
        return {"kind": "TrendsQuery", "series": [numerator], "interval": "day", "dateRange": {"date_from": "-14d"}}
    if kind == "rate" and denominator:
        return {
            "kind": "TrendsQuery",
            "series": [numerator, {"kind": "EventsNode", "event": denominator, "math": "dau"}],
            "interval": "day",
            "dateRange": {"date_from": "-14d"},
            "trendsFilter": {"formula": "A/B", "aggregationAxisFormat": "percentage_scaled"},
        }
    if kind == "per_person":
        return {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": event, "math": "total"}, numerator],
            "interval": "day",
            "dateRange": {"date_from": "-14d"},
            "trendsFilter": {"formula": "A/B"},
        }
    return None


def top_events(team: Team) -> list[str]:
    with tags_context(product=Product.SIGNALS, feature=Feature.QUERY, team_id=team.id):
        rows = execute_hogql_query(
            "select event, count() as total from events where timestamp > now() - interval 30 day "
            "group by event order by total desc limit {limit}",
            team=team,
            placeholders={"limit": ast.Constant(value=MAX_EVENTS)},
            query_type="goal_scout_top_events",
            workload=Workload.ONLINE,
        ).results
    return [row[0] for row in rows]


def wait_days(team: Team, events: list[str]) -> dict[str, int]:
    if not events:
        return {}
    with tags_context(product=Product.SIGNALS, feature=Feature.QUERY, team_id=team.id):
        rows = execute_hogql_query(
            """
            select e.event, count() as total,
                quantile(0.01)(dateDiff('second', f.first_seen, e.timestamp)) / 86400 as floor_days
            from events e
            join (select person_id, min(timestamp) as first_seen from events
                  where timestamp > now() - interval 60 day group by person_id) f on e.person_id = f.person_id
            where e.timestamp > now() - interval 30 day and e.event in {events}
            group by e.event""",
            team=team,
            placeholders={"events": ast.Constant(value=tuple(events))},
            query_type="goal_scout_wait_days",
            workload=Workload.ONLINE,
        ).results
    return {row[0]: int(row[2]) for row in rows if row[1] >= FLOOR_EVENTS and row[2] >= 1}


class MeasureModelUnavailable(Exception):
    pass


def complete(team: Team, system: str, content: str) -> dict[str, Any]:
    try:
        client = build_openai_client("signals", ai_product="signals", distinct_id=team_distinct_id(team.id))
        response = client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            user=team_distinct_id(team.id),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        )
    except (APIError, GatewayNotConfiguredError) as error:
        logger.warning("goal_scout_measure_model_failed", team_id=team.id, error=str(error))
        raise MeasureModelUnavailable from error
    try:
        answer = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {}
    return answer if isinstance(answer, dict) else {}


@frozen
class Catalog:
    insights: dict[str, tuple[str, str]]
    queries: dict[str, dict[str, Any]]
    events: list[str]


@frozen
class MeasureOption:
    insight: str
    name: str
    source: str
    definition: str
    current: float | None
    unit: str
    wait_days: int
    test_days: int | None
    values: list[float]
    dates: list[str]


@frozen
class MeasureSearch:
    options: list[MeasureOption]
    draft: str


@frozen
class BeliefLabels:
    name: str
    area: str


@frozen
class GuardrailOption:
    insight: str
    name: str
    definition: str
    direction: str


@frozen
class _Pick:
    key: str
    source: str
    query: dict[str, Any]
    text: str
    item: dict[str, Any]


def ask(team: Team, system: str, goal: str, found: Catalog, extra: str = "") -> dict[str, Any]:
    listing = "\n".join(f"- {short_id}: {name} ({summary})" for short_id, (name, summary) in found.insights.items())
    return complete(
        team,
        system,
        f"What should change: {goal}{extra}\n\nSaved insights:\n{listing or '- none'}\n\nEvents:\n{', '.join(found.events)}",
    )


def check(team: Team, goal: str, candidates: dict[str, str]) -> dict[str, str]:
    listing = "\n".join(f"- {key}: {text}" for key, text in candidates.items())
    rows = complete(team, CHECK, f"What should change: {goal}\n\nMeasures:\n{listing}").get("checks") or []
    return {str(row.get("id")): str(row.get("verdict")) for row in rows if isinstance(row, dict)}


def catalog(team: Team, user: User) -> Catalog:
    saved = saved_insights_for_read(team=team, user=user, limit=MAX_INSIGHTS)
    return Catalog(
        insights={
            item.short_id: (item.name or "Untitled", summary)
            for item in saved
            if (summary := describe(item.query)) is not None
        },
        queries={item.short_id: item.query for item in saved},
        events=top_events(team),
    )


ORDINAL_WINDOW = re.compile(
    r"\b(?:first|second|third|fourth|last|\d+(?:st|nd|rd|th))[- ](?:minute|hour|day|week|month)\b[- ]?", re.IGNORECASE
)
TIME_WINDOW = re.compile(
    r"\s+(?:after|within|in|during|over)\s+(?:their|the|a)?\s*(?:first|last)?\s*(?:\d+|one|two|three|seven)?\s*"
    r"(?:minutes?|hours?|days?|weeks?|months?)\b(?:\s+of\s+\w+)?",
    re.IGNORECASE,
)


def parse(raw: list[Any], found: Catalog) -> list[_Pick]:
    picks: list[_Pick] = []
    for item in raw[: MAX_OPTIONS + 2]:
        if not isinstance(item, dict):
            continue
        if item.get("insight") in found.insights:
            name, summary = found.insights[item["insight"]]
            picks.append(
                _Pick(
                    key=item["insight"],
                    source="existing",
                    query=found.queries[item["insight"]],
                    text=f"{name} ({summary})",
                    item=item,
                )
            )
            continue
        spec = item.get("new") or {}
        event, denominator = spec.get("event"), spec.get("denominator")
        if event not in found.events or (denominator and denominator not in found.events) or denominator == event:
            continue
        query = new_query(str(spec.get("kind")), event, denominator)
        if query is None:
            continue
        name = ORDINAL_WINDOW.sub("", TIME_WINDOW.sub("", str(spec.get("name") or ""))).strip(" ,-")
        name = (name[:1].upper() + name[1:])[:100]
        if not name:
            definition = describe(query) or event
            name = (definition[:1].upper() + definition[1:])[:100]
        picks.append(
            _Pick(
                key=f"new{len(picks)}",
                source="new",
                query={**query, "name": name},
                text=f"{name} ({describe(query)})",
                item=item,
            )
        )
    return list({pick.text: pick for pick in picks}.values())


def clean_draft(raw: object) -> str:
    draft = str(raw or "").strip()
    return draft if len(draft) <= MAX_DRAFT and draft.startswith(DRAFT_STARTS) else ""


def materialize(team: Team, user: User, goal: str, query: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    body = {key: value for key, value in query.items() if key != "name"}
    digest = hashlib.sha256(f"{team.id}:{json.dumps(body, sort_keys=True)}".encode()).digest()
    short_id = "gm" + "".join(ALPHABET[byte % len(ALPHABET)] for byte in digest[:6])
    get_or_create_saved_insight(
        team_id=team.id,
        user_id=user.id,
        short_id=short_id,
        name=query["name"],
        description=goal[:400],
        query=body,
        saved=False,
    )
    return short_id, str(query["name"]), body


def _test_days(team: Team, user: User, short_id: str) -> int | None:
    measured = metric(team, user, short_id)
    anchor = plan_anchor(measured, daily_audience(observed(delivery(team, user, short_id, workload=Workload.ONLINE))))
    return anchor.days if anchor else None


def measure_options(team: Team, user: User, goal: str) -> MeasureSearch:
    key = f"signals:goal-measures:{team.id}:{user.id}:{hashlib.sha256(goal.strip().lower().encode()).hexdigest()}"
    cached = cache.get(key)
    if isinstance(cached, MeasureSearch):
        return cached
    found = catalog(team, user)
    try:
        answer = ask(team, PROMPT, goal, found)
    except MeasureModelUnavailable:
        return MeasureSearch(options=[], draft="")
    draft = clean_draft(answer.get("draft"))
    picks = parse(answer.get("options") or [], found)
    try:
        verdicts = check(team, goal, {pick.key: pick.text for pick in picks}) if picks else {}
    except MeasureModelUnavailable:
        return MeasureSearch(options=[], draft=draft)
    kept: list[tuple[str, str, dict[str, Any], str]] = []
    for pick in picks:
        if verdicts.get(pick.key) != "fits":
            continue
        short_id, name, query = pick.key, "", pick.query
        if pick.source == "new":
            short_id, name, query = materialize(team, user, goal, pick.query)
        kept.append((short_id, pick.source, query, name))
    kept = kept[: MAX_OPTIONS + 1]
    waits = wait_days(team, sorted({event for _, _, query, _ in kept for event in series_events(query)}))
    options = []
    for short_id, source, query, new_name in kept:
        measured = metric(team, user, short_id, blocking=True)
        options.append(
            MeasureOption(
                insight=short_id,
                name=new_name or measured.name,
                source=source,
                definition=describe(query) or "",
                current=measured.current,
                unit=measured.unit,
                wait_days=max((waits.get(event, 0) for event in series_events(query)), default=0),
                test_days=_test_days(team, user, short_id),
                values=measured.values[-SPARK_POINTS:],
                dates=measured.dates[-SPARK_POINTS:],
            )
        )
    options.sort(key=lambda option: (option.wait_days, option.test_days or 999))
    search = MeasureSearch(options=options[:MAX_OPTIONS], draft=draft)
    if options:
        cache.set(key, search, CACHE_SECONDS)
    return search


def guardrail_options(team: Team, user: User, goal: str, measure: str) -> list[GuardrailOption]:
    key = f"signals:goal-guardrails:{team.id}:{user.id}:{measure}:{hashlib.sha256(goal.strip().lower().encode()).hexdigest()}"
    cached = cache.get(key)
    if isinstance(cached, list):
        return cached
    found = catalog(team, user)
    chosen = found.insights.get(measure)
    extra = f"\nChosen measure: {chosen[0]} ({chosen[1]})" if chosen else ""
    try:
        answer = ask(team, GUARD, goal, found, extra)
    except MeasureModelUnavailable:
        return []
    options = []
    for pick in parse(answer.get("options") or [], found):
        if pick.key == measure:
            continue
        short_id, query = pick.key, pick.query
        name = str(query.get("name") or found.insights.get(short_id, ("",))[0])
        if pick.source == "new":
            short_id, name, query = materialize(team, user, goal, query)
        options.append(
            GuardrailOption(
                insight=short_id,
                name=name,
                definition=describe(query) or "",
                direction="decrease" if pick.item.get("better") == "lower" else "increase",
            )
        )
    options = options[:MAX_OPTIONS]
    cache.set(key, options, CACHE_SECONDS)
    return options


def existing_areas(team_id: int) -> list[str]:
    tags = SignalScoutConfig.objects.for_team(team_id).filter(tags__contains=[GOAL_TAG]).values_list("tags", flat=True)
    return sorted({tag for row in tags for tag in row or [] if tag != GOAL_TAG})[:30]


def belief_labels(team: Team, belief: str) -> BeliefLabels:
    text = belief.strip()
    if not text:
        return BeliefLabels(name="", area="")
    key = f"signals:goal-labels:{team.id}:{hashlib.sha256(text.lower().encode()).hexdigest()}"
    cached = cache.get(key)
    if isinstance(cached, BeliefLabels):
        return cached
    areas = existing_areas(team.id)
    try:
        answer = complete(team, LABELS, f"Belief: {text[:2000]}\n\nExisting areas: {', '.join(areas) or 'none'}")
    except MeasureModelUnavailable:
        return BeliefLabels(name="", area="")
    name = " ".join(str(answer.get("name") or "").split()).strip(" .\"'")[:MAX_NAME]
    area = " ".join(str(answer.get("area") or "").split()).strip(" .\"'")[:MAX_AREA]
    match = next((existing for existing in areas if existing.lower() == area.lower()), None)
    labels = BeliefLabels(name=name[:1].upper() + name[1:], area=match or area[:1].upper() + area[1:])
    cache.set(key, labels, CACHE_SECONDS)
    return labels
