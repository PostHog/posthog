"""The Origin section of a self-driving pull request.

A self-driving pull request states the problem it fixes, but a reviewer also needs to know where
the work came from: which error, ticket, or scout raised it, and whether a person or the automation
started the run. The backend writes that section itself, below the Problem section, so that the
agent cannot paraphrase it.

Pull requests are often public. So the section carries only allowlisted facts: source types,
entity links that need a PostHog login, dates, a commit hash, and the priority. It never carries
signal content, ticket text, or volumes.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TypeVar

from django.conf import settings

import structlog
from pydantic import BaseModel, ValidationError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_schemas import PriorityAssessment, SignalFinding, TaskRunArtefact
from products.signals.backend.enums import SIGNAL_SOURCE_PRODUCT_LABELS, SignalSourceProduct
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.pull_request_body import BodyEditOutcome, edit_pull_request_body
from products.signals.backend.signal_metadata import (
    OriginSignal,
    fetch_origin_signals_for_report,
    fetch_source_references_for_report,
)

logger = structlog.get_logger(__name__)

ORIGIN_MARKER_PREFIX = "posthog-self-driving-origin"
MAX_LINKS_PER_SOURCE = 5

# Identifiers go into a URL path, so anything outside this set is counted but not linked.
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SOURCE_PRODUCT_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_SCOUT_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_PROBLEM_HEADING_RE = re.compile(r"^##[ \t]+Problem[ \t]*$", re.MULTILINE | re.IGNORECASE)
_ORIGIN_HEADING_RE = re.compile(r"^##[ \t]+Origin[ \t]*$", re.MULTILINE | re.IGNORECASE)
_MARKED_BLOCK_RE = re.compile(rf"<!-- {ORIGIN_MARKER_PREFIX}:\S+ -->.*?<!-- /{ORIGIN_MARKER_PREFIX}:\S+ -->", re.DOTALL)
# A section ends at the next level-two heading, a horizontal rule, or a PostHog Origin block.
_SECTION_END_RE = re.compile(rf"^(##[ \t]|---[ \t]*$|<!-- {ORIGIN_MARKER_PREFIX}:)", re.MULTILINE)

# Linear and GitHub signals come from `fetch_source_references_for_report`, which already
# validates their public links.
_ISSUE_TRACKER_PRODUCTS = frozenset({"linear", "github"})

ArtefactModel = TypeVar("ArtefactModel", bound=BaseModel)


@frozen
class EntityPage:
    link_label: str
    # Path under the project, with `{id}` for the entity.
    path: str


# Sources whose signals point at one entity with its own page in PostHog.
_ENTITY_PAGES: dict[str, EntityPage] = {
    SignalSourceProduct.ERROR_TRACKING: EntityPage(link_label="issue", path="/error_tracking/{id}"),
    SignalSourceProduct.SESSION_REPLAY: EntityPage(link_label="recording", path="/replay/{id}"),
    SignalSourceProduct.CONVERSATIONS: EntityPage(link_label="ticket", path="/support/tickets/{id}"),
    SignalSourceProduct.LLM_ANALYTICS: EntityPage(link_label="trace", path="/ai-observability/traces/{id}"),
}


@frozen
class OriginLink:
    label: str
    url: str

    def render(self) -> str:
        return f"[{self.label}]({self.url})"


@frozen
class OriginSource:
    label: str
    links: tuple[OriginLink, ...]
    count: int

    def render(self) -> str:
        if not self.links:
            noun = "signal" if self.count == 1 else "signals"
            return f"- {self.label}: {self.count} {noun}"
        rendered = ", ".join(link.render() for link in self.links)
        hidden = self.count - len(self.links)
        if hidden > 0:
            rendered = f"{rendered} and {hidden} more"
        return f"- {self.label}: {rendered}"


def _source_label(source_product: str) -> str:
    if source_product in SIGNAL_SOURCE_PRODUCT_LABELS:
        return SIGNAL_SOURCE_PRODUCT_LABELS[SignalSourceProduct(source_product)]
    if _SOURCE_PRODUCT_RE.match(source_product):
        return source_product.replace("_", " ").capitalize()
    return "Other"


def _entity_id(signal: OriginSignal) -> str:
    # A support ticket page resolves the readable ticket number as well as the uuid.
    return str(signal.ticket_number) if signal.ticket_number > 0 else signal.source_id


def _entity_link(team_id: int, signal: OriginSignal, index: int, total: int) -> OriginLink | None:
    page = _ENTITY_PAGES.get(signal.source_product)
    entity_id = _entity_id(signal)
    if page is None or not _SOURCE_ID_RE.match(entity_id):
        return None
    label = page.link_label if total == 1 else f"{page.link_label} {index}"
    path = page.path.format(id=entity_id)
    return OriginLink(label=label, url=f"{settings.SITE_URL}/project/{team_id}{path}")


def _product_sources(team_id: int, signals: list[OriginSignal]) -> list[OriginSource]:
    grouped: dict[str, list[OriginSignal]] = {}
    for signal in signals:
        # A scout signal's source_id names the scout run, not an entity, so the scout line covers it.
        if signal.scout_name or signal.source_product in _ISSUE_TRACKER_PRODUCTS:
            continue
        grouped.setdefault(signal.source_product, []).append(signal)

    sources: list[OriginSource] = []
    for source_product, group in grouped.items():
        unique = list({_entity_id(signal): signal for signal in group}.values())
        links: list[OriginLink] = []
        for index, signal in enumerate(unique[:MAX_LINKS_PER_SOURCE], start=1):
            link = _entity_link(team_id, signal, index, len(unique))
            if link is not None:
                links.append(link)
        sources.append(OriginSource(label=_source_label(source_product), links=tuple(links), count=len(unique)))
    return sources


def _latest_artefact_as(
    team_id: int, report_id: str, artefact_type: str, model: type[ArtefactModel]
) -> ArtefactModel | None:
    artefact = (
        SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type=artefact_type)
        .order_by("-created_at", "-id")
        .first()
    )
    if artefact is None:
        return None
    try:
        return model.model_validate_json(artefact.content)
    except ValidationError:
        return None


def _cause_commit(team_id: int, report_id: str, repository: str) -> OriginLink | None:
    """The first commit of the newest finding, which the research prompt orders causative first."""
    finding = _latest_artefact_as(team_id, report_id, SignalReportArtefact.ArtefactType.SIGNAL_FINDING, SignalFinding)
    if finding is None:
        return None
    for sha in finding.relevant_commit_hashes:
        if _COMMIT_SHA_RE.match(sha):
            return OriginLink(label=f"`{sha[:8]}`", url=f"https://github.com/{repository}/commit/{sha}")
    return None


def _started_automatically(team_id: int, report_id: str, task_id: str) -> bool | None:
    """Whether auto-start opened this run. None when the report has no record of the run."""
    artefacts = SignalReportArtefact.objects.filter(
        team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.TASK_RUN, task_id=task_id
    ).order_by("-created_at", "-id")
    for artefact in artefacts:
        try:
            task_run = TaskRunArtefact.model_validate_json(artefact.content)
        except ValidationError:
            continue
        return task_run.automation_branch is not None
    return None


def _priority(team_id: int, report_id: str) -> str | None:
    judgment = _latest_artefact_as(
        team_id, report_id, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT, PriorityAssessment
    )
    return judgment.priority.value if judgment else None


@frozen
class PullRequestOrigin:
    """Where a self-driving pull request came from, reduced to facts that are safe to publish."""

    report_id: str
    report_url: str
    sources: tuple[OriginSource, ...]
    issue_references: tuple[OriginLink, ...]
    scout_name: str | None
    first_seen: date | None
    cause_commit: OriginLink | None
    started_automatically: bool | None
    priority: str | None

    @classmethod
    def for_report(cls, *, team: Team, report_id: str, task_id: str, repository: str) -> PullRequestOrigin:
        signals = fetch_origin_signals_for_report(team, report_id)
        return cls(
            report_id=report_id,
            report_url=f"{settings.SITE_URL}/project/{team.pk}/inbox/reports/{report_id}",
            sources=tuple(_product_sources(team.pk, signals)),
            issue_references=tuple(
                OriginLink(label=reference.label, url=reference.url)
                for reference in fetch_source_references_for_report(team, report_id)
            ),
            scout_name=next((s.scout_name for s in signals if _SCOUT_NAME_RE.match(s.scout_name)), None),
            first_seen=signals[0].timestamp.date() if signals else None,
            cause_commit=_cause_commit(team.pk, report_id, repository),
            started_automatically=_started_automatically(team.pk, report_id, task_id),
            priority=_priority(team.pk, report_id),
        )

    def _started_line(self) -> str | None:
        if self.started_automatically is None:
            return None
        if not self.started_automatically:
            return "- Started by: a person, from the inbox"
        if self.priority:
            return f"- Started by: auto-start, after the report was rated {self.priority} and ready to fix"
        return "- Started by: auto-start, after the report was rated ready to fix"

    def render(self) -> str:
        lines = [source.render() for source in self.sources]
        if self.issue_references:
            lines.append(f"- Issues: {', '.join(link.render() for link in self.issue_references)}")
        if self.scout_name:
            lines.append(f"- Scout: `{self.scout_name}`")
        if self.first_seen:
            lines.append(f"- First signal: {self.first_seen.isoformat()}")
        lines.append(f"- Inbox report: [open]({self.report_url})")
        if self.cause_commit:
            lines.append(f"- Likely cause: {self.cause_commit.render()}")
        started = self._started_line()
        if started:
            lines.append(started)

        body = "\n".join(lines)
        return (
            f"<!-- {ORIGIN_MARKER_PREFIX}:{self.report_id} -->\n"
            f"## Origin\n\n{body}\n"
            f"<!-- /{ORIGIN_MARKER_PREFIX}:{self.report_id} -->"
        )


def _section_end(body: str, position: int) -> int:
    match = _SECTION_END_RE.search(body, position)
    return match.start() if match else len(body)


def _splice(body: str, start: int, end: int, section: str) -> str:
    before, after = body[:start].rstrip(), body[end:].strip()
    return "\n\n".join(part for part in (before, section, after) if part) + "\n"


def _agent_origin_heading(body: str) -> re.Match[str] | None:
    """The first Origin heading outside a PostHog block, which only an agent can have written."""
    marked = [block.span() for block in _MARKED_BLOCK_RE.finditer(body)]
    for heading in _ORIGIN_HEADING_RE.finditer(body):
        if not any(start <= heading.start() < end for start, end in marked):
            return heading
    return None


def place_origin_section(body: str, *, report_id: str, section: str) -> str:
    """Put the section below the Problem section, replacing an earlier copy for the same report.

    A body without a Problem section, as in a repository with another template, gets it appended.
    """
    start = f"<!-- {ORIGIN_MARKER_PREFIX}:{report_id} -->"
    end = f"<!-- /{ORIGIN_MARKER_PREFIX}:{report_id} -->"
    start_index = body.find(start)
    end_index = body.find(end, start_index)
    if start_index != -1 and end_index != -1:
        return body[:start_index] + section + body[end_index + len(end) :]

    # An agent can write its own Origin section despite the prompt. Replace it rather than add a second one.
    agent_origin = _agent_origin_heading(body)
    if agent_origin is not None:
        return _splice(body, agent_origin.start(), _section_end(body, agent_origin.end()), section)

    problem = _PROBLEM_HEADING_RE.search(body)
    if problem is None:
        return _splice(body, len(body), len(body), section)
    insert_at = _section_end(body, problem.end())
    return _splice(body, insert_at, insert_at, section)


def write_origin_section(*, team_id: int, report_id: str, task_id: str, pr_url: str) -> BodyEditOutcome:
    """Write or refresh the Origin section of a pull request.

    Never raises: a missing section must not stop the tracker cross-link that runs beside it.
    """
    try:
        team = Team.objects.get(pk=team_id)

        def add_origin(body: str, repository: str) -> str:
            origin = PullRequestOrigin.for_report(
                team=team, report_id=report_id, task_id=task_id, repository=repository
            )
            return place_origin_section(body, report_id=report_id, section=origin.render())

        return edit_pull_request_body(
            team_id=team_id, report_id=report_id, pr_url=pr_url, edit=add_origin, log_event="signals.pr_origin"
        )
    except Exception:
        logger.exception("signals.pr_origin_unexpected_error", report_id=report_id, team_id=team_id)
        return BodyEditOutcome.FAILED
