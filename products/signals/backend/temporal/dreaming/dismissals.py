"""Dismissal-reason learning for the Dreaming Agent.

When a user suppresses an inbox report, the backend persists a
``SignalReportArtefact`` of type ``DISMISSAL`` whose ``content`` is JSON
``{"reason": <code>, "note": <free text>}`` (see
``products/signals/backend/views.py`` for the write and
``serializers.SignalReportSerializer._get_dismissal_artefact_data`` for the read).

This module reads the dismissals recorded since the team's previous dreaming run
and folds them into a compact, well-typed summary: how many of each reason code,
a few representative notes, and — where derivable — which source products the
dismissed reports came from. That summary is the raw material for two things:

- the nightly briefing's "what matters" judgment (a class of signal being mass
  dismissed as ``not_a_bug`` is signal-quality news worth surfacing), and
- noise-awareness for future scout/grouping tuning (recurring false-positive
  patterns the daily-grouping pass will eventually act on).

Everything here returns small primitives. The aggregation runs inside the
briefing activity, and only the compact ``DismissalSummary`` (capped counts +
a handful of short notes) crosses the activity boundary — never raw artefacts —
so we stay well under the ~2 MiB Temporal payload limit.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.temporal.signal_queries import fetch_source_products_for_reports

logger = logging.getLogger(__name__)

# Default window when the team has no recorded previous dreaming run — one night's worth.
DEFAULT_DISMISSAL_LOOKBACK = timedelta(hours=24)

# Caps so the summary stays small no matter how noisy the night was: a runaway count of
# dismissals can't blow the activity payload or the briefing prompt.
MAX_DISMISSALS_SCANNED = 500
MAX_REPRESENTATIVE_NOTES = 5
MAX_NOTE_LEN = 240
MAX_REPORTS_FOR_SOURCE_LOOKUP = 200


@dataclass(frozen=True)
class DismissalSummary:
    """A compact, serialization-safe summary of recent dismissals.

    All fields are plain primitives so the summary can cross the Temporal activity
    boundary and feed straight into the briefing prompt without further shaping.
    """

    total: int
    # reason code -> count, e.g. {"not_a_bug": 7, "duplicate": 2}.
    by_reason: dict[str, int]
    # source product -> count of dismissed reports from that source, e.g.
    # {"error_tracking": 5}. Best-effort: a report whose source can't be resolved
    # is simply absent here, so the per-source counts can sum to less than `total`.
    by_source_product: dict[str, int]
    # A handful of short, representative free-text notes (deduped, clipped).
    representative_notes: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return self.total == 0

    @property
    def top_reason(self) -> tuple[str, int] | None:
        """The single most common reason code and its count, if any."""
        if not self.by_reason:
            return None
        reason, count = max(self.by_reason.items(), key=lambda kv: kv[1])
        return reason, count


def _parse_artefact_content(content: str) -> dict[str, str] | None:
    """Read a dismissal artefact's JSON, returning the reason/note pair if present.

    Mirrors ``serializers._get_dismissal_artefact_data`` — same shape, same tolerance
    of malformed content — so dreaming and the API read dismissals identically.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, str] = {}
    reason = data.get("reason")
    if isinstance(reason, str) and reason:
        out["reason"] = reason
    note = data.get("note")
    if isinstance(note, str) and note.strip():
        out["note"] = note.strip()
    return out


def _clip_note(note: str) -> str:
    note = " ".join(note.split())
    if len(note) <= MAX_NOTE_LEN:
        return note
    return note[: MAX_NOTE_LEN - 1].rstrip() + "…"


def resolve_dismissal_since(last_run_at_iso: str | None) -> datetime:
    """The lower bound to read dismissals from: the previous dreaming run, or 24h ago."""
    if last_run_at_iso:
        parsed = datetime.fromisoformat(last_run_at_iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.get_current_timezone())
        return parsed
    return timezone.now() - DEFAULT_DISMISSAL_LOOKBACK


def aggregate_dismissals(team_id: int, *, last_run_at_iso: str | None) -> DismissalSummary:
    """Read recent dismissal artefacts for ``team_id`` and aggregate them.

    Counts by reason code, collects a few representative notes, and groups the
    dismissed reports by their source product (resolved via ClickHouse signal
    metadata, best-effort). Runs synchronously; call from inside the activity.
    """
    since = resolve_dismissal_since(last_run_at_iso)

    artefacts = list(
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            created_at__gte=since,
        )
        .order_by("-created_at")
        .values_list("report_id", "content")[:MAX_DISMISSALS_SCANNED]
    )

    if not artefacts:
        return DismissalSummary(total=0, by_reason={}, by_source_product={}, representative_notes=())

    reason_counter: Counter[str] = Counter()
    notes: list[str] = []
    seen_notes: set[str] = set()
    # Take only the latest dismissal per report so a report dismissed, reopened, and
    # dismissed again counts once — matching the "latest artefact per report" read in
    # the serializer. Artefacts are already newest-first, so first-seen wins.
    latest_reason_by_report: dict[str, str] = {}

    for report_id, content in artefacts:
        parsed = _parse_artefact_content(content)
        if parsed is None:
            continue
        report_key = str(report_id)
        reason = parsed.get("reason")
        if reason and report_key not in latest_reason_by_report:
            latest_reason_by_report[report_key] = reason
            reason_counter[reason] += 1
        note = parsed.get("note")
        if note and len(notes) < MAX_REPRESENTATIVE_NOTES:
            clipped = _clip_note(note)
            if clipped.lower() not in seen_notes:
                seen_notes.add(clipped.lower())
                notes.append(clipped)

    total = len(latest_reason_by_report) if latest_reason_by_report else len({str(rid) for rid, _ in artefacts})
    by_source_product = _group_reports_by_source(team_id, list(latest_reason_by_report.keys()))

    return DismissalSummary(
        total=total,
        by_reason=dict(reason_counter),
        by_source_product=by_source_product,
        representative_notes=tuple(notes),
    )


def _group_reports_by_source(team_id: int, report_ids: list[str]) -> dict[str, int]:
    """Best-effort count of dismissed reports per source product.

    Resolves each report's source products via the same ClickHouse query the inbox
    list view uses. A failure here (ClickHouse hiccup, no signals) degrades to an
    empty mapping rather than failing the whole aggregation — the reason counts are
    the load-bearing part of the summary.
    """
    if not report_ids:
        return {}
    capped = report_ids[:MAX_REPORTS_FOR_SOURCE_LOOKUP]
    try:
        from posthog.models import Team  # noqa: PLC0415 — keeps the ORM Team off the module import path

        team = Team.objects.get(id=team_id)
        mapping = fetch_source_products_for_reports(team, capped)
    except Exception:
        logger.warning(
            "dreaming dismissals: source-product grouping failed; continuing without it",
            extra={"team_id": team_id},
        )
        return {}

    counter: Counter[str] = Counter()
    for source_products in mapping.values():
        for source_product in source_products:
            if source_product:
                counter[source_product] += 1
    return dict(counter)


def summarize_dismissals_for_briefing(summary: DismissalSummary) -> list[str]:
    """Render the dismissal summary into a few briefing-prompt lines.

    Empty input yields an empty list so the briefing simply omits the section.
    The lines are deliberately terse — they're context for the LLM, not output.
    """
    if summary.is_empty:
        return []

    lines: list[str] = [f"{summary.total} report(s) dismissed since the last run."]

    if summary.by_reason:
        ranked = sorted(summary.by_reason.items(), key=lambda kv: kv[1], reverse=True)
        reason_str = ", ".join(f"{reason} ({count})" for reason, count in ranked)
        lines.append(f"By reason: {reason_str}.")

    if summary.by_source_product:
        ranked_sources = sorted(summary.by_source_product.items(), key=lambda kv: kv[1], reverse=True)
        source_str = ", ".join(f"{source} ({count})" for source, count in ranked_sources)
        lines.append(f"By source: {source_str}.")

    for note in summary.representative_notes:
        lines.append(f'Note: "{note}"')

    return lines


def known_false_positive_memory_section(summary: DismissalSummary) -> str | None:
    """Render durable "why users dismiss" learnings as a markdown memory section body.

    Returns ``None`` when there's nothing worth recording, so the memory hook can
    no-op. This is the content written into project memory once agent_memory lands.
    """
    if summary.is_empty or not summary.by_reason:
        return None

    parts: list[str] = []
    ranked = sorted(summary.by_reason.items(), key=lambda kv: kv[1], reverse=True)
    parts.append("Recent dismissals (what users reject and why):")
    for reason, count in ranked:
        parts.append(f"- {reason}: {count}")

    if summary.by_source_product:
        ranked_sources = sorted(summary.by_source_product.items(), key=lambda kv: kv[1], reverse=True)
        parts.append("")
        parts.append("Most-dismissed sources:")
        for source, count in ranked_sources:
            parts.append(f"- {source}: {count}")

    if summary.representative_notes:
        parts.append("")
        parts.append("Representative notes:")
        for note in summary.representative_notes:
            parts.append(f"- {note}")

    return "\n".join(parts)
