# Re-export from the canonical location for backward compatibility
from products.signals.backend.signal_metadata import EMBEDDING_MODEL
from products.signals.backend.temporal.signal_queries import _ensure_tz_aware, soft_delete_report_signals

__all__ = [
    "EMBEDDING_MODEL",
    "_ensure_tz_aware",
    "soft_delete_report_signals",
]
