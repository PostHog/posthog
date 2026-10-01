"""Renders the briefing prompt from `prompts/briefing.md.j2`: the items PostHog picked and the person's last briefings."""

import json
from collections.abc import Sequence
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from posthog.models import User

from products.signals.backend.facade import api as signals

from ..models import DailyBriefing
from .content import BriefingContent
from .fact_sheet import FactSheet, stored_fact_sheet

MAX_WORDS = 70
MAX_LINK_WORDS = 8
MAX_LABEL_WORDS = 6
MAX_SIGNAL_CHARS = 40


def _item_rows(reports: Sequence[signals.BriefingReport], fact_sheet: FactSheet) -> list[dict[str, object]]:
    return [
        {
            "key": item.key,
            "reason": item.reason.value,
            "priority": report.priority,
            "status": report.status,
            "source_product": item.source_product,
            "has_implementation_pr": report.has_implementation_pr,
            "title": report.title,
            "summary": report.summary,
        }
        for item, report in zip(fact_sheet.items, reports, strict=True)
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
    fact_sheet: FactSheet,
    previous: Sequence[DailyBriefing],
) -> str:
    """The prompt for one briefing: `reports` in the order of `fact_sheet`, `previous` the person's latest briefings."""
    return _environment.get_template("briefing.md.j2").render(
        first_name=" ".join((user.first_name or "").split())[:40] or "there",
        team_id=briefing.team_id,
        local_day=briefing.local_day.isoformat(),
        max_words=MAX_WORDS,
        max_link_words=MAX_LINK_WORDS,
        max_label_words=MAX_LABEL_WORDS,
        max_signal_chars=MAX_SIGNAL_CHARS,
        items_json=_data_block(_item_rows(reports, fact_sheet)),
        recent_json=_data_block(_recent_rows(previous)),
    )
