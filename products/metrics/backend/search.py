"""Shared search helpers for the metrics autocomplete endpoints."""

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES

# Autocomplete tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do.
AUTOCOMPLETE_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)


def ilike_pattern(search: str) -> str:
    """Escape ILIKE metacharacters so a literal '%'/'_' in the search doesn't wildcard."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
