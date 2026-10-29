from posthog.api import sharing
from posthog.api.routing import RouterRegistry

import products.alerts.backend.presentation.views.alert as alert
from products.product_analytics.backend.presentation.events_retention import (
    EventsRetentionViewSet,
    OrganizationEventsRetentionViewSet,
)
from products.product_analytics.backend.presentation.insight import InsightViewSet
from products.product_analytics.backend.presentation.insight_variable import InsightVariableViewSet
from products.product_analytics.backend.presentation.paths_v2 import PathsV2ViewSet


def register_routes(routers: RouterRegistry) -> None:
    insights_router = routers.projects.register(r"insights", InsightViewSet, "project_insights", ["team_id"])

    # SharingConfigurationViewSet is shared (core); the route lives under
    # insights/<id>/sharing — product_analytics owns the sub-route.
    insights_router.register(
        r"sharing",
        sharing.SharingConfigurationViewSet,
        "project_insight_sharing",
        ["team_id", "insight_id"],
    )

    # ThresholdViewSet is owned by the alerts product but nests under insights.
    insights_router.register(
        "thresholds",
        alert.ThresholdViewSet,
        "project_insight_thresholds",
        ["team_id", "insight_id"],
    )

    routers.projects.register(
        r"insight_variables",
        InsightVariableViewSet,
        "project_insight_variables",
        ["team_id"],
    )

    routers.projects.register(
        r"paths_v2",
        PathsV2ViewSet,
        "project_paths_v2",
        ["team_id"],
    )

    routers.projects.register(
        r"events_retention",
        EventsRetentionViewSet,
        "project_events_retention",
        ["team_id"],
    )

    # Not "events_retention": the schema generator marks an organization path that repeats a project path as a
    # deprecated duplicate and leaves it out of the generated client.
    routers.organizations.register(
        r"events_retention_setting",
        OrganizationEventsRetentionViewSet,
        "organization_events_retention_setting",
        ["organization_id"],
    )
