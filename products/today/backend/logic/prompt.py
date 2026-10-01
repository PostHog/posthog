"""Renders the briefing agent's prompt from `prompts/briefing.md.j2` with what PostHog already knows about the person."""

import json
from collections.abc import Sequence
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from posthog.models import User

from products.signals.backend.facade import api as signals

from ..facade.enums import BriefingStatus
from ..models import DailyBriefing
from .content import BriefingContent
from .fact_sheet import stored_fact_sheet

# How many pre-ranked reports the agent gets handed; it chooses from these and from what it finds itself.
PRERANKED_REPORTS = 10
# How many of the person's previous briefings the agent sees, so it does not repeat itself.
RECENT_BRIEFINGS = 3

_RELATION_ORDER = {
    signals.BriefingReportRelation.WAITING_FOR_YOU: 0,
    signals.BriefingReportRelation.CLAIMED: 1,
    signals.BriefingReportRelation.SUGGESTED_REVIEWER: 2,
    signals.BriefingReportRelation.URGENT_UNOWNED: 3,
}
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


def rank_reports(reports: Sequence[signals.BriefingReport]) -> list[signals.BriefingReport]:
    """The reports in the order the agent should prefer them: what waits for the person, then what
    they claimed, then what names them, then unowned urgencies; inside that, P0, the better chance
    of a merged PR, priority, newest."""

    def key(report: signals.BriefingReport) -> tuple[float, ...]:
        chance = report.pr_merged_probability
        return (
            _RELATION_ORDER[report.relation],
            0 if report.priority == "P0" else 1,
            0 if chance is not None else 1,
            -(chance or 0.0),
            _PRIORITY_ORDER.get(report.priority or "", 5),
            -report.updated_at.timestamp(),
        )

    return sorted(reports, key=key)[:PRERANKED_REPORTS]


def _report_rows(reports: Sequence[signals.BriefingReport], team_id: int) -> list[dict[str, object]]:
    return [
        {
            "key": f"report:{report.report_id}",
            "relation": report.relation.value,
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


def recent_briefings(briefing: DailyBriefing) -> list[DailyBriefing]:
    """The person's latest ready briefings before this one, newest first."""
    return list(
        DailyBriefing.objects.for_team(briefing.team_id)
        .filter(user_id=briefing.user_id, status=BriefingStatus.READY, created_at__lt=briefing.created_at)
        .order_by("-created_at")[:RECENT_BRIEFINGS]
    )


def _recent_rows(briefings: Sequence[DailyBriefing]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for previous in briefings:
        fact_sheet = stored_fact_sheet(previous)
        content = BriefingContent.model_validate(previous.content or {})
        rows.append(
            {
                "local_day": previous.local_day.isoformat(),
                "edition": previous.edition,
                "headline": content.headline,
                "items": [
                    {
                        "key": item.key,
                        "label": content.labels.get(item.key, item.title),
                        "signal": content.signals.get(item.key, ""),
                    }
                    for item in (fact_sheet.text_items if fact_sheet else [])
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


def build_prompt(
    briefing: DailyBriefing,
    user: User,
    reports: Sequence[signals.BriefingReport],
    previous: Sequence[DailyBriefing] = (),
) -> str:
    return _environment.get_template("briefing.md.j2").render(
        first_name=user.first_name or "there",
        team_id=briefing.team_id,
        local_day=briefing.local_day.isoformat(),
        edition=briefing.edition,
        briefing_id=str(briefing.id),
        reports_json=json.dumps(_report_rows(rank_reports(reports), briefing.team_id), ensure_ascii=False, indent=2),
        recent_json=json.dumps(_recent_rows(previous), ensure_ascii=False, indent=2),
    )
