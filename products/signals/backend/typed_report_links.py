"""The read side of the typed, directed links between inbox reports.

A `report_link` artefact is one row on the report the sentence starts from: "this report `kind`
that report". The write path and its invariants (no self-link, same team, no cycle within a kind)
live on `SignalReportArtefact`. Every reader goes through this module instead of parsing the rows
itself, so the tolerance for a row that no longer parses, the graph budgets, and the direction
vocabulary are decided once.

Reading outgoing edges is a seek on `(report, type)`. Reading incoming edges is a team-scoped scan,
because `content` is a `TextField` and nothing mirrors the row onto the target: the candidate rows
are narrowed with a `content__contains` on the target's UUID and then confirmed by parsing. Links
are rare and team-scoped, so the scan is cheap. If it ever shows up in query timings, the fix is a
materialised target column or a JSON index, not a mirror row, because the direction is the payload.
"""

import uuid
from collections.abc import Collection

import structlog
import posthoganalytics
from pydantic import ValidationError

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.artefact_schemas import ReportLink
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest

logger = structlog.get_logger(__name__)


@frozen
class ReportEdge:
    """One stored link, read the same way from either end: "`source_id` `kind` `target_id`"."""

    source_id: str
    kind: ReportLinkKind
    target_id: str
    reason: str | None = None


def _canonical_report_id(report_id: str | uuid.UUID) -> str | None:
    """The lowercase, canonical form a stored link holds, or None when the id is not a UUID.

    `ReportLink` canonicalizes `report_id` on write, so a caller that addressed the report with an
    uppercase or braced UUID would otherwise match no row at all in the incoming scan.
    """
    try:
        return str(uuid.UUID(str(report_id)))
    except (ValueError, AttributeError, TypeError):
        return None


def _edges_from_rows(
    rows: Collection[tuple[uuid.UUID, str]], *, kinds: Collection[ReportLinkKind] | None
) -> list[ReportEdge]:
    edges: list[ReportEdge] = []
    for source_id, content in rows:
        try:
            link = ReportLink.model_validate_json(content)
        except ValidationError:
            # A row that no longer parses names no edge. Every other read of the artefact log is
            # tolerant of legacy content the same way.
            continue
        if kinds is not None and link.kind not in kinds:
            continue
        edges.append(ReportEdge(source_id=str(source_id), kind=link.kind, target_id=link.report_id, reason=link.reason))
    return edges


def outgoing_links(
    *, team_id: int, report_id: str | uuid.UUID, kinds: Collection[ReportLinkKind] | None = None
) -> list[ReportEdge]:
    """The links written on this report, oldest first: what this report says about others."""
    source_id = _canonical_report_id(report_id)
    if source_id is None:
        return []
    rows = (
        SignalReportArtefact.objects.using("default")
        .filter(team_id=team_id, report_id=source_id, type=SignalReportArtefact.ArtefactType.REPORT_LINK)
        .order_by("created_at", "id")
        .values_list("report_id", "content")[: SignalReportArtefact.MAX_REPORT_LINK_GRAPH_ROWS]
    )
    return _edges_from_rows(list(rows), kinds=kinds)


def incoming_links(
    *,
    team_id: int,
    report_id: str | uuid.UUID,
    kinds: Collection[ReportLinkKind] | None = None,
    include_deleted_sources: bool = False,
) -> list[ReportEdge]:
    """The links other reports wrote about this one, oldest first.

    Deleted source reports are dropped by default: a report a reviewer removed makes no claim a
    reader should act on. The recurrence chain is the exception, because it walks *through* deleted
    intermediates to find the live successor.
    """
    target_id = _canonical_report_id(report_id)
    if target_id is None:
        return []
    candidates = SignalReportArtefact.objects.using("default").filter(
        team_id=team_id,
        type=SignalReportArtefact.ArtefactType.REPORT_LINK,
        content__contains=target_id,
    )
    if not include_deleted_sources:
        candidates = candidates.exclude(report__status=SignalReport.Status.DELETED)
    rows = list(
        candidates.order_by("created_at", "id").values_list("report_id", "content")[
            : SignalReportArtefact.MAX_REPORT_LINK_GRAPH_ROWS
        ]
    )
    # `content__contains` also matches a row whose free-text `reason` quotes the UUID, so the
    # parsed target decides.
    return [edge for edge in _edges_from_rows(rows, kinds=kinds) if edge.target_id == target_id]


def duplicate_chain(*, team_id: int, report_id: str | uuid.UUID) -> list[str]:
    """The reports this one duplicates, nearest first, ending at the one that duplicates nothing.

    The whole chain is the answer, not only its last member: a pull request stays on the report
    whose run opened it, so in A -> B -> C the work can sit on B while C carries none. A reader
    asking "is this already being done?" has to see every member.

    The write path rejects a `duplicate_of` cycle, but the visited set and the level budget stand
    anyway: a reader must never loop on a graph a concurrent write left in a shape it did not
    expect. Exhausting the budget returns the path walked so far, which is the most specific answer
    available without walking further.
    """
    current = _canonical_report_id(report_id)
    if current is None:
        return []
    visited = {current}
    chain: list[str] = []
    for _ in range(SignalReportArtefact.MAX_REPORT_LINK_GRAPH_LEVELS):
        edges = outgoing_links(team_id=team_id, report_id=current, kinds=(ReportLinkKind.DUPLICATE_OF,))
        if not edges:
            return chain
        # A report duplicates at most one other in practice. When an agent wrote several, the
        # oldest claim wins so the chain does not move as later rows land.
        next_id = edges[0].target_id
        if next_id in visited:
            return chain
        visited.add(next_id)
        chain.append(next_id)
        current = next_id
    logger.warning("signals report link duplicate chain exceeded budget", report_id=str(report_id), team_id=team_id)
    return chain


def duplicate_root(*, team_id: int, report_id: str | uuid.UUID) -> str:
    """Follow `duplicate_of` until a report that duplicates nothing, and return that report's id.

    The root names the cluster. A reader deciding whether the cluster is already being worked on
    wants `duplicate_chain` instead, because the work sits wherever it started.
    """
    chain = duplicate_chain(team_id=team_id, report_id=report_id)
    if chain:
        return chain[-1]
    return _canonical_report_id(report_id) or str(report_id)


def linked_reports(*, team_id: int, report_ids: Collection[str]) -> dict[str, SignalReport]:
    """The live reports behind a set of link targets, keyed by id, with only the display columns."""
    if not report_ids:
        return {}
    rows = (
        SignalReport.objects.using("default")
        .filter(team_id=team_id, id__in=list(report_ids))
        .exclude(status=SignalReport.Status.DELETED)
        .only("id", "title", "summary", "status", "team")
    )
    return {str(report.id): report for report in rows}


def has_open_or_merged_pull_request(*, team_id: int, report_ids: Collection[str]) -> set[str]:
    """Which of these reports carry a pull request that is not known to be closed.

    "Work exists for it" is the question every link gate asks. Only a verified `closed` answers no,
    because nothing landed and nothing is in flight. `unknown` counts as work like everywhere else
    in the product: it is the column default and the state an attach keeps when the GitHub lookup
    fails, so reading it as "no pull request" would open a second one against work already in
    flight.
    """
    from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports

    live_states = {
        SignalReportPullRequest.State.OPEN,
        SignalReportPullRequest.State.DRAFT,
        SignalReportPullRequest.State.MERGED,
        SignalReportPullRequest.State.UNKNOWN,
    }
    # Writer-pinned like every other read in this module: a pull request attached moments ago must
    # not read as absent and buy a second one.
    prs_by_report = fetch_implementation_prs_for_reports(list(report_ids), team_id=team_id, using="default")
    return {report_id for report_id, prs in prs_by_report.items() if any(pr.state in live_states for pr in prs)}


def capture_report_linked(*, team_id: int, edge: ReportEdge, actor_kind: str | None, actor_agent: str | None) -> None:
    """`signals_report_linked` — one event per stored link, so the share of reports that carry each
    kind of edge becomes readable.

    Links live as Postgres artefacts, which gives the pipeline no denominator for how often a
    report duplicates or belongs to another one. This event is that denominator. Fired from the one
    write path every producer shares (scouts, grouping's recurrence fork, the check re-surface), so
    a new producer is counted without touching this module.
    """
    try:
        team = Team.objects.select_related("organization").filter(pk=team_id).first()
        if team is None:
            return
        posthoganalytics.capture(
            event="signals_report_linked",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "organization_id": str(team.organization.id),
                "report_id": edge.source_id,
                "linked_report_id": edge.target_id,
                "kind": edge.kind.value,
                "has_reason": bool(edge.reason),
                "actor_kind": actor_kind,
                "actor_agent": actor_agent,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        # Analytics must never break a link write.
        logger.exception("Failed to capture signals_report_linked", report_id=edge.source_id)
