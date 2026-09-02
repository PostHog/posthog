"""A watch: a hypothesis on a page, compiled into evidence the server rechecks and a scout that
follows the signals around it. The thread keeps the brief, the checks, and the verdict."""

import re
import json
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.team import Team

from ..facade.enums import DataShape, WatchVerdict
from . import data_points

MAX_HISTORY = 60
MAX_EVIDENCE = 4
MAX_SIGNALS = 6
MOVED_RATIO = 0.2
CHECK_EVERY = timedelta(hours=24)
SCOUT_SOURCE_PRODUCT = "docs"
SCOUT_NAME_PREFIX = "signals-scout-doc-watch-"

_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


@frozen
class Evidence:
    """One number the claim stands on. The baseline is the value when the brief landed."""

    label: str
    query: str
    shape: str
    baseline: float | None
    value: float | None
    checked_at: str | None
    error: str | None
    history: list[list[Any]] = dataclasses.field(default_factory=list)
    moved: bool = False

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Evidence":
        return cls(
            label=str(raw.get("label") or ""),
            query=str(raw.get("query") or ""),
            shape=str(raw.get("shape") or DataShape.NUMBER.value),
            baseline=_as_float(raw.get("baseline")),
            value=_as_float(raw.get("value")),
            checked_at=raw.get("checked_at"),
            error=raw.get("error"),
            history=list(raw.get("history") or []),
            moved=bool(raw.get("moved", False)),
        )


@frozen
class Brief:
    """What the agent compiled the claim into."""

    claim: str
    confirms: str
    refutes: str
    evidence: list[Evidence]
    signals: list[str]
    submitted_at: str
    run_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "confirms": self.confirms,
            "refutes": self.refutes,
            "evidence": [entry.to_json() for entry in self.evidence],
            "signals": self.signals,
            "submitted_at": self.submitted_at,
            "run_id": self.run_id,
        }

    @classmethod
    def from_json(cls, raw: object) -> "Brief | None":
        if not isinstance(raw, dict) or not raw.get("claim"):
            return None
        return cls(
            claim=str(raw["claim"]),
            confirms=str(raw.get("confirms") or ""),
            refutes=str(raw.get("refutes") or ""),
            evidence=[Evidence.from_json(entry) for entry in raw.get("evidence") or [] if isinstance(entry, dict)],
            signals=[str(entry) for entry in raw.get("signals") or []],
            submitted_at=str(raw.get("submitted_at") or ""),
            run_id=raw.get("run_id"),
        )


@frozen
class EvidenceInput:
    label: str
    query: str


@frozen
class EvidenceResult:
    """What one evidence query gave when the brief was checked."""

    label: str
    ok: bool
    value: str | None
    error: str | None


@frozen
class ScoutDefinition:
    name: str
    description: str
    body: str


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    return float(text) if _NUMBER.match(text) else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def format_value(value: float | None) -> str:
    if value is None:
        return "no value"
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.2f}"


def has_moved(baseline: float | None, value: float | None) -> bool:
    """A fifth of the baseline, or a change of sign. Small integers move on any change."""
    if baseline is None or value is None:
        return False
    if (baseline > 0) != (value > 0) and value != 0:
        return True
    return abs(value - baseline) >= MOVED_RATIO * max(abs(baseline), 1.0)


def run_evidence(team: Team, entry: EvidenceInput) -> tuple[Evidence | None, EvidenceResult]:
    """Runs one evidence query the first time. Only a number or a trend can be rechecked."""
    query = data_points.clean_query(entry.query)
    label = entry.label.strip() or "evidence"
    if not data_points.is_read_query(query):
        return None, EvidenceResult(label=label, ok=False, value=None, error="Only one SELECT is accepted.")
    run = data_points.run_once(team, query)
    if run.error or run.shape is None:
        return None, EvidenceResult(label=label, ok=False, value=None, error=run.error or "No rows came back.")
    if run.shape == DataShape.TABLE:
        return None, EvidenceResult(
            label=label, ok=False, value=None, error="Evidence must be one number or a date and a number per row."
        )
    value = _as_float(run.value)
    now = _now_iso()
    evidence = Evidence(
        label=label,
        query=query,
        shape=run.shape.value,
        baseline=value,
        value=value,
        checked_at=now,
        error=None,
        history=[[now, value]],
    )
    return evidence, EvidenceResult(label=label, ok=True, value=run.value, error=None)


def recheck(team: Team, evidence: Evidence) -> Evidence:
    """Runs the evidence again and records where it stands against its baseline."""
    run = data_points.run_once(team, evidence.query)
    now = _now_iso()
    if run.error or run.shape is None:
        return dataclasses.replace(evidence, checked_at=now, error=run.error or "No rows came back.")
    value = _as_float(run.value)
    history = [*evidence.history, [now, value]][-MAX_HISTORY:]
    return dataclasses.replace(
        evidence,
        value=value,
        checked_at=now,
        error=None,
        history=history,
        moved=has_moved(evidence.baseline, value),
    )


def moved_line(evidence: Evidence) -> str:
    return f"“{evidence.label}” moved from {format_value(evidence.baseline)} to {format_value(evidence.value)}."


def verdict_after_check(brief: Brief) -> WatchVerdict:
    """What the checks alone say: stale when nothing could run, moved when any evidence did."""
    if brief.evidence and all(entry.error for entry in brief.evidence):
        return WatchVerdict.STALE
    if any(entry.moved for entry in brief.evidence):
        return WatchVerdict.MOVED
    return WatchVerdict.HOLDING


def next_check(now: datetime) -> datetime:
    return now + CHECK_EVERY


def anchor_keys(content: object) -> set[str]:
    """Every discussion anchor and data request still in the page body."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        for mark in node.get("marks") or []:
            if isinstance(mark, dict) and mark.get("type") == "discussionAnchor":
                key = (mark.get("attrs") or {}).get("anchorKey")
                if key:
                    found.add(str(key))
        request_id = (node.get("attrs") or {}).get("requestId")
        if request_id:
            found.add(str(request_id))
            found.add(f"watch:{request_id}")
        walk(node.get("content"))

    walk(content)
    return found


def extract_structured_brief(text: str) -> dict[str, Any] | None:
    """A turn that ended as the brief JSON: ``{claim, confirms, refutes, evidence, signals}``."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if not body.startswith("{"):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or not str(data.get("claim") or "").strip():
        return None
    evidence = [
        {"label": str(entry.get("label") or ""), "query": str(entry.get("query") or "")}
        for entry in data.get("evidence") or []
        if isinstance(entry, dict) and entry.get("query")
    ]
    return {
        "claim": str(data["claim"]).strip(),
        "confirms": str(data.get("confirms") or "").strip(),
        "refutes": str(data.get("refutes") or "").strip(),
        "evidence": evidence[:MAX_EVIDENCE],
        "signals": [str(entry).strip() for entry in data.get("signals") or [] if str(entry).strip()][:MAX_SIGNALS],
    }


def reminder_text(request_id: str) -> str:
    """The one fixed follow-up a run gets when it wrote prose and no brief."""
    call = (
        f'call doc-watch-brief-submit {{"request_id": "{request_id}", "claim": "<the claim in one sentence>", '
        '"confirms": "<what would confirm it>", "refutes": "<what would refute it>", '
        '"evidence": [{"label": "<what it counts>", "query": "<SELECT>"}], "signals": ["<what to follow>"]}'
    )
    return "\n".join(
        [
            "The page did not receive a watch brief. Hand it in now through the PostHog MCP `exec` tool:",
            call,
            "Each evidence query must return one number, or a date and a number per row.",
        ]
    )


def report_post(title: str, summary: str) -> str:
    head = title.strip()
    body = summary.strip()
    if head and body:
        return f"**{head}**\n\n{body}"
    return head or body


def scout_name(thread_id: str) -> str:
    return f"{SCOUT_NAME_PREFIX}{str(thread_id).replace('-', '')[:12]}"


def scout_definition(
    *, thread_id: str, request_id: str, brief: Brief, doc_title: str, page_url: str
) -> ScoutDefinition:
    """The scout that follows this hypothesis. The body is a template filled from the brief, so
    every watch's scout has the same shape and a small model has nothing to invent. It follows
    the fleet's own anatomy and leaves where to look to the scout."""
    name = scout_name(thread_id)
    evidence_lines = [f"- {entry.label}: `{entry.query}`" for entry in brief.evidence] or ["- none"]
    context_lines = [f"- {entry}" for entry in brief.signals] or ["- none"]
    memory = f"doc-watch:{request_id}"
    verdict_call = (
        f'call doc-watch-verdict-submit {{"request_id": "{request_id}", "verdict": "<holding|moved|confirmed|refuted>", '
        '"reason": "<one line>"}'
    )
    body = "\n".join(
        [
            "---",
            f"name: {name}",
            "description: >",
            f"  Follows the hypothesis “{_one_line(brief.claim)}” written on the page “{_one_line(doc_title)}” and",
            "  reports when this project's data confirms, refutes, or moves it.",
            "allowed_tools:",
            "  - emit_report",
            "  - edit_report",
            "metadata:",
            "  owner_team: docs",
            "  scope: doc_watch",
            "---",
            "",
            f"# Hypothesis watch: {_one_line(brief.claim)}",
            "",
            f"You follow one hypothesis a person wrote on the page “{_one_line(doc_title)}” ({page_url}).",
            "The signal-versus-noise discriminator is the claim itself: a finding is worth a report only when it",
            "confirms the claim, refutes it, or moves what it stands on. Everything else is baseline. Internalize",
            "that: you are not looking for anything interesting, you are looking for what bears on this one claim.",
            "",
            "## The hypothesis",
            "",
            f"Claim: {brief.claim}",
            f"What confirms it: {brief.confirms or 'the evidence below keeps holding'}",
            f"What refutes it: {brief.refutes or 'the evidence below turns the other way'}",
            "",
            "## Quick close-out",
            "",
            f"Read `scout-scratchpad-search` with `text={memory}` first. If nothing in this project has moved",
            "on the claim since the last run, refresh the baseline entry and close out empty. A quiet run is a real outcome.",
            "",
            "## Orient",
            "",
            f"- `scout-scratchpad-search` (`text={memory}`): what you saw, reported, and ruled out before.",
            "- `scout-runs-list` (last 7 days): what your own recent runs found.",
            "- `scout-project-profile-get`: a first hint of what this project uses. It is not complete.",
            "",
            "## Where to look",
            "",
            "Decide that yourself. Build your own map of this project with the read tools you have, and follow",
            "whatever could bear on the claim, in any product this project uses. The page gives you two kinds of context,",
            "as starting points and not as a boundary:",
            "",
            "Numbers the page already rechecks every day (do not report these on their own; explain what moves them):",
            "",
            *evidence_lines,
            "",
            "What the page's author thought was related:",
            "",
            *context_lines,
            "",
            "## Save memory as you go",
            "",
            f"Write scratchpad entries under `{memory}:` with the fleet prefixes, for example `{memory}:pattern:baseline`",
            f"for what normal looks like, `{memory}:dedupe:<finding>` for what you already filed, `{memory}:noise:<what>`",
            "for what to ignore next time.",
            "",
            "## Decide",
            "",
            "Check `inbox-reports-list` before you author. If a report on this claim exists, `edit_report` it with the",
            "new evidence. Otherwise `emit_report` one report: title = one sentence on what changed for the claim;",
            'summary = at most six lines with the numbers, each cited as <hogql label="what it counts">SELECT ...</hogql>,',
            "and what it means for the claim. Below the bar: remember it in the scratchpad instead.",
            "",
            "After a report, set the verdict on the page through the PostHog MCP `exec` tool:",
            f"`{verdict_call}`",
            "Use confirmed or refuted only when the data leaves no doubt; those end the watch.",
            "",
            "## Disqualifiers",
            "",
            "- The page's own daily numbers, unchanged: the page already shows them.",
            "- Single-user quirks, dev or test traffic, and what the scratchpad marks as noise.",
            "- Anything that does not bear on this claim, however interesting.",
            "",
            "## Close out",
            "",
            "One paragraph: what you looked at, what you filed or edited, what you remembered, what you ruled out.",
            "Do not edit the page. Do not build or save an insight, dashboard, or notebook.",
        ]
    )
    return ScoutDefinition(
        name=name,
        description=f"Follows the hypothesis “{_one_line(brief.claim)[:140]}” from the page “{_one_line(doc_title)[:60]}”.",
        body=body,
    )


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().replace('"', "'")
