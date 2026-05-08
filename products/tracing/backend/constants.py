"""Shared HogQL settings for tracing queries hitting the logs ClickHouse cluster."""

from posthog.hogql.constants import HogQLGlobalSettings

# List/detail queries may need larger scans than chart aggregates.
_TRACE_SPANS_LIST_SETTINGS = HogQLGlobalSettings(
    allow_experimental_object_type=False,
    allow_experimental_join_condition=False,
    transform_null_in=False,
    max_bytes_to_read=None,
    read_overflow_mode=None,
)

def TRACE_SPANS_LIST_SETTINGS() -> HogQLGlobalSettings:  # noqa: N802
    return _TRACE_SPANS_LIST_SETTINGS.model_copy()

# Volume sparkline: projection-friendly; still cap cost defensively.
TRACE_SPANS_SPARKLINE_SETTINGS = HogQLGlobalSettings(
    allow_experimental_object_type=False,
    allow_experimental_join_condition=False,
    transform_null_in=False,
    max_execution_time=30,
    max_bytes_to_read=2_000_000_000,
    read_overflow_mode="throw",
)

# Latency heatmap: no projection today; strict caps.
TRACE_SPANS_HEATMAP_SETTINGS = HogQLGlobalSettings(
    allow_experimental_object_type=False,
    allow_experimental_join_condition=False,
    transform_null_in=False,
    max_execution_time=30,
    max_bytes_to_read=2_000_000_000,
    read_overflow_mode="throw",
)
