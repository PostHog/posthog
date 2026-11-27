"""The exposure event that an experiment counts when its exposure criteria name none."""

from products.experiments.backend.hogql_queries.exposure_query_logic import resolve_default_exposure_event

__all__ = [
    "resolve_default_exposure_event",
]
