"""Query-runner wiring facade for metrics.

Core dispatch (`posthog/hogql_queries/query_runner.py`) imports the runner
through this module so internal modules stay behind the facade seam. Import
lazily at the dispatch site — this module pulls in HogQL machinery that must
stay off the `django.setup()` path.
"""

from products.metrics.backend.metrics_query_runner import MetricsQueryRunner

__all__ = ["MetricsQueryRunner"]
