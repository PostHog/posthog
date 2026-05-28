"""Facade for metrics.

This is the ONLY module other products (and the presentation layer) are
allowed to import. Internal modules (query runners) stay behind this seam
so import-linter's strict-mode contract holds.
"""

from posthog.models import Team

from products.metrics.backend.has_metrics_query_runner import team_has_metrics as _team_has_metrics


def team_has_metrics(team: Team) -> bool:
    """Return True if the given team has ingested at least one metric."""
    return _team_has_metrics(team)
