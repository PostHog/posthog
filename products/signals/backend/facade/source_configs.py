"""Reads of a team's per-source signal config rows, for products that own a signal source."""

from collections.abc import Sequence

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalSourceConfig


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
