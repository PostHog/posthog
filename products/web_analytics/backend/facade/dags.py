"""Dagster wiring of the web_analytics facade.

Core's dag location registry (posthog/dags/locations/web_analytics.py) imports
these modules to register the product's assets, asset checks, jobs, and
schedules. The assets live at the product root (products/web_analytics/dags/),
outside backend/; re-export the modules here so the registration crosses the
boundary through the facade like the temporal and query-runner wiring.
"""

from products.web_analytics.dags import (
    cache_favicons,
    cache_warming,
    eager_web_analytics_precompute,
    web_analytics_watchdog,
    web_dimensional_precompute,
    web_pre_aggregated_accuracy,
    web_preaggregated,
    web_preaggregated_asset_checks,
    web_preaggregated_team_selection,
)

__all__ = [
    "cache_favicons",
    "cache_warming",
    "eager_web_analytics_precompute",
    "web_analytics_watchdog",
    "web_dimensional_precompute",
    "web_pre_aggregated_accuracy",
    "web_preaggregated",
    "web_preaggregated_asset_checks",
    "web_preaggregated_team_selection",
]
