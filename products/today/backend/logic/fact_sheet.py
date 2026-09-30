"""The fact sheet: the ranked items and the only facts the writer may use."""

from datetime import date
from typing import Any

from ..facade.enums import ItemGroup
from .ranking import RankedItem


def build_fact_sheet(
    *,
    first_name: str,
    local_day: date,
    items: list[RankedItem],
    reports_for_me_count: int,
    failed_sources: list[str],
) -> dict[str, Any]:
    reports_in_bar = sum(1 for item in items if item.candidate.group == ItemGroup.REPORT)
    return {
        "first_name": first_name,
        "local_day": local_day.isoformat(),
        "counts": {
            "reports_in_text": sum(1 for i in items if i.in_text and i.candidate.group == ItemGroup.REPORT),
            "more_reports_for_you": max(reports_for_me_count - reports_in_bar, 0),
        },
        "failed_sources": failed_sources,
        "items": [
            {
                "key": item.candidate.key,
                "group": item.candidate.group.value,
                "source": item.candidate.source.value,
                "reason": item.candidate.reason.value,
                "title": item.candidate.title,
                "url": item.candidate.url,
                "rank": item.rank,
                "in_text": item.in_text,
                "top": item.top,
                "facts": item.candidate.facts,
            }
            for item in items
        ],
    }
