from posthog.entitlements.contracts import EntitlementChange, EntitlementReactor
from posthog.models.organization import Organization
from posthog.models.team.logs_retention import LOGS_RETENTION_PAID_FEATURE, reset_logs_retention_for_missing_features

LOGS_RETENTION_REACTOR_KEY = "logs-retention"
LOGS_RETENTION_FEATURE_KEYS = frozenset({LOGS_RETENTION_PAID_FEATURE.value})


def reset_logs_retention_without_entitlement(change: EntitlementChange) -> None:
    missing_feature_keys = LOGS_RETENTION_FEATURE_KEYS - change.current.keys()
    if not missing_feature_keys:
        return
    organization = Organization.objects.using("default").only("id").get(id=change.organization_id)
    reset_logs_retention_for_missing_features(organization, missing_feature_keys)


ENTITLEMENT_REACTORS: tuple[EntitlementReactor, ...] = (
    EntitlementReactor(
        key=LOGS_RETENTION_REACTOR_KEY,
        feature_keys=LOGS_RETENTION_FEATURE_KEYS,
        react=reset_logs_retention_without_entitlement,
    ),
)
