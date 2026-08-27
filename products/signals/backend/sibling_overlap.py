"""Find a sibling report whose implementation already targets the same fix.

Signals groups signals into reports before research, so two reports can be genuinely distinct
signals (different exceptions, different pages) and still resolve to one line of code. The overlap
only becomes visible after research, in the `signal_finding` artefacts: both reports name the same
causative commit, or the same primary file. Nothing downstream compared those artefacts, so each
report auto-started its own implementation and each opened its own pull request against the same
code.

This module is that comparison. It is pure Postgres over artefacts the pipeline already writes, so
it costs no LLM call and gives the same answer every time it runs.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta
from typing import Literal

from django.conf import settings
from django.utils import timezone

import structlog
from pydantic import ValidationError

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import NoteArtefact, RelatedTo, SignalFinding
from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION

logger = structlog.get_logger(__name__)

# How far back a sibling counts. Long enough to cover the days-long drip of reports one root cause
# produces, short enough that a file touched again months later is treated as new work.
SIBLING_LOOKBACK_DAYS = 30

# Findings carry 7-character short SHAs, but agents sometimes write the full hash. Comparing the
# first 7 characters makes both forms of the same commit match.
_SHORT_SHA_LENGTH = 7


@frozen
class FindingOverlap:
    """What two reports' findings have in common, in words a person can read."""

    kind: Literal["commit", "code path"]
    value: str


@frozen
class SiblingFix:
    """A sibling report that is already being fixed, and what it has in common with this one."""

    report_id: str
    title: str | None
    overlap: FindingOverlap
    pr_url: str | None


@frozen
class _FindingFingerprint:
    """The parts of a report's findings that identify which fix it is asking for."""

    commit_hashes: frozenset[str]
    primary_paths: frozenset[str]

    def is_empty(self) -> bool:
        return not self.commit_hashes and not self.primary_paths

    def overlap_with(self, other: _FindingFingerprint) -> FindingOverlap | None:
        """The strongest thing the two fingerprints share, or None when they share nothing.

        A commit beats a path: two reports blaming one commit are the same regression, while two
        reports on one file may only be neighbours in a big module. Both sides are sorted so the
        reported value does not depend on set iteration order.
        """
        shared_commits = sorted(self.commit_hashes & other.commit_hashes)
        if shared_commits:
            return FindingOverlap(kind="commit", value=shared_commits[0])
        shared_paths = sorted(self.primary_paths & other.primary_paths)
        if shared_paths:
            return FindingOverlap(kind="code path", value=shared_paths[0])
        return None


def _normalize_commit(sha: str) -> str | None:
    short = sha.strip().lower()[:_SHORT_SHA_LENGTH]
    return short if len(short) == _SHORT_SHA_LENGTH else None


def _normalize_path(path: str) -> str:
    return path.strip().removeprefix("./").removeprefix("/")


def _primary_paths(findings: list[SignalFinding]) -> set[str]:
    """The paths that stand for the whole report, rather than every file it mentions.

    `relevant_code_paths` is ordered most critical first and then lists supporting files, so the
    first entry is the report's subject. A path every finding repeats is a subject too: several
    independent signals landing on one file is what a shared root cause looks like. Supporting
    files are excluded, otherwise a shared `package.json` would make unrelated reports overlap.
    """
    per_finding: list[list[str]] = []
    for finding in findings:
        cleaned = [_normalize_path(path) for path in finding.relevant_code_paths if path.strip()]
        if cleaned:
            per_finding.append(cleaned)
    if not per_finding:
        return set()
    primary = {paths[0] for paths in per_finding}
    if len(per_finding) > 1:
        primary |= set.intersection(*(set(paths) for paths in per_finding))
    return primary


def _fingerprint(findings: Iterable[SignalFinding]) -> _FindingFingerprint:
    findings = list(findings)
    commits = {
        short
        for finding in findings
        for short in (_normalize_commit(sha) for sha in finding.relevant_commit_hashes)
        if short is not None
    }
    return _FindingFingerprint(commit_hashes=frozenset(commits), primary_paths=frozenset(_primary_paths(findings)))


def _effective_findings_by_report(report_ids: list[str]) -> dict[str, list[SignalFinding]]:
    """Latest `signal_finding` per (report, signal_id), the same latest-wins rule research applies.

    Rows that fail to parse are skipped: a legacy or hand-edited artefact must not stop the check.
    """
    if not report_ids:
        return {}
    latest: dict[str, dict[str, SignalFinding]] = {}
    rows = (
        SignalReportArtefact.objects.filter(
            report_id__in=report_ids, type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING
        )
        .order_by("created_at")
        .values_list("report_id", "content")
    )
    for report_id, content in rows:
        try:
            finding = SignalFinding.model_validate_json(content)
        except ValidationError:
            continue
        latest.setdefault(str(report_id), {})[finding.signal_id] = finding
    return {report_id: list(by_signal.values()) for report_id, by_signal in latest.items()}


def _implementation_pr_urls(report_ids: list[str]) -> dict[str, str]:
    """Best-effort: the link is decoration on the skip, so a lookup failure must not change it."""
    try:
        return fetch_implementation_pr_urls_for_reports(report_ids)
    except Exception:
        logger.exception("signals sibling overlap PR lookup failed", report_ids=report_ids)
        return {}


def find_sibling_with_same_fix(*, team_id: int, report_id: str) -> SiblingFix | None:
    """The sibling report already being implemented for the same fix as *report_id*, if there is one.

    A sibling only counts once it has an implementation task. That is deliberately narrower than
    "any sibling with overlapping findings": if overlap alone were enough, two reports naming one
    commit would each see the other and both stand down, and the fix nobody is working on would
    get no pull request at all. Requiring a started implementation makes the first report through
    the gate the one that ships, and every later report defer to it.

    That ordering is read, not locked: two reports whose research finishes at the same instant can
    both find no started sibling. Reports arrive minutes to days apart, so this deduplicates the
    real case; the row lock in `auto_start` still holds the per-report guarantee.
    """
    own_findings = _effective_findings_by_report([report_id]).get(report_id, [])
    own = _fingerprint(own_findings)
    if own.is_empty():
        return None

    # Resolved reports stay in scope: their fix landed, so a second pull request for it is still a
    # duplicate. Suppressed and dismissed reports drop out, because signals closes their pull
    # request, which would leave this report deferring to nothing.
    candidates: dict[str, str | None] = {
        str(candidate_id): title
        for candidate_id, title in SignalReport.objects.filter(
            team_id=team_id,
            status__in=(SignalReport.Status.READY, SignalReport.Status.RESOLVED),
            created_at__gte=timezone.now() - timedelta(days=SIBLING_LOOKBACK_DAYS),
        )
        .exclude(id=report_id)
        .order_by("created_at", "id")
        .values_list("id", "title")
    }
    if not candidates:
        return None

    implementing = SignalReport.associated_task_runs_for_reports(
        report_ids=list(candidates),
        team_id=team_id,
        product=SIGNALS_PRODUCT,
        type=TASK_RUN_TYPE_IMPLEMENTATION,
    )
    findings_by_report = _effective_findings_by_report([str(candidate) for candidate in implementing])

    matches: list[SiblingFix] = []
    for candidate_id, title in candidates.items():
        if candidate_id not in implementing:
            continue
        overlap = own.overlap_with(_fingerprint(findings_by_report.get(candidate_id, [])))
        if overlap is not None:
            matches.append(SiblingFix(report_id=candidate_id, title=title, overlap=overlap, pr_url=None))
    if not matches:
        return None

    # Prefer the sibling that already has a pull request: that is the one this report would
    # duplicate, and the one worth pointing a reader at. Otherwise take the oldest match, so
    # repeated evaluations of the same report keep naming the same sibling.
    pr_urls = _implementation_pr_urls([match.report_id for match in matches])
    for match in matches:
        pr_url = pr_urls.get(match.report_id)
        if pr_url:
            return replace(match, pr_url=pr_url)
    return matches[0]


def _report_url(team_id: int, report_id: str) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/inbox/reports/{report_id}"


def _skip_note(*, team_id: int, sibling: SiblingFix) -> str:
    link = f"[{sibling.title or 'Another report'}]({_report_url(team_id, sibling.report_id)})"
    note = (
        f"No pull request opened for this report. {link} is already being fixed, and both reports "
        f"point at the same {sibling.overlap.kind} `{sibling.overlap.value}`."
    )
    return f"{note} Pull request: {sibling.pr_url}" if sibling.pr_url else note


def _has_note_for_sibling(*, team_id: int, report_id: str, sibling_report_id: str) -> bool:
    """Whether this report's log already explains a skip in favour of *sibling_report_id*.

    Keyed on the sibling's link, which every such note carries. A `related_to` row would be the
    obvious marker, but reports get linked for other reasons too (grouping writes one when a signal
    would have joined an already-resolved report), and one of those must not silence the note.
    """
    marker = f"/inbox/reports/{sibling_report_id}"
    return any(
        marker in content
        for content in SignalReportArtefact.objects.filter(
            team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.NOTE
        ).values_list("content", flat=True)
    )


def _is_linked_to(*, team_id: int, report_id: str, sibling_report_id: str) -> bool:
    for content in SignalReportArtefact.objects.filter(
        team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.RELATED_TO
    ).values_list("content", flat=True):
        try:
            if json.loads(content).get("report_id") == sibling_report_id:
                return True
        except (TypeError, ValueError):
            continue
    return False


def record_sibling_fix_skip(*, team_id: int, report_id: str, sibling: SiblingFix) -> None:
    """Say in the inbox why no pull request opened, and link the two reports.

    Auto-start is re-evaluated whenever a report's reviewers change, so each write is guarded:
    repeated evaluations leave one note and one link, not a growing pile.
    """
    if not _has_note_for_sibling(team_id=team_id, report_id=report_id, sibling_report_id=sibling.report_id):
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=report_id,
            content=NoteArtefact(note=_skip_note(team_id=team_id, sibling=sibling), author="Self-driving"),
            attribution=ArtefactAttribution.system(),
        )
    if not _is_linked_to(team_id=team_id, report_id=report_id, sibling_report_id=sibling.report_id):
        # Symmetric by construction, so the report shipping the fix also shows what deferred to it.
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=report_id,
            content=RelatedTo(report_id=sibling.report_id),
            attribution=ArtefactAttribution.system(),
        )
