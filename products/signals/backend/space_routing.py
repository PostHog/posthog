"""Routes a report to the space whose CONTEXT.md names what the report is about.

A space's CONTEXT.md carries a `## Watching` section listing the dashboards, insights, flags,
experiments, error issues, and surveys the space owns, one bullet per object with its app URL, and
a `## Goals` section with one `###` heading per goal. When a report surfaces, its evidence (the
signals behind it, the charts it carries, its title and summary) is matched against every public
space's watchlist. A match on an object id is strong; a match on a name is weak. The best space
takes the report through a `channel_assignment` artefact, which is how the space's Context page
and Reports tab already read ownership. A report nobody's context names stays unassigned.

The person or an agent can move it afterwards through the report state API; the router never
overrides an assignment that already exists.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from uuid import UUID

import structlog

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ChannelAssignment
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

ROUTABLE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT})

# Weight of one matched object id against one matched name.
ID_MATCH = 3
NAME_MATCH = 1
# Minimum score for an assignment, and the smaller score that still assigns when no other space
# comes close.
ASSIGN_SCORE = ID_MATCH
CLEAR_LEAD_SCORE = 2 * NAME_MATCH
MIN_NAME_LENGTH = 5

_SECTION_HEADINGS = {
    "watching": "objects",
    "posthog objects": "objects",
    "objects": "objects",
    "goals": "goals",
    "goals and measures": "goals",
}

# Mirrors `OBJECT_PATH_RULES` in the desktop's `contextDocument.ts`.
_OBJECT_PATHS: list[tuple[str, re.Pattern[str]]] = [
    ("insight", re.compile(r"/insights/([^/?#]+)")),
    ("dashboard", re.compile(r"/dashboard/(\d+)")),
    ("flag", re.compile(r"/feature_flags/(\d+)")),
    ("experiment", re.compile(r"/experiments/(\d+)")),
    ("survey", re.compile(r"/surveys/([^/?#]+)")),
    ("error", re.compile(r"/error_tracking/([0-9a-fA-F-]{36})")),
    ("replay", re.compile(r"/replay/([^/?#]+)")),
    ("notebook", re.compile(r"/notebooks/([^/?#]+)")),
    ("cohort", re.compile(r"/cohorts/(\d+)")),
    ("action", re.compile(r"/data-management/actions/(\d+)")),
]

_BULLET = re.compile(r"^\s*[-*]\s+(?:[\w][\w ]*?:\s+)?\[([^\]]*)\]\(([^)\s]+)\)")
_GOAL_HEADING = re.compile(r"^###\s+(.+?)\s*$")
_SECTION = re.compile(r"^##\s+(.+?)\s*$")
_TOP_HEADING = re.compile(r"^#{1,2}\s")


@dataclass(frozen=True)
class WatchedObject:
    kind: str
    id: str
    title: str


@dataclass(frozen=True)
class SpaceWatchlist:
    channel_id: UUID
    objects: list[WatchedObject] = field(default_factory=list)
    goal_names: list[str] = field(default_factory=list)


def parse_watchlist(channel_id: UUID, markdown: str) -> SpaceWatchlist:
    """The objects and goal names a CONTEXT.md asks agents to watch."""
    objects: list[WatchedObject] = []
    goal_names: list[str] = []
    section: str | None = None
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _TOP_HEADING.match(line):
            heading = _SECTION.match(line)
            section = _SECTION_HEADINGS.get(heading.group(1).lower()) if heading else None
            continue
        if section == "objects":
            bullet = _BULLET.match(line)
            if not bullet:
                continue
            title, url = bullet.group(1).strip(), bullet.group(2)
            for kind, pattern in _OBJECT_PATHS:
                found = pattern.search(url)
                if found:
                    objects.append(WatchedObject(kind=kind, id=found.group(1), title=title))
                    break
        elif section == "goals":
            heading = _GOAL_HEADING.match(line)
            if heading:
                goal_names.append(heading.group(1).strip())
    return SpaceWatchlist(channel_id=channel_id, objects=objects, goal_names=goal_names)


def _id_pattern(object_id: str) -> re.Pattern[str]:
    # Short numeric ids match only as whole tokens; a "42" inside "1420" is not the flag.
    return re.compile(rf"(?<![\w-]){re.escape(object_id)}(?![\w-])")


def score_report(
    watchlist: SpaceWatchlist,
    *,
    evidence_text: str,
    prose: str,
) -> int:
    """How strongly a report's evidence and prose point at one space's watchlist."""
    score = 0
    lowered_prose = prose.lower()
    for obj in watchlist.objects:
        if _id_pattern(obj.id).search(evidence_text):
            score += ID_MATCH
        elif len(obj.title) >= MIN_NAME_LENGTH and obj.title.lower() in lowered_prose:
            score += NAME_MATCH
    for name in watchlist.goal_names:
        if len(name) >= MIN_NAME_LENGTH and name.lower() in lowered_prose:
            score += NAME_MATCH
    return score


def choose_space(scores: dict[UUID, int]) -> UUID | None:
    """The one space a report belongs to, or None when nothing is clear enough."""
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return None
    best_id, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if best >= ASSIGN_SCORE and best > second:
        return best_id
    if best >= CLEAR_LEAD_SCORE and second == 0:
        return best_id
    return None


def _load_watchlists(team_id: int) -> list[SpaceWatchlist]:
    watchlists: list[SpaceWatchlist] = []
    for channel in tasks_facade.list_channels(team_id, None):
        instructions = tasks_facade.get_channel_instructions(channel.id, team_id, None)
        if instructions is None or not instructions.content.strip():
            continue
        watchlist = parse_watchlist(channel.id, instructions.content)
        if watchlist.objects or watchlist.goal_names:
            watchlists.append(watchlist)
    return watchlists


def _has_assignment(team_id: int, report_id: str) -> bool:
    return SignalReportArtefact.objects.filter(
        team_id=team_id,
        report_id=report_id,
        type=SignalReportArtefact.ArtefactType.CHANNEL_ASSIGNMENT,
    ).exists()


def _evidence_text(team: Team, report: SignalReport) -> str:
    # Function-local: the ClickHouse reader pulls the query stack, which the startup-import-budget
    # test forbids at django.setup().
    from products.signals.backend.temporal.signal_queries import fetch_signals_for_report_sync  # noqa: PLC0415

    parts: list[str] = [json.dumps(report.charts or [], default=str)]
    try:
        parts.append(json.dumps(fetch_signals_for_report_sync(team, str(report.id)), default=str))
    except Exception:
        logger.warning("space_routing.signals_unavailable", report_id=str(report.id), exc_info=True)
    return "\n".join(parts)


def route_report_to_space(team_id: int, report_id: str) -> UUID | None:
    """Assign a surfaced report to the space whose context names it. Idempotent; never reassigns."""
    with team_scope(team_id):
        if _has_assignment(team_id, report_id):
            return None
        report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
        if report is None or report.status not in ROUTABLE_STATUSES:
            return None
        watchlists = _load_watchlists(team_id)
        if not watchlists:
            return None
        team = Team.objects.get(id=team_id)
        evidence_text = _evidence_text(team, report)
        prose = f"{report.title or ''}\n{report.summary or ''}"
        scores = {
            watchlist.channel_id: score_report(watchlist, evidence_text=evidence_text, prose=prose)
            for watchlist in watchlists
        }
        chosen = choose_space(scores)
        if chosen is None:
            return None
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=report_id,
            content=ChannelAssignment(channel_id=chosen),
            attribution=ArtefactAttribution(kind="system"),
            reevaluate_autostart=False,
        )
        logger.info("space_routing.assigned", report_id=report_id, channel_id=str(chosen), score=scores[chosen])
        return chosen
