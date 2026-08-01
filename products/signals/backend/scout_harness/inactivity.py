"""Inactivity sweep: warn, then auto-pause scouts that produce nothing anyone uses.

`SignalScoutConfig.enabled` only ever moves by hand, so a scout nobody is getting value from
keeps spending sandbox runs on its cadence indefinitely. This module is the missing stop: once a
day (`tasks.pause_inactive_signal_scouts`, deliberately not the 30-minute coordinator tick, which
is kept short-lived and bounded) it decides whether each enabled scout is still earning its runs.

The sweep judges **consumption, not emission**. Emitting a report is not evidence anyone wanted
it; a scout that files report after report nobody acts on is the expensive failure mode (a full
sandbox run per interval, plus inbox noise, plus pipeline work per finding), while a scout that
is merely quiet may be a watchdog whose silence is the job. So the two reasons behave
differently:

- `ignored` — the scout's reports show no human consumption. This is the pausing verdict: warn
  (`pending_pause`, still scheduled), then pause (`paused_by_system`) once `WARNING_GRACE`
  elapses.
- `no_output` — the scout surfaced nothing at all and has no report evidence to judge. This
  only ever warns: the badge asks a human to look, but silence alone never pauses a scout.

A scout counts as **consumed** when a person acted on any report it wrote or edited inside the
`TOUCHED_REPORT_LOOKBACK`: they left a log artefact on it (a note, a dismissal, a code
reference…) inside the window, or the report recently reached a state only a deliberate action
produces (`_ENGAGED_REPORT_STATUSES`). `resolved` is deliberately in that set even though the
GitHub webhook sets it without an in-app action, because the webhook resolves on PR *merge*: a
human merging the report's PR on GitHub is real consumption that leaves no other server-side
trace. `suppressed` is deliberately NOT in the set, because the same webhook suppresses a report
when its PR closes unmerged, which a stale-bot can do with no human anywhere in the loop; a
human archiving a report leaves a `DISMISSAL` artefact and is counted there instead. Client-side
opens aren't persisted server-side, so a report someone read but never acted on still counts as
unconsumed; a rescue feed of richer evidence (frontend opens, indirect report attribution) is a
planned follow-up, and its absence fails toward this rule's plain evidence, never toward extra
pauses. Report status changes carry no actor today, so a status flipped by another agent can
still read as consumption; tightening that needs actor attribution on status transitions.

The `ignored` verdict only applies when there is fair evidence to judge: the scout must hold at
least one touched report older than `ESTABLISHED_REPORT_AGE` (a report nobody has seen yet is
not a report nobody wanted), and Slack-routed scouts are exempt from it entirely because their
output is consumed in Slack where no evidence flows back. A scout with output but no judgeable
report evidence (findings-only, Slack-routed, or all reports too fresh) is left alone.

The sweep speaks the scout lifecycle vocabulary rather than keeping fields of its own. Every
write goes through `transition_status_by_system`, whose writer-scoped ownership rule keeps this
sweep and the failure breaker (`repeated_failures`) from touching each other's pauses (the sweep
owns both of its reasons, so it may reclassify its own warning in either direction: a `no_output`
warning becomes `ignored` when report evidence establishes, and an `ignored` warning downgrades
to `no_output` when its evidence ages out, so a pause never lands on stale grounds), and
whose `evaluated_at` check makes a racing human edit win over a sweep decision made on stale
reads. There is no half-open probe on this axis: an inactivity pause never runs again on its
own; a human re-enable is the only exit, and the update serializer marks that re-enable
`auto_pause_exempt` so the sweep never overrules it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.models.activity_logging.activity_log import Trigger
from posthog.models.activity_logging.model_activity import ActivityTriggerContext

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.slack_delivery import get_scout_slack_destination

logger = structlog.get_logger(__name__)

# How far back productivity is judged. Long enough that a daily scout is assessed on a couple of
# weeks of runs rather than a bad afternoon, short enough that the waste stops mattering in days.
INACTIVITY_WINDOW = timedelta(days=14)

# Breathing room between the warning and the pause: the team gets a full week's notice on the fleet
# page, and a scout someone engages with in the meantime clears its own warning.
WARNING_GRACE = timedelta(days=7)

# A scout is only judged once it has actually had a fair number of attempts in the window. Guards
# the sparse cases — a monthly cron, or a scout whose team spent its daily budget elsewhere — where
# "no output" says more about how rarely it ran than about what it found.
MIN_RUNS_IN_WINDOW = 5

# How far back to look for the reports a scout has touched. Bounds the run scan on a table that grows
# a row per scout per interval forever; a report nobody engaged with in three months isn't about to
# rescue the scout that wrote it.
TOUCHED_REPORT_LOOKBACK = timedelta(days=90)

# A report younger than this hasn't been ignored, it just hasn't been seen yet, so it cannot count
# toward the `ignored` verdict. Engagement with a fresh report still counts in the scout's favor.
ESTABLISHED_REPORT_AGE = timedelta(days=7)

# Blast-radius cap: new warnings issued per sweep. Most of the running fleet qualifies as
# unconsumed on this rule the day it ships, and a pause can only ever follow a warning by
# `WARNING_GRACE`, so capping warnings alone bounds the pauses each later sweep can land while
# keeping every warned scout's "pauses in a week" promise honest. Applied in iteration order
# (team id, then skill name) — deterministic, so the sweep works through the backlog rather than
# re-sampling it. Deferrals are counted and logged: a capped sweep must read as "more to do",
# never as a clean bill of health.
MAX_WARNS_PER_SWEEP = 200

# The two pause reasons this sweep owns, from the model (`INACTIVITY_PAUSE_REASONS`). The
# writer-scoped ownership rule means the sweep may only advance or recover a warning carrying one
# of these.
SWEEP_REASONS: frozenset[str] = frozenset(SignalScoutConfig.INACTIVITY_PAUSE_REASONS)

# Artefact types that mean work was done on a report. Only ones attributed to a person count (see
# `_engaged_report_ids`). The status artefacts (safety / actionability / priority judgments, repo
# selection) are excluded outright — they are pipeline assessments, never a person's work.
_ENGAGEMENT_ARTEFACT_TYPES: frozenset[str] = SignalReportArtefact.LOG_ARTEFACT_TYPES | frozenset(
    {SignalReportArtefact.ArtefactType.DISMISSAL}
)

# Statuses that mean a person deliberately consumed the report. `resolved` covers both an in-app
# resolve and the GitHub webhook's resolve-on-merge (a merged PR is consumption even when the
# merge never touched the app). `suppressed` is excluded: the same webhook suppresses a report
# whose PR closed unmerged, which needs no human, and a human archive leaves a `DISMISSAL`
# artefact that the artefact half already counts.
_ENGAGED_REPORT_STATUSES: frozenset[str] = frozenset(
    {
        SignalReport.Status.RESOLVED,
        SignalReport.Status.DELETED,
    }
)

_SWEEP_JOB_TYPE = "signals_scout_inactivity_sweep"


@dataclass
class SweepOutcome:
    """What one sweep did, for logging and analytics."""

    considered: int = 0
    warned: list[SignalScoutConfig] = field(default_factory=list)
    paused: list[SignalScoutConfig] = field(default_factory=list)
    recovered: int = 0
    # Scouts that qualified for a warning after the per-sweep cap was already spent. They stay
    # active and are re-derived by the next sweep — counted so a capped sweep is visibly partial.
    deferred: int = 0
    # Whether each warned/paused config had output inside the window, keyed by config pk. Rides
    # the analytics events so the read-back can split noisy-but-unconsumed from silent.
    had_output: dict[UUID, bool] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TeamAssessment:
    """Per-skill verdict inputs for one team's scouts."""

    # Ran often enough in the window for a verdict to mean anything.
    judgeable: set[str]
    # A person acted on a report the scout touched (any report age; the action is recent).
    engaged: set[str]
    # Recorded output on any emit channel inside the window.
    emitted: set[str]
    # Holds at least one touched report old enough to judge, so the `ignored` verdict applies.
    judged_on_reports: set[str]


def sweep_inactive_scouts(now: datetime | None = None) -> SweepOutcome:
    """Warn or pause every enabled scout whose output nobody consumes.

    Idempotent: re-running the same day re-derives the same verdict from the runs and reports
    themselves, a warning already in place is only advanced once `WARNING_GRACE` has actually
    elapsed, and every transition goes through `transition_status_by_system`, which no-ops
    repeats and refuses to touch state the sweep doesn't own.
    """
    now = now or timezone.now()
    outcome = SweepOutcome()

    # A fleet-wide sweep is genuinely cross-team, so it reads through the unscoped manager; every
    # per-team query below is then keyed on the `team_id` carried by the config rows themselves.
    candidates = (
        SignalScoutConfig.all_teams.filter(
            enabled=True,
            # A dry-run scout emits nothing by design, so the productivity test can't say anything
            # about it — `emit_finding` is a no-op there and never records output on the run.
            emit=True,
            auto_pause_exempt=False,
            # Cheap SQL prefilter for the common case; `in_cold_start_grace()` below is the real
            # gate and also covers the re-anchor on a resume, which this filter can't see.
            created_at__lte=now - SignalScoutConfig.COLD_START_GRACE,
        )
        .order_by("team_id", "skill_name")
        .iterator()
    )
    by_team: dict[int, list[SignalScoutConfig]] = {}
    for config in candidates:
        if config.in_cold_start_grace():
            continue
        by_team.setdefault(config.team_id, []).append(config)

    for team_id, configs in by_team.items():
        outcome.considered += len(configs)
        try:
            assessment = _assess_team(team_id, [c.skill_name for c in configs], now)
        except Exception:
            # One team's data problem must not cost the rest of the fleet its sweep.
            logger.exception("signals_scout inactivity sweep: team assessment failed", team_id=team_id)
            continue
        for config in configs:
            _apply_verdict(config, assessment, outcome, now)

    return outcome


def _apply_verdict(config: SignalScoutConfig, assessment: TeamAssessment, outcome: SweepOutcome, now: datetime) -> None:
    name = config.skill_name
    sweep_warned = config.status == SignalScoutConfig.Status.PENDING_PAUSE and config.pause_reason in SWEEP_REASONS

    if name in assessment.engaged:
        # Someone is using this scout's output — drop any pending warning so a consumed scout is
        # never one quiet week away from a pause it already worked off.
        if sweep_warned and _transition(config, SignalScoutConfig.Status.ACTIVE, config.pause_reason, evaluated_at=now):
            outcome.recovered += 1
        return
    if name not in assessment.judgeable:
        return

    # A Slack-routed scout's output is consumed in Slack, where no evidence flows back, so the
    # `ignored` verdict cannot be trusted for it. Its silence still warns below.
    slack_routed = get_scout_slack_destination(config.output_destinations) is not None
    if name in assessment.judged_on_reports and not slack_routed:
        _apply_ignored_verdict(config, outcome, now, had_output=name in assessment.emitted, sweep_warned=sweep_warned)
        return

    if name in assessment.emitted:
        # Producing output, but nothing judgeable on the report side (findings-only,
        # Slack-routed, or every report still fresh). Nothing to hold against it; a warning it
        # picked up earlier under different evidence gets cleared.
        if sweep_warned and _transition(config, SignalScoutConfig.Status.ACTIVE, config.pause_reason, evaluated_at=now):
            outcome.recovered += 1
        return

    # Silent, with no report evidence either way. Warn so a human looks at it, but never pause:
    # a watch scout that only speaks when something is wrong looks exactly like this.
    if sweep_warned and config.pause_reason == SignalScoutConfig.PauseReason.IGNORED:
        # The evidence behind the scheduled pause is gone (the touching runs aged past the
        # lookback, or the scout was re-routed to Slack since the warning), so the pause must not
        # land on stale grounds. Downgrade to the badge-only warning. Deliberately not capped:
        # deferring a downgrade would leave the scout scheduled to pause. Appended to `warned` so
        # the analytics event re-fires with the corrected reason.
        if _transition(
            config, SignalScoutConfig.Status.PENDING_PAUSE, SignalScoutConfig.PauseReason.NO_OUTPUT, evaluated_at=now
        ):
            outcome.warned.append(config)
            outcome.had_output[config.pk] = False
            logger.info(
                "signals_scout inactivity sweep: warned",
                team_id=config.team_id,
                skill_name=config.skill_name,
                reason=config.pause_reason,
            )
        return
    if config.status == SignalScoutConfig.Status.ACTIVE:
        if len(outcome.warned) >= MAX_WARNS_PER_SWEEP:
            outcome.deferred += 1
            return
        if _transition(
            config, SignalScoutConfig.Status.PENDING_PAUSE, SignalScoutConfig.PauseReason.NO_OUTPUT, evaluated_at=now
        ):
            outcome.warned.append(config)
            outcome.had_output[config.pk] = False
            logger.info(
                "signals_scout inactivity sweep: warned",
                team_id=config.team_id,
                skill_name=config.skill_name,
                reason=config.pause_reason,
            )


def _apply_ignored_verdict(
    config: SignalScoutConfig, outcome: SweepOutcome, now: datetime, *, had_output: bool, sweep_warned: bool
) -> None:
    """Warn, reclassify, or pause a scout whose established reports show no consumption."""
    already_ignored = sweep_warned and config.pause_reason == SignalScoutConfig.PauseReason.IGNORED
    if config.status == SignalScoutConfig.Status.ACTIVE or (sweep_warned and not already_ignored):
        # Reclassifying a `no_output` warning to `ignored` schedules a pause for the first time,
        # so it restarts the grace clock and spends a slot under the cap like any fresh warning.
        if len(outcome.warned) >= MAX_WARNS_PER_SWEEP:
            outcome.deferred += 1
            return
        if _transition(
            config, SignalScoutConfig.Status.PENDING_PAUSE, SignalScoutConfig.PauseReason.IGNORED, evaluated_at=now
        ):
            outcome.warned.append(config)
            outcome.had_output[config.pk] = had_output
            logger.info(
                "signals_scout inactivity sweep: warned",
                team_id=config.team_id,
                skill_name=config.skill_name,
                reason=config.pause_reason,
            )
        return
    if already_ignored:
        warned_at = config.status_changed_at
        if warned_at is None or now - warned_at < WARNING_GRACE:
            return
        if _transition(config, SignalScoutConfig.Status.PAUSED_BY_SYSTEM, config.pause_reason, evaluated_at=now):
            outcome.paused.append(config)
            outcome.had_output[config.pk] = had_output
            logger.info(
                "signals_scout inactivity sweep: paused",
                team_id=config.team_id,
                skill_name=config.skill_name,
                reason=config.pause_reason,
            )


def _transition(
    config: SignalScoutConfig,
    new_status: SignalScoutConfig.Status,
    reason: str | None,
    *,
    evaluated_at: datetime,
) -> bool:
    """One sweep transition, attributed to the sweep in the activity log.

    No acting user: the sweep is the actor, so the activity entry carries the job trigger
    rather than being pinned on whoever happened to enable the scout months ago.
    """
    if reason is None:
        return False
    trigger = Trigger(
        job_type=_SWEEP_JOB_TYPE,
        job_id=str(config.id),
        payload={"skill_name": config.skill_name, "reason": reason},
    )
    with ActivityTriggerContext(trigger):
        return config.transition_status_by_system(
            new_status,
            pause_reason=SignalScoutConfig.PauseReason(reason),
            evaluated_at=evaluated_at,
        )


def _assess_team(team_id: int, skill_names: list[str], now: datetime) -> TeamAssessment:
    window_start = now - INACTIVITY_WINDOW
    runs = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(
            skill_name__in=skill_names,
            created_at__gte=now - TOUCHED_REPORT_LOOKBACK,
        )
        .values_list("skill_name", "created_at", "emitted_finding_ids", "emitted_report_ids", "edited_report_ids")
    )

    runs_in_window: dict[str, int] = {}
    emitted: set[str] = set()
    touched: dict[str, set[str]] = {}
    for skill_name, created_at, finding_ids, report_ids, edited_ids in runs:
        if created_at >= window_start:
            runs_in_window[skill_name] = runs_in_window.get(skill_name, 0) + 1
            if bool(finding_ids) or bool(report_ids) or bool(edited_ids):
                emitted.add(skill_name)
        reports = {str(report_id) for report_id in (report_ids or []) + (edited_ids or [])}
        if reports:
            touched.setdefault(skill_name, set()).update(reports)

    judgeable = {name for name, count in runs_in_window.items() if count >= MIN_RUNS_IN_WINDOW}
    relevant = {name: reports for name, reports in touched.items() if name in judgeable}
    all_touched: set[str] = set().union(*relevant.values()) if relevant else set()
    engaged_ids = _engaged_report_ids(team_id, all_touched, window_start)
    established_ids = _established_report_ids(team_id, all_touched, now - ESTABLISHED_REPORT_AGE)
    return TeamAssessment(
        judgeable=judgeable,
        engaged={name for name, reports in relevant.items() if reports & engaged_ids},
        emitted=emitted,
        judged_on_reports={name for name, reports in relevant.items() if reports & established_ids},
    )


def _engaged_report_ids(team_id: int, report_ids: set[str], window_start: datetime) -> set[str]:
    """Of `report_ids`, the ones a person acted on since `window_start`."""
    if not report_ids:
        return set()
    engaged = {
        str(report_id)
        for report_id in SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id__in=report_ids,
            type__in=_ENGAGEMENT_ARTEFACT_TYPES,
            # Attributed to a person. Pipeline writers attribute to a task or to the system (both
            # NULL here), and several of them append log artefacts on their own — grouping writes a
            # symmetric `related_to` when a resolved report recurs, autostart writes `task_run` — so
            # counting those would let a scout keep itself alive with no human anywhere in the loop.
            created_by__isnull=False,
            created_at__gte=window_start,
        ).values_list("report_id", flat=True)
    }
    engaged |= {
        str(report_id)
        for report_id in SignalReport.objects.filter(
            team_id=team_id,
            id__in=report_ids,
            status__in=_ENGAGED_REPORT_STATUSES,
            updated_at__gte=window_start,
        ).values_list("id", flat=True)
    }
    return engaged


def _established_report_ids(team_id: int, report_ids: set[str], created_before: datetime) -> set[str]:
    """Of `report_ids`, the ones old enough that no consumption is meaningful, not just unseen."""
    if not report_ids:
        return set()
    return {
        str(report_id)
        for report_id in SignalReport.objects.filter(
            team_id=team_id,
            id__in=report_ids,
            created_at__lte=created_before,
        ).values_list("id", flat=True)
    }
