"""Reads of a team's per-source signal config rows, for products that own a signal source."""

import enum
from collections.abc import Sequence

import re2
import structlog

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.contracts import (
    ALERT_ALLOW_PATTERNS_KEY,
    ALERT_BLOCK_PATTERNS_KEY,
    ALERT_SCOPE_KEY,
    ALERT_SCOPE_SOURCE,
    AlertScope,
    alert_patterns_problem,
)
from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

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


def get_analytics_alert_scope(*, team_id: int) -> AlertScope:
    """Which firing insight alerts the team's analytics source turns into signals.

    This reads only the scope. The caller still checks that the source is enabled. The result is
    `investigated_only` when the row or the key is missing, when the stored value is unknown, and when
    the rollout flag is off for the team's organization.
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
    if scope == AlertScope.INVESTIGATED_ONLY or not _analytics_all_alerts_enabled(team_id):
        return AlertScope.INVESTIGATED_ONLY
    return scope


@frozen
class AlertNamePatterns:
    """The analytics source's allow and block patterns for firing insight alerts."""

    allow: tuple[str, ...] = ()
    block: tuple[str, ...] = ()
    # A stored list failed validation, or the patterns could not be read. Callers then drop every alert
    # instead of applying part of a filter or none of it.
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
