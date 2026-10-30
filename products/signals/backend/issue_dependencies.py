"""Turn the dependency lines of GitHub issues into `depends_on` report links.

The GitHub issues emitter stores the issues a body names on "Depends on" and "Blocked by" lines as
`depends_on_issues` on the signal. Before auto-start decides, `resolve_issue_dependencies` maps each
of them to the report that holds that issue and writes the link, so the existing link gate holds the
report until the dependency has a pull request.

The dependency issue can be filed in the same minute as the dependent, so its report may not exist
yet. Such a ref holds auto-start too. When the dependency's report settles later,
`reports_waiting_on_issues_of` finds the reports that wait on it, so they can be evaluated again.
"""

import re
import json
from collections.abc import Collection
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    AutostartSkip,
    NoteArtefact,
    ReportLink,
)
from products.signals.backend.enums import ReportLinkKind, ReportLinkWritePath
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.signal_metadata import EMBEDDING_MODEL, _deduped_signals_subquery, _signals_query_context
from products.signals.backend.typed_report_links import (
    ReportEdge,
    duplicate_root,
    has_open_or_merged_pull_request,
    outgoing_links,
)

logger = structlog.get_logger(__name__)

LINK_REASON_PREFIX = "Depends on GitHub issue "
UNRESOLVED_DETAIL_PREFIX = "No work started here because no report holds GitHub issue "
# A held report is evaluated again only while its hold is this recent. Older holds stay held until
# their own report is researched again or a person presses Implement.
WAITING_LOOKBACK = timedelta(days=30)
_ROW_CAP = 500
_UNUSABLE_STATUSES = (SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED, SignalReport.Status.FAILED)


@frozen
class IssueRef:
    repository: str
    number: int

    @property
    def label(self) -> str:
        return f"{self.repository}#{self.number}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repository}/issues/{self.number}"

    @classmethod
    def from_url(cls, url: str) -> "IssueRef | None":
        parsed = GitHubIntegrationBase.parse_issue_url(url)
        if parsed is None:
            return None
        return cls(repository=f"{parsed.owner}/{parsed.repo}".lower(), number=parsed.number)


@frozen
class ReportIssue:
    """One GitHub issue of a report, read from the newest signal of that issue."""

    ref: IssueRef
    depends_on: tuple[IssueRef, ...]


@frozen
class IssueMatch:
    report_ids: tuple[str, ...]
    closed: bool


def _parse_refs(raw: object) -> tuple[IssueRef, ...]:
    if not isinstance(raw, list):
        return ()
    refs: list[IssueRef] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        repository, number = item.get("repository"), item.get("number")
        if isinstance(repository, str) and isinstance(number, int):
            refs.append(IssueRef(repository=repository.lower(), number=number))
    return tuple(refs)


def report_issues(team: Team, report_id: str, *, ch_user: ClickHouseUser) -> list[ReportIssue]:
    """The GitHub issues whose signals sit in this report, each with its current dependency refs."""
    query = f"""
        SELECT metadata
        FROM ({_deduped_signals_subquery(include_content=False, candidate_document_filter="JSONExtractString(metadata, 'report_id') = {report_id}")})
        WHERE JSONExtractString(metadata, 'report_id') = {{report_id}}
          AND NOT JSONExtractBool(metadata, 'deleted')
          AND JSONExtractString(metadata, 'source_product') = 'github'
          AND JSONExtractString(metadata, 'source_type') = 'issue'
        ORDER BY timestamp DESC
        LIMIT {{row_cap}}
    """
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        ch_user=ch_user,
        query_type="SignalsFetchReportGithubIssues",
        query=query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "report_id": ast.Constant(value=report_id),
            "row_cap": ast.Constant(value=_ROW_CAP),
        },
        context=_signals_query_context(team),
    )
    issues: list[ReportIssue] = []
    seen_sources: set[str] = set()
    for (metadata_str,) in result.results or []:
        metadata = json.loads(metadata_str)
        # An edited issue emits a new signal, so only the newest one says what the body lists now.
        source_id = metadata.get("source_id")
        if source_id in seen_sources:
            continue
        seen_sources.add(source_id)
        extra = metadata.get("extra") or {}
        ref = IssueRef.from_url(extra.get("html_url") or "")
        if ref is not None:
            issues.append(ReportIssue(ref=ref, depends_on=_parse_refs(extra.get("depends_on_issues"))))
    return issues


def _issue_matches(team: Team, refs: Collection[IssueRef], *, ch_user: ClickHouseUser) -> dict[IssueRef, IssueMatch]:
    """For each ref, the reports that hold a signal of that issue, newest first, and its last state."""
    urls = {ref.url: ref for ref in refs}
    url_filter = (
        "JSONExtractString(metadata, 'source_product') = 'github' "
        "AND JSONExtractString(metadata, 'source_type') = 'issue' "
        "AND lower(JSONExtractString(metadata, 'extra', 'html_url')) IN {issue_urls}"
    )
    query = f"""
        SELECT
            lower(JSONExtractString(metadata, 'extra', 'html_url')),
            JSONExtractString(metadata, 'report_id'),
            JSONExtractString(metadata, 'extra', 'state')
        FROM ({_deduped_signals_subquery(include_content=False, candidate_document_filter=url_filter)})
        WHERE NOT JSONExtractBool(metadata, 'deleted')
          AND {url_filter}
        ORDER BY timestamp DESC
        LIMIT {{row_cap}}
    """
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        ch_user=ch_user,
        query_type="SignalsFetchReportsForGithubIssues",
        query=query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "issue_urls": ast.Tuple(exprs=[ast.Constant(value=url) for url in urls]),
            "row_cap": ast.Constant(value=_ROW_CAP),
        },
        context=_signals_query_context(team),
    )
    report_ids: dict[IssueRef, list[str]] = {}
    closed: dict[IssueRef, bool] = {}
    for url, report_id, state in result.results or []:
        ref = urls.get(url)
        if ref is None:
            continue
        # Rows arrive newest first, so the first row of an issue carries its current state.
        closed.setdefault(ref, state == "closed")
        if report_id and report_id not in report_ids.setdefault(ref, []):
            report_ids[ref].append(report_id)
    return {
        ref: IssueMatch(report_ids=tuple(report_ids.get(ref, ())), closed=closed[ref])
        for ref in urls.values()
        if ref in closed
    }


def _pick_target(*, team_id: int, report_id: str, candidate_ids: Collection[str]) -> str | None:
    """The report a dependency points at: the canonical report, one with a pull request first, then the oldest."""
    canonical_ids = list(dict.fromkeys(duplicate_root(team_id=team_id, report_id=rid) for rid in candidate_ids))
    rows = list(
        SignalReport.objects.using("default")
        .filter(team_id=team_id, id__in=canonical_ids)
        .exclude(status__in=_UNUSABLE_STATUSES)
        .exclude(id=report_id)
        .values_list("id", "created_at")
    )
    if not rows:
        return None
    with_work = has_open_or_merged_pull_request(team_id=team_id, report_ids=[str(rid) for rid, _ in rows])
    rows.sort(key=lambda row: (str(row[0]) not in with_work, row[1]))
    return str(rows[0][0])


def resolve_issue_dependencies(
    *, team_id: int, report_id: str, ch_user: ClickHouseUser = ClickHouseUser.DEFAULT
) -> tuple[IssueRef, ...]:
    """Write a `depends_on` link for each dependency ref of the report's GitHub issues.

    Returns the refs that hold auto-start without a link: no usable report holds the issue yet. A
    closed dependency issue counts as met and gets no link. A ref that the issue no longer lists
    keeps its link, and the report's work log gets a note about it.
    """
    team = Team.objects.get(pk=team_id)
    issues = report_issues(team, report_id, ch_user=ch_user)
    if not issues:
        return ()
    own_refs = {issue.ref for issue in issues}
    refs = list(dict.fromkeys(ref for issue in issues for ref in issue.depends_on if ref not in own_refs))
    existing = outgoing_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.DEPENDS_ON,))
    _note_removed_refs(team_id=team_id, report_id=report_id, existing=existing, refs=refs)
    if not refs:
        return ()

    linked_ids = {edge.target_id for edge in existing}
    matches = _issue_matches(team, refs, ch_user=ch_user)
    unresolved: list[IssueRef] = []
    for ref in refs:
        match = matches.get(ref)
        if match is not None and match.closed:
            continue
        target_id = (
            _pick_target(team_id=team_id, report_id=report_id, candidate_ids=match.report_ids) if match else None
        )
        if target_id is None:
            unresolved.append(ref)
            continue
        if target_id in linked_ids:
            continue
        try:
            SignalReportArtefact.add_log(
                team_id=team_id,
                report_id=report_id,
                content=ReportLink(
                    kind=ReportLinkKind.DEPENDS_ON, report_id=target_id, reason=f"{LINK_REASON_PREFIX}{ref.label}."
                ),
                attribution=ArtefactAttribution.system(),
                write_path=ReportLinkWritePath.PIPELINE,
            )
        except ArtefactContentValidationError:
            # The target already depends on this report. A person linked it the other way, and an
            # inferred link must not hold either report forever.
            logger.warning(
                "signals.issue_dependencies.link_rejected", team_id=team_id, report_id=report_id, target_id=target_id
            )
            continue
        linked_ids.add(target_id)
    return tuple(unresolved)


def _note_removed_refs(
    *, team_id: int, report_id: str, existing: Collection[ReportEdge], refs: Collection[IssueRef]
) -> None:
    labels = {ref.label for ref in refs}
    for edge in existing:
        reason = edge.reason or ""
        if not reason.startswith(LINK_REASON_PREFIX):
            continue
        label = reason.removeprefix(LINK_REASON_PREFIX).rstrip(".")
        if label in labels:
            continue
        note = (
            f"The GitHub issue no longer lists {label} as a dependency. "
            f"The `depends_on` link to report {edge.target_id} stays in place."
        )
        already_noted = SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.NOTE,
            content__contains=json.dumps(note)[1:-1],
        ).exists()
        if not already_noted:
            SignalReportArtefact.add_log(
                team_id=team_id,
                report_id=report_id,
                content=NoteArtefact(note=note, author="Signals pipeline"),
                attribution=ArtefactAttribution.system(),
            )


def unresolved_dependency_skip(refs: Collection[IssueRef]) -> AutostartSkip:
    labels = [ref.label for ref in refs]
    shown = ", ".join(labels[:5]) + (f" and {len(labels) - 5} more" if len(labels) > 5 else "")
    return AutostartSkip(
        skip_reason="blocked_by_dependency",
        detail=f"{UNRESOLVED_DETAIL_PREFIX}{shown} yet. Work starts after that issue has a report with a pull request.",
    )


def reports_waiting_on_issues_of(
    *, team_id: int, report_id: str, ch_user: ClickHouseUser = ClickHouseUser.DEFAULT
) -> list[str]:
    """The reports whose recent auto-start hold names a GitHub issue that this report holds."""
    holds = SignalReportArtefact.objects.using("default").filter(
        team_id=team_id,
        type=SignalReportArtefact.ArtefactType.AUTOSTART_SKIP,
        created_at__gte=timezone.now() - WAITING_LOOKBACK,
        content__contains=UNRESOLVED_DETAIL_PREFIX,
    )
    if not holds.exists():
        return []
    issues = report_issues(Team.objects.get(pk=team_id), report_id, ch_user=ch_user)
    if not issues:
        return []
    # The digit guard stops `owner/repo#12` from matching a hold on `owner/repo#123`.
    label_filter = Q()
    for issue in issues:
        label_filter |= Q(content__iregex=rf"{re.escape(issue.ref.label)}([^0-9]|$)")
    waiting = holds.filter(label_filter).exclude(report_id=report_id).values_list("report_id", flat=True)
    return list(dict.fromkeys(str(rid) for rid in waiting))
