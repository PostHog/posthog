"""Which buffered changes a streaming table's consumer has not loaded yet.

Each extraction run that writes a table's buffer adds one to the table's generation, after every
file of that run is in S3. The consumer stamps its job with the generation it read before it listed
the buffer. A completed run whose stamp reaches the current generation therefore listed after every
counted file existed, so it read them all. The comparison uses no clock, so skew between pods
cannot make a file look consumed.

A run that dies after a write and before it counts leaves the write open. The table then owes a
load until a later run that completes counts the write.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# On the schema's `sync_type_config`.
BUFFER_GENERATION_KEY = "cdc_buffer_generation"
BUFFER_WRITE_OPEN_KEY = "cdc_buffer_write_open"

# On the consumer's job, beside the listing stamp.
BUFFER_GENERATION_SEEN_KEY = "cdc_buffer_generation_seen"


def buffer_generation(config: Mapping[str, Any] | None) -> int:
    value = (config or {}).get(BUFFER_GENERATION_KEY)
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return value


def open_buffer_write(config: dict[str, Any]) -> None:
    """Mark the buffer as written but not counted yet. Set before the first file of a run is written."""
    config[BUFFER_WRITE_OPEN_KEY] = True


def close_buffer_write(config: dict[str, Any], *, wrote: bool) -> None:
    """Count every write made so far.

    Called only by a run that completed, after its last write. An open write is counted even when
    this run wrote nothing, because it belongs to an earlier run. That assumes the earlier run is
    over. An attempt that outlives its heartbeat timeout can still write after its retry counted,
    and nothing then counts that file. The consumer's periodic full run reads it.
    """
    was_open = bool(config.pop(BUFFER_WRITE_OPEN_KEY, False))
    if wrote or was_open:
        config[BUFFER_GENERATION_KEY] = buffer_generation(config) + 1
