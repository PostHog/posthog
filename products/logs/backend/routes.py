from posthog.api.routing import RouterRegistry

import products.logs.backend.presentation.views.api as logs


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"logs", logs.LogsViewSet, "environment_logs", ["team_id"])
    routers.register_legacy_dual_route(r"logs/alerts", logs.LogsAlertViewSet, "environment_logs_alerts", ["team_id"])
    routers.register_legacy_dual_route(
        r"logs/sampling_rules", logs.LogsSamplingRuleViewSet, "environment_logs_sampling_rules", ["team_id"]
    )
    routers.register_legacy_dual_route(r"logs/views", logs.LogsViewViewSet, "project_logs_views", ["team_id"])
    routers.register_legacy_dual_route(
        r"logs/explainLogWithAI", logs.LogExplainViewSet, "project_logs_explain_with_ai", ["team_id"]
    )
