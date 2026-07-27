from posthog.api.routing import RouterRegistry

import products.logs.backend.presentation.views.api as logs


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"logs", logs.LogsViewSet, "project_logs", ["team_id"])
    routers.projects.register(r"logs/alerts", logs.LogsAlertViewSet, "project_logs_alerts", ["team_id"])
    routers.projects.register(
        r"logs/sampling_rules", logs.LogsSamplingRuleViewSet, "project_logs_sampling_rules", ["team_id"]
    )
    routers.projects.register(
        r"logs/metric_rules", logs.LogsMetricRuleViewSet, "project_logs_metric_rules", ["team_id"]
    )
    routers.projects.register(r"logs/views", logs.LogsViewViewSet, "project_logs_views", ["team_id"])
    routers.projects.register(
        r"logs/explainLogWithAI", logs.LogExplainViewSet, "project_logs_explain_with_ai", ["team_id"]
    )
