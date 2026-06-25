"""Facade re-exports for logs HogQL query runners.

Core's query-runner registry (``posthog/hogql_queries/query_runner.py``) dispatches on
query ``kind`` and constructs ``LogsQueryRunner`` by class identity — it's registered
there for server-side CSV export only (direct ``LogsQuery`` execution is blocked).
Re-exporting the class keeps that registry coupling at the facade boundary while the
heavy HogQL imports stay out of ``facade/api.py``, so config-only consumers don't drag
them onto the ``django.setup()`` path.
"""

from products.logs.backend.logs_query_runner import LogsQueryRunner
from products.logs.backend.saved_view_query import build_logs_query_for_saved_view

__all__ = ["LogsQueryRunner", "build_logs_query_for_saved_view"]
