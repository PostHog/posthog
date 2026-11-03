"""Reads of a team's per-source signal config rows, for products that own a signal source."""

from collections.abc import Sequence

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.contracts import ISSUE_FILTERS_KEY
from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

SOURCE_FILTER_DROPPED_EVENT = "signal_source_filter_dropped"


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
