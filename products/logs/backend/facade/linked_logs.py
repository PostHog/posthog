"""Facade for the linked logs lookup.

Kept apart from ``facade/api.py``, which imports the alerting and Temporal modules: error tracking's
query runners import this lookup, and that chain leads back into them as a circular import.
"""

from products.logs.backend.linked_logs import LinkedLogsLookupError, LogLinkCandidate, find_log_linked_keys

__all__ = ["LinkedLogsLookupError", "LogLinkCandidate", "find_log_linked_keys"]
