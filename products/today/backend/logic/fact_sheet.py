"""The fact sheet: the ranked items and the only facts the writer may use."""

from datetime import date
from typing import Any

from ..facade.enums import ItemGroup
from .candidates import URGENCY_LABELS
from .ranking import RankedItem

# What each reason means for the person, so the writer can say why an item needs them.
REASON_GLOSSARY = {
    "claimed_by_you": "A self-driving report the person has claimed and is working on.",
    "waiting_for_you": "A self-driving report that stopped because it needs the person's answer or decision.",
    "suggested_reviewer": "A self-driving report that names the person as the right reviewer.",
    "urgent_for_project": "A P0 self-driving report that nobody in the project owns yet.",
    "dashboard_you_viewed": "A dashboard the person opened recently whose biggest metric moved week over week.",
    "insight_you_viewed": "An insight the person opened recently that moved week over week.",
    "alert_firing": "An alert on an insight the person set up that is firing right now.",
    "assigned_ticket": "A support ticket assigned to the person. Only metadata, never the customer's words.",
    "assigned_error_issue": "An active error tracking issue assigned to the person or one of their roles.",
    "review_requested": "A pull request where someone asked the person by name for a review.",
    "your_pull_request": "A pull request the person wrote that is failing checks or is approved and ready to merge.",
}


def build_fact_sheet(
    *,
    first_name: str,
    local_day: date,
    items: list[RankedItem],
    failed_sources: list[str],
) -> dict[str, Any]:
    return {
        "first_name": first_name,
        "local_day": local_day.isoformat(),
        "counts": {
            "items_in_text": sum(1 for i in items if i.in_text),
            "reports_in_text": sum(1 for i in items if i.in_text and i.candidate.group == ItemGroup.REPORT),
        },
        "failed_sources": failed_sources,
        "urgency_scale": URGENCY_LABELS,
        "reason_glossary": {
            reason: REASON_GLOSSARY[reason]
            for reason in sorted({item.candidate.reason.value for item in items})
            if reason in REASON_GLOSSARY
        },
        "items": [
            {
                "key": item.candidate.key,
                "group": item.candidate.group.value,
                "source": item.candidate.source.value,
                "reason": item.candidate.reason.value,
                "title": item.candidate.title,
                "url": item.candidate.url,
                "rank": item.rank,
                "urgency": item.candidate.urgency,
                "urgency_label": URGENCY_LABELS.get(item.candidate.urgency, "when you have time"),
                "in_text": item.in_text,
                "top": item.top,
                "facts": item.candidate.facts,
            }
            for item in items
        ],
    }
