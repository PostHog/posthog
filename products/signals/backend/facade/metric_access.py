from collections.abc import Mapping

from rest_framework.request import Request

from posthog.models import Team

from products.signals.backend.report_metric_access import ReportMetricAccessPolicy


def may_read_metric_context(*, request: Request, team: Team, queries: object) -> bool:
    policy = ReportMetricAccessPolicy(request=request, team=team)
    return isinstance(queries, list) and all(
        isinstance(query, Mapping) and policy.may_read_snapshot({"query": query}) for query in queries
    )
