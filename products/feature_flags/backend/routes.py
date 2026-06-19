from posthog.api.routing import RouterRegistry

from products.feature_flags.backend.api import feature_flag, flag_value, organization_feature_flag, scheduled_change


def register_routes(routers: RouterRegistry) -> None:
    # Library-side feature flag evaluation (legacy root path).
    routers.root.register(r"feature_flag", feature_flag.LegacyFeatureFlagViewSet)
    routers.projects.register(
        r"feature_flags", feature_flag.FeatureFlagViewSet, "project_feature_flags", ["project_id"]
    )
    routers.projects.register(
        r"scheduled_changes", scheduled_change.ScheduledChangeViewSet, "project_scheduled_changes", ["project_id"]
    )
    routers.projects.register(r"flag_value", flag_value.FlagValueViewSet, "project_flag_value", ["project_id"])
    routers.organizations.register(
        r"feature_flags",
        organization_feature_flag.OrganizationFeatureFlagView,
        "organization_feature_flags",
        ["organization_id"],
    )
