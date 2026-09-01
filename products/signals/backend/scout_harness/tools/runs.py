"""Run-history tools: read access to past `SignalScoutRun` rows for the team.

These are the agent's window into what previous runs concluded. Used for best-effort
dedupe ("have I seen this hypothesis recently?") and continuity ("what was I
working on yesterday?"). Strictly team-scoped — no cross-team reads.

`SignalScoutRun` is a thin bridge to `tasks.TaskRun`: status, timestamps, and
error all flow from the linked TaskRun via `select_related("task_run")`. The
scout-owned content on the row itself is `summary` — the one-paragraph close-out
the agent emits at end_turn, used as the dedupe key for runs that didn't emit any
findings (and so left no `Signal` row to query against) — plus the
`emitted_count` / `emitted_finding_ids` emit tally bumped post-success by
`emit_finding`. Findings are recoverable as emitted `Signal` rows keyed by
`source_id = run:<run_id>:finding:<finding_id>`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.db import connection
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog
from croniter import CroniterError, croniter

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.limits import MAX_ENABLED_SCOUTS_PER_TEAM
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

# Defensive caps so a runaway agent loop can't pull thousands of rows in one call.
DEFAULT_RUN_SEARCH_LIMIT = 20
MAX_RUN_SEARCH_LIMIT = 100

# The per-scout run window backing the inbox scout surfaces. 25 runs covers a day for an hourly
# scout and a month for a daily one — the point being that both get enough history to judge, which
# a single fleet-wide time window can't do.
DEFAULT_RUNS_PER_SCOUT = 25
MAX_RUNS_PER_SCOUT = 100

# The staleness guard, so a scout that stopped running doesn't render its last runs as current.
# `..._MAX_AGE_DAYS` is a floor rather than a fixed cutoff: `run_interval_minutes` allows up to
# 43200 (30 days), which is the floor exactly, so a scout on the slowest supported cadence would
# have its whole history cut the moment dispatch slipped by a minute. Each scout's own cadence
# extends its lookback to `STALENESS_INTERVAL_MULTIPLE` runs' worth, capped at the ceiling.
DEFAULT_RUNS_PER_SCOUT_MAX_AGE_DAYS = 30
MAX_RUNS_PER_SCOUT_MAX_AGE_DAYS = 365
STALENESS_INTERVAL_MULTIPLE = 3
# A cron schedule has no interval to read, so sample its next few gaps and take the widest — a
# monthly cron reads as ~31 days, a weekday-only one as the weekend gap.
CRON_GAP_SAMPLES = 4

# Bounds the fan-out of the per-scout probe. Deliberately a limit on *scouts* rather than on rows:
# capping rows after the per-scout ranking would drop the slowest scouts' history, which is the
# exact crowd-out this query exists to remove. A scout that makes the cut gets its full history.
MAX_SCOUTS_PER_RUNS_QUERY = MAX_ENABLED_SCOUTS_PER_TEAM

# The "Scout findings" callout summary tallies findings over a fixed lookback window. The default
# window, the run cap, and the report cap mirror the cloud/desktop frontend
# (`SCOUT_RUNS_WINDOW_HOURS = 72` / `MAX_FLEET_EMITTED_RUNS = 120` / `MAX_FLEET_TOUCHED_REPORTS = 50`)
# so the callout counts match the set the findings page renders; the max window bounds a
# pathological lookback.
DEFAULT_FINDINGS_WINDOW_HOURS = 72
MAX_FINDINGS_WINDOW_HOURS = 168
FLEET_FINDINGS_SUMMARY_RUN_CAP = 120
FLEET_FINDINGS_SUMMARY_REPORT_CAP = 50

# `failure_reason` is the concise, list-safe derived signal; `error` carries the full
# `TaskRun.error_message`. Bound the derived reason so it stays cheap to scan in bulk.
MAX_FAILURE_REASON_LENGTH = 500


@dataclass(frozen=True)
class RunSummary:
    """Lightweight projection of a run row — what's needed to scan and pick one."""

    run_id: str
    skill_name: str
    skill_version: int
    status: str
    # `created_at` is the bridge row's own timestamp — the field `search_recent_runs`
    # filters and orders on, hence the cursor key for walking past the result cap.
    # `started_at` is the linked TaskRun's creation time and can differ slightly.
    created_at: str
    started_at: str
    completed_at: str | None
    summary: str
    emitted_count: int = 0
    emitted_finding_ids: list[str] = field(default_factory=list)
    # Reports authored via the `emit_report` channel — separate from `emitted_count`/`emitted_finding_ids`
    # (which count weak `emit_signal` findings), so a run that only authored a report still reads as
    # having emitted something.
    emitted_report_ids: list[str] = field(default_factory=list)
    # Reports this run *mutated* via the `edit_report` channel (rewrote title/summary and/or appended a
    # note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are
    # generally not reports the run authored. Lets "which reports did this run edit?" be a column lookup.
    edited_report_ids: list[str] = field(default_factory=list)
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None
    # `error` is the full `TaskRun.error_message`; `failure_reason` is the concise derived
    # one-liner. Both are surfaced only for failed/cancelled runs — null otherwise (incl. success).
    error: str | None = None
    failure_reason: str | None = None
    # Scout-owned per-run context: runner-stamped keys from run creation (today: the routed model
    # triple `model` / `runtime_adapter` / `reasoning_effort`) plus the nested `derived` map of
    # harness-computed run flags written at finalize. Empty for default-model runs that never
    # finalized, and for rows predating the column.
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunDetail:
    """Full run row — call `get_run` to fetch this when a `RunSummary` looks relevant.

    Same fields as `RunSummary` today; kept distinct so future detail-only
    extensions (linked Signal rows, LLMA token-cost join) can land here without
    bloating the list projection.
    """

    run_id: str
    skill_name: str
    skill_version: int
    status: str
    created_at: str
    started_at: str
    completed_at: str | None
    summary: str
    emitted_count: int = 0
    emitted_finding_ids: list[str] = field(default_factory=list)
    # Reports authored via the `emit_report` channel — separate from `emitted_count`/`emitted_finding_ids`
    # (which count weak `emit_signal` findings), so a run that only authored a report still reads as
    # having emitted something.
    emitted_report_ids: list[str] = field(default_factory=list)
    # Reports this run *mutated* via the `edit_report` channel (rewrote title/summary and/or appended a
    # note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are
    # generally not reports the run authored. Lets "which reports did this run edit?" be a column lookup.
    edited_report_ids: list[str] = field(default_factory=list)
    task_id: str | None = None
    task_run_id: str | None = None
    task_url: str | None = None
    # `error` is the full `TaskRun.error_message`; `failure_reason` is the concise derived
    # one-liner. Both are surfaced only for failed/cancelled runs — null otherwise (incl. success).
    error: str | None = None
    failure_reason: str | None = None
    # Scout-owned per-run context: runner-stamped keys from run creation (today: the routed model
    # triple `model` / `runtime_adapter` / `reasoning_effort`) plus the nested `derived` map of
    # harness-computed run flags written at finalize. Empty for default-model runs that never
    # finalized, and for rows predating the column.
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_recent_runs(
    *,
    team_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    text: str | None = None,
    emitted: bool | None = None,
    skill_name: str | None = None,
    skill_version: int | None = None,
    limit: int = DEFAULT_RUN_SEARCH_LIMIT,
) -> list[RunSummary]:
    """Return the most recent runs for a team, newest first.

    `date_from` / `date_to` are a half-open time window on `created_at` (the
    bridge-row insert timestamp, which fires right after `MultiTurnSession.start`)
    — `created_at >= date_from` and `created_at < date_to`. Pass `date_to` to walk
    backwards past the result cap on subsequent calls (cursor-style iteration).
    `text` is a case-insensitive substring match on the agent's end-of-run
    `summary` — the primary dedupe path for runs that didn't emit findings.
    `emitted` filters on emit outcome: `True` keeps only runs that emitted at least
    one finding *or* authored a report (`emitted_count > 0` or a non-empty
    `emitted_report_ids`), `False` keeps only runs that emitted nothing on either
    channel; omit it for both. `skill_name` is an exact-match filter that narrows the dump to
    a single scout — the primary scoping path for a specialist deduping against its
    own past work; pair it with `skill_version` to pin a specific version. Results
    are capped at `MAX_RUN_SEARCH_LIMIT`.
    """
    clamped_limit = _clamp_limit(limit)
    qs = SignalScoutRun.objects.filter(team_id=team_id).select_related("task_run").order_by("-created_at")
    if date_from is not None:
        qs = qs.filter(created_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(created_at__lt=date_to)
    if text:
        qs = qs.filter(summary__icontains=text)
    if emitted is not None:
        # A run "emitted" if it surfaced a weak finding (emitted_count) or authored a report
        # (emitted_report_ids). Treat null/[] report lists as empty for the negative case.
        emitted_a_report = ~Q(emitted_report_ids=[]) & ~Q(emitted_report_ids__isnull=True)
        if emitted:
            qs = qs.filter(Q(emitted_count__gt=0) | emitted_a_report)
        else:
            qs = qs.filter(emitted_count=0).filter(Q(emitted_report_ids=[]) | Q(emitted_report_ids__isnull=True))
    if skill_name:
        qs = qs.filter(skill_name=skill_name)
    if skill_version is not None:
        qs = qs.filter(skill_version=skill_version)
    qs = qs[:clamped_limit]
    return [_to_summary(row, team_id=team_id) for row in qs]


def _schedule_gap_minutes(config: SignalScoutConfig) -> int:
    """How long this scout is expected to go between runs, in minutes.

    A cron schedule has no interval field, so sample its next few occurrences and take the widest
    gap — an irregular expression (weekdays only, monthly) has to be judged by its longest quiet
    stretch, not its shortest. Falls back to the rolling interval when the expression can't be read.
    """
    if not config.run_cron_schedule:
        return config.run_interval_minutes
    try:
        iterator = croniter(config.run_cron_schedule, timezone.now())
        previous: datetime = iterator.get_next(datetime)
        widest = 0.0
        for _ in range(CRON_GAP_SAMPLES):
            occurrence: datetime = iterator.get_next(datetime)
            widest = max(widest, (occurrence - previous).total_seconds() / 60)
            previous = occurrence
        return int(widest) or config.run_interval_minutes
    except (CroniterError, ValueError):
        # A stored expression the coordinator can't read either — the scout isn't running on it,
        # so its rolling interval is the honest estimate.
        return config.run_interval_minutes


def _staleness_cutoff(config: SignalScoutConfig, *, now: datetime, floor_days: int) -> datetime:
    """The oldest run worth showing for this scout.

    Cadence-aware on purpose: a fixed cutoff at the floor would erase the entire history of a scout
    on the slowest supported cadence (`run_interval_minutes` allows exactly 43200, i.e. the 30-day
    default), or on a monthly cron, the moment dispatch slipped past it — reporting "no runs" for a
    scout running exactly as configured.
    """
    cadence_days = (_schedule_gap_minutes(config) * STALENESS_INTERVAL_MULTIPLE) / (60 * 24)
    lookback_days = min(max(floor_days, cadence_days), MAX_RUNS_PER_SCOUT_MAX_AGE_DAYS)
    return now - timedelta(days=lookback_days)


def recent_runs_per_scout(
    *,
    team_id: int,
    per_scout_limit: int = DEFAULT_RUNS_PER_SCOUT,
    max_age_days: int = DEFAULT_RUNS_PER_SCOUT_MAX_AGE_DAYS,
) -> list[RunSummary]:
    """Return each configured scout's most recent runs, newest first across the fleet.

    A cadence-invariant alternative to `search_recent_runs`' fixed time window. A fleet-wide
    lookback has to serve an hourly scout and a weekly one from one budget: widen it and the busy
    scouts fill the result cap, leaving the sparse ones with a history that gets shorter the
    healthier the rest of the fleet is. Probing per scout gives every scout the same depth of
    history no matter its schedule, and bounds the read at scouts x `per_scout_limit` instead of at
    "however many runs the fleet happened to do".

    The scouts come from `SignalScoutConfig`, which does three things at once: it constrains
    `skill_name` so the `(team, skill_name, created_at)` index can bound each probe to the rows it
    returns (a fleet-wide scan can't, since an unconstrained `skill_name` sits between the two
    predicates); it keeps runs of deleted and renamed scouts out of the fleet rollups, which read
    their stats off whatever skill names appear here; and it carries the schedule each scout's
    staleness cutoff is derived from.

    `max_age_days` is the floor of that cutoff, not a fixed window — see `_staleness_cutoff`.
    """
    per_scout_limit = max(1, min(per_scout_limit, MAX_RUNS_PER_SCOUT))
    floor_days = max(1, min(max_age_days, MAX_RUNS_PER_SCOUT_MAX_AGE_DAYS))
    now = timezone.now()

    # Enabled first so that if a fleet ever exceeds the bound, the scouts dropped are the ones
    # nobody is watching run. Ordered within each group for a deterministic cut.
    configs = list(
        SignalScoutConfig.objects.filter(team_id=team_id)
        .order_by("-enabled", "skill_name")
        .only("skill_name", "run_interval_minutes", "run_cron_schedule", "enabled")
    )
    if len(configs) > MAX_SCOUTS_PER_RUNS_QUERY:
        # Never silently: a truncated fleet reads as a complete one on every surface downstream.
        logger.warning(
            "signals_scout_runs_per_scout_fleet_truncated",
            team_id=team_id,
            scout_count=len(configs),
            bound=MAX_SCOUTS_PER_RUNS_QUERY,
            dropped=[config.skill_name for config in configs[MAX_SCOUTS_PER_RUNS_QUERY:]],
        )
        configs = configs[:MAX_SCOUTS_PER_RUNS_QUERY]
    if not configs:
        return []

    # One probe per scout via LATERAL, each an indexed top-N over
    # `(team_id, skill_name, created_at DESC)` — all three keys constrained, so a probe reads
    # `per_scout_limit` index entries rather than walking the team's whole run history and
    # filtering. The ORM has no LATERAL, and the alternatives are worse: a window function over the
    # fleet can't bound its scan, and a query per scout is one round trip per scout on a 60s poll.
    # Team scoping is explicit in the predicate, standing in for the fail-closed manager raw SQL
    # bypasses; `skill_name` and the cutoffs are bound parameters, never interpolated.
    probe_values = ", ".join(["(%s::text, %s::timestamptz)"] * len(configs))
    params: list[Any] = []
    for config in configs:
        params.extend([config.skill_name, _staleness_cutoff(config, now=now, floor_days=floor_days)])
    params.extend([team_id, per_scout_limit])
    sql = f"""
        SELECT probe.id
        FROM (VALUES {probe_values}) AS scout(skill_name, cutoff)
        CROSS JOIN LATERAL (
            SELECT run.id
            FROM {SignalScoutRun._meta.db_table} run
            WHERE run.team_id = %s
              AND run.skill_name = scout.skill_name
              AND run.created_at >= scout.cutoff
            ORDER BY run.created_at DESC
            LIMIT %s
        ) probe
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        run_ids = [row[0] for row in cursor.fetchall()]
    if not run_ids:
        return []

    rows = (
        SignalScoutRun.objects.filter(team_id=team_id, id__in=run_ids)
        .select_related("task_run")
        .order_by("-created_at")
    )
    return [_to_summary(row, team_id=team_id) for row in rows]


@dataclass(frozen=True)
class FleetFindingsSummary:
    """Cheap fleet-wide tally of recent scout output — what the "Scout findings" callout reads.

    Covers both emit channels: weak `emit_signal` findings (`count`) and the report channel
    (`authored_report_count` / `edited_report_count`), so a fleet of report-channel scouts
    doesn't read as silent.
    """

    count: int
    scout_count: int
    authored_report_count: int
    edited_report_count: int
    run_count: int
    latest_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def fleet_findings_summary(*, team_id: int, window_hours: int = DEFAULT_FINDINGS_WINDOW_HOURS) -> FleetFindingsSummary:
    """Summarise the output the fleet produced in the recent window, in a single query.

    Replaces the client-side tally that walked the whole paginated runs window just to count
    findings for the callout. Counts runs that produced output on either channel — emitted a
    finding (`emitted_count > 0`) or authored/edited an inbox report (non-empty
    `emitted_report_ids` / `edited_report_ids`) — whose `created_at` falls in the last
    `window_hours`, capped to the most recent `FLEET_FINDINGS_SUMMARY_RUN_CAP` runs by completion
    time (falling back to creation) — the same set the findings page renders, so the callout
    can't over-advertise. Returns the finding total (sum of `emitted_count`), the distinct scout
    count, the distinct reports authored and edited (edits of a report also authored *within the
    capped run set* fold into authored, matching the scout detail view — a report whose authoring
    run ages out of the cap while a later edit survives counts as edited, the same classification
    the findings page derives from its identically-capped window), and the most recent output time.
    The report tallies are additionally capped at the `FLEET_FINDINGS_SUMMARY_REPORT_CAP` most
    recently touched reports — the same 50 the findings page slices `touchedReports` to — so the
    callout never advertises reports the page won't list.
    """
    window_hours = max(1, min(window_hours, MAX_FINDINGS_WINDOW_HOURS))
    window_start = timezone.now() - timedelta(hours=window_hours)
    # Every run in the window, quiet ones included, so the roster's runs headline sits on the same
    # span as its report tallies instead of a per-scout depth that doesn't sum across a fleet.
    run_count = SignalScoutRun.objects.filter(team_id=team_id, created_at__gte=window_start).count()
    touched_a_report = (~Q(emitted_report_ids=[]) & ~Q(emitted_report_ids__isnull=True)) | (
        ~Q(edited_report_ids=[]) & ~Q(edited_report_ids__isnull=True)
    )
    # Order by completion (fall back to creation) so the cap keeps the *most recently emitted* runs,
    # matching the frontend's `completed_at ?? created_at` sort; `-id` tie-breaks on the time-ordered PK.
    rows = (
        SignalScoutRun.objects.filter(team_id=team_id, created_at__gte=window_start)
        .filter(Q(emitted_count__gt=0) | touched_a_report)
        .annotate(_emitted_at=Coalesce("task_run__completed_at", "created_at"))
        .order_by("-_emitted_at", "-id")
        .values_list("emitted_count", "skill_name", "_emitted_at", "emitted_report_ids", "edited_report_ids")[
            :FLEET_FINDINGS_SUMMARY_RUN_CAP
        ]
    )
    materialized = list(rows)
    count = 0
    scouts: set[str] = set()
    latest_at: datetime | None = None
    for emitted_count, skill_name, emitted_at, _emitted_report_ids, _edited_report_ids in materialized:
        count += emitted_count or 0
        # Finding-emitting scouts always count (findings aren't report-capped); report-only scouts
        # are added below only when a report they touched survives the report cap — the same rule
        # the findings page uses for its scout filter, so the callout can't advertise a scout the
        # page won't show.
        if emitted_count:
            scouts.add(skill_name)
        if emitted_at is not None and (latest_at is None or emitted_at > latest_at):
            latest_at = emitted_at
    # Distinct touched reports, most recently touched first (rows are newest-first), capped at the
    # same 50 the findings page keeps (`MAX_FLEET_TOUCHED_REPORTS`) — so the callout never
    # advertises reports the page has sliced away. Dict preserves insertion (recency) order.
    kept_report_ids: dict[str, None] = {}
    for _, _, _, emitted_report_ids, edited_report_ids in materialized:
        for report_id in [*(edited_report_ids or []), *(emitted_report_ids or [])]:
            if report_id not in kept_report_ids and len(kept_report_ids) < FLEET_FINDINGS_SUMMARY_REPORT_CAP:
                kept_report_ids[report_id] = None
    for _, skill_name, _, emitted_report_ids, edited_report_ids in materialized:
        if any(report_id in kept_report_ids for report_id in [*(emitted_report_ids or []), *(edited_report_ids or [])]):
            scouts.add(skill_name)
    # Authoring supersedes an edit of the same report — one report, one bucket.
    authored_reports: set[str] = set()
    for _, _, _, emitted_report_ids, _edited_report_ids in materialized:
        authored_reports.update(report_id for report_id in emitted_report_ids or [] if report_id in kept_report_ids)
    edited_reports = {report_id for report_id in kept_report_ids if report_id not in authored_reports}
    return FleetFindingsSummary(
        count=count,
        scout_count=len(scouts),
        authored_report_count=len(authored_reports),
        edited_report_count=len(edited_reports),
        run_count=run_count,
        latest_at=latest_at.isoformat() if latest_at is not None else None,
    )


def get_run(*, team_id: int, run_id: str) -> RunDetail | None:
    """Fetch a single run by ID, scoped to the team. Returns None if not found.

    Team scoping is non-negotiable: a run row from another team must not be
    readable, even if the caller knows the UUID.
    """
    row = SignalScoutRun.objects.select_related("task_run").filter(team_id=team_id, id=run_id).first()
    if row is None:
        return None
    return _to_detail(row, team_id=team_id)


def _to_summary(row: SignalScoutRun, *, team_id: int) -> RunSummary:
    task_run = row.task_run
    task_id = str(task_run.task_id) if task_run is not None else None
    task_run_id = str(task_run.id) if task_run is not None else None
    error, failure_reason = _derive_failure(task_run)
    return RunSummary(
        run_id=str(row.id),
        skill_name=row.skill_name,
        skill_version=row.skill_version,
        status=task_run.status if task_run is not None else "",
        created_at=row.created_at.isoformat(),
        started_at=task_run.created_at.isoformat() if task_run is not None else row.created_at.isoformat(),
        completed_at=task_run.completed_at.isoformat() if task_run is not None and task_run.completed_at else None,
        summary=row.summary,
        emitted_count=row.emitted_count or 0,
        emitted_finding_ids=list(row.emitted_finding_ids or []),
        emitted_report_ids=list(row.emitted_report_ids or []),
        edited_report_ids=list(row.edited_report_ids or []),
        task_id=task_id,
        task_run_id=task_run_id,
        task_url=_build_task_url(team_id=team_id, task_id=task_id, task_run_id=task_run_id),
        error=error,
        failure_reason=failure_reason,
        metadata=dict(row.metadata or {}),
    )


def _to_detail(row: SignalScoutRun, *, team_id: int) -> RunDetail:
    summary = _to_summary(row, team_id=team_id)
    return RunDetail(**asdict(summary))


def _derive_failure(task_run: TaskRun | None) -> tuple[str | None, str | None]:
    """Return `(error, failure_reason)` for a run — both None unless it failed/cancelled.

    Gating both on terminal-failure status keeps a non-null `error` a genuine failure signal:
    a stray `error_message` left on a run that reached COMPLETED is not surfaced, so the
    "both null on success" contract holds. `error` is the full `TaskRun.error_message`;
    `failure_reason` is the concise list-safe derived one-liner — the first line of the message
    bounded to `MAX_FAILURE_REASON_LENGTH`, or a status-derived fallback when none was recorded.
    `failure_reason` is what a bulk run scan reads to see *why* a run emitted nothing without
    pulling every stack trace.
    """
    if task_run is None or task_run.status not in (
        tasks_facade.TaskRunStatus.FAILED,
        tasks_facade.TaskRunStatus.CANCELLED,
    ):
        return None, None
    error = task_run.error_message or None
    message = (task_run.error_message or "").strip()
    if message:
        return error, message.splitlines()[0][:MAX_FAILURE_REASON_LENGTH]
    fallback = (
        "cancelled" if task_run.status == tasks_facade.TaskRunStatus.CANCELLED else "failed (no error message recorded)"
    )
    return error, fallback


def _build_task_url(*, team_id: int, task_id: str | None, task_run_id: str | None) -> str | None:
    """Build the relative Tasks UI deep-link, or None if the linkage isn't captured.

    Path shape follows the project URL convention (no host, includes `/project/{id}/`
    for the front-end router; MCP clients render it against their own host). Both
    IDs must be present — a task without a run id can't be opened on the right tab.
    """
    if not task_id or not task_run_id:
        return None
    return f"/project/{team_id}/tasks/{task_id}?runId={task_run_id}"


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_RUN_SEARCH_LIMIT:
        return MAX_RUN_SEARCH_LIMIT
    return limit
