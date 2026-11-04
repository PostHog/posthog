"""Reads of a team's per-source signal config rows, for products that own a signal source."""

from collections.abc import Sequence

import structlog

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.contracts import ALERT_SCOPE_KEY, ALERT_SCOPE_SOURCE, AlertScope
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


def _analytics_all_alerts_enabled(team_id: int) -> bool:
    # Fails closed: a flag-service error keeps the team on the default scope.
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
        return False
