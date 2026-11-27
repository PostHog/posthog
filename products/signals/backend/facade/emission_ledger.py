"""The emission ledger that a product's own scheduled emitter uses to skip source records it already emitted."""

from collections.abc import Sequence

from django.utils import timezone

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalEmissionRecord


@frozen
class EmissionKey:
    source_type: str
    source_id: str


def emitted_keys(*, team_id: int, source_product: str, source_ids: Sequence[str]) -> set[EmissionKey]:
    """The ledger keys already recorded for `source_ids`, across every source type of `source_product`."""
    rows = SignalEmissionRecord.objects.filter(
        team_id=team_id,
        source_product=source_product,
        source_id__in=source_ids,
    ).values_list("source_type", "source_id")
    return {EmissionKey(source_type=source_type, source_id=source_id) for source_type, source_id in rows}


def record_emission(*, team_id: int, source_product: str, source_type: str, source_id: str) -> None:
    """Record one emitted source record. A record that is already in the ledger is left as it is."""
    SignalEmissionRecord.objects.bulk_create(
        [
            SignalEmissionRecord(
                team_id=team_id,
                source_product=source_product,
                source_type=source_type,
                source_id=source_id,
                emitted_at=timezone.now(),
            )
        ],
        ignore_conflicts=True,
    )
