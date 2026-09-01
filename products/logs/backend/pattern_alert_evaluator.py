"""Evaluation logic for pattern-trigger alerts (new_pattern / pattern_threshold).

Sits between `GroupedPatternCheckQuery` (ClickHouse) and the Temporal activity:
turns one check window's (service_name, pattern) groups into a breach decision
plus the seen-set rows to persist. Postgres writes are NOT done here: staged
rows ride the evaluation into the cohort save phase, which commits them only
when the notification was delivered (same rollback contract as alert state).

new_pattern semantics:
- First check seeds the seen-set from a lookback window without alerting, so
  pre-existing error shapes never fire.
- Later checks anti-join the window's fingerprints against the seen-set; a
  fingerprint not in the set is net-new and fires once `threshold_count`
  occurrences accumulate in the window (the min-occurrences floor).
- A PATTERN_VERSION bump (the ingest masker changed) re-mints every
  fingerprint. Groups whose version is ahead of everything in the seen-set are
  staged silently instead of alerting, so a masker deploy never causes a storm.

pattern_threshold semantics: any single fingerprint reaching threshold_count
occurrences in the window breaches. Stateless, with no seen-set involved.
"""

import hashlib
import datetime as dt
from dataclasses import dataclass
from itertools import batched

from django.db.models import Max

from products.logs.backend.models import LogsAlertConfiguration, LogsAlertSeenPattern
from products.logs.backend.pattern_alert_check_query import (
    MAX_PATTERN_GROUPS,
    GroupedPatternCheckQuery,
    PatternGroupCount,
)

# new_pattern seed window (days of history inserted without alerting on the first
# check). Bounded by logs retention (15-30d), so "not seen in the seed window" is
# a close proxy for "first occurrence ever".
DEFAULT_SEED_LOOKBACK_DAYS = 7
MAX_SEED_LOOKBACK_DAYS = 30

# Seed checks cover days, not minutes, so they legitimately see far more groups
# than a check window. Cap at the seen-set bound instead of MAX_PATTERN_GROUPS.
MAX_SEEN_PATTERNS_PER_ALERT = 50_000

# `last_seen_at` refreshes lazily: only rows older than this get an UPDATE per
# check, bounding write amplification on high-frequency checks.
LAST_SEEN_REFRESH_MIN_AGE = dt.timedelta(days=1)

# Stored/display pattern templates are truncated to this many characters.
PATTERN_SAMPLE_MAX_LENGTH = 1_000

_FINGERPRINT_CHUNK_SIZE = 1_000


class PatternAlertCheckError(Exception):
    """Check failure with a user-safe message, surfaced on the alert like a query
    error. Non-transient by default so repeated failures escalate to BROKEN."""

    def __init__(self, user_message: str, *, is_transient: bool = False) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.is_transient = is_transient


def pattern_alert_fingerprint(service_name: str, pattern: str, pattern_version: int) -> str:
    """Stable identity for a (version, service, pattern) triple.

    Version-scoped on purpose: a PATTERN_VERSION bump changes what the masker
    emits, so cross-version template equality is meaningless.
    """
    digest = hashlib.sha256(f"{pattern_version}\x00{service_name}\x00{pattern}".encode()).hexdigest()
    return digest[:32]


@dataclass(frozen=True)
class StagedSeenPattern:
    fingerprint: str
    service_name: str
    pattern: str
    pattern_version: int


@dataclass(frozen=True)
class PatternCheckOutcome:
    """One pattern check's result: breach decision + seen-set writes to stage.

    `result_count` is the number of breaching fingerprints (new-and-over-floor
    for new_pattern, over-threshold for pattern_threshold). It is the analog of
    the count trigger's window count in events and payloads.
    """

    result_count: int
    threshold_breached: bool
    query_duration_ms: int
    breaching: tuple[PatternGroupCount, ...]
    staged_new: tuple[StagedSeenPattern, ...]
    refresh_fingerprints: tuple[str, ...]
    seeded: bool = False


def evaluate_pattern_alert(
    alert: LogsAlertConfiguration,
    *,
    date_to: dt.datetime,
    now: dt.datetime,
) -> PatternCheckOutcome:
    """Run the grouped check for one pattern-trigger alert ending at `date_to`.

    Pattern triggers evaluate 1-of-1, so the window is exactly
    `alert.window_minutes` (no rolling M-window lookback). Raises
    `PatternAlertCheckError` for config-shaped failures (stamping disabled,
    fingerprint cardinality blowout); ClickHouse errors propagate for the
    activity's standard classification.
    """
    if alert.trigger_type == LogsAlertConfiguration.TriggerType.NEW_PATTERN:
        return _evaluate_new_pattern(alert, date_to=date_to, now=now)
    if alert.trigger_type == LogsAlertConfiguration.TriggerType.PATTERN_THRESHOLD:
        return _evaluate_pattern_threshold(alert, date_to=date_to)
    raise ValueError(f"Not a pattern trigger: {alert.trigger_type!r}")


def seed_lookback_days(alert: LogsAlertConfiguration) -> int:
    raw = (alert.trigger_config or {}).get("seed_lookback_days", DEFAULT_SEED_LOOKBACK_DAYS)
    if not isinstance(raw, int) or isinstance(raw, bool):
        return DEFAULT_SEED_LOOKBACK_DAYS
    return max(1, min(raw, MAX_SEED_LOOKBACK_DAYS))


def _window_date_from(alert: LogsAlertConfiguration, date_to: dt.datetime) -> dt.datetime:
    return date_to - dt.timedelta(minutes=alert.window_minutes)


def _run_groups(
    alert: LogsAlertConfiguration,
    *,
    date_from: dt.datetime,
    date_to: dt.datetime,
    limit: int,
) -> tuple[list[PatternGroupCount], int]:
    """Grouped query + the shared guardrails (cardinality cap, stamping probe)."""
    query = GroupedPatternCheckQuery(team=alert.team, alert=alert, date_from=date_from, date_to=date_to)
    result = query.execute_groups(limit=limit)
    duration_ms = result.query_duration_ms

    if result.truncated:
        raise PatternAlertCheckError(
            f"This alert's filters match more than {limit:,} distinct log patterns per check. "
            "Narrow the filters (fewer services or severities) so per-pattern alerting stays meaningful."
        )

    if not result.groups:
        probe = query.execute_stamping_probe()
        duration_ms += probe.query_duration_ms
        if probe.total > 0 and probe.stamped == 0:
            raise PatternAlertCheckError(
                "Matching logs carry no pattern fingerprints, so pattern alerts cannot evaluate. "
                "Pattern stamping is not enabled for this project. Contact support to enable it."
            )

    return result.groups, duration_ms


def _evaluate_pattern_threshold(alert: LogsAlertConfiguration, *, date_to: dt.datetime) -> PatternCheckOutcome:
    groups, duration_ms = _run_groups(
        alert,
        date_from=_window_date_from(alert, date_to),
        date_to=date_to,
        limit=MAX_PATTERN_GROUPS,
    )
    breaching = tuple(g for g in groups if g.occurrences >= alert.threshold_count)
    return PatternCheckOutcome(
        result_count=len(breaching),
        threshold_breached=bool(breaching),
        query_duration_ms=duration_ms,
        breaching=breaching,
        staged_new=(),
        refresh_fingerprints=(),
    )


def _evaluate_new_pattern(
    alert: LogsAlertConfiguration,
    *,
    date_to: dt.datetime,
    now: dt.datetime,
) -> PatternCheckOutcome:
    seen_qs = LogsAlertSeenPattern.objects.for_team(alert.team_id).filter(alert_id=alert.id)
    is_seed = not seen_qs.exists()

    if is_seed:
        date_from = date_to - dt.timedelta(days=seed_lookback_days(alert))
        groups, duration_ms = _run_groups(
            alert, date_from=date_from, date_to=date_to, limit=MAX_SEEN_PATTERNS_PER_ALERT
        )
        return PatternCheckOutcome(
            result_count=0,
            threshold_breached=False,
            query_duration_ms=duration_ms,
            breaching=(),
            staged_new=tuple(_stage(g) for g in groups),
            refresh_fingerprints=(),
            seeded=True,
        )

    groups, duration_ms = _run_groups(
        alert,
        date_from=_window_date_from(alert, date_to),
        date_to=date_to,
        limit=MAX_PATTERN_GROUPS,
    )
    if not groups:
        return PatternCheckOutcome(
            result_count=0,
            threshold_breached=False,
            query_duration_ms=duration_ms,
            breaching=(),
            staged_new=(),
            refresh_fingerprints=(),
        )

    by_fingerprint = {pattern_alert_fingerprint(g.service_name, g.pattern, g.pattern_version): g for g in groups}

    seen_last_seen: dict[str, dt.datetime] = {}
    for chunk in batched(by_fingerprint.keys(), _FINGERPRINT_CHUNK_SIZE, strict=False):
        seen_last_seen.update(dict(seen_qs.filter(fingerprint__in=chunk).values_list("fingerprint", "last_seen_at")))

    # A group whose pattern_version is ahead of everything seen means the ingest
    # masker was redeployed: every fingerprint re-mints, so stage silently.
    max_seen_version = seen_qs.aggregate(v=Max("pattern_version"))["v"] or 0

    new_groups: list[PatternGroupCount] = []
    staged: list[StagedSeenPattern] = []
    for fingerprint, group in by_fingerprint.items():
        if fingerprint in seen_last_seen:
            continue
        staged.append(_stage(group))
        if group.pattern_version <= max_seen_version:
            new_groups.append(group)

    if staged:
        seen_count = seen_qs.count()
        if seen_count + len(staged) > MAX_SEEN_PATTERNS_PER_ALERT:
            raise PatternAlertCheckError(
                f"This alert tracks more than {MAX_SEEN_PATTERNS_PER_ALERT:,} distinct patterns. "
                "Narrow the filters (fewer services or severities) so per-pattern alerting stays meaningful."
            )

    # The floor: a novel fingerprint alerts only at threshold_count+ occurrences in
    # the window. Below-floor fingerprints are still staged (no longer new), which
    # is the anti-flap behavior: one stray line never alerts later checks either.
    breaching = tuple(g for g in new_groups if g.occurrences >= alert.threshold_count)

    refresh = tuple(
        fingerprint for fingerprint, last_seen in seen_last_seen.items() if now - last_seen >= LAST_SEEN_REFRESH_MIN_AGE
    )

    return PatternCheckOutcome(
        result_count=len(breaching),
        threshold_breached=bool(breaching),
        query_duration_ms=duration_ms,
        breaching=breaching,
        staged_new=tuple(staged),
        refresh_fingerprints=refresh,
    )


def _stage(group: PatternGroupCount) -> StagedSeenPattern:
    return StagedSeenPattern(
        fingerprint=pattern_alert_fingerprint(group.service_name, group.pattern, group.pattern_version),
        service_name=group.service_name,
        pattern=group.pattern[:PATTERN_SAMPLE_MAX_LENGTH],
        pattern_version=group.pattern_version,
    )
