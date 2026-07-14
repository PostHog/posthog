"""Report-authoring harness tools: the second emit channel (`emit_report` / `edit_report`).

Where `emit.py` forwards a weak signal through `emit_signal()` and lets the pipeline decide, these
tools let an opted-in scout author or edit a full `SignalReport` directly. They are thin harness
adapters: input validation + the shared preflight gates + attribution, then calls into the sanctioned
`scout_report/` service (`judge_scout_report` + `create_scout_report` for emit; `update_scout_report` /
`append_report_note` for edit). The tool never touches `SignalReport` or the embeddings pipeline itself
— that boundary lives in the service (see `scout_harness/AGENTS.md`).

Opt-in is by `allowed_tools`: a scout gets these only if its skill lists `emit_report` / `edit_report`,
intersected with what `tools/__init__.py` re-exports.

Like `emit_finding`, these are NOT idempotent — a retried `emit_report` authors a second report. The
dedup story is the vanilla inbox tools (`inbox-reports-list` / `inbox-reports-retrieve`) plus a
`report:<domain>:<entity>` scratchpad key the scout maintains; callers must not retry an authoring call
that may have succeeded.
"""

from __future__ import annotations

import re
import uuid
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import posthoganalytics
from asgiref.sync import async_to_sync

from posthog.api.capture import capture_internal
from posthog.event_usage import groups
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.artefact_schemas import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalScoutRun
from products.signals.backend.report_generation.resolve_reviewers import get_org_member_github_logins_by_user_uuid
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.scout_harness.prompt import SELF_IMPROVEMENT_REPORT_TITLE_PREFIX
from products.signals.backend.scout_harness.tools.emit import (
    SCOUT_SIGNAL_WEIGHT,
    # Shared harness gates/attribution — the report channel applies the same preflight as emit.
    _assert_team_owns_run,
    _preflight_emit_gates,
    _resolve_task_id,
    remediation_for_skip,
)
from products.signals.backend.scout_report import (
    MAX_REPORT_SIGNALS,
    InvalidScoutReportError,
    ScoutReportSignal,
    append_report_note,
    create_scout_report,
    get_scout_report_title,
    record_report_edit,
    set_scout_report_reviewers,
    update_scout_report,
)
from products.signals.backend.scout_report.judge import ScoutReportJudgement, judge_scout_report

logger = logging.getLogger(__name__)

# Defensive caps at the tool boundary (the service caps signals too; these bound caller input early).
MAX_REPORT_TITLE_LENGTH = 300
MAX_SUGGESTED_REVIEWERS = 10
# Bound the free-text the scout supplies before any of it is rendered into the safety-judge prompt or
# the embedding requests — a report can carry up to MAX_REPORT_SIGNALS evidence items, so an unbounded
# per-item description (or summary) lets one malformed call spend/fail on a huge LLM prompt.
MAX_EVIDENCE_DESCRIPTION_LENGTH = 4000
MAX_REPORT_SUMMARY_LENGTH = 20000

# Repository modes for `emit_report`, mirroring `custom_agent`'s three-mode contract:
#   "owner/repo" -> that repo; NO_REPO -> explicitly no repo (lands without a draft PR);
#   omitted (None) -> free-form selection across the team's repos (`select_repository_for_team`).
NO_REPO = "NO_REPO"


@dataclass(frozen=True)
class ReportEvidence:
    """One observation backing an authored report — becomes a bound `document_embeddings` signal row."""

    description: str
    source_id: str
    weight: float = SCOUT_SIGNAL_WEIGHT


@dataclass(frozen=True)
class ReviewerInput:
    """One reviewer a scout supplies to `emit_report` / `edit_report` — by `github_login`, `user_uuid`, or both.

    Mirrors the inbox `SuggestedReviewerEntryWriteSerializer`: at least one of the two must be set. A
    `user_uuid` is resolved server-side to the org member's linked GitHub login (and wins over a
    supplied `github_login` when both are given), so a scout that only knows a PostHog user — e.g.
    routing a report to an account owner — can route it without first looking up the handle."""

    github_login: str | None = None
    user_uuid: str | None = None


@dataclass(frozen=True)
class EmitReportResult:
    """Outcome of an `emit_report` call.

    The report is always persisted when not gate-skipped (so the agent can edit/dedup against
    `report_id` even when it was suppressed). `emitted` means it actually surfaced in the inbox
    (status READY or PENDING_INPUT); a safety-suppressed or not-actionable report has emitted=False.
    `skipped_reason` is set only when a preflight gate stopped the call before any report was created.
    `remediation` carries a one-line, scout-actionable next step for that skip (see
    `EMIT_SKIP_REMEDIATION`) so a gate-skipped report isn't a dead end — the scout learns why its
    report was dropped and how to unblock it rather than losing a full run to a silent skip.
    """

    report_id: str | None
    status: str | None
    emitted: bool
    skipped_reason: str | None
    safety_explanation: str | None
    remediation: str | None = None


@dataclass(frozen=True)
class EditReportResult:
    report_id: str
    updated_fields: list[str]
    note_appended: bool
    reviewers_set: bool = False
    # The report's effective title after the edit (the rewritten title, or the stored one for a
    # note/reviewer-only edit) — telemetry-only, so the edited lifecycle event can classify the report
    # (`_report_classification_props`) even when the edit didn't touch the title.
    report_title: str | None = None


def _surfaced(status: SignalReport.Status) -> bool:
    return status in (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)


def _build_signals(evidence: list[ReportEvidence]) -> list[ScoutReportSignal]:
    return [ScoutReportSignal(description=e.description, source_id=e.source_id, weight=e.weight) for e in evidence]


def _build_actionability(*, explanation: str, choice: str, already_addressed: bool) -> ActionabilityAssessment:
    try:
        actionability_choice = ActionabilityChoice(choice)
    except ValueError:
        valid = ", ".join(c.value for c in ActionabilityChoice)
        raise InvalidScoutReportError(f"actionability must be one of [{valid}], got {choice!r}")
    return ActionabilityAssessment(
        explanation=explanation, actionability=actionability_choice, already_addressed=already_addressed
    )


def _validate_emit_inputs(title: str, summary: str, evidence: list[ReportEvidence]) -> None:
    if not title or not title.strip():
        raise InvalidScoutReportError("title must not be empty")
    if len(title) > MAX_REPORT_TITLE_LENGTH:
        raise InvalidScoutReportError(f"title exceeds {MAX_REPORT_TITLE_LENGTH} chars ({len(title)})")
    if len(summary) > MAX_REPORT_SUMMARY_LENGTH:
        raise InvalidScoutReportError(f"summary exceeds {MAX_REPORT_SUMMARY_LENGTH} chars ({len(summary)})")
    if not evidence:
        raise InvalidScoutReportError("emit_report needs at least one piece of evidence")
    # Enforce the service's evidence cap here, before the expensive safety-judge LLM call below — an
    # oversized report would otherwise pay for the judge only to be rejected by `create_scout_report`.
    if len(evidence) > MAX_REPORT_SIGNALS:
        raise InvalidScoutReportError(
            f"emit_report accepts at most {MAX_REPORT_SIGNALS} evidence items ({len(evidence)})"
        )
    for item in evidence:
        if len(item.description) > MAX_EVIDENCE_DESCRIPTION_LENGTH:
            raise InvalidScoutReportError(
                f"evidence description exceeds {MAX_EVIDENCE_DESCRIPTION_LENGTH} chars ({len(item.description)})"
            )


def _normalize_repository(repository: str | None) -> str | None:
    """Validate + normalize the scout's `repository` input. `None` / the `NO_REPO` sentinel pass through;
    an explicit value is lowercased and format-checked as `owner/repo`. Raises `InvalidScoutReportError`
    on a malformed value. Pure and cheap — called before the safety judge so a bad explicit repo fails
    fast (rather than after paying for the judge), and reused by the resolver so the parsing lives once."""
    if repository is None or repository == NO_REPO:
        return repository
    normalized = repository.strip().lower()
    parts = normalized.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise InvalidScoutReportError("repository must be in 'owner/repo' format (or the NO_REPO sentinel)")
    return normalized


def _gate_skip_result(preflight: str) -> EmitReportResult:
    logger.warning("signals_scout.emit_report: skipped %s", preflight, extra={"skipped_reason": preflight})
    return EmitReportResult(
        report_id=None,
        status=None,
        emitted=False,
        skipped_reason=preflight,
        safety_explanation=None,
        remediation=remediation_for_skip(preflight),
    )


def _emit_result(persisted_report_id: str, judgement: ScoutReportJudgement) -> EmitReportResult:
    return EmitReportResult(
        report_id=persisted_report_id,
        status=judgement.status,
        emitted=_surfaced(judgement.status),
        skipped_reason=None,
        safety_explanation=judgement.safety.explanation,
    )


def _attribution_for(task_id: str | None) -> ArtefactAttribution:
    return ArtefactAttribution.from_task(task_id) if task_id is not None else ArtefactAttribution.system()


def _build_priority(priority: str | None, explanation: str | None) -> PriorityAssessment | None:
    """Build the `priority_judgment` artefact content from scout-supplied inputs, or None to omit it.

    Autostart needs a priority, so omitting it (or actionability != immediately_actionable) just means
    the report lands without a draft PR. When a priority is given, an explanation is required."""
    if priority is None:
        return None
    try:
        priority_level = Priority(priority)
    except ValueError:
        valid = ", ".join(p.value for p in Priority)
        raise InvalidScoutReportError(f"priority must be one of [{valid}], got {priority!r}")
    if not explanation or not explanation.strip():
        raise InvalidScoutReportError("priority_explanation is required when priority is set")
    return PriorityAssessment(priority=priority_level, explanation=explanation)


def _build_suggested_reviewers(team_id: int, reviewers: list[ReviewerInput] | None) -> SuggestedReviewers | None:
    """Resolve scout-supplied reviewer entries to a canonical, lowercased, deduped `suggested_reviewers`
    artefact (GitHub logins), or None to omit it.

    Each entry identifies a reviewer by `github_login`, `user_uuid`, or both — mirroring the inbox
    `SuggestedReviewerEntryWriteSerializer`. A `user_uuid` is resolved to the org member's linked GitHub
    login (and wins over a supplied `github_login` when both are given), so a scout that only knows a
    PostHog user can still route a report. Resolution is fail-loud: a `user_uuid` that isn't an org
    member of this team with a linked GitHub identity raises `InvalidScoutReportError` rather than
    silently dropping the reviewer (matching the inbox artefact-write endpoint), since a quietly-lost
    reviewer is what leaves a report routed to no one. Entries are deduped by resolved login; an
    all-empty list yields None. Does a DB read (UUID resolution), so callers on the async path must
    bridge it off the event loop."""
    if not reviewers:
        return None

    # Cap the input list *before* resolving — otherwise a malformed call with hundreds of uuid entries
    # would fire one unbounded `IN` query (parameter/timeout risk) just to be rejected afterwards. The
    # DRF ListField enforces the same bound at the API boundary; this guards the direct callers too.
    if len(reviewers) > MAX_SUGGESTED_REVIEWERS:
        raise InvalidScoutReportError(f"at most {MAX_SUGGESTED_REVIEWERS} suggested reviewers, got {len(reviewers)}")

    for entry in reviewers:
        has_login = bool(entry.github_login and entry.github_login.strip())
        if not has_login and not entry.user_uuid:
            raise InvalidScoutReportError("each suggested reviewer needs a github_login or a user_uuid")

    uuids_to_resolve = [str(entry.user_uuid) for entry in reviewers if entry.user_uuid]
    uuid_to_login = get_org_member_github_logins_by_user_uuid(team_id, uuids_to_resolve) if uuids_to_resolve else {}

    logins: list[str] = []
    seen: set[str] = set()
    for entry in reviewers:
        if entry.user_uuid:
            resolved = uuid_to_login.get(str(entry.user_uuid))
            if not resolved:
                raise InvalidScoutReportError(
                    f"user_uuid '{entry.user_uuid}' is not an org member of this team with a linked GitHub identity"
                )
            login = resolved.lower()
        else:
            login = (entry.github_login or "").strip().lower()
            if not login:
                raise InvalidScoutReportError("github_login resolved to empty after normalization")
        if login in seen:
            continue
        seen.add(login)
        logins.append(login)

    if not logins:
        return None
    return SuggestedReviewers(root=[SuggestedReviewerEntry(github_login=login) for login in logins])


def _wants_repo_selection(
    repository: str | None, priority: PriorityAssessment | None, reviewers: SuggestedReviewers | None
) -> bool:
    """Whether to run repo selection at all. Resolve a repo only when the scout signalled PR intent —
    either an explicit `repository`, or the priority + reviewers an autostart needs. An informational
    report that supplies none of these skips selection entirely, so it never pays for the (free-form)
    selection sandbox just to surface in the inbox."""
    return repository is not None or (priority is not None and reviewers is not None)


def _repo_request_section(title: str, summary: str, evidence: list[ReportEvidence]) -> str:
    """Render the report into the free-text request the repo selector reasons over."""
    lines = [title, "", summary]
    if evidence:
        lines += ["", "Evidence:"]
        lines += [f"- {e.description}" for e in evidence]
    return "\n".join(lines)


async def _resolve_report_repository(
    *, team_id: int, repository: str | None, title: str, summary: str, evidence: list[ReportEvidence]
) -> RepoSelectionResult | None:
    """Resolve the scout's `repository` input into a `repo_selection` artefact (or None to write none).

    Three modes mirror `custom_agent`: ``NO_REPO`` -> explicitly no repo; ``"owner/repo"`` -> that
    repo (validated, lowercased); omitted (None) -> free-form selection across the team's repos. The
    free-form path is the slow one — for a team with many repos it spawns a selection sandbox — so a
    scout that knows its repo should pass it explicitly (see the report contract). The cheap
    `NO_REPO` / `owner/repo` cases are validated by `_normalize_repository` up front (before the judge),
    so by here an explicit repo is already well-formed; only the free-form path remains."""
    repository = _normalize_repository(repository)
    if repository == NO_REPO:
        return RepoSelectionResult(repository=None, reason="Scout passed NO_REPO; report lands without a draft PR.")
    if repository is not None:
        return RepoSelectionResult(repository=repository, reason="Repository provided by the scout.")

    # Free-form: let the shared selector pick across the team's repos. Imports are deferred to keep the
    # temporal/agentic + sandbox stack off this harness-tool module's import path (it loads at worker boot).
    from products.signals.backend.report_generation.select_repo import (
        select_repository_for_team,  # noqa: PLC0415 — break worker-boot import cycle
    )
    from products.signals.backend.temporal.agentic import (  # noqa: PLC0415 — break worker-boot import cycle
        SIGNALS_REPO_DISCOVERY_ENV_NAME,
        get_or_create_signals_sandbox_env,
        resolve_user_id_for_team,
    )
    from products.signals.backend.temporal.agentic.select_repository import (
        GITHUB_ONLY_DOMAINS,  # noqa: PLC0415 — break worker-boot import cycle
    )
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415 — break worker-boot import cycle

    # A team with no GitHub integration can't resolve an acting user — `resolve_user_id_for_team`
    # raises. Repo selection / autostart is optional, so treat that as "no repo" (the report still
    # surfaces, just without a draft PR) rather than failing the whole emit — same null-repo outcome
    # the repo-selection activity returns for a GitHub-less team.
    try:
        user_id = await database_sync_to_async(resolve_user_id_for_team, thread_sensitive=False)(team_id)
    except Exception as exc:
        logger.info(
            "signals_scout.emit_report: skipping repo selection, no acting user for team",
            extra={"team_id": team_id, "error": str(exc)},
        )
        return RepoSelectionResult(repository=None, reason="No GitHub integration; report lands without a draft PR.")

    sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
        team_id,
        SIGNALS_REPO_DISCOVERY_ENV_NAME,
        tasks_facade.SandboxNetworkAccessLevel.CUSTOM,
        allowed_domains=GITHUB_ONLY_DOMAINS,
    )
    return await select_repository_for_team(
        team_id=team_id,
        user_id=user_id,
        request_section=_repo_request_section(title, summary, evidence),
        step_name="scout_repo_selection",
        sandbox_environment_id=sandbox_env_id,
    )


async def _maybe_autostart_report(*, team_id: int, report_id: str) -> None:
    """Best-effort autostart hand-off after a report surfaced. Reconstructs the autostart inputs from
    the report's artefacts (the same shared entry point the reviewer-edit hook uses) and swallows
    failures so a draft-PR hiccup never fails the emit. No-ops unless the report is immediately
    actionable, has a repo + priority, and a suggested reviewer clears their autonomy threshold."""
    from products.signals.backend.auto_start import (
        maybe_autostart_from_report_artefacts,  # noqa: PLC0415 — break worker-boot import cycle
    )

    try:
        await maybe_autostart_from_report_artefacts(team_id=team_id, report_id=report_id)
    except Exception:
        logger.exception("signals_scout.emit_report: autostart failed", extra={"report_id": report_id})


# Telemetry caps for the report content carried on the lifecycle events. The signal channel surfaces a
# finding's content on `signal_emitted` (via `_telemetry_props_from_extra`); the report channel now does
# the same so internal consumers (dashboards, alerts, CDP forwards) can act on a report's substance, not
# just its ids/status. Summary gets a wider cap than the signal channel's 256 — that limit silently clips
# real content — while still bounding the event payload.
#
# This is a deliberate, scoped exception to the signal channel's `extra`-passthrough policy (see the
# `_telemetry_props_from_extra` comment in `facade/api.py`). That policy keeps the opaque `extra` blob to
# truncated scalars because it can nest *uncurated* customer-derived content (raw SQL, replay history) the
# scout never authored. These fields are the opposite: a curated, scout-authored report title/summary —
# the deliberate product output — not an arbitrary nested blob. They're forwarded by name (no blob
# passthrough) and length-capped here, which is what makes carrying them acceptable.
#
# The summary cap must comfortably exceed what CDP forwards deliver downstream — a Slack forward posts
# the event's `summary` verbatim, so a cap below the authored length silently cuts the message mid-content
# (this happened at 2000). 10000 bounds the payload while leaving digest-style summaries intact; the
# report row itself allows up to MAX_REPORT_SUMMARY_LENGTH.
_MAX_TELEMETRY_SUMMARY_LEN = 10000
_MAX_TELEMETRY_TEXT_LEN = 1000


def _clip(value: str | None, limit: int) -> str | None:
    return value[:limit] if value is not None else None


# Values of the `report_kind` classification property on the report-channel lifecycle events.
REPORT_KIND_SELF_IMPROVEMENT = "self_improvement"
REPORT_KIND_FINDING = "finding"

# Tolerant matcher for `SELF_IMPROVEMENT_REPORT_TITLE_PREFIX` ("Scout self-improvement:"): anchored at
# the start of the title, but forgiving of the case, spacing, and hyphen drift LLM-authored titles show
# ("scout self improvement :", "  Scout Self-Improvement:"). A missed match silently undercounts the
# self-improvement funnel, so lenient-but-anchored beats exact. Keep in sync with the prompt constant.
_SELF_IMPROVEMENT_TITLE_RE = re.compile(r"^\s*scout\s+self[\s-]?improvement\s*:", re.IGNORECASE)
# Import-time guard: if the prompt's mandated prefix ever changes shape, classification must be
# updated with it — fail loudly here rather than silently undercounting.
assert _SELF_IMPROVEMENT_TITLE_RE.match(SELF_IMPROVEMENT_REPORT_TITLE_PREFIX)


def _report_classification_props(effective_title: str | None) -> dict[str, Any]:
    """Derived classification dimensions stamped on both report-channel lifecycle events (and their
    customer-facing copies): `report_kind` (enum, breakdown-friendly) + `is_self_improvement_report`
    (bool, filter-friendly). Classified server-side off the title contract the prompt mandates
    (`SELF_IMPROVEMENT_REPORT_TITLE_PREFIX`, matched leniently via `_SELF_IMPROVEMENT_TITLE_RE`) rather
    than scout-declared, so the flag can't be omitted by the model and needs no tool-schema change.
    This helper is the single extension point for future derived telemetry dimensions — add them here
    so the emit and edit events never drift apart."""
    is_self_improvement = _SELF_IMPROVEMENT_TITLE_RE.match(effective_title or "") is not None
    return {
        "report_kind": REPORT_KIND_SELF_IMPROVEMENT if is_self_improvement else REPORT_KIND_FINDING,
        "is_self_improvement_report": is_self_improvement,
    }


def _report_event_base(run: SignalScoutRun) -> dict[str, Any]:
    """Shared dimensions for the report-channel lifecycle events, mirroring the `signals_scout_run_*`
    events so the two join on `run_id` / `task_run_id` — a report event sits under the run that authored
    it. All fields are plain columns on the bridge row (no FK query)."""
    return {
        "skill_name": run.skill_name,
        "skill_version": run.skill_version,
        "scout_config_id": str(run.scout_config_id) if run.scout_config_id else None,
        "run_id": str(run.id),
        "task_run_id": str(run.task_run_id) if run.task_run_id else None,
    }


# Customer-facing copies of the report-channel lifecycle events, captured into the scout's *own team*
# project (via `capture_internal`) — distinct from the `signals_scout_report_*` events above, which go to
# PostHog's internal analytics via the `posthoganalytics` SDK. Landing them in the team's own event stream
# lets a team act on its scout reports with no PostHog-side wiring: HogQL/insights/alerts over the events,
# or a CDP destination (e.g. the Slack destination) filtering on the event and templating off `report_url`
# / `title` / `summary`. The `$` prefix marks a PostHog-generated event (cf. `$session_summary_ready`,
# `$ai_tag`), keeping them out of a customer's own custom-event namespace.
CUSTOMER_REPORT_EMITTED_EVENT = "$scout_report_emitted"
CUSTOMER_REPORT_EDITED_EVENT = "$scout_report_edited"
_REPORT_EVENT_SOURCE = "signals_scout_report"

# Gate-skip reasons that mean the scout isn't active — deliberately off (`scout_emit_disabled` /
# `source_disabled`) or fail-closed because its dispatch-time config is gone (`scout_config_missing`,
# from a deleted/nulled `SignalScoutConfig`). See `_preflight_emit_gates`. An inactive scout must produce
# no side effects, so its attempt is still recorded on the internal stream but is NOT fanned out as a
# customer-facing, automation-driving event. Other gate-skips that represent a real, customer-controlled
# condition (e.g. `ai_processing_not_approved`) still forward the raw event.
_INACTIVE_SKIP_REASONS = frozenset({"scout_emit_disabled", "source_disabled", "scout_config_missing"})


@dataclass
class _ReportForward:
    """The payload for the customer-facing fan-out, built on the sync/DB thread and handed to
    `_forward_report_event_to_team` — so the blocking `capture_internal` HTTP can be offloaded off the
    DB-thread pool (via `asyncio.to_thread` on the async path) instead of running inside it."""

    event_name: str
    distinct_id: str
    event_uuid: str
    properties: dict[str, Any]


def _report_url(team_id: int, report_id: str | None) -> str | None:
    """Inbox deep link for an authored report, or None when no report exists yet (gate-skipped emit). The
    canonical form used by the Slack inbox notifications (`slack_inbox_notifications.py`)."""
    if not report_id:
        return None
    return f"{settings.SITE_URL}/project/{team_id}/inbox/reports/{report_id}"


def _report_event_uuid(*parts: object) -> str:
    """Deterministic event uuid from the parts that identify a distinct emit/edit. A retried capture of the
    same authored report (or an identical re-applied edit) collapses to one event at ingestion instead of
    double-firing a destination — `emit_report`/`edit_report` are non-idempotent, so the same logical action
    can reach this path more than once. Distinct actions (a different report, a different edit) differ in
    the parts and stay separate events."""
    key = "|".join("" if part is None else str(part) for part in parts)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"signals_scout_report:{key}"))


def _forward_report_event_to_team(*, team: Team, forward: _ReportForward) -> None:
    """Mirror a report-channel lifecycle event into the scout's own team project through the sanctioned
    `capture_internal` path, so the team can drive HogQL / alerts / CDP destinations off its reports.
    Person processing is OFF with a synthetic per-scout `distinct_id` — a report is the scout's output, not
    an end-user action, so it must never create or merge a person profile. `capture_internal` is a blocking
    HTTP call (2s default timeout); the async callers offload it via `asyncio.to_thread` so it never holds a
    DB-thread-pool thread. Best-effort: a forward failure must never fail or mask the emit/edit (it only
    feeds downstream automation)."""
    try:
        capture_internal(
            token=team.api_token,
            event_name=forward.event_name,
            event_source=_REPORT_EVENT_SOURCE,
            distinct_id=forward.distinct_id,
            properties=forward.properties,
            event_uuid=forward.event_uuid,
            process_person_profile=False,
        ).raise_for_status()
    except Exception:
        logger.warning(
            "signals_scout: failed to forward report event %s to team project",
            forward.event_name,
            extra={"team_id": team.id, "distinct_id": forward.distinct_id},
        )


async def _forward_report_event_async(team: Team, forward: _ReportForward | None) -> None:
    """Offload the blocking customer-facing forward to a worker thread on the async path, keeping the
    DB-thread pool free for DB work (mirrors the `$session_summary_ready` `asyncio.to_thread` pattern).
    No-op when the capture decided not to fan out (a disabled / dry-run gate-skip)."""
    if forward is not None:
        await asyncio.to_thread(_forward_report_event_to_team, team=team, forward=forward)


def _capture_report_emitted(
    *,
    team: Team,
    run: SignalScoutRun,
    result: EmitReportResult,
    evidence_count: int,
    title: str,
    summary: str,
    actionability: str,
    already_addressed: bool,
    priority: str | None,
    repository: str | None,
) -> _ReportForward | None:
    """Emit the scout-owned `signals_scout_report_emitted` event — the report-channel counterpart to
    `signals_scout_run_finished`, fired once per `emit_report` call that reached a terminal outcome.

    `outcome` is the single dimension to segment the channel funnel on: `gate_skipped` (a preflight gate
    stopped the call before any report existed), `suppressed` (authored but the judge / actionability kept
    it out of the inbox), or `surfaced` (landed in the inbox as READY / PENDING_INPUT). The event also
    carries the report's content (`title` / `summary` / `actionability` / `priority` / `repository` /
    `safety_explanation`) — parity with the signal channel's `signal_emitted`, so internal consumers
    (dashboards, alerts, CDP forwards) can act on a report's substance, not just its ids. Content rides
    every outcome, including `gate_skipped` (it records what would have been authored). Also stamped
    with the derived classification dimensions (`_report_classification_props`) so e.g. self-improvement
    reports are separable from findings without title heuristics downstream. Keyed on the team
    and carrying the run / task ids so it joins to the run lifecycle events. Best-effort: a capture failure
    must never fail or mask the emit. Accesses `team.organization` — call on a sync thread.

    Returns the customer-facing fan-out payload for the caller to forward, or None to suppress the
    fan-out — a disabled / dry-run gate-skip records the attempt on the internal stream here but must
    not fire an automation-driving event into the team's own project."""
    if result.skipped_reason is not None:
        outcome = "gate_skipped"
    elif result.emitted:
        outcome = "surfaced"
    else:
        outcome = "suppressed"
    properties = {
        **_report_event_base(run),
        **_report_classification_props(title),
        "report_id": result.report_id,
        "status": result.status,
        "outcome": outcome,
        "skipped_reason": result.skipped_reason,
        "evidence_count": evidence_count,
        "title": title,
        "summary": _clip(summary, _MAX_TELEMETRY_SUMMARY_LEN),
        "actionability": actionability,
        "already_addressed": already_addressed,
        "priority": priority,
        "repository": repository,
        "safety_explanation": _clip(result.safety_explanation, _MAX_TELEMETRY_TEXT_LEN),
        "report_url": _report_url(team.id, result.report_id),
    }
    try:
        posthoganalytics.capture(
            event="signals_scout_report_emitted",
            distinct_id=str(team.uuid),
            properties=properties,
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture report-emitted analytics event",
            extra={"team_id": team.id, "run_id": str(run.id), "skill_name": run.skill_name},
        )
    if result.skipped_reason in _INACTIVE_SKIP_REASONS:
        return None
    return _ReportForward(
        event_name=CUSTOMER_REPORT_EMITTED_EVENT,
        distinct_id=f"signals_scout:{run.skill_name}",
        event_uuid=_report_event_uuid("emit", run.id, result.report_id, title),
        properties=properties,
    )


def _capture_report_edited(
    *,
    team: Team,
    run: SignalScoutRun,
    result: EditReportResult,
    title: str | None,
    summary: str | None,
    note: str | None,
    suggested_reviewers: list[ReviewerInput] | None = None,
) -> _ReportForward:
    """Emit the scout-owned `signals_scout_report_edited` event when a scout mutates an existing report via
    `edit_report`, so edits are observable separately from fresh authorship. `updated_fields` /
    `note_appended` / `reviewers_set` distinguish a title/summary rewrite from a note-only append from a
    reviewer (re-routing) change; `title` / `summary` / `note` carry the content the edit applied (each None
    when that field wasn't touched) — parity with the emit event so a consumer sees *what* changed, not just
    that something did. Classification (`_report_classification_props`) reads `result.report_title` — the
    report's effective title after the edit — so a note-only append to a self-improvement report still
    classifies correctly. Best-effort; never fails the edit. Accesses `team.organization` — call on a sync
    thread. Returns the customer-facing fan-out payload for the caller to forward."""
    properties = {
        **_report_event_base(run),
        **_report_classification_props(result.report_title),
        "report_id": result.report_id,
        "updated_fields": result.updated_fields,
        "note_appended": result.note_appended,
        "reviewers_set": result.reviewers_set,
        "title": _clip(title, MAX_REPORT_TITLE_LENGTH),
        "summary": _clip(summary, _MAX_TELEMETRY_SUMMARY_LEN),
        "note": _clip(note, _MAX_TELEMETRY_TEXT_LEN),
        "report_url": _report_url(team.id, result.report_id),
    }
    try:
        posthoganalytics.capture(
            event="signals_scout_report_edited",
            distinct_id=str(team.uuid),
            properties=properties,
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture report-edited analytics event",
            extra={"team_id": team.id, "run_id": str(run.id), "skill_name": run.skill_name},
        )
    # Sort `updated_fields` so a retried edit that changed the same set hashes to one `event_uuid` — the
    # set's iteration order isn't guaranteed stable across worker processes, and an unstable key would
    # double-fire a destination on retry. A reviewer-only edit carries no `updated_fields` and no
    # title/summary/note, so two distinct reviewer corrections to the same report in one run would
    # otherwise hash identically and ingestion would collapse the later routing change; key on the
    # reviewer identity too (only when reviewers were set, so non-reviewer edits keep their existing uuid).
    parts: list[object] = ["edit", run.id, result.report_id, sorted(result.updated_fields), title, summary, note]
    if result.reviewers_set and suggested_reviewers:
        parts.append(",".join(sorted(f"{r.github_login or ''}:{r.user_uuid or ''}" for r in suggested_reviewers)))
    return _ReportForward(
        event_name=CUSTOMER_REPORT_EDITED_EVENT,
        distinct_id=f"signals_scout:{run.skill_name}",
        event_uuid=_report_event_uuid(*parts),
        properties=properties,
    )


async def emit_report(
    *,
    team: Team,
    run: SignalScoutRun,
    title: str,
    summary: str,
    evidence: list[ReportEvidence],
    actionability_explanation: str,
    actionability: str,
    already_addressed: bool = False,
    repository: str | None = None,
    priority: str | None = None,
    priority_explanation: str | None = None,
    suggested_reviewers: list[ReviewerInput] | None = None,
) -> EmitReportResult:
    """Author a full report: judge for safety, then persist at the judged status. Async entry (used by
    the in-Temporal runner); routes the sync DB work through `database_sync_to_async`.

    `repository` / `priority` / `priority_explanation` / `suggested_reviewers` are the optional
    autostart inputs (custom_agent parity): with them a surfaced, immediately-actionable report can
    open a draft PR. They're only resolved/written when the report actually surfaces."""
    _assert_team_owns_run(team, run)
    _validate_emit_inputs(title, summary, evidence)
    # Validate the explicit repository format up front (cheap, pure) so a malformed `owner/repo` fails
    # before the safety-judge LLM call rather than after. Free-form selection still runs only if surfaced.
    _normalize_repository(repository)
    signals = _build_signals(evidence)
    actionability_assessment = _build_actionability(
        explanation=actionability_explanation, choice=actionability, already_addressed=already_addressed
    )
    priority_assessment = _build_priority(priority, priority_explanation)
    # Resolves user_uuid → github_login (a DB read), so bridge it off the event loop. Runs before the
    # safety judge so an unresolvable reviewer fails fast rather than after paying for the LLM call.
    reviewers = await database_sync_to_async(_build_suggested_reviewers, thread_sensitive=False)(
        team.id, suggested_reviewers
    )

    preflight = await database_sync_to_async(_preflight_emit_gates, thread_sensitive=False)(team, run)
    if preflight is not None:
        result = _gate_skip_result(preflight)
        forward = await database_sync_to_async(_capture_report_emitted, thread_sensitive=False)(
            team=team,
            run=run,
            result=result,
            evidence_count=len(evidence),
            title=title,
            summary=summary,
            actionability=actionability,
            already_addressed=already_addressed,
            priority=priority,
            repository=repository,
        )
        await _forward_report_event_async(team, forward)
        return result

    task_id = await database_sync_to_async(_resolve_task_id, thread_sensitive=False)(run)
    attribution = _attribution_for(task_id)
    judgement = await judge_scout_report(
        team_id=team.id, title=title, summary=summary, signals=signals, actionability=actionability_assessment
    )
    surfaced = _surfaced(judgement.status)
    repo_selection = (
        await _resolve_report_repository(
            team_id=team.id, repository=repository, title=title, summary=summary, evidence=evidence
        )
        if surfaced and _wants_repo_selection(repository, priority_assessment, reviewers)
        else None
    )
    persisted = await database_sync_to_async(create_scout_report, thread_sensitive=False)(
        team_id=team.id,
        title=title,
        summary=summary,
        signals=signals,
        attribution=attribution,
        status=judgement.status,
        safety=judgement.safety,
        actionability=judgement.actionability,
        repo_selection=repo_selection,
        priority=priority_assessment if surfaced else None,
        suggested_reviewers=reviewers if surfaced else None,
        # Don't index the backing observations of a safety-suppressed (unsafe) report — they'd
        # otherwise become semantic-search / matching context despite never surfacing.
        emit_signals=judgement.safety.choice,
        run=run,
    )
    if surfaced:
        await _maybe_autostart_report(team_id=team.id, report_id=persisted.report_id)
    result = _emit_result(persisted.report_id, judgement)
    forward = await database_sync_to_async(_capture_report_emitted, thread_sensitive=False)(
        team=team,
        run=run,
        result=result,
        evidence_count=len(evidence),
        title=title,
        summary=summary,
        actionability=actionability,
        already_addressed=already_addressed,
        priority=priority,
        repository=repository,
    )
    await _forward_report_event_async(team, forward)
    return result


def emit_report_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    title: str,
    summary: str,
    evidence: list[ReportEvidence],
    actionability_explanation: str,
    actionability: str,
    already_addressed: bool = False,
    repository: str | None = None,
    priority: str | None = None,
    priority_explanation: str | None = None,
    suggested_reviewers: list[ReviewerInput] | None = None,
) -> EmitReportResult:
    """Sync entry used by the DRF view path. Mirrors `emit_report` but keeps the sync DB work on the
    calling thread/connection (gates, persist) — only the safety-judge LLM call, the free-form repo
    selection, and the autostart hand-off are bridged via `async_to_sync` (each runs before/after the
    report transaction, so they don't share its connection). Wrapping the whole async function instead
    would run every DB op on a separate connection, which a request's transaction can't see."""
    _assert_team_owns_run(team, run)
    _validate_emit_inputs(title, summary, evidence)
    # Validate the explicit repository format up front (cheap, pure) so a malformed `owner/repo` fails
    # before the safety-judge LLM call rather than after. Free-form selection still runs only if surfaced.
    _normalize_repository(repository)
    signals = _build_signals(evidence)
    actionability_assessment = _build_actionability(
        explanation=actionability_explanation, choice=actionability, already_addressed=already_addressed
    )
    priority_assessment = _build_priority(priority, priority_explanation)
    reviewers = _build_suggested_reviewers(team.id, suggested_reviewers)

    preflight = _preflight_emit_gates(team, run)
    if preflight is not None:
        result = _gate_skip_result(preflight)
        forward = _capture_report_emitted(
            team=team,
            run=run,
            result=result,
            evidence_count=len(evidence),
            title=title,
            summary=summary,
            actionability=actionability,
            already_addressed=already_addressed,
            priority=priority,
            repository=repository,
        )
        if forward is not None:
            _forward_report_event_to_team(team=team, forward=forward)
        return result

    task_id = _resolve_task_id(run)
    attribution = _attribution_for(task_id)
    judgement = async_to_sync(judge_scout_report)(
        team_id=team.id, title=title, summary=summary, signals=signals, actionability=actionability_assessment
    )
    surfaced = _surfaced(judgement.status)
    repo_selection = (
        async_to_sync(_resolve_report_repository)(
            team_id=team.id, repository=repository, title=title, summary=summary, evidence=evidence
        )
        if surfaced and _wants_repo_selection(repository, priority_assessment, reviewers)
        else None
    )
    persisted = create_scout_report(
        team_id=team.id,
        title=title,
        summary=summary,
        signals=signals,
        attribution=attribution,
        status=judgement.status,
        safety=judgement.safety,
        actionability=judgement.actionability,
        repo_selection=repo_selection,
        priority=priority_assessment if surfaced else None,
        suggested_reviewers=reviewers if surfaced else None,
        # Don't index the backing observations of a safety-suppressed (unsafe) report — they'd
        # otherwise become semantic-search / matching context despite never surfacing.
        emit_signals=judgement.safety.choice,
        run=run,
    )
    if surfaced:
        async_to_sync(_maybe_autostart_report)(team_id=team.id, report_id=persisted.report_id)
    result = _emit_result(persisted.report_id, judgement)
    forward = _capture_report_emitted(
        team=team,
        run=run,
        result=result,
        evidence_count=len(evidence),
        title=title,
        summary=summary,
        actionability=actionability,
        already_addressed=already_addressed,
        priority=priority,
        repository=repository,
    )
    if forward is not None:
        _forward_report_event_to_team(team=team, forward=forward)
    return result


def _do_edit_report(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str | None,
    summary: str | None,
    append_note: str | None,
    suggested_reviewers: list[ReviewerInput] | None,
) -> EditReportResult:
    """Fully-sync edit core (no LLM step). The async/sync entrypoints both funnel here — directly in
    the sync path, via `database_sync_to_async` in the async path. Reviewer resolution does a DB read
    and the autostart re-eval bridges an async hand-off via `async_to_sync`, both safe on this sync
    thread."""
    preflight = _preflight_emit_gates(team, run)
    if preflight is not None:
        raise InvalidScoutReportError(f"edit_report blocked by preflight gate: {preflight}")

    attribution = _attribution_for(_resolve_task_id(run))
    # Resolve reviewers *before* any write. Resolution (user_uuid → login) is the only step that can
    # reject caller input — an unresolvable user_uuid raises, which the view turns into a 400. Doing it
    # first means a combined edit (title/summary + a bad reviewer) fails before the content write
    # commits, rather than leaving the report partially mutated behind a failed call.
    reviewers = _build_suggested_reviewers(team.id, suggested_reviewers)

    updated_fields: list[str] = []
    if title is not None or summary is not None:
        updated_fields = update_scout_report(
            team_id=team.id,
            report_id=report_id,
            title=title,
            summary=summary,
            attribution=attribution,
            author=run.skill_name,
        )
    # Replace the report's `suggested_reviewers` status artefact (latest-wins). This is the routing
    # fix — a report authored without a reviewer (so it routes to no one) can have one added after the
    # fact. `reviewers` is None for empty/all-blank input, which leaves existing reviewers untouched.
    reviewers_set = (
        set_scout_report_reviewers(
            team_id=team.id,
            report_id=report_id,
            suggested_reviewers=reviewers,
            attribution=attribution,
            author=run.skill_name,
        )
        if reviewers is not None
        else False
    )
    note_appended = False
    if append_note is not None:
        append_report_note(
            team_id=team.id, report_id=report_id, note=append_note, attribution=attribution, author=run.skill_name
        )
        note_appended = True
    # Re-run autostart only when reviewers changed: it's idempotent (a report with an implementation
    # task already started no-ops), but a report that was missing a qualifying reviewer can now open a
    # draft PR. Fired outside any txn since it spawns a Task — mirrors emit's post-commit hand-off.
    if reviewers_set:
        async_to_sync(_maybe_autostart_report)(team_id=team.id, report_id=report_id)
    logger.info(
        "signals_scout.edit_report: edited",
        extra={
            "team_id": team.id,
            "report_id": report_id,
            "fields": updated_fields,
            "note": note_appended,
            "reviewers_set": reviewers_set,
        },
    )
    # Resolve the report's effective title for the edited event's classification — the rewritten title
    # when this edit set one, else the stored title (one indexed read; the edits above already proved
    # the report exists for this team). Telemetry-only and best-effort: the edit has already committed,
    # so a transient read failure here must not fail the call (or skip the tally below) — degrade to an
    # unclassified event instead.
    report_title: str | None = title
    if report_title is None:
        try:
            report_title = get_scout_report_title(team_id=team.id, report_id=report_id)
        except Exception:
            logger.warning(
                "signals_scout.edit_report: failed to resolve report title for telemetry",
                extra={"team_id": team.id, "report_id": report_id},
            )
    result = EditReportResult(
        report_id=report_id,
        updated_fields=updated_fields,
        note_appended=note_appended,
        reviewers_set=reviewers_set,
        report_title=report_title,
    )
    # Record the edit on the run tally only when something actually changed — a no-op edit (e.g. a
    # title rewrite to its current value) must not claim the run touched the report.
    if updated_fields or note_appended or reviewers_set:
        record_report_edit(team_id=team.id, run_id=run.id, report_id=report_id)
    return result


def _validate_edit_inputs(team: Team, run: SignalScoutRun, title, summary, append_note, suggested_reviewers) -> None:
    _assert_team_owns_run(team, run)
    if title is None and summary is None and append_note is None and not suggested_reviewers:
        raise InvalidScoutReportError(
            "edit_report needs at least one of title, summary, append_note, suggested_reviewers"
        )


async def edit_report(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str | None = None,
    summary: str | None = None,
    append_note: str | None = None,
    suggested_reviewers: list[ReviewerInput] | None = None,
) -> EditReportResult:
    """Edit an existing inbox report: rewrite title/summary, append a note, and/or set suggested
    reviewers (which re-runs autostart so a report missing a qualifying reviewer can open a draft PR).
    Team-scoped fail-closed in the service. Async entry; runs the sync edit core in the thread pool."""
    _validate_edit_inputs(team, run, title, summary, append_note, suggested_reviewers)
    result = await database_sync_to_async(_do_edit_report, thread_sensitive=False)(
        team=team,
        run=run,
        report_id=report_id,
        title=title,
        summary=summary,
        append_note=append_note,
        suggested_reviewers=suggested_reviewers,
    )
    forward = await database_sync_to_async(_capture_report_edited, thread_sensitive=False)(
        team=team,
        run=run,
        result=result,
        title=title,
        summary=summary,
        note=append_note,
        suggested_reviewers=suggested_reviewers,
    )
    await _forward_report_event_async(team, forward)
    return result


def edit_report_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str | None = None,
    summary: str | None = None,
    append_note: str | None = None,
    suggested_reviewers: list[ReviewerInput] | None = None,
) -> EditReportResult:
    """Sync entry used by the DRF view path. Same behavior as `edit_report`, on the calling thread."""
    _validate_edit_inputs(team, run, title, summary, append_note, suggested_reviewers)
    result = _do_edit_report(
        team=team,
        run=run,
        report_id=report_id,
        title=title,
        summary=summary,
        append_note=append_note,
        suggested_reviewers=suggested_reviewers,
    )
    forward = _capture_report_edited(
        team=team,
        run=run,
        result=result,
        title=title,
        summary=summary,
        note=append_note,
        suggested_reviewers=suggested_reviewers,
    )
    _forward_report_event_to_team(team=team, forward=forward)
    return result
