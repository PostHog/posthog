from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from ...facade.contracts import NewsBrief, NewsLeadStory, NewsStory
from ...facade.enums import NewsTone
from .candidates import SCOPES, Candidate, change_percent
from .plan import Fact, Plan
from .queries import SERIES_DAYS
from .writer import Copy, Draft

Series = Mapping[tuple[str, str], Mapping[int, float]]

PRODUCTS = {
    "error": ("error_tracking", "Error tracking"),
    "user action": ("product_analytics", "Product analytics"),
    "key metric": ("product_analytics", "Growth"),
    "survey answer": ("surveys", "What users say"),
    "visitors": ("web_analytics", "Web analytics"),
}


@frozen
class StoredLead:
    story: NewsLeadStory
    scopes: tuple[str, ...]


@frozen
class StoredStory:
    story: NewsStory
    scopes: tuple[str, ...]


@frozen
class StoredBrief:
    brief: NewsBrief
    scopes: tuple[str, ...]


@frozen
class StoredEdition:
    lead: StoredLead
    stories: tuple[StoredStory, ...]
    briefs: tuple[StoredBrief, ...]


def series_labels(anchor: datetime) -> list[str]:
    days = [anchor - timedelta(days=days_ago) for days_ago in range(SERIES_DAYS - 1, -1, -1)]
    return [f"{day:%b} {day.day}" for day in days]


def picked(plan: Plan) -> list[Candidate]:
    facts = [*plan.lead, *(fact for slot in plan.stories for fact in slot), *plan.briefs]
    return [candidate for fact in facts for candidate in fact.candidates]


def _values(facts: Sequence[Fact], series: Series) -> list[float]:
    candidates = [c for fact in facts for c in fact.candidates]
    values = [
        sum(series.get((c.source, c.key), {}).get(day, 0.0) for c in candidates)
        for day in range(SERIES_DAYS - 1, -1, -1)
    ]
    return values if any(values) else []


def _change(facts: Sequence[Fact]) -> float | None:
    candidates = [c for fact in facts for c in fact.candidates]
    return change_percent(candidates[0].change) if len(candidates) == 1 else None


def _tone(fact: Fact, change: float | None) -> NewsTone:
    if fact.kind in ("error", "friction", "user_voice"):
        return NewsTone.RISK
    if change is not None and change < 0:
        return NewsTone.RISK
    return NewsTone.GOOD if fact.kind in ("growth", "improvement") else NewsTone.NEUTRAL


def _product(fact: Fact) -> tuple[str, str]:
    if fact.surface == "app sign-in":
        return "error_tracking", "Sign-in"
    if fact.kind == "growth":
        return "product_analytics", "Growth"
    if fact.kind == "user_voice":
        return "surveys", "What users say"
    return PRODUCTS[fact.candidates[0].source]


def _scopes(facts: Sequence[Fact]) -> tuple[str, ...]:
    return tuple(sorted({scope for fact in facts for c in fact.candidates for scope in SCOPES[c.source]}))


def _story(facts: Sequence[Fact], copy: Copy, series: Series, labels: list[str]) -> StoredStory:
    product, product_label = _product(facts[0])
    change = _change(facts)
    values = _values(facts, series)
    return StoredStory(
        story=NewsStory(
            id=f"{facts[0].candidates[0].source}:{facts[0].candidates[0].key}",
            product=product,
            product_label=product_label,
            title=copy.title,
            summary=copy.summary,
            change=change,
            tone=_tone(facts[0], change),
            dive_prompt=copy.dive_prompt,
            series=values,
            series_labels=labels if values else [],
        ),
        scopes=_scopes(facts),
    )


def lead_story(story: NewsStory) -> NewsLeadStory:
    return NewsLeadStory(
        id=story.id,
        product=story.product,
        product_label=story.product_label,
        title=story.title,
        summary=story.summary,
        change=story.change,
        tone=story.tone,
        dive_prompt=story.dive_prompt,
        metric_label="Last 14 days" if story.series else "",
        metric_value=f"{int(story.series[-1]):,}" if story.series else "",
        series=story.series,
        series_labels=story.series_labels,
        url=story.url,
    )


def edition(plan: Plan, draft: Draft, series: Series, anchor: datetime) -> StoredEdition:
    labels = series_labels(anchor)
    lead = _story(plan.lead, draft.lead, series, labels)
    stories = tuple(_story(slot, copy, series, labels) for slot, copy in zip(plan.stories, draft.stories))
    briefs = []
    for fact, label in zip(plan.briefs, draft.briefs):
        change = _change([fact])
        values = _values([fact], series)
        briefs.append(
            StoredBrief(
                brief=NewsBrief(
                    id=f"{fact.candidates[0].source}:{fact.candidates[0].key}",
                    value=fact.people,
                    text=label,
                    change=change,
                    is_new=fact.is_new,
                    tone=_tone(fact, change),
                    series=values,
                    series_labels=labels if values else [],
                ),
                scopes=_scopes([fact]),
            )
        )
    return StoredEdition(
        lead=StoredLead(story=lead_story(lead.story), scopes=lead.scopes), stories=stories, briefs=tuple(briefs)
    )
