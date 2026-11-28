from typing import cast

from posthog.entitlements.contracts import EntitlementChange, EntitlementReactor, Entitlements
from posthog.models.events_plan_deletion import apply_events_retention_change
from posthog.models.organization import Organization, ProductFeature
from posthog.models.team.event_retention import (
    EVENTS_DATA_RETENTION_FEATURE,
    STANDARD_DATA_RETENTION_FEATURE,
    parse_events_feature_to_months,
)

EVENTS_RETENTION_REACTOR_KEY = "events-retention"
EVENTS_RETENTION_FEATURE_KEYS = frozenset({EVENTS_DATA_RETENTION_FEATURE.value, STANDARD_DATA_RETENTION_FEATURE.value})


def _plan_months(entitlements: Entitlements) -> int:
    retention_feature = next(
        (entry for entry in entitlements.to_snapshot() if entry["key"] == EVENTS_DATA_RETENTION_FEATURE), None
    )
    return parse_events_feature_to_months(cast(ProductFeature | None, retention_feature))


def _previous_plan_months(previous: Entitlements | None) -> int | None:
    # A checkpoint with neither key comes from a first sync or from a plan without retention. It cannot tell them apart.
    # Both cases get no previous period, so neither sends a notice.
    if previous is None or previous.keys().isdisjoint(EVENTS_RETENTION_FEATURE_KEYS):
        return None
    return _plan_months(previous)


def apply_events_retention_plan_change(change: EntitlementChange) -> None:
    previous_months = _previous_plan_months(change.previous)
    if previous_months == _plan_months(change.current):
        return
    organization = (
        Organization.objects.using("default")
        .only("id", "name", "available_product_features")
        .get(id=change.organization_id)
    )
    apply_events_retention_change(
        organization,
        previous_months,
        change.previous is not None and change.previous.has(STANDARD_DATA_RETENTION_FEATURE),
    )


ENTITLEMENT_REACTORS: tuple[EntitlementReactor, ...] = (
    EntitlementReactor(
        key=EVENTS_RETENTION_REACTOR_KEY,
        feature_keys=EVENTS_RETENTION_FEATURE_KEYS,
        react=apply_events_retention_plan_change,
    ),
)
