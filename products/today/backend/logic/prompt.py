"""Renders the briefing agent's prompt from `prompts/briefing.md.j2` with what PostHog already knows about the person."""

import json
from collections.abc import Sequence
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from posthog.models import User

from products.signals.backend.facade import api as signals

from ..facade.enums import ItemReason
from ..models import DailyBriefing
from .agent_output import MAX_ITEMS
from .checks import MAX_LABEL_WORDS, MAX_LINK_WORDS, MAX_SIGNAL_CHARS, MAX_WORDS
from .content import BriefingContent
from .fact_sheet import stored_fact_sheet

# How many pre-ranked reports the agent gets handed; it chooses from these and from what it finds itself.
PRERANKED_REPORTS = 10

# The relation signals gives a report, as the reason the agent must put on the item.
_REASON_FOR_RELATION = {
    signals.BriefingReportRelation.WAITING_FOR_YOU: ItemReason.WAITING_FOR_YOU,
    signals.BriefingReportRelation.CLAIMED: ItemReason.CLAIMED_BY_YOU,
    signals.BriefingReportRelation.SUGGESTED_REVIEWER: ItemReason.SUGGESTED_REVIEWER,
    signals.BriefingReportRelation.URGENT_UNOWNED: ItemReason.URGENT_FOR_PROJECT,
}


def _report_rows(reports: Sequence[signals.BriefingReport], team_id: int) -> list[dict[str, object]]:
    return [
        {
            "key": f"report:{report.report_id}",
            "reason": _REASON_FOR_RELATION[report.relation].value,
            "priority": report.priority,
            "status": report.status,
            "source_product": report.source_products[0] if report.source_products else None,
            "has_implementation_pr": report.has_implementation_pr,
            "title": report.title,
            "summary": report.summary,
            "url": f"/project/{team_id}/inbox/{report.report_id}",
        }
        for report in reports
    ]


def _recent_rows(briefings: Sequence[DailyBriefing]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for previous in briefings:
        fact_sheet = stored_fact_sheet(previous)
        content = BriefingContent.model_validate(previous.content or {})
        rows.append(
            {
                "local_day": previous.local_day.isoformat(),
                "viewed": previous.last_viewed_at is not None,
                "headline": content.headline,
                "items": [
                    {
                        "key": item.key,
                        "label": content.labels.get(item.key, item.title),
                        "signal": content.signals.get(item.key, ""),
                    }
                    for item in (fact_sheet.items if fact_sheet else [])
                ],
            }
        )
    return rows


_TEMPLATE_DIR = Path(__file__).parent / "prompts"
_environment = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    undefined=StrictUndefined,
    autoescape=select_autoescape(),
    keep_trailing_newline=True,
)


def _data_block(rows: object) -> str:
    """JSON for the prompt. Angle brackets are escaped so a report title cannot close the data tag around it."""
    return json.dumps(rows, ensure_ascii=False, indent=2).replace("<", "\\u003c").replace(">", "\\u003e")


def build_prompt(
    briefing: DailyBriefing,
    user: User,
    reports: Sequence[signals.BriefingReport],
    previous: Sequence[DailyBriefing],
) -> str:
    """The prompt for one briefing: `reports` already in briefing order, `previous` the person's latest ones."""
    return _environment.get_template("briefing.md.j2").render(
        first_name=" ".join((user.first_name or "").split())[:40] or "there",
        team_id=briefing.team_id,
        local_day=briefing.local_day.isoformat(),
        max_items=MAX_ITEMS,
        max_words=MAX_WORDS,
        max_link_words=MAX_LINK_WORDS,
        max_label_words=MAX_LABEL_WORDS,
        max_signal_chars=MAX_SIGNAL_CHARS,
        reports_json=_data_block(_report_rows(reports, briefing.team_id)),
        recent_json=_data_block(_recent_rows(previous)),
    )
