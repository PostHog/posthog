from collections.abc import Callable, Mapping

from rest_framework.request import Request

from posthog.models import Team, User

from products.signals.backend.report_metric_access import ReportMetricAccessPolicy


def metric_context_reader(
    *, team: Team, request: Request | None = None, user: User | None = None
) -> Callable[[object], bool]:
    policy = ReportMetricAccessPolicy(request=request, team=team, user=user)

    def may_read(queries: object) -> bool:
        return isinstance(queries, list) and all(
            isinstance(query, Mapping) and policy.may_read_snapshot({"query": query}) for query in queries
        )

    return may_read
