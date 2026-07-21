"""Facade re-exports for logs HogQL query runners.

Core's query-runner registry (``posthog/hogql_queries/query_runner.py``) dispatches on
query ``kind`` and constructs the logs runner via ``build_logs_query_runner_for_export``
— it's registered there for server-side CSV export only (direct ``LogsQuery`` execution
is blocked). Keeping the factory here confines the archive-runner coupling to the facade
boundary while the heavy HogQL imports stay out of ``facade/api.py``, so config-only
consumers don't drag them onto the ``django.setup()`` path.
"""

from typing import Any

from products.logs.backend.logs_query_runner import LogsQueryRunner
from products.logs.backend.saved_view_query import build_logs_query_for_saved_view


def build_logs_query_runner_for_export(query: Any, **kwargs: Any) -> LogsQueryRunner:
    """Pick the archive runner when the export's source requested it, else the hot runner.

    The registry has already gated ``useArchive`` behind the feature flag at export-creation
    time (see the logs ``export`` action), so honouring it here is safe.
    """
    use_archive = query.get("useArchive", False) if isinstance(query, dict) else getattr(query, "useArchive", False)
    if use_archive:
        from products.logs.backend.archive_query_runners import ArchivedLogsQueryRunner

        return ArchivedLogsQueryRunner(query=query, **kwargs)
    return LogsQueryRunner(query=query, **kwargs)


__all__ = ["LogsQueryRunner", "build_logs_query_for_saved_view", "build_logs_query_runner_for_export"]
