from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from uuid import UUID

import yaml
import structlog

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ChannelAssignment
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

ROUTABLE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT})

ID_MATCH = 3
NAME_MATCH = 1
ASSIGN_SCORE = ID_MATCH
CLEAR_LEAD_SCORE = 2 * NAME_MATCH
MIN_NAME_LENGTH = 5

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

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*):")


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
    watched = (_watched_object(entry) for entry in _frontmatter_list(channel_id, markdown, "watching"))
    goals = _frontmatter_list(channel_id, markdown, "goals")
    return SpaceWatchlist(
        channel_id=channel_id,
        objects=[obj for obj in watched if obj is not None],
        goal_names=[str(entry["name"]).strip() for entry in goals if entry.get("name")],
    )


def _watched_object(entry: dict[str, object]) -> WatchedObject | None:
    url = str(entry.get("url", ""))
    for kind, pattern in _OBJECT_PATHS:
        found = pattern.search(url)
        if found:
            return WatchedObject(kind=kind, id=found.group(1), title=str(entry.get("title", "")).strip())
    return None


def _frontmatter_list(channel_id: UUID, markdown: str, key: str) -> list[dict[str, object]]:
    match = _FRONTMATTER.match(markdown)
    if not match:
        return []
    block: list[str] = []
    inside = False
    for line in match.group(1).splitlines():
        key_line = _KEY_LINE.match(line)
        if key_line:
            inside = key_line.group(1) == key
        if inside:
            block.append(line)
    if not block:
        return []
    try:
        data = yaml.safe_load("\n".join(block))
    except yaml.YAMLError:
        logger.warning("space_routing_frontmatter_invalid", channel_id=str(channel_id), key=key)
        return []
    value = data.get(key) if isinstance(data, dict) else None
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _id_pattern(object_id: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-]){re.escape(object_id)}(?![\w-])")


def score_report(
    watchlist: SpaceWatchlist,
    *,
    evidence_text: str,
    prose: str,
) -> int:
    lowered_prose = prose.lower()

    def named(text: str) -> bool:
        return len(text) >= MIN_NAME_LENGTH and text.lower() in lowered_prose

    score = 0
    for watched in watchlist.objects:
        if _id_pattern(watched.id).search(evidence_text):
            score += ID_MATCH
        elif named(watched.title):
            score += NAME_MATCH
    score += NAME_MATCH * sum(1 for name in watchlist.goal_names if named(name))
    return score


def choose_space(scores: dict[UUID, int]) -> UUID | None:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return None
    best_id, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if best_score >= ASSIGN_SCORE and best_score > runner_up:
        return best_id
    if best_score >= CLEAR_LEAD_SCORE and runner_up == 0:
        return best_id
    return None


def _load_watchlists(team_id: int) -> list[SpaceWatchlist]:
    watchlists = (
        parse_watchlist(channel.id, instructions.content)
        for channel in tasks_facade.list_channels(team_id, None)
        if (instructions := tasks_facade.get_channel_instructions(channel.id, team_id, None)) is not None
    )
    return [watchlist for watchlist in watchlists if watchlist.objects or watchlist.goal_names]


def _has_assignment(team_id: int, report_id: str) -> bool:
    return SignalReportArtefact.objects.filter(
        team_id=team_id,
        report_id=report_id,
        type=SignalReportArtefact.ArtefactType.CHANNEL_ASSIGNMENT,
    ).exists()


def _evidence_text(team: Team, report: SignalReport) -> str:
    from products.signals.backend.temporal.signal_queries import fetch_signals_for_report_sync  # noqa: PLC0415

    parts: list[str] = [json.dumps(report.charts or [], default=str)]
    try:
        parts.append(json.dumps(fetch_signals_for_report_sync(team, str(report.id)), default=str))
    except Exception:
        logger.warning("space_routing.signals_unavailable", report_id=str(report.id), exc_info=True)
    return "\n".join(parts)


def route_report_to_space(team_id: int, report_id: str) -> UUID | None:
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
