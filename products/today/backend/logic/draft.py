"""The template briefing, built from the fact sheet with no LLM.

It is shown at once while the LLM writes, and it stays when the LLM fails or its output does not
pass the checks. Same input, same output.
"""

from ..facade.enums import ItemGroup, ItemSource
from .candidates import FactValue
from .checks import MAX_LABEL_WORDS, MAX_SIGNAL_CHARS
from .content import BriefingContent, ContentSegment
from .fact_sheet import FactSheet, FactSheetItem

_COUNT_WORDS = ["No", "One", "Two", "Three", "Four", "Five"]
_REPORT_REASON = {
    "claimed_by_you": "You are working on it",
    "waiting_for_you": "It waits for your input",
    "suggested_reviewer": "You are a suggested reviewer",
    "urgent_for_project": "It is urgent and nobody owns it",
}


def _segment(text: str, item_key: str | None = None, highlight: bool = False) -> ContentSegment:
    return ContentSegment(text=text, item_key=item_key, highlight=highlight)


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:] if text[:2].istitle() else text


def _change(facts: dict[str, FactValue]) -> str:
    pct = float(facts.get("pct_change") or 0)
    return f"{'up' if pct > 0 else 'down'} {abs(pct):.0f}%"


def signal_for(item: FactSheetItem) -> str:
    facts = item.facts
    if item.group == ItemGroup.REPORT:
        priority = facts.get("priority")
        text = _REPORT_REASON.get(item.reason.value, "Needs you")
        return f"{priority}, {text[0].lower()}{text[1:]}"[:MAX_SIGNAL_CHARS] if priority else text[:MAX_SIGNAL_CHARS]
    if item.source == ItemSource.ALERTS:
        return "Alert firing"
    if item.group == ItemGroup.DASHBOARD:
        return f"{_change(facts).capitalize()} this week"
    if item.source == ItemSource.SUPPORT:
        if facts.get("sla_at_risk_or_breached"):
            return "SLA at risk"
        if facts.get("unread_messages"):
            return f"{facts['unread_messages']} unread messages"
        return f"No update for {facts.get('days_without_update', 0)} days"
    if item.source == ItemSource.ERROR_TRACKING:
        return "Assigned to your role" if facts.get("assigned_via_role") else "Assigned to you"
    if item.source == ItemSource.GITHUB:
        return str(facts.get("state") or "Pull request").capitalize()[:MAX_SIGNAL_CHARS]
    return ""


def label_for(item: FactSheetItem) -> str:
    return " ".join(item.title.split()[:MAX_LABEL_WORDS])


def _clause(item: FactSheetItem) -> str:
    """The rest of the sentence after the linked title: why the item needs the person."""
    facts = item.facts
    if item.group == ItemGroup.REPORT:
        text = _REPORT_REASON.get(item.reason.value, "It needs you")
        priority = facts.get("priority")
        return f" is {priority}. {text}." if priority else f". {text}."
    if item.source == ItemSource.ALERTS:
        return " is firing."
    if item.group == ItemGroup.DASHBOARD:
        return f" shows {_lower_first(str(facts.get('metric', 'the main metric')))} {_change(facts)} this week."
    if item.source == ItemSource.SUPPORT:
        if facts.get("sla_at_risk_or_breached"):
            return " has its SLA at risk."
        if facts.get("unread_messages"):
            return f" has {facts['unread_messages']} unread messages."
        return f" has had no update for {facts.get('days_without_update', 0)} days."
    if item.source == ItemSource.ERROR_TRACKING:
        holder = "your role" if facts.get("assigned_via_role") else "you"
        return f" is assigned to {holder}, first seen {facts.get('days_since_first_seen', 0)} days ago."
    if item.source == ItemSource.GITHUB:
        days = facts.get("days_open")
        state = str(facts.get("state") or "")
        if state == "review requested":
            waiting = "waits for your review"
        elif state == "checks failing":
            waiting = "has failing checks"
        elif state == "approved":
            waiting = "is approved and ready to merge"
        else:
            waiting = "needs you"
        return f" {waiting}, open for {days} days." if days is not None else f" {waiting}."
    return " needs you."


def build_draft(fact_sheet: FactSheet) -> BriefingContent:
    in_text = fact_sheet.text_items
    reports = [item for item in in_text if item.group == ItemGroup.REPORT]

    count = len(in_text)
    if not in_text:
        headline = "Nothing needs you right now"
    elif len(reports) == count:
        headline = f"{_COUNT_WORDS[count]} {'report needs' if count == 1 else 'reports need'} your input"
    else:
        headline = f"{_COUNT_WORDS[count]} {'item needs' if count == 1 else 'items need'} your attention"

    paragraphs: list[list[ContentSegment]] = []
    for index, item in enumerate(in_text):
        sentence = [_segment(item.title, item.key, item.top), _segment(_clause(item))]
        if index < 2:
            paragraphs.append(sentence)
        else:
            paragraphs[-1].append(_segment(" "))
            paragraphs[-1] += sentence

    return BriefingContent(
        headline=headline,
        paragraphs=paragraphs,
        labels={item.key: label_for(item) for item in fact_sheet.items},
        signals={item.key: signal_for(item) for item in fact_sheet.items},
    )
