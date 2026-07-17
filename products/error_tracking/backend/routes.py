from posthog.api.routing import RouterRegistry

from products.error_tracking.backend.presentation.views import (
    ErrorTrackingAssignmentRuleViewSet,
    ErrorTrackingBypassRuleViewSet,
    ErrorTrackingExternalReferenceViewSet,
    ErrorTrackingFingerprintViewSet,
    ErrorTrackingGroupingRuleViewSet,
    ErrorTrackingIssueViewSet,
    ErrorTrackingQueryViewSet,
    ErrorTrackingRecommendationViewSet,
    ErrorTrackingReleaseViewSet,
    ErrorTrackingSettingsViewSet,
    ErrorTrackingSpikeDetectionConfigViewSet,
    ErrorTrackingSpikeEventViewSet,
    ErrorTrackingStackFrameViewSet,
    ErrorTrackingSuppressionRuleViewSet,
    ErrorTrackingSymbolSetViewSet,
    GitProviderFileLinksViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    # releases and symbol_sets keep separate env (team_id) / project (project_id)
    # parent lookups, so they register manually rather than via the dual-route helper.
    routers.environments.register(
        r"error_tracking/releases", ErrorTrackingReleaseViewSet, "environment_error_tracking_release", ["team_id"]
    )
    routers.projects.register(
        r"error_tracking/releases", ErrorTrackingReleaseViewSet, "project_error_tracking_release", ["project_id"]
    )
    routers.environments.register(
        r"error_tracking/symbol_sets",
        ErrorTrackingSymbolSetViewSet,
        "environment_error_tracking_symbol_set",
        ["team_id"],
    )
    routers.projects.register(
        r"error_tracking/symbol_sets",
        ErrorTrackingSymbolSetViewSet,
        "project_error_tracking_symbol_set",
        ["project_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/assignment_rules",
        ErrorTrackingAssignmentRuleViewSet,
        "project_error_tracking_assignment_rule",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/grouping_rules",
        ErrorTrackingGroupingRuleViewSet,
        "project_error_tracking_grouping_rule",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/suppression_rules",
        ErrorTrackingSuppressionRuleViewSet,
        "project_error_tracking_suppression_rule",
        ["team_id"],
    )
    # Dual-route (env + project) to match the other rule types: the shared frontend rule API
    # helper targets the /api/environments/.../error_tracking/<rule_type> path.
    routers.register_legacy_dual_route(
        r"error_tracking/bypass_rules",
        ErrorTrackingBypassRuleViewSet,
        "project_error_tracking_bypass_rule",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/recommendations",
        ErrorTrackingRecommendationViewSet,
        "project_error_tracking_recommendation",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/fingerprints",
        ErrorTrackingFingerprintViewSet,
        "project_error_tracking_fingerprint",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/issues", ErrorTrackingIssueViewSet, "project_error_tracking_issue", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"error_tracking/query", ErrorTrackingQueryViewSet, "project_error_tracking_query", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"error_tracking/external_references",
        ErrorTrackingExternalReferenceViewSet,
        "project_error_tracking_external_references",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/stack_frames",
        ErrorTrackingStackFrameViewSet,
        "project_error_tracking_stack_frames",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/spike_detection_config",
        ErrorTrackingSpikeDetectionConfigViewSet,
        "project_error_tracking_spike_detection_config",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/settings", ErrorTrackingSettingsViewSet, "project_error_tracking_settings", ["team_id"]
    )
    routers.register_legacy_dual_route(
        r"error_tracking/spike_events",
        ErrorTrackingSpikeEventViewSet,
        "project_error_tracking_spike_events",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"error_tracking/git-provider-file-links",
        GitProviderFileLinksViewSet,
        "project_error_tracking_git_provider_file_links",
        ["team_id"],
    )
