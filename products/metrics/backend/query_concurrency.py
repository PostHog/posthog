"""Concurrency slots for metrics queries that run outside a query runner."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings

from posthog.clickhouse.client.limit import (
    app_org_concurrency_slot,
    get_api_team_rate_limiter,
    get_app_dashboard_queries_rate_limiter,
)
from posthog.clickhouse.query_tagging import get_query_tag_value, is_api_key_access_method
from posthog.constants import AvailableFeature
from posthog.models import Team


def _api_key_concurrency_limit(team: Team) -> int | None:
    if not settings.EE_AVAILABLE or not settings.API_QUERIES_ENABLED:
        return None
    feature = team.organization.get_available_feature(AvailableFeature.API_QUERIES_CONCURRENCY)
    return feature.get("limit") if feature else None


@contextmanager
def query_concurrency_slots(team: Team, dashboard_id: int | None = None) -> Iterator[None]:
    """Hold the slots a query runner holds, so the query counts against the same limits.

    Browser sessions skip the API throttles, so the per-organization slot is what bounds them.
    Raises `ConcurrencyLimitExceeded` when no slot frees up in time.
    """
    is_api_key_access = is_api_key_access_method(get_query_tag_value("access_method"))
    with (
        get_api_team_rate_limiter().run(
            is_api=is_api_key_access,
            team_id=team.pk,
            limit=_api_key_concurrency_limit(team) if is_api_key_access else None,
        ),
        app_org_concurrency_slot(team),
        get_app_dashboard_queries_rate_limiter().run(
            org_id=team.organization_id, dashboard_id=dashboard_id, team_id=team.pk, is_api=is_api_key_access
        ),
    ):
        yield
