# Re-export from the canonical location for backward compatibility
from products.signals.backend.temporal.signal_queries import (
    EMBEDDING_MODEL,
    _ensure_tz_aware,
    soft_delete_report_signals,
)

__all__ = [
    "EMBEDDING_MODEL",
    "_ensure_tz_aware",
    "soft_delete_report_signals",
]
