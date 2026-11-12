"""Reads of a team's per-source signal config rows, for products that own a signal source."""

import enum
from collections.abc import Sequence

import re2
import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.contracts import (
    ALERT_ALLOW_PATTERNS_KEY,
    ALERT_BLOCK_PATTERNS_KEY,
    ALERT_SCOPE_KEY,
    ALERT_SCOPE_SOURCE,
    ISSUE_FILTERS_KEY,
    AlertScope,
    alert_patterns_problem,
)
from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

SOURCE_FILTER_DROPPED_EVENT = "signal_source_filter_dropped"
ANALYTICS_ALL_ALERTS_FLAG = "signals-analytics-all-alerts"


@frozen
class SignalSourceConfigSnapshot:
    enabled: bool
    created_by_id: int | None
    # The row's JSON config. A stored value that is not a JSON object reads as empty.
    config: dict[str, object]


def _to_snapshot(row: SignalSourceConfig) -> SignalSourceConfigSnapshot:
    return SignalSourceConfigSnapshot(
        enabled=row.enabled,
        created_by_id=row.created_by_id,
        config=row.config if isinstance(row.config, dict) else {},
    )


def get_source_config(*, team_id: int, source_product: str, source_type: str) -> SignalSourceConfigSnapshot | None:
    row = (
        SignalSourceConfig.objects.filter(team_id=team_id, source_product=source_product, source_type=source_type)
        .only("enabled", "created_by_id", "config")
        .first()
    )
    if row is None:
        return None
    return _to_snapshot(row)


def latest_enabled_source_config(
    *, team_id: int, source_product: str, source_types: Sequence[str]
) -> SignalSourceConfigSnapshot | None:
    """The most recently updated enabled row among `source_types`, or None when none is enabled."""
    row = (
        SignalSourceConfig.objects.filter(
            team_id=team_id,
            source_product=source_product,
            source_type__in=source_types,
            enabled=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if row is None:
        return None
    return _to_snapshot(row)


def enabled_issue_filters(*, team_id: int, source_product: str, source_type: str) -> object | None:
    """The stored issue filter of an enabled source row, or None when there is no filter to apply.

    A disabled or missing row returns None, because `emit_signal` skips the signal anyway. The
    value is returned as stored, so the caller can drop a signal whose filter is malformed.
    """
    config = (
        SignalSourceConfig.objects.filter(
            team_id=team_id, source_product=source_product, source_type=source_type, enabled=True
        )
        .values_list("config", flat=True)
        .first()
    )
    if not isinstance(config, dict):
        return None
    return config.get(ISSUE_FILTERS_KEY)


def record_source_filter_drop(
    *, team: Team, source_product: str, source_type: str, source_id: str, reason: str
) -> None:
    """Count a signal that a source filter dropped before `emit_signal`.

    A separate event from `signal_data_source_filtered`, which counts steering drops after
    `signal_emission_started`. A filter drop has no started event, so it must not enter that funnel.
    """
    logger.info(
        "Filtered signal by source filter",
        team_id=team.id,
        signal_source_product=source_product,
        signal_source_type=source_type,
        signal_source_id=source_id,
        filter_reason=reason,
    )
    try:
        posthoganalytics.capture(
            event=SOURCE_FILTER_DROPPED_EVENT,
            distinct_id=str(team.uuid),
            properties={
                "source_product": source_product,
                "source_type": source_type,
                "source_id": source_id,
                "filter_reason": reason,
            },
            # The team carries its organization id, so this reads no organization row.
            groups=groups(team=team),
        )
    except Exception:
        # A lost analytics event must not fail the activity, which would retry the whole signal.
        logger.exception("Failed to capture source filter drop", team_id=team.id, source_type=source_type)


def analytics_source_enabled(team_id: int) -> bool:
    """Whether the team turned on the Product analytics source, which also controls anomaly scoring."""
    source_product, source_type = ALERT_SCOPE_SOURCE
    return SignalSourceConfig.objects.filter(
        team_id=team_id, source_product=source_product, source_type=source_type, enabled=True
    ).exists()


def get_analytics_alert_scope(*, team_id: int) -> AlertScope:
    """Which firing insight alerts the team's analytics source turns into signals.

    This reads only the scope. The caller still checks that the source is enabled. The result is
    `investigated_only` when the row or the key is missing, when the stored value is unknown, and when
    the rollout flag is off for the team's organization. The rollout flag gates only `all_firing_alerts`,
    so `off` applies to every team.
    """
    source_product, source_type = ALERT_SCOPE_SOURCE
    snapshot = get_source_config(team_id=team_id, source_product=source_product, source_type=source_type)
    if snapshot is None:
        return AlertScope.INVESTIGATED_ONLY
    raw_scope = snapshot.config.get(ALERT_SCOPE_KEY, AlertScope.INVESTIGATED_ONLY)
    if not isinstance(raw_scope, str):
        return AlertScope.INVESTIGATED_ONLY
    try:
        scope = AlertScope(raw_scope)
    except ValueError:
        return AlertScope.INVESTIGATED_ONLY
    if scope == AlertScope.OFF:
        return scope
    if scope == AlertScope.INVESTIGATED_ONLY or not _analytics_all_alerts_enabled(team_id):
        return AlertScope.INVESTIGATED_ONLY
    return scope


@frozen
class AlertNamePatterns:
    """The analytics source's allow and block patterns for firing insight alerts."""

    allow: tuple[str, ...] = ()
    block: tuple[str, ...] = ()
    # The stored patterns could not be read or validated, so callers drop every alert.
    invalid: bool = False


class AlertFilterOutcome(enum.StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    NOT_ALLOWED = "not_allowed"
    INVALID = "invalid"


def get_analytics_alert_name_patterns(*, team_id: int) -> AlertNamePatterns:
    """The allow and block patterns of the team's analytics source.

    The result is empty, so every alert passes, when the row or both keys are missing and when the
    rollout flag is off for the team's organization. It fails closed: when a stored list is not a list
    of valid patterns, or the flag check raises, the result is `invalid`, and `evaluate_alert_filter`
    then drops every alert.
    """
    source_product, source_type = ALERT_SCOPE_SOURCE
    snapshot = get_source_config(team_id=team_id, source_product=source_product, source_type=source_type)
    if snapshot is None:
        return AlertNamePatterns()
    config = snapshot.config
    if ALERT_ALLOW_PATTERNS_KEY not in config and ALERT_BLOCK_PATTERNS_KEY not in config:
        return AlertNamePatterns()
    flag_enabled = _analytics_all_alerts_flag(team_id)
    if flag_enabled is None:
        return AlertNamePatterns(invalid=True)
    if not flag_enabled:
        return AlertNamePatterns()
    raw_allow = config.get(ALERT_ALLOW_PATTERNS_KEY, [])
    raw_block = config.get(ALERT_BLOCK_PATTERNS_KEY, [])
    if not (
        isinstance(raw_allow, list)
        and isinstance(raw_block, list)
        and alert_patterns_problem(raw_allow) is None
        and alert_patterns_problem(raw_block) is None
    ):
        return AlertNamePatterns(invalid=True)
    return AlertNamePatterns(allow=tuple(raw_allow), block=tuple(raw_block))


def evaluate_alert_filter(
    patterns: AlertNamePatterns, *, alert_name: str | None, insight_name: str | None
) -> AlertFilterOutcome:
    """Whether a firing alert passes the source's patterns. Block wins over allow.

    A pattern matches when it finds a match anywhere in the alert name or the insight name. An empty
    allow list admits every alert. A pattern that does not compile drops the alert.
    """
    if patterns.invalid:
        return AlertFilterOutcome.INVALID
    names = [name for name in (alert_name, insight_name) if name]
    try:
        if _any_pattern_matches(patterns.block, names):
            return AlertFilterOutcome.BLOCKED
        if patterns.allow and not _any_pattern_matches(patterns.allow, names):
            return AlertFilterOutcome.NOT_ALLOWED
    except re2.error:
        return AlertFilterOutcome.INVALID
    return AlertFilterOutcome.PASSED


def _any_pattern_matches(patterns: Sequence[str], names: Sequence[str]) -> bool:
    return any(re2.search(pattern, name) for pattern in patterns for name in names)


def _analytics_all_alerts_enabled(team_id: int) -> bool:
    # Fails closed: a flag-service error keeps the team on the default scope.
    return _analytics_all_alerts_flag(team_id) is True


def _analytics_all_alerts_flag(team_id: int) -> bool | None:
    """The rollout flag for the team's organization, or None when the flag check raised."""
    try:
        organization_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
        return feature_enabled_or_false(
            ANALYTICS_ALL_ALERTS_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
            only_evaluate_locally=True,
        )
    except Exception:
        logger.exception("signals.alert_scope.flag_check_failed", team_id=team_id)
        return None
