from collections.abc import Callable, Mapping, Sequence
from functools import cache

from posthog.models import Team, User

from products.signals.backend.report_metric_access import ReportMetricAccessPolicy


def metric_context_reader(
    *, team_id: int, user_id: int | None, token_scopes: Sequence[str] | None = None
) -> Callable[[object], bool]:
    @cache
    def policy() -> ReportMetricAccessPolicy:
        return ReportMetricAccessPolicy(
            request=None,
            team=Team.objects.get(id=team_id),
            user=User.objects.filter(id=user_id).first(),
            token_scopes=token_scopes,
        )

    def may_read(queries: object) -> bool:
        return isinstance(queries, list) and all(
            isinstance(query, Mapping) and policy().may_read_snapshot({"query": query}) for query in queries
        )

    return may_read
