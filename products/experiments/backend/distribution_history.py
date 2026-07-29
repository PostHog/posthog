"""Detect variant-split changes made after an experiment launched.

Variant assignment is deterministic rather than a rebalance: the flag matcher hashes each
distinct ID once and walks the variants' cumulative rollout percentages. Moving the split
boundary therefore only switches the users whose hash lands in the band that moved — everyone
else keeps the variant they already had — and the results collected before and after the change
describe two different allocations.

The signal is the feature flag's own activity log rather than a new column on the experiment, so
splits changed straight from the feature flag page count too, and experiments that were already
edited mid-run surface the warning without needing another edit first.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from posthog.models.activity_logging.activity_log import ActivityLog

if TYPE_CHECKING:
    from products.experiments.backend.models import Experiment


def _variant_split(filters: Any) -> dict[str, Any] | None:
    """The variant key → rollout percentage mapping in a set of flag filters, or None when absent."""
    if not isinstance(filters, dict):
        return None
    variants = (filters.get("multivariate") or {}).get("variants")
    if not isinstance(variants, list):
        return None
    return {variant.get("key"): variant.get("rollout_percentage") for variant in variants if isinstance(variant, dict)}


def variant_split_changed_at(experiment: "Experiment") -> datetime | None:
    """When the experiment's variant split first changed after launch, or None if it never did.

    Only the split between variants counts. Raising or lowering the overall rollout percentage
    uses a different hash salt, so it admits or holds back users without moving anyone between
    variants — that is a normal way to steer exposure, not a source of mixed results.
    """
    if experiment.start_date is None or experiment.feature_flag_id is None:
        return None

    entries = ActivityLog.objects.filter(
        team_id=experiment.feature_flag.team_id,
        scope="FeatureFlag",
        item_id=str(experiment.feature_flag_id),
        created_at__gt=experiment.start_date,
    )
    if experiment.end_date is not None:
        entries = entries.filter(created_at__lte=experiment.end_date)

    for created_at, detail in entries.order_by("created_at").values_list("created_at", "detail"):
        for change in (detail or {}).get("changes") or []:
            if not isinstance(change, dict) or change.get("field") != "filters":
                continue
            before = _variant_split(change.get("before"))
            after = _variant_split(change.get("after"))
            if before is not None and after is not None and before != after:
                return created_at

    return None
