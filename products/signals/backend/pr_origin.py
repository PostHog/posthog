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
from bisect import bisect_right
from datetime import date, datetime
from typing import TypeVar

from django.conf import settings

import structlog
from pydantic import BaseModel, ValidationError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_schemas import (
    PriorityAssessment,
    SignalFinding,
    SuggestedReviewers,
    TaskRunArtefact,
)
from products.signals.backend.enums import SIGNAL_SOURCE_PRODUCT_LABELS, SignalSourceProduct
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.pull_request_body import BodyEditOutcome, edit_pull_request_body
from products.signals.backend.scout_harness.lazy_seed import canonical_skill_names
from products.signals.backend.signal_metadata import (
    OriginSource,
    SignalSourceReference,
    fetch_origin_sources_for_report,
    fetch_source_references_for_report,
)
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

ORIGIN_MARKER_PREFIX = "posthog-self-driving-origin"
MAX_LINKS_PER_SOURCE = 5

# Identifiers go into a URL path, so a signal with any other id keeps its source type but gets no link.
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SOURCE_PRODUCT_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_PROBLEM_HEADING_RE = re.compile(r"^##[ \t]+Problem[ \t]*$", re.MULTILINE | re.IGNORECASE)
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


_ENTITY_PAGES: dict[str, EntityPage] = {
    SignalSourceProduct.ERROR_TRACKING: EntityPage(link_label="issue", path="/error_tracking/{id}"),
    SignalSourceProduct.SESSION_REPLAY: EntityPage(link_label="recording", path="/replay/{id}"),
    SignalSourceProduct.CONVERSATIONS: EntityPage(link_label="ticket", path="/support/tickets/{id}"),
}


@frozen
class OriginLink:
    label: str
    # None when only the label is safe to publish.
    url: str | None

    def render(self) -> str:
        return f"[{self.label}]({self.url})" if self.url else self.label


@frozen
class OriginSourceLine:
    label: str
    links: tuple[OriginLink, ...]
    has_more: bool

    def render(self) -> str:
        # Counts stay out, because the number of private recordings or tickets is itself private.
        if not self.links:
            return f"- {self.label}"
        rendered = ", ".join(link.render() for link in self.links)
        if self.has_more:
            rendered = f"{rendered} and more"
        return f"- {self.label}: {rendered}"


def _source_label(source_product: str) -> str:
    if source_product in SIGNAL_SOURCE_PRODUCT_LABELS:
        return SIGNAL_SOURCE_PRODUCT_LABELS[SignalSourceProduct(source_product)]
    if _SOURCE_PRODUCT_RE.match(source_product):
        return source_product.replace("_", " ").capitalize()
    return "Other"


def _entity_link(team_id: int, source_product: str, entity_id: str, index: int, total: int) -> OriginLink | None:
    page = _ENTITY_PAGES.get(source_product)
    if page is None or not _SOURCE_ID_RE.match(entity_id):
        return None
    label = page.link_label if total == 1 else f"{page.link_label} {index}"
    path = page.path.format(id=entity_id)
    return OriginLink(label=label, url=f"{settings.SITE_URL}/project/{team_id}{path}")


def _source_lines(team_id: int, sources: list[OriginSource]) -> list[OriginSourceLine]:
    lines: list[OriginSourceLine] = []
    for source in sources:
        # A scout signal's source_id names the scout run, not an entity, so the scout line covers it.
        if source.scout_name or source.source_product in _ISSUE_TRACKER_PRODUCTS:
            continue
        shown = source.entity_ids[:MAX_LINKS_PER_SOURCE]
        links: list[OriginLink] = []
        for index, entity_id in enumerate(shown, start=1):
            link = _entity_link(team_id, source.source_product, entity_id, index, len(source.entity_ids))
            if link is not None:
                links.append(link)
        lines.append(
            OriginSourceLine(
                label=_source_label(source.source_product),
                links=tuple(links),
                has_more=len(source.entity_ids) > len(shown),
            )
        )
    return lines


def _latest_artefact_as(
    team_id: int,
    report_id: str,
    artefact_type: str,
    model: type[ArtefactModel],
    created_before: datetime | None = None,
) -> ArtefactModel | None:
    artefacts = SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type=artefact_type)
    if created_before is not None:
        artefacts = artefacts.filter(created_at__lte=created_before)
    artefact = artefacts.order_by("-created_at", "-id").first()
    if artefact is None:
        return None
    try:
        return model.model_validate_json(artefact.content)
    except ValidationError:
        return None


def _cause_commit(team_id: int, report_id: str, repository: str) -> OriginLink | None:
    """The first commit of the newest finding, which the research prompt orders causative first.

    A finding stores a short hash with no repository, so research into another repository could
    produce a hash that does not exist here. The commit links only when the suggested reviewers
    carry the same commit under this pull request's repository.
    """
    finding = _latest_artefact_as(team_id, report_id, SignalReportArtefact.ArtefactType.SIGNAL_FINDING, SignalFinding)
    reviewers = _latest_artefact_as(
        team_id, report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS, SuggestedReviewers
    )
    if finding is None or reviewers is None:
        return None
    commit_prefix = f"https://github.com/{repository}/commit/".lower()
    # The stored URL is only evidence. The link is rebuilt from a validated hash, so no stored text reaches the body.
    known_shas = [
        full_sha
        for reviewer in reviewers.root
        for commit in reviewer.relevant_commits
        if commit.url.lower().startswith(commit_prefix)
        and _COMMIT_SHA_RE.match(full_sha := commit.url.lower().removeprefix(commit_prefix))
    ]
    for sha in finding.relevant_commit_hashes:
        if not _COMMIT_SHA_RE.match(sha):
            continue
        for full_sha in known_shas:
            if full_sha.startswith(sha.lower()):
                return OriginLink(label=f"`{sha[:8]}`", url=f"https://github.com/{repository}/commit/{full_sha}")
    return None


@frozen
class RunStart:
    automatic: bool
    # The priority when the run started. A later judgment did not trigger this run.
    priority: str | None


def _run_start(team_id: int, report_id: str, task_id: str) -> RunStart | None:
    """How this run started. None when the report has no record of the run."""
    artefacts = SignalReportArtefact.objects.filter(
        team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.TASK_RUN, task_id=task_id
    ).order_by("-created_at", "-id")
    for artefact in artefacts:
        try:
            task_run = TaskRunArtefact.model_validate_json(artefact.content)
        except ValidationError:
            continue
        judgment = _latest_artefact_as(
            team_id,
            report_id,
            SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            PriorityAssessment,
            created_before=artefact.created_at,
        )
        return RunStart(
            automatic=task_run.automation_branch is not None,
            priority=judgment.priority.value if judgment else None,
        )
    return None


def _scout_label(sources: list[OriginSource]) -> str | None:
    """Name a scout only when it ships with PostHog. A custom scout's name comes from its creator and can be private."""
    scout_name = next((source.scout_name for source in sources if source.scout_name), None)
    if scout_name is None:
        return None
    return f"`{scout_name}`" if scout_name in canonical_skill_names() else "a custom scout"


def _issue_link(reference: SignalSourceReference, repository: str) -> OriginLink:
    """Link an issue only when it is as public as the pull request itself.

    An issue in another repository or in Linear can be private, and its URL alone can name the
    workspace or the title, so those keep a plain label.
    """
    same_repository = f"https://github.com/{repository}/issues/".lower()
    if reference.source_product == "github":
        if reference.url.lower().startswith(same_repository):
            return OriginLink(label=reference.label, url=reference.url)
        # A bare "#42" would render as a link to issue 42 of this pull request's repository.
        return OriginLink(label="GitHub issue", url=None)
    # A Linear identifier names a private team key and a sequential issue number.
    return OriginLink(label="Linear issue", url=None)


@frozen
class PullRequestOrigin:
    """Where a self-driving pull request came from, reduced to facts that are safe to publish."""

    report_id: str
    report_url: str
    sources: tuple[OriginSourceLine, ...]
    issue_references: tuple[OriginLink, ...]
    scout_label: str | None
    first_seen: date | None
    cause_commit: OriginLink | None
    run_start: RunStart | None

    @classmethod
    def for_report(cls, *, team: Team, report_id: str, task_id: str, repository: str) -> PullRequestOrigin:
        sources = fetch_origin_sources_for_report(team, report_id)
        return cls(
            report_id=report_id,
            report_url=f"{settings.SITE_URL}/project/{team.pk}/inbox/reports/{report_id}",
            sources=tuple(_source_lines(team.pk, sources)),
            issue_references=tuple(
                _issue_link(reference, repository) for reference in fetch_source_references_for_report(team, report_id)
            ),
            scout_label=_scout_label(sources),
            first_seen=min(source.first_seen for source in sources).date() if sources else None,
            cause_commit=_cause_commit(team.pk, report_id, repository),
            run_start=_run_start(team.pk, report_id, task_id),
        )

    def _started_line(self) -> str | None:
        if self.run_start is None:
            return None
        if not self.run_start.automatic:
            return "- Task started by: a person, from the inbox"
        if self.run_start.priority:
            return (
                f"- Task started by: auto-start, after the report was rated {self.run_start.priority} and ready to fix"
            )
        return "- Task started by: auto-start, after the report was rated ready to fix"

    def render(self) -> str:
        lines = [source.render() for source in self.sources]
        if self.issue_references:
            lines.append(f"- Issues: {', '.join(link.render() for link in self.issue_references)}")
        if self.scout_label:
            lines.append(f"- Scout: {self.scout_label}")
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


@frozen
class TextSpan:
    start: int
    end: int


def _fenced_spans(body: str) -> list[TextSpan]:
    """Find fenced code blocks in one pass, because a heading or rule inside one is code, not structure.

    Follows the CommonMark fence rules: up to three spaces of indent, a closing fence at least as
    long as the opener, and an unclosed fence that runs to the end of the body.
    """
    spans: list[TextSpan] = []
    offset = 0
    fence_char = ""
    fence_length = 0
    fence_start = 0
    for line in body.splitlines(keepends=True):
        text = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent <= 3 and text[:3] in ("```", "~~~"):
            char = text[0]
            run = len(text) - len(text.lstrip(char))
            if not fence_char:
                fence_char, fence_length, fence_start = char, run, offset
            elif char == fence_char and run >= fence_length and not text.strip(char):
                spans.append(TextSpan(start=fence_start, end=offset + len(line)))
                fence_char = ""
        offset += len(line)
    if fence_char:
        spans.append(TextSpan(start=fence_start, end=len(body)))
    return spans


def _first_outside(pattern: re.Pattern[str], body: str, position: int, fenced: list[TextSpan]) -> re.Match[str] | None:
    # The spans are sorted and do not overlap, so a binary search finds the only span that can hold a match.
    starts = [span.start for span in fenced]
    for match in pattern.finditer(body, position):
        index = bisect_right(starts, match.start()) - 1
        if index < 0 or match.start() >= fenced[index].end:
            return match
    return None


def _splice(body: str, position: int, section: str) -> str:
    before, after = body[:position].rstrip(), body[position:].strip()
    return "\n\n".join(part for part in (before, section, after) if part) + "\n"


def place_origin_section(body: str, *, report_id: str, section: str) -> str:
    """Put the section below the Problem section, replacing an earlier copy for the same report.

    Only a block inside this report's markers is ever replaced. An unmarked Origin section can be
    part of the repository's own template, so it stays. A body without a Problem section, as in a
    repository with another template, gets the section appended.
    """
    start = f"<!-- {ORIGIN_MARKER_PREFIX}:{report_id} -->"
    end = f"<!-- /{ORIGIN_MARKER_PREFIX}:{report_id} -->"
    start_index = body.find(start)
    end_index = body.find(end, start_index)
    if start_index != -1 and end_index != -1:
        return body[:start_index] + section + body[end_index + len(end) :]

    fenced = _fenced_spans(body)
    problem = _first_outside(_PROBLEM_HEADING_RE, body, 0, fenced)
    if problem is None:
        return _splice(body, len(body), section)
    section_end = _first_outside(_SECTION_END_RE, body, problem.end(), fenced)
    return _splice(body, section_end.start() if section_end else len(body), section)


def write_origin_section(*, team_id: int, report_id: str, task_id: str, pr_url: str) -> BodyEditOutcome:
    """Write or refresh the Origin section of a pull request.

    Never raises: a missing section must not stop the tracker cross-link that runs beside it.
    """
    try:
        # Anyone who controls the task can write a run's pr_url, so only a webhook-confirmed PR gets edited.
        # The webhook usually lands after the agent reports the URL, so this is a retry, not a skip.
        if not tasks_facade.is_verified_task_pr_url(task_id=task_id, team_id=team_id, pr_url=pr_url):
            logger.info("signals.pr_origin_unverified_pr", report_id=report_id, pr_url=pr_url)
            return BodyEditOutcome.FAILED
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
