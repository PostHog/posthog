"""The logs side of the alerts platform comparison contract.

Answers what the production logs stack held for the check that corresponds to one platform
check. The correspondence is reconstructed rather than looked up, because production logs keeps
no per-check row: `LogsAlertEvent` is written only when a check moves the alert or errors, plus
the control-plane rows a user action writes.

So the walk runs backwards from the present. The configuration's current `state` and `enabled`
are known, and every event row carries the state on both sides of itself, which makes the state
at any past instant the `state_before` of the first event after it. An alert that never moved
has no rows at all and resolves to its current state, which is the common case and the one a
forward walk would have to give up on.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from django.db.models import QuerySet

import structlog

from posthog.models import Team

from products.alerts_platform.backend.facade.contracts import (
    CheckRef,
    IntentionalDivergence,
    PlatformCheck,
    SourceCorrespondence,
    SourceCoverage,
    SourceKind,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts_platform.backend.facade.lifecycle import (
    LOGS_ALERT_POLICY,
    PLATFORM_LOGS_ALERT_POLICY,
    AlertState,
    NotificationAction,
)
from products.logs.backend.alert_source_cycle import is_in_quiet_hours, window_end_of
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

logger = structlog.get_logger(__name__)

# An alert that flaps holds many transitions in one window. Past this bound the chain is not
# worth holding in memory, and a truncated chain would date checks wrongly.
MAX_EVENTS_PER_WINDOW = 5000

# The bound the per-alert one does not give: alerts each under their own ceiling still add up.
MAX_EVENTS_PER_BATCH = 100_000

_TOGGLE_KINDS = frozenset({LogsAlertEvent.Kind.ENABLE, LogsAlertEvent.Kind.DISABLE})
_CHAIN_FIELDS = ("id", "alert_id", "kind", "created_at", "state_before", "state_after")


def _mute_gates_notification_only(check: PlatformCheck, verdict: SourceVerdict) -> bool:
    """True when this difference is the platform evaluating an alert production logs would not.

    Two shapes, because production logs leaves two different traces. A mute it knows about parks
    the alert in SNOOZED, which the walk reports as suppressed. A schedule restriction reschedules
    the check instead, writing nothing and stalling `last_checked_at`, which the walk reports as
    behind. The platform's held announcement is what separates that stall from a real lag.
    """
    if verdict.coverage is SourceCoverage.SUPPRESSED:
        return verdict.suppressed_by is SuppressionReason.MUTED
    return verdict.coverage is SourceCoverage.BEHIND and check.muted_notification not in (
        "",
        NotificationAction.NONE.value,
    )


LOGS_INTENTIONAL_DIVERGENCES: tuple[IntentionalDivergence, ...] = (
    IntentionalDivergence(
        cause="mute_gates_notification_only",
        policy_flag="mute_gates_notification_only",
        recognizes=_mute_gates_notification_only,
        why=(
            "The platform evaluates a muted alert and holds the announcement, so the alert keeps "
            "tracking reality through a snooze or a schedule restriction. Production logs excludes "
            "a snoozed alert from discovery and reschedules a restricted one, so it makes no check "
            "at all. Without this entry every snoozed logs alert reads as divergent."
        ),
    ),
)


class LogsCorrespondence(SourceCorrespondence):
    source = SourceKind.LOGS
    production_policy = LOGS_ALERT_POLICY
    platform_policy = PLATFORM_LOGS_ALERT_POLICY
    intentional_divergences = LOGS_INTENTIONAL_DIVERGENCES

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]:
        verdicts: dict[CheckRef, SourceVerdict] = {}
        by_alert: dict[tuple[int, UUID], list[PlatformCheck]] = defaultdict(list)
        for check in checks:
            if check.legacy_configuration_id is None:
                verdicts[check.ref] = _unknown("the platform configuration names no logs alert")
            else:
                by_alert[(check.team_id, check.legacy_configuration_id)].append(check)

        if not by_alert:
            return verdicts

        configurations = {
            (configuration.team_id, configuration.id): configuration
            for configuration in LogsAlertConfiguration.objects.filter(
                id__in=[alert_id for _, alert_id in by_alert],
                team_id__in={team_id for team_id, _ in by_alert},
            ).only("id", "team_id", "state", "enabled", "schedule_restriction", "last_checked_at")
        }
        # One narrow row per team, rather than the Team row `select_related` attaches to every
        # configuration to reach one field.
        timezones = dict(
            Team.objects.filter(id__in={team_id for team_id, _ in configurations}).values_list("id", "timezone")
        )
        instants = [check.occurred_at for group in by_alert.values() for check in group]
        events = self._chains(set(configurations), since=min(instants), until=max(instants))

        for key, group in by_alert.items():
            configuration = configurations.get(key)
            chain = events.get(key[1])
            for check in group:
                if configuration is None:
                    verdicts[check.ref] = _unknown("no logs alert with that id in this project")
                elif chain is None:
                    verdicts[check.ref] = _unknown("too many logs transitions to date this check against")
                else:
                    verdicts[check.ref] = _verdict_at(configuration, chain, check, tz_name=timezones[key[0]])

        return verdicts

    def _chains(
        self, keys: set[tuple[int, UUID]], *, since: datetime, until: datetime
    ) -> dict[UUID, list[LogsAlertEvent]]:
        """Every transition each alert made after `since`, oldest first, keyed by alert.

        Bounded by the window being compared rather than by wall-clock time, plus the few later
        transitions a check at the end of the window is dated by. Reading to the present instead
        would spend the per-alert bound on transitions no check asks about.

        An alert whose chain could not be read whole is left out, so a caller cannot read a
        truncated chain as a complete one.
        """
        alert_ids = [alert_id for _, alert_id in keys]
        team_ids = {team_id for team_id, _ in keys}
        in_window = list(
            self._events(alert_ids, team_ids)
            .filter(created_at__gt=since, created_at__lte=until)
            .order_by("alert_id", "-created_at")[: MAX_EVENTS_PER_BATCH + 1]
        )

        held = in_window[:MAX_EVENTS_PER_BATCH]
        chains: dict[UUID, list[LogsAlertEvent]] = {alert_id: [] for alert_id in alert_ids}
        for row in held:
            chains[row.alert_id].append(row)

        incomplete = {alert_id for alert_id, chain in chains.items() if len(chain) > MAX_EVENTS_PER_WINDOW}
        if len(in_window) > MAX_EVENTS_PER_BATCH:
            # Ordered by alert, so the batch bound cut one alert short and left the rest unread.
            incomplete |= set(alert_ids) - {row.alert_id for row in held}
            incomplete.add(held[-1].alert_id)
        if incomplete:
            logger.warning(
                "Logs alert comparison could not read every transition it needs",
                since=since.isoformat(),
                alerts=len(incomplete),
            )

        complete = {alert_id: chain for alert_id, chain in chains.items() if alert_id not in incomplete}
        for chain in complete.values():
            chain.reverse()
        for row in self._first_of_each_kind_and_state_after(list(complete), team_ids, until):
            complete[row.alert_id].append(row)
        for chain in complete.values():
            # Only the rows past the window arrive out of order, and they all follow the window's rows.
            chain.sort(key=lambda row: row.created_at)
        return complete

    def _first_of_each_kind_and_state_after(
        self, alert_ids: list[UUID], team_ids: set[int], moment: datetime
    ) -> QuerySet[LogsAlertEvent]:
        """Each alert's earliest transition after `moment` of every kind and resulting state.

        A check is dated by the next transition of any kind, `enabled` by the next toggle, and
        `caught_up_at` by the next move into the check's state. Each of those is the earliest row
        of some (kind, state) pair, so one read answers all three. The pairs are few: a handful of
        kinds times a handful of states.
        """
        return (
            self._events(alert_ids, team_ids)
            .filter(created_at__gt=moment)
            .order_by("alert_id", "kind", "state_after", "created_at")
            .distinct("alert_id", "kind", "state_after")
        )

    def _events(self, alert_ids: list[UUID], team_ids: set[int]) -> QuerySet[LogsAlertEvent]:
        return LogsAlertEvent.objects.filter(
            alert_id__in=alert_ids,
            # Restated, so a reader never meets a query on this table without a team term.
            alert__team_id__in=team_ids,
        ).only(*_CHAIN_FIELDS)


def _unknown(detail: str) -> SourceVerdict:
    return SourceVerdict(caught_up_at=None, coverage=SourceCoverage.UNKNOWN, state=None, detail=detail)


def _verdict_at(
    configuration: LogsAlertConfiguration,
    chain: Sequence[LogsAlertEvent],
    check: PlatformCheck,
    *,
    tz_name: str,
) -> SourceVerdict:
    at = check.occurred_at
    after = [event for event in chain if event.created_at > at]
    boundary = after[0] if after else None
    state = boundary.state_before if boundary is not None else configuration.state

    toggle = next((event for event in after if event.kind in _TOGGLE_KINDS), None)
    enabled = toggle.kind == LogsAlertEvent.Kind.DISABLE if toggle is not None else configuration.enabled

    # The boundary is the transition that ended the state being reported, so it dates that state
    # rather than the check. None means the state still holds.
    observed_at = boundary.created_at if boundary is not None else None
    evidence_id = str(boundary.id) if boundary is not None else None
    # The first transition *into* the state this check decided, not merely the next one.
    caught_up = next((event for event in after if event.state_after == check.state), None)

    def verdict(coverage: SourceCoverage, *, suppressed_by: SuppressionReason | None = None) -> SourceVerdict:
        return SourceVerdict(
            coverage=coverage,
            state=state,
            suppressed_by=suppressed_by,
            observed_at=observed_at,
            caught_up_at=caught_up.created_at if caught_up is not None else None,
            evidence_id=evidence_id,
        )

    if not enabled:
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.DISABLED)
    if state == AlertState.BROKEN:
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.BROKEN)
    if state == AlertState.SNOOZED:
        # No history of `snooze_until` is kept, so the state overstates the snooze by up to the
        # one check interval production logs takes to write the transition out of it.
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.MUTED)
    # The platform's parse, not production's, which reschedules past a blocked window rather than
    # testing one. A disagreement between the two parses is invisible here.
    if is_in_quiet_hours(configuration.schedule_restriction, at, tz_name, alert_id=configuration.id):
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.MUTED)

    # Production logs must have reached this data before it can have disagreed about it.
    bound = window_end_of(check.evaluation_key) or at
    if configuration.last_checked_at is None or configuration.last_checked_at < bound:
        return verdict(SourceCoverage.BEHIND)

    return verdict(SourceCoverage.EVALUATED)
