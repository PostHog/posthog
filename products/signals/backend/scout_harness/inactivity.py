"""Inactivity sweep: warn, then auto-pause scouts that produce nothing anyone uses.

`SignalScoutConfig.enabled` only ever moves by hand, so a scout that surfaces nothing keeps
spending sandbox runs on its cadence indefinitely. This module is the missing stop: once a day
(`tasks.pause_inactive_signal_scouts`, deliberately not the 30-minute coordinator tick, which is
kept short-lived and bounded) it decides whether each enabled scout is still earning its runs.

A scout counts as **productive** if either half holds over the window:

- *output* — any run in the window recorded something on any of the three emit channels
  (`emitted_finding_ids`, `emitted_report_ids`, `edited_report_ids`). All three matter: a
  report-channel scout writes through `emit_report` / `edit_report`, so judging on the finding
  tally alone would read every one of them as silent.
- *engagement* — a person acted on a report the scout wrote or edited before the window: they left a
  log artefact on it (a note, a dismissal, a code reference…) inside the window, or the report
  reached a state only a human action produces. Reports the scout touched
  *inside* the window are excluded from this half — they are already covered by the output half, and
  including them would count the scout's own writes as engagement with itself. Client-side opens
  aren't persisted server-side, so they can't count either way.

The sweep speaks the scout lifecycle vocabulary rather than keeping fields of its own: a warning is
`status=pending_pause` (still scheduled), the pause is `status=paused_by_system`, and both carry a
`pause_reason` the sweep owns — `no_output` (it surfaced nothing at all) or `ignored` (it surfaced
reports nobody picked up). Every write goes through `transition_status_by_system`, whose
reason-scoped ownership rule keeps this sweep and the failure breaker (`repeated_failures`) from
touching each other's pauses, and whose `evaluated_at` check makes a racing human edit win over a
sweep decision made on stale reads. There is no half-open probe on this axis: an inactivity pause
never runs again on its own — a human re-enable is the only exit, and the update serializer marks
that re-enable `auto_pause_exempt` so the sweep never overrules it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.utils import timezone

import structlog

from posthog.models.activity_logging.activity_log import Trigger
from posthog.models.activity_logging.model_activity import ActivityTriggerContext

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalScoutConfig, SignalScoutRun

logger = structlog.get_logger(__name__)

# How far back productivity is judged. Long enough that a daily scout is assessed on a couple of
# weeks of runs rather than a bad afternoon, short enough that the waste stops mattering in days.
INACTIVITY_WINDOW = timedelta(days=14)

# Breathing room between the warning and the pause: the team gets a full week's notice on the fleet
# page, and a scout that surfaces something in the meantime clears its own warning.
WARNING_GRACE = timedelta(days=7)

# A scout is only judged once it has actually had a fair number of attempts in the window. Guards
# the sparse cases — a monthly cron, or a scout whose team spent its daily budget elsewhere — where
# "no output" says more about how rarely it ran than about what it found.
MIN_RUNS_IN_WINDOW = 5

# How far back to look for the reports a scout has touched. Bounds the run scan on a table that grows
# a row per scout per interval forever; a report nobody engaged with in three months isn't about to
# rescue the scout that wrote it.
TOUCHED_REPORT_LOOKBACK = timedelta(days=90)

# Blast-radius cap: new warnings issued per sweep. Most of the running fleet qualifies as inactive
# on this rule the day it ships, and a pause can only ever follow a warning by `WARNING_GRACE`, so
# capping warnings alone bounds the pauses each later sweep can land while keeping every warned
# scout's "pauses in a week" promise honest. Applied in iteration order (team id, then skill name) —
# deterministic, so the sweep works through the backlog rather than re-sampling it. Deferrals are
# counted and logged: a capped sweep must read as "more to do", never as a clean bill of health.
MAX_WARNS_PER_SWEEP = 200

# The two pause reasons this sweep owns, from the model (`INACTIVITY_PAUSE_REASONS`): `no_output`
# for a scout that surfaced nothing at all, `ignored` for one that surfaced reports nobody picked
# up. Separated because they call for different fixes — an ignored scout needs retuning, a silent
# one may be watching a surface this project doesn't have. The reason-scoped ownership rule means
# the sweep may only advance or recover a warning carrying one of these.
SWEEP_REASONS: frozenset[str] = frozenset(SignalScoutConfig.INACTIVITY_PAUSE_REASONS)

# Artefact types that mean work was done on a report. Only ones attributed to a person count (see
# `_engaged_report_ids`). The status artefacts (safety / actionability / priority judgments, repo
# selection) are excluded outright — they are pipeline assessments, never a person's work.
_ENGAGEMENT_ARTEFACT_TYPES: frozenset[str] = SignalReportArtefact.LOG_ARTEFACT_TYPES | frozenset(
    {SignalReportArtefact.ArtefactType.DISMISSAL}
)

# Statuses no pipeline transition produces: archiving, resolving, and deleting a report are all
# user-driven, which is what makes "report is in this state, and moved recently" a durable
# engagement signal even when the action left no artefact behind.
_ENGAGED_REPORT_STATUSES: frozenset[str] = frozenset(
    {
        SignalReport.Status.SUPPRESSED,
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


def sweep_inactive_scouts(now: datetime | None = None) -> SweepOutcome:
    """Warn or pause every enabled scout that produced nothing anyone engaged with.

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
            productive, judgeable, has_past_output = assessment
        except Exception:
            # One team's data problem must not cost the rest of the fleet its sweep.
            logger.exception("signals_scout inactivity sweep: team assessment failed", team_id=team_id)
            continue
        for config in configs:
            sweep_warned = (
                config.status == SignalScoutConfig.Status.PENDING_PAUSE and config.pause_reason in SWEEP_REASONS
            )
            if config.skill_name in productive:
                # It surfaced something again — drop the pending warning so a productive scout is
                # never one quiet fortnight away from a pause it already worked off.
                if sweep_warned and _transition(
                    config, SignalScoutConfig.Status.ACTIVE, config.pause_reason, evaluated_at=now
                ):
                    outcome.recovered += 1
                continue
            if config.skill_name not in judgeable:
                continue
            if config.status == SignalScoutConfig.Status.ACTIVE:
                if len(outcome.warned) >= MAX_WARNS_PER_SWEEP:
                    outcome.deferred += 1
                    continue
                # Two shapes of the same waste, separated because they call for different fixes:
                # a scout whose reports nobody picks up needs retuning, one that finds nothing at
                # all may be watching a surface this project doesn't have.
                reason = (
                    SignalScoutConfig.PauseReason.IGNORED
                    if config.skill_name in has_past_output
                    else SignalScoutConfig.PauseReason.NO_OUTPUT
                )
                if _transition(config, SignalScoutConfig.Status.PENDING_PAUSE, reason, evaluated_at=now):
                    outcome.warned.append(config)
                    logger.info(
                        "signals_scout inactivity sweep: warned",
                        team_id=config.team_id,
                        skill_name=config.skill_name,
                        reason=config.pause_reason,
                    )
            elif sweep_warned:
                # The pause carries the warned reason rather than reclassifying: a scout that
                # produced anything since the warning recovered above, so the classification can
                # only have moved by leaving the sweep's jurisdiction entirely.
                warned_at = config.status_changed_at
                if warned_at is None or now - warned_at < WARNING_GRACE:
                    continue
                if _transition(
                    config, SignalScoutConfig.Status.PAUSED_BY_SYSTEM, config.pause_reason, evaluated_at=now
                ):
                    outcome.paused.append(config)
                    logger.info(
                        "signals_scout inactivity sweep: paused",
                        team_id=config.team_id,
                        skill_name=config.skill_name,
                        reason=config.pause_reason,
                    )

    return outcome


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


def _assess_team(team_id: int, skill_names: list[str], now: datetime) -> tuple[set[str], set[str], set[str]]:
    """Return `(productive, judgeable, has_past_output)` skill-name sets for one team.

    Judgeable means the scout ran often enough in the window for "it found nothing" to mean
    anything; productive means it passed either half of the productivity test; has_past_output
    means it wrote reports before the window, which is what separates an ignored scout from one
    that never surfaces anything.
    """
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
    productive: set[str] = set()
    # Reports each scout touched *before* the window — the only ones the engagement half reads, so a
    # scout's own in-window writes can't be mistaken for someone engaging with them.
    touched_before_window: dict[str, set[str]] = {}
    for skill_name, created_at, finding_ids, report_ids, edited_ids in runs:
        emitted_anything = bool(finding_ids) or bool(report_ids) or bool(edited_ids)
        if created_at >= window_start:
            runs_in_window[skill_name] = runs_in_window.get(skill_name, 0) + 1
            if emitted_anything:
                productive.add(skill_name)
            continue
        touched = {str(report_id) for report_id in (report_ids or []) + (edited_ids or [])}
        if touched:
            touched_before_window.setdefault(skill_name, set()).update(touched)

    judgeable = {name for name, count in runs_in_window.items() if count >= MIN_RUNS_IN_WINDOW}
    pending = {
        name: reports for name, reports in touched_before_window.items() if name in judgeable and name not in productive
    }
    if pending:
        engaged = _engaged_report_ids(team_id, set().union(*pending.values()), window_start)
        productive.update(name for name, reports in pending.items() if reports & engaged)
    return productive, judgeable, set(touched_before_window)


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
