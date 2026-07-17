"""DRF throttles for the endpoints run API.

Materialized endpoints get a higher rate budget than inline ones. Readiness is
resolved through the facade (cached, with a DB fallback); the throttle classes
and their request-parsing helpers are pure HTTP concerns and live here.
"""

from prometheus_client import Counter
from rest_framework.throttling import SimpleRateThrottle

from posthog.rate_limit import (
    APIQueriesBurstThrottle,
    APIQueriesSustainedThrottle,
    PersonalOrProjectSecretApiKeyRateThrottle,
    ProjectSecretApiKeyTeamRateThrottle,
)

from products.endpoints.backend.facade.api import is_materialization_ready

ENDPOINT_RATE_LIMITED_TOTAL = Counter(
    "posthog_endpoint_rate_limited_total",
    "Rate-limited endpoint requests",
    labelnames=["scope"],
)


def _parse_requested_version(request) -> int | None:
    """Best-effort parse of the targeted version from the request (body first, then query params).

    Mirrors EndpointViewSet._parse_version_param; invalid or absent values fall back to None
    (current version) — the view validates and rejects properly later.
    """
    try:
        body_version = request.data.get("version") if hasattr(request, "data") else None
        raw_version = body_version if body_version is not None else request.query_params.get("version")
        return int(raw_version) if raw_version is not None else None
    except Exception:
        return None


def _get_endpoint_info_from_request(request, view) -> tuple[int | None, str | None, int | None]:
    """Extract team_id, endpoint_name, and requested version from request/view context."""
    team_id = getattr(view, "team_id", None)
    endpoint_name = view.kwargs.get("name") if hasattr(view, "kwargs") else None
    return team_id, endpoint_name, _parse_requested_version(request)


def _is_materialized_endpoint_request(request, view) -> bool:
    """Check if this request targets a materialized endpoint version (cached check with lazy loading)."""
    team_id, endpoint_name, version = _get_endpoint_info_from_request(request, view)
    if not team_id or not endpoint_name:
        return False
    return is_materialization_ready(team_id, endpoint_name, version)


class _MaterializedRateMixin(SimpleRateThrottle):
    """Swaps in the higher materialized-endpoint rate and records 429s, on top of any base throttle.

    Mix in before a SimpleRateThrottle subclass — `allow_request` adjusts the rate/scope for
    materialized endpoints, then defers to the base throttle's own gating (which sits between
    this mixin and SimpleRateThrottle in the MRO).
    """

    materialized_rate: str
    materialized_scope: str

    def allow_request(self, request, view):
        if _is_materialized_endpoint_request(request, view):
            self.rate = self.materialized_rate
            self.scope = self.materialized_scope
            self.num_requests, self.duration = self.parse_rate(self.rate)

        allowed = super().allow_request(request, view)
        if not allowed:
            try:
                ENDPOINT_RATE_LIMITED_TOTAL.labels(scope=self.scope).inc()
            except Exception:
                pass
        return allowed


class EndpointBurstThrottle(_MaterializedRateMixin, PersonalOrProjectSecretApiKeyRateThrottle, APIQueriesBurstThrottle):
    """
    Adaptive burst throttle for endpoints, keyed per credential (personal API key or PSAK).
    Uses higher rate limit for materialized endpoints.
    Non-materialized endpoints share the api_queries_burst bucket.
    """

    materialized_rate = "1200/minute"
    materialized_scope = "materialized_endpoint_burst"


class EndpointSustainedThrottle(
    _MaterializedRateMixin, PersonalOrProjectSecretApiKeyRateThrottle, APIQueriesSustainedThrottle
):
    """
    Adaptive sustained throttle for endpoints, keyed per credential (personal API key or PSAK).
    Uses higher rate limit for materialized endpoints.
    Non-materialized endpoints share the api_queries_sustained bucket.
    """

    materialized_rate = "12000/hour"
    materialized_scope = "materialized_endpoint_sustained"


class EndpointProjectSecretApiKeyTeamBurstThrottle(_MaterializedRateMixin, ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate burst budget across all of a project's PSAKs — same size as the per-key
    budget, so minting extra keys never multiplies a project's total burst capacity."""

    # Own scope (not api_queries_burst) so 429 metrics and cache keys name the bucket that tripped.
    scope = "endpoint_psak_team_burst"
    rate = APIQueriesBurstThrottle.rate
    materialized_rate = EndpointBurstThrottle.materialized_rate
    materialized_scope = "materialized_endpoint_psak_team_burst"


class EndpointProjectSecretApiKeyTeamSustainedThrottle(_MaterializedRateMixin, ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate sustained budget across all of a project's PSAKs."""

    scope = "endpoint_psak_team_sustained"
    rate = APIQueriesSustainedThrottle.rate
    materialized_rate = EndpointSustainedThrottle.materialized_rate
    materialized_scope = "materialized_endpoint_psak_team_sustained"
