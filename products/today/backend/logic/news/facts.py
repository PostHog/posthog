from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from typing import TypeVar, cast

import structlog
from pydantic import TypeAdapter

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.scopes import APIScopeObject
from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.access_control.backend.facade.api import (
    every_member_has_resource_access,
    object_ids_restricted_from_any_member,
)
from products.annotations.backend.facade.api import list_changes
from products.annotations.backend.facade.change_feed import Change, ChangeKind, ChangeWindow, KindVisibility

from ...facade.contracts import HighlightSource, NewsFact
from ...facade.enums import NewsTone
from ..highlight_registry import source_product

logger = structlog.get_logger(__name__)
T = TypeVar("T")

WINDOW_DAYS = 7
RECENT_DAYS = 3
OLDER_RECENCY = 0.8
UNSHARED_BREADTH = 0.7
STRONG_SCORE = 0.5
LEAD_SCORE = 0.75
SUPPORT_SCORE = 0.4
STRONG_FACTS_NEEDED = 3
SUPPORT_FACTS_NEEDED = 2
MAX_STORED_FACTS = 50
MAX_PROMPT_FACTS = 25
MAX_TEXT_LENGTH = 280
CHANGE_FEED_LIMIT = 200
CHANGE_FEED_SOURCE = "change_feed"

KIND_RESOURCES: dict[ChangeKind, str] = {
    ChangeKind.FEATURE_FLAG: "feature_flag",
    ChangeKind.EXPERIMENT: "experiment",
    ChangeKind.RELEASE: "error_tracking",
    ChangeKind.ANNOTATION: "annotation",
}
KIND_PRODUCTS: dict[ChangeKind, str] = {
    ChangeKind.FEATURE_FLAG: "feature_flags",
    ChangeKind.EXPERIMENT: "experiments",
    ChangeKind.RELEASE: "error_tracking",
    ChangeKind.ANNOTATION: "annotations",
}


@frozen
class ScoredFact:
    fact: NewsFact
    score: float


@frozen
class _ChangeRule:
    kind: str
    importance: float
    magnitude: float
    url: str | None


SCORED_FACTS = TypeAdapter(list[ScoredFact])


def clean(text: str | None) -> str:
    return sanitize_user_text(text, MAX_TEXT_LENGTH)


class NewsCollectionContext:
    def __init__(self, team: Team, end: datetime) -> None:
        self.team = team
        self.end = end
        self.start = end - timedelta(days=WINDOW_DAYS)
        self.failures: list[str] = []
        self._shared: dict[str, bool] = {}
        self._withheld: dict[str, frozenset[str]] = {}

    def shared(self, resource: str) -> bool:
        if resource not in self._shared:
            self._shared[resource] = every_member_has_resource_access(
                team_id=self.team.id, resource=cast(APIScopeObject, resource), required_level="viewer"
            )
        return self._shared[resource]

    def withheld(self, resource: str) -> frozenset[str]:
        if resource not in self._withheld:
            self._withheld[resource] = frozenset(
                object_ids_restricted_from_any_member(
                    team_id=self.team.id, resource=cast(APIScopeObject, resource), required_level="viewer"
                )
            )
        return self._withheld[resource]

    def visible(self, fact: NewsFact) -> bool:
        resources = {fact.resource, *(scope.split(":")[0] for scope in fact.scopes)}
        if not all(self.shared(resource) for resource in resources):
            return False
        return fact.object_id is None or fact.object_id not in self.withheld(fact.resource)

    def guard(self, name: str, provider: Callable[[], T], default: T) -> T:
        try:
            return provider()
        except Exception as error:
            logger.warning("today_news_source_failed", source=name, team_id=self.team.id, error=str(error))
            self.failures.append(name)
            capture_exception(error, {"source": name, "team_id": self.team.id, "product": "today"})
            return default


def _change_rule(kind: ChangeKind, changes: Sequence[Change]) -> _ChangeRule | None:
    fields = {field for change in changes for field in change.changed_fields}
    activities = {change.activity for change in changes}
    item_id = changes[0].item_id
    if kind == ChangeKind.EXPERIMENT:
        url = f"/experiments/{item_id}"
        if "end_date" in fields:
            return _ChangeRule(kind="experiment_ended", importance=0.7, magnitude=1.0, url=url)
        if "start_date" in fields:
            return _ChangeRule(kind="experiment_started", importance=0.45, magnitude=1.0, url=url)
        return None
    if kind == ChangeKind.FEATURE_FLAG:
        url = f"/feature_flags/{item_id}"
        if "active" in fields or "deleted" in activities:
            return _ChangeRule(kind="flag_switched", importance=0.5, magnitude=1.0, url=url)
        if "filters" in fields:
            return _ChangeRule(kind="flag_rollout_changed", importance=0.5, magnitude=0.8, url=url)
        return None
    if kind == ChangeKind.RELEASE:
        return _ChangeRule(kind="release", importance=0.3, magnitude=1.0, url=None)
    return _ChangeRule(kind="annotation", importance=0.3, magnitude=1.0, url=None)


def _change_fact(kind: ChangeKind, changes: Sequence[Change]) -> NewsFact | None:
    rule = _change_rule(kind, changes)
    if rule is None:
        return None
    latest = max(changes, key=lambda change: change.timestamp)
    people = {change.actor_name for change in changes if change.actor_name}
    project_wide = kind in (ChangeKind.RELEASE, ChangeKind.ANNOTATION)
    numbers: dict[str, float | int | str] = {"changes": len(changes), "people": len(people)}
    if latest.service:
        numbers["service"] = clean(latest.service)
    return NewsFact(
        key=f"{kind.value}:{latest.item_id}",
        kind=rule.kind,
        title=clean(latest.name) or kind.label,
        importance=rule.importance,
        magnitude=rule.magnitude,
        breadth=1.0 if project_wide or len(people) >= 2 else UNSHARED_BREADTH,
        at=latest.timestamp,
        tone=NewsTone.NEUTRAL,
        resource=KIND_RESOURCES[kind],
        scopes=(f"{KIND_RESOURCES[kind]}:read",),
        object_id=None if kind == ChangeKind.RELEASE else latest.item_id,
        numbers=numbers,
        url=rule.url,
        product=KIND_PRODUCTS[kind],
    )


def change_feed_facts(context: NewsCollectionContext) -> tuple[NewsFact, ...]:
    visibility: dict[ChangeKind, KindVisibility] = {}
    for kind, resource in KIND_RESOURCES.items():
        if not context.shared(resource):
            continue
        visibility[kind] = (
            KindVisibility() if kind == ChangeKind.RELEASE else KindVisibility(blocked_ids=context.withheld(resource))
        )
    if not visibility:
        return ()
    feed = list_changes(
        team_id=context.team.id,
        organization_id=context.team.organization_id,
        user_is_staff=False,
        window=ChangeWindow(start=context.start, end=context.end),
        visibility=visibility,
        limit=CHANGE_FEED_LIMIT,
    )
    grouped: dict[tuple[ChangeKind, str], list[Change]] = defaultdict(list)
    for change in feed.results:
        grouped[(change.kind, change.item_id)].append(change)
    facts = (_change_fact(kind, changes) for (kind, _), changes in grouped.items())
    return tuple(fact for fact in facts if fact is not None)


def score(fact: NewsFact, end: datetime) -> float:
    recency = 1.0 if fact.at >= end - timedelta(days=RECENT_DAYS) else OLDER_RECENCY
    value = fact.importance * min(max(fact.magnitude, 0.0), 1.0) * min(max(fact.breadth, 0.0), 1.0) * recency
    return round(value, 3)


def enough(scored: Iterable[ScoredFact]) -> bool:
    scores = sorted((item.score for item in scored), reverse=True)
    strong = sum(1 for value in scores if value >= STRONG_SCORE)
    if strong >= STRONG_FACTS_NEEDED:
        return True
    return (
        bool(scores)
        and scores[0] >= LEAD_SCORE
        and sum(1 for value in scores[1:] if value >= SUPPORT_SCORE) >= SUPPORT_FACTS_NEEDED
    )


def _sanitized(fact: NewsFact, product: str) -> NewsFact:
    return replace(
        fact,
        title=clean(fact.title),
        numbers={clean(key): clean(value) if isinstance(value, str) else value for key, value in fact.numbers.items()},
        metric_label=clean(fact.metric_label) or None,
        series_labels=tuple(clean(label) for label in fact.series_labels),
        product=fact.product or product,
    )


def rank(facts: Iterable[NewsFact], end: datetime) -> list[ScoredFact]:
    unique = {fact.key: fact for fact in facts}
    scored = [ScoredFact(fact=fact, score=score(fact, end)) for fact in unique.values()]
    scored.sort(key=lambda item: (-item.score, item.fact.key))
    return scored[:MAX_STORED_FACTS]


def collect(team: Team, end: datetime, sources: Sequence[HighlightSource]) -> list[ScoredFact]:
    context = NewsCollectionContext(team, end)
    found: list[NewsFact] = []
    with tags_context(product=Product.TODAY, feature=Feature.QUERY, team_id=team.id):
        none: tuple[NewsFact, ...] = ()
        found += context.guard(CHANGE_FEED_SOURCE, partial(change_feed_facts, context), none)
        for source in sources:
            if source.news is None:
                continue
            product = source_product(source.name) or source.name
            facts = context.guard(source.name, partial(source.news, context), none)
            found += [_sanitized(fact, product) for fact in facts]
    return rank((fact for fact in found if context.visible(fact)), end)
