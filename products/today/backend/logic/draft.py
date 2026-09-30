"""The template briefing, built from the fact sheet with no LLM.

It is shown at once while the LLM writes, and it stays when the LLM fails or its output does not
pass the checks. Same input, same output.
"""

from typing import Any

_COUNT_WORDS = ["No", "One", "Two", "Three", "Four", "Five"]
_REPORT_REASON = {
    "claimed_by_you": "You are working on it",
    "waiting_for_you": "It waits for your input",
    "suggested_reviewer": "You are a suggested reviewer",
    "urgent_for_project": "It is urgent and nobody owns it",
}


def _segment(text: str, item_key: str | None = None, highlight: bool = False) -> dict[str, Any]:
    return {"text": text, "item_key": item_key, "highlight": highlight}


def _join(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joined: list[dict[str, Any]] = []
    for index, link in enumerate(links):
        if index:
            joined.append(_segment(" and " if index == len(links) - 1 else ", "))
        joined.append(link)
    return joined


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:] if text[:2].istitle() else text


def _change(facts: dict[str, Any]) -> str:
    pct = facts.get("pct_change") or 0
    return f"{'up' if pct > 0 else 'down'} {abs(pct):.0f}%"


def signal_for(item: dict[str, Any]) -> str:
    facts = item["facts"]
    if item["group"] == "report":
        priority = facts.get("priority")
        text = _REPORT_REASON.get(item["reason"], "Needs you")
        return f"{priority}, {text[0].lower()}{text[1:]}"[:40] if priority else text[:40]
    if item["source"] == "alerts":
        return "Alert firing"
    if item["group"] == "dashboard":
        return f"{_change(facts).capitalize()} this week"
    if item["source"] == "support":
        if facts.get("sla_at_risk_or_breached"):
            return "SLA at risk"
        if facts.get("unread_messages"):
            return f"{facts['unread_messages']} unread messages"
        return f"No update for {facts.get('days_without_update', 0)} days"
    if item["source"] == "error_tracking":
        return "Assigned to your role" if facts.get("assigned_via_role") else "Assigned to you"
    if item["source"] == "github":
        return str(facts.get("state") or "Pull request").capitalize()[:40]
    return ""


def label_for(item: dict[str, Any]) -> str:
    return " ".join(item["title"].split()[:6])


def build_draft(fact_sheet: dict[str, Any]) -> dict[str, Any]:
    items = fact_sheet["items"]
    in_text = [item for item in items if item["in_text"]]
    reports = [item for item in in_text if item["group"] == "report"]
    movements = [item for item in in_text if item["group"] == "dashboard"]
    others = [item for item in in_text if item["group"] == "other"]

    if reports:
        count = len(reports)
        headline = f"{_COUNT_WORDS[count]} {'report needs' if count == 1 else 'reports need'} your input this morning"
    elif movements:
        headline = "Here is how your dashboards moved this week"
    elif others:
        headline = "A few things need you this morning"
    else:
        headline = "Nothing needs you right now"

    paragraphs: list[list[dict[str, Any]]] = []
    if reports:
        top, *rest = reports
        paragraph = [_segment("Start with "), _segment(top["title"], top["key"], top.get("top", False))]
        paragraph.append(_segment(f". {_REPORT_REASON.get(top['reason'], 'It needs you')}."))
        if rest:
            paragraph.append(_segment(" Also waiting: "))
            paragraph += _join(
                [_segment(_lower_first(item["title"]), item["key"], item.get("top", False)) for item in rest]
            )
            paragraph.append(_segment("."))
        paragraphs.append(paragraph)
    if movements:
        paragraph = []
        for index, item in enumerate(movements):
            facts = item["facts"]
            paragraph += [
                _segment("On " if index == 0 else " On "),
                _segment(item["title"], item["key"], item.get("top", False)),
            ]
            if item["source"] == "alerts":
                paragraph.append(_segment(", an alert is firing."))
            else:
                paragraph.append(
                    _segment(
                        f", {_lower_first(str(facts.get('metric', 'the main metric')))} is {_change(facts)} this week."
                    )
                )
        paragraphs.append(paragraph)
    if others:
        paragraph = [_segment("Also: ")]
        paragraph += _join([_segment(item["title"], item["key"], item.get("top", False)) for item in others])
        paragraph.append(_segment("."))
        paragraphs.append(paragraph)

    return {
        "headline": headline,
        "paragraphs": paragraphs,
        "labels": {item["key"]: label_for(item) for item in items},
        "signals": {item["key"]: signal_for(item) for item in items},
    }
