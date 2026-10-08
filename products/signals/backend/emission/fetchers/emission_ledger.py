from collections.abc import Sequence

from posthog.models import Team

from products.signals.backend.emission.registry import SignalSourceTableConfig
from products.signals.backend.models import SignalEmissionRecord


def already_emitted_source_ids(team: Team, config: SignalSourceTableConfig, source_ids: Sequence[str]) -> set[str]:
    """The `source_ids` that already produced a signal for this team and source.

    The ledger is the idempotence key for fetchers that read the same rows on more than one sync.
    """
    return set(
        SignalEmissionRecord.objects.filter(
            team=team,
            source_product=config.source_product,
            source_type=config.source_type,
            source_id__in=source_ids,
        ).values_list("source_id", flat=True)
    )
